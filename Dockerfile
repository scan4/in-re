FROM python:3.12-slim

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# 先装 CPU 版 torch（避免 sentence-transformers 拉取 2GB+ 的 CUDA 版）
# 本项目 BGE 模型纯 CPU 推理 (BGE_FORCE_CPU=1)
RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    --timeout 300 --retries 5 \
    torch

# Python 依赖（先装依赖层，利用 Docker 缓存；用清华镜像加速）
COPY back/requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# 源码 + 入口脚本
COPY back/ ./back/
COPY docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh

WORKDIR /app/back

EXPOSE 8000

# 入口: 首次启动建表 → 导入数据 → 生成向量 → 启动服务
ENTRYPOINT ["/app/docker-entrypoint.sh"]
