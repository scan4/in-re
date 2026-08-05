"""BGE Embedding 模块 — 本地模型生成文本向量，纯 CPU 多线程"""
import os
import asyncio
import logging
import numpy as np
from functools import lru_cache
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", "bge-small-zh")

# 强制 CPU — 当前环境 4 张 RTX 4090 被 OCR 任务占满 (96-100%)，
# 我们的进程根本拿不到 GPU，强行 GPU 反而会排队等待。
# 384 核 CPU 空闲 ~378 核，纯 CPU 多线程跑 BGE 远比争抢 GPU 快。
FORCE_CPU = os.environ.get("BGE_FORCE_CPU", "1") == "1"


@lru_cache(maxsize=1)
def _load_model():
    import torch
    # 限制 torch 内部 OpenMP 线程数：
    # BGE 是小模型，单次编码本身很快，默认 get_num_threads() 会等于 CPU 核数(96)。
    # 高并发下，多个请求 × 96 线程会严重争抢 CPU 核（线程过载 + 频繁上下文切换），
    # 反而比单线程慢。并发靠多 worker(多进程) 真正并行，单次编码用单线程即可。
    try:
        torch.set_num_threads(int(os.environ.get("BGE_NUM_THREADS", "1")))
        logger.info(f"torch.set_num_threads = {torch.get_num_threads()}")
    except Exception as e:
        logger.warning(f"设置 torch 线程数失败: {e}")

    device = "cpu"
    if not FORCE_CPU:
        try:
            if torch.cuda.is_available():
                device = f"cuda:{torch.cuda.current_device()}"
                logger.info(f"检测到 GPU: {torch.cuda.get_device_name()} → 使用 {device}")
        except ImportError:
            pass
    logger.info(f"加载 BGE 模型: {MODEL_PATH} (device={device})")
    return SentenceTransformer(MODEL_PATH, device=device)


def encode_text(text: str) -> list[float]:
    """单条文本 → 512 维向量（跑在线程池中，不阻塞事件循环）"""
    if not text or not text.strip():
        return [0.0] * 512
    model = _load_model()
    vec = model.encode(text.strip(), normalize_embeddings=True)
    return vec.tolist()


def encode_batch(texts: list[str]) -> list[list[float]]:
    """批量编码（跑在线程池中，高度并行）"""
    model = _load_model()
    vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vecs.tolist()


async def encode_text_async(text: str) -> list[float]:
    """单条文本 → 向量（异步，扔到独立线程不阻塞事件循环）"""
    return await asyncio.to_thread(encode_text, text)


async def encode_batch_async(texts: list[str]) -> list[list[float]]:
    """批量编码（异步，跑在线程池并行）"""
    return await asyncio.to_thread(encode_batch, texts)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    arr_a, arr_b = np.array(a), np.array(b)
    return float(np.dot(arr_a, arr_b))
