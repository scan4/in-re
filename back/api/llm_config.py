"""LLM 厂商配置管理 — 侧边栏保存后即时生效"""
import json
import os
import logging
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/config", tags=["llm-config"])
logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "llm_config.json")

VENDOR_PRESETS = {
    "siliconflow": {
        "label": "硅基流动",
        "endpoint": "https://api.siliconflow.cn/v1",
        "default_model": "Qwen/Qwen2.5-7B-Instruct",
    },
    "deepseek": {
        "label": "DeepSeek",
        "endpoint": "https://api.deepseek.com/v1",
        "default_model": "deepseek-v4-flash",
    },
    "qwen": {
        "label": "通义千问",
        "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
    },
    "kimi": {
        "label": "Kimi (月之暗面)",
        "endpoint": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k",
    },
    "zhipu": {
        "label": "智谱 GLM",
        "endpoint": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4-flash",
    },
}


class LLMConfigSave(BaseModel):
    vendor: str
    api_key: str | None = ""
    model: str | None = ""


def _load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {"vendor": "deepseek", "api_key": "", "model": "deepseek-v4-flash",
                "endpoint": "https://api.deepseek.com/v1"}


def _save_config(cfg: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def get_llm_config() -> dict:
    """供 llm_scorer 等模块调用，返回当前有效的 LLM 配置"""
    return _load_config()


@router.get("/llm")
async def get_config():
    """获取当前 LLM 配置 + 可用厂商列表"""
    cfg = _load_config()
    # 隐藏 api_key 部分字符
    masked = dict(cfg)
    if masked.get("api_key") and len(masked["api_key"]) > 8:
        masked["api_key"] = masked["api_key"][:4] + "****" + masked["api_key"][-4:]
    return {
        "current": masked,
        "vendors": {
            k: {"label": v["label"], "endpoint": v["endpoint"], "default_model": v["default_model"]}
            for k, v in VENDOR_PRESETS.items()
        },
    }


@router.post("/llm")
async def save_config(data: LLMConfigSave):
    """保存 LLM 配置，并清空 Redis 缓存（避免新旧模型缓存混淆）"""
    vendor = data.vendor
    preset = VENDOR_PRESETS.get(vendor)
    if not preset:
        return {"code": 400, "message": f"不支持的厂商: {vendor}，可选: {list(VENDOR_PRESETS.keys())}"}

    model = data.model or preset["default_model"]

    cfg = {
        "vendor": vendor,
        "api_key": data.api_key or "",
        "model": model,
        "endpoint": preset["endpoint"],
    }
    _save_config(cfg)
    logger.info(f"LLM 配置已更新: vendor={vendor}, model={model}")

    # 清 Redis 缓存，避免新模型读到旧评分
    try:
        from db.redis_client import get_redis
        r = await get_redis()
        await r.flushall()
        logger.info("Redis 已清空（LLM 配置变更）")
    except Exception as e:
        logger.warning(f"清空 Redis 失败（不影响功能）: {e}")

    return {"code": 200, "message": "配置已保存，缓存已清空"}
