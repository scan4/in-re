#!/bin/bash
# ============================================================
# Docker 打包构建脚本（在服务器/构建机上执行）
#
# 功能：
#   1. 构建后端镜像 (in-re-agent-app)
#   2. 构建前端镜像 (in-re-agent-front)
#   3. 通过 docker-compose 启动整个项目
#
# 用法：
#   ./docker-build.sh           # 构建并启动
#   ./docker-build.sh --build   # 仅构建不启动
#   ./docker-build.sh --save    # 构建并导出镜像压缩包（用于拷贝到内网机）
#   ./docker-build.sh --load    # 导入镜像压缩包并启动（目标机上用）
#   ./docker-build.sh --down    # 停止并删除容器
# ============================================================

set -e
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

ACTION="${1:-up}"

case "$ACTION" in
  --build)
    echo "== 构建镜像（不启动） =="
    docker compose build
    ;;
  --save)
    echo "== 构建并导出镜像压缩包 =="
    docker compose build
    docker save -o in-re-agent-images.tar in-re-agent-app:latest in-re-agent-front:latest
    echo "已导出到: $PROJECT_DIR/in-re-agent-images.tar"
    echo "拷贝到目标机后，在目标机执行: ./docker-build.sh --load"
    ;;
  --load)
    echo "== 导入镜像并启动 =="
    docker load -i in-re-agent-images.tar
    docker compose up -d
    ;;
  --down)
    echo "== 停止并删除容器 =="
    docker compose down
    ;;
  --restart)
    echo "== 重启服务 =="
    docker compose restart
    ;;
  *)
    echo "== 构建并启动 =="
    docker compose build
    docker compose up -d
    ;;
esac

echo ""
echo "========== 完成 =========="
echo "  前端页面: http://<服务器IP>            (nginx 80端口)"
echo "  后端 API: http://<服务器IP>:8000"
echo "  健康检查: curl http://<服务器IP>:8000/api/v1/health"
echo "==========================="
