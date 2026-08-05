#!/bin/bash
# ============================================================
# 智能推荐 Agent — 一键启动脚本
#
# 功能：
#   1. 检查 Docker 是否可用（权限）
#   2. 检查/构建应用镜像
#   3. 启动全部服务 (postgres + redis + app + front)
#   4. 等待就绪后展示状态与访问地址
#
# 用法：
#   ./start.sh           # 启动（缺镜像时自动构建）
#   ./start.sh --build   # 强制重新构建镜像后启动
#   ./start.sh --status  # 只查看当前状态
#   ./start.sh --stop    # 停止全部服务
#   ./start.sh --logs    # 跟踪 app 容器日志
# ============================================================
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

# 颜色
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${GREEN}[信息]${NC} $1"; }
warn()  { echo -e "${YELLOW}[警告]${NC} $1"; }
err()   { echo -e "${RED}[错误]${NC} $1"; }

ACTION="${1:-up}"

# ── 检查 docker 是否可用 ──
check_docker() {
  if ! docker info >/dev/null 2>&1; then
    err "Docker 不可用（权限或 daemon 未启动）。"
    err "若为权限问题，请先执行: newgrp docker  或 重新登录。"
    exit 1
  fi
  info "Docker 可用 ✓"
}

# ── 检查 docker-compose ──
check_compose() {
  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
  elif docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
  else
    err "未找到 docker-compose。"
    exit 1
  fi
  info "使用 compose 命令: $COMPOSE"
}

# ── 检查镜像是否已构建 ──
images_ready() {
  docker image inspect intelligent_recommendation-app >/dev/null 2>&1 && \
  docker image inspect intelligent_recommendation-front >/dev/null 2>&1
}

case "$ACTION" in
  --status)
    check_docker
    echo ""
    info "当前服务状态:"
    docker ps --filter "name=intelligent_recommendation" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' || true
    exit 0
    ;;

  --stop)
    check_docker
    info "停止全部服务..."
    docker-compose down 2>/dev/null || docker compose down 2>/dev/null || true
    info "已停止。"
    exit 0
    ;;

  --logs)
    check_docker
    info "跟踪 app 日志 (Ctrl+C 退出):"
    docker logs -f intelligent_recommendation-app-1 2>&1
    exit 0
    ;;

  --build)
    check_docker
    check_compose
    info "重新构建应用镜像..."
    $COMPOSE build
    info "镜像构建完成，启动服务..."
    $COMPOSE up -d
    ;;

  up)
    check_docker
    check_compose

    # 若镜像缺失，自动构建
    if ! images_ready; then
      warn "应用镜像不存在，开始构建（首次构建较慢，约需几分钟）..."
      $COMPOSE build
    else
      info "应用镜像已存在，直接启动。"
    fi

    info "启动全部服务..."
    $COMPOSE up -d

    # 等待 postgres / redis 健康
    info "等待数据库就绪..."
    sleep 10
    ;;

  *)
    err "未知参数: $ACTION"
    echo "用法: ./start.sh [--build | --status | --stop | --logs]"
    exit 1
    ;;
esac

# ── 展示结果 ──
echo ""
echo "============================================================"
echo "  启动完成"
echo "============================================================"
docker ps --filter "name=intelligent_recommendation" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
echo ""
echo "  前端页面:  http://<服务器IP>:5437"
echo "  后端 API:  http://<服务器IP>:8000"
echo "  健康检查:  curl http://localhost:8000/api/v1/health"
echo "  推荐接口:  POST http://localhost:8000/api/v1/recommend"
echo ""
echo "  常用命令:"
echo "    ./start.sh --status   # 查看状态"
echo "    ./start.sh --logs     # 跟踪后端日志"
echo "    ./start.sh --stop     # 停止服务"
echo "============================================================"
