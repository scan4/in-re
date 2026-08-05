"""
LLM 客户端 — 同时出分数和推荐理由，供本地融合计算。
API 配置从 llm_config.json 动态读取，支持运行时切换厂商/模型。
"""
import json
import re
import asyncio
import logging
import httpx
from config import LLM_TIMEOUT_MS

logger = logging.getLogger(__name__)


class LLMError(Exception):
    pass


def _get_chat_config() -> tuple[str, str, str, str]:
    try:
        from api.llm_config import get_llm_config
        cfg = get_llm_config()
        endpoint = cfg.get("endpoint", "").rstrip("/")
        api_key = cfg.get("api_key", "")
        model = cfg.get("model", "deepseek-v4-flash")
        if endpoint and api_key:
            return endpoint, api_key, model, f"{endpoint}/chat/completions"
    except Exception:
        pass
    from config import LLM_API_ENDPOINT, LLM_API_KEY, LLM_MODEL
    return LLM_API_ENDPOINT, LLM_API_KEY, LLM_MODEL, f"{LLM_API_ENDPOINT}/chat/completions"


async def chat(messages: list[dict], temperature: float = 0.3, max_tokens: int = 4096) -> str:
    endpoint, api_key, model, chat_url = _get_chat_config()
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    timeout = LLM_TIMEOUT_MS / 1000.0

    last_err = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(chat_url, headers=headers, json=payload)
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            last_err = e
            status = e.response.status_code
            logger.warning(f"LLM HTTP {status} (attempt {attempt+1}/2)")
            if status in (429, 503, 502) and attempt < 1:
                await asyncio.sleep(3)
                continue
            raise LLMError(f"HTTP {status}")
        except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as e:
            last_err = e
            logger.warning(f"LLM 连接异常 (attempt {attempt+1}/2): {type(e).__name__}")
            if attempt < 1:
                await asyncio.sleep(3)
                continue
            break

    raise LLMError(f"2次尝试后仍失败: {type(last_err).__name__}")


async def llm_score_and_rank(
    user_context: str,
    candidates: list[dict],
    field_importance: dict,
    content_type: str,
    limit: int = 4
) -> dict[str, dict]:
    """
    LLM 对候选内容评分 + 给推荐理由。

    Returns:
        {content_id: {"llm_score": float, "reason": str}, ...}
    """
    if not candidates:
        return {}

    importance_info = _build_importance_info(field_importance)

    cand_items = []
    for i, c in enumerate(candidates):
        cand_items.append(_format_candidate(i + 1, c, field_importance))
    cand_text = "\n".join(cand_items)

    type_labels = {"course": "课程", "training": "培训班", "skill": "技能岗位",
                   "scale": "测评量表", "career": "职业规划方案", "news": "资讯"}
    type_label = type_labels.get(content_type, content_type)

    prompt = f"""你是职业技能培训平台的智能推荐专家。请根据用户背景与每条候选{type_label}的【实际内容】，给出相关性评分和推荐理由。

【字段重要性说明】
{importance_info}

【用户信息】
{user_context[:600]}

【候选{type_label}列表】
{cand_text}

【评分铁律】
1. 打分必须**严格基于候选的实际内容（名称/字段文本）**，结合用户背景评估匹配度；不得仅凭用户背景臆断"该内容适合用户"。
2. **若候选内容缺失**（名称或关键字段为空/极短），说明该条信息不完整，应给**低分（score ≤ 0.3）**，reason 明确写"内容信息缺失，暂无法评估"，**严禁**虚构出具体匹配理由（如"计算机专业高度匹配"）。
3. 只对有真实内容、且与用户背景确实相关的候选给高分；内容为空的一律低分。
4. 重点看高重要性字段，忽略低重要性字段；专业不符的不推（如建筑不推IT、财务不推电工）。
5. 返回 JSON 对象，content_id 必须与候选列表完全一致：
{{"content_id值":{{"score":0.95,"reason":"15字以内理由"}},"content_id值":{{...}}}}
6. score 范围 0.0-1.0，reason 必须基于该候选的实际内容给出，不要空泛套话。"""

    logger.info(f"LLM评分: type={content_type}, {len(candidates)}条候选")
    try:
        content = await chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0, max_tokens=4096
        )
        return _parse_json_response(content.strip())
    except (httpx.TimeoutException, httpx.HTTPError) as e:
        logger.error(f"LLM网络错误: {e}")
        raise LLMError(f"网络错误: {e}")
    except json.JSONDecodeError as e:
        logger.error(f"LLM解析失败: {e}")
        raise LLMError(f"解析失败: {e}")


def _build_importance_info(field_importance: dict) -> str:
    lines = []
    sorted_fields = sorted(field_importance.items(),
                           key=lambda x: x[1].get("importance", 0), reverse=True)
    for name, info in sorted_fields:
        imp = info.get("importance", 3)
        label = info.get("field_label", name)
        desc = info.get("description", "")
        stars = "★" * imp + "☆" * (5 - imp)
        lines.append(f"  {stars} {label}{': ' + desc if desc else ''}")
    return "\n".join(lines)


def _format_candidate(index: int, item: dict, field_importance: dict) -> str:
    parts = [f"{index}. {item.get('title', '(无标题)')} (id={item.get('content_id', '')})"]
    sorted_fields = sorted(field_importance.items(),
                           key=lambda x: x[1].get("importance", 0), reverse=True)
    for name, info in sorted_fields:
        imp = info.get("importance", 1)
        if imp < 3:
            continue
        label = info.get("field_label", name)
        value = item.get(name, "")
        if value and str(value).strip():
            val_str = str(value).strip()
            if imp >= 4:
                parts.append(f"   {label}: {val_str[:300]}")
            else:
                parts.append(f"   {label}: {val_str[:100]}")
    return "\n".join(parts)


def _parse_json_response(content: str) -> dict[str, dict]:
    errors = []

    def try_parse(s: str):
        try:
            result = json.loads(s)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError as e:
            errors.append(str(e))
        return None

    # 1) 直接解析
    r = try_parse(content)
    if r: return r

    # 2) ```json ... ```
    m = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
    if m:
        r = try_parse(m.group(1).strip())
        if r: return r

    # 3) {...}
    m = re.search(r'\{[\s\S]*\}', content)
    if m:
        r = try_parse(m.group())
        if r: return r

    raise LLMError(f"无法解析LLM响应: {'; '.join(errors)}. 原始: {content[:300]}")
