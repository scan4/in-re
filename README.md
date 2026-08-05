# 智能推荐 Agent（in-re）

基于 **FastAPI + PostgreSQL/pgvector + BGE + LLM** 的职业技能培训智能推荐系统。

## 功能特性

- **多类型内容推荐**：课程(course)、培训班(training)、技能岗位(skill)、测评量表(scale)、职业规划方案(career)、资讯(news)
- **混合推荐引擎**：BGE 语义初筛 + LLM 打分排序 + 本地融合计算（LLM×0.7 + BGE×0.1 + 字段完整性×0.05 + 时间衰减）
- **个性化推荐理由**：LLM 生成每条的推荐原因
- **冷启动策略**：新用户无画像/行为时按字段完整度推荐
- **降级与容错**：LLM 不可用时自动降级到纯 BGE/字段打分，带熔断器保护
- **Redis 缓存**：LLM 评分结果缓存 10 分钟，大幅降低延迟
- **用户权限隔离**：按用户 token 同步可见内容范围
- **定时同步**：自动从外部接口同步内容与用户行为

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | FastAPI / SQLAlchemy async / asyncpg / psycopg2 |
| 数据库 | PostgreSQL 16 + pgvector |
| 向量模型 | BGE-small-zh（本地 CPU 推理） |
| 大模型 | DeepSeek（可切换通义/Kimi/智谱） |
| 缓存 | Redis 7 |
| 前端 | React 19 + Vite（nginx 托管静态页） |
| 部署 | Docker / Docker Compose |

## 架构

```
前端(React) → FastAPI → 推荐引擎 → PostgreSQL(pgvector) + Redis + LLM
```

推荐全链路：
1. 查用户画像 + 行为
2. BGE 语义初筛（pgvector 检索，缩到 30 条）
3. LLM 对候选评分 + 出理由
4. 本地融合计算排序
5. 返回推荐 + 理由

## 快速开始（Docker）

### 1. 配置环境变量

复制 `.env.docker` 并填写真实配置：

```bash
cp .env.example .env.docker
```

需要填写的关键配置：
- `JWT_TOKEN`：外部业务接口访问凭证
- `LLM_API_KEY`：大模型 API Key

### 2. 准备 BGE 模型

模型文件较大（约 90MB），不在 git 仓库中。将 `bge-small-zh` 模型放到：

```
back/models/bge-small-zh/
```

### 3. 一键启动

```bash
./start.sh          # 一键启动（缺镜像自动构建）
./start.sh --status # 查看状态
./start.sh --logs   # 跟踪后端日志
./start.sh --stop   # 停止服务
```

或手动：

```bash
docker-compose build
docker-compose up -d
```

### 4. 访问

| 服务 | 地址 |
|------|------|
| 前端页面 | `http://<服务器IP>:5437` |
| 后端 API | `http://<服务器IP>:8000` |
| 健康检查 | `http://<服务器IP>:8000/api/v1/health` |

### 5. 端口

| 服务 | 宿主机端口 |
|------|-----------|
| 前端 nginx | 5437 |
| 后端 FastAPI | 8000 |
| PostgreSQL | 15433 |
| Redis | 6379 |

## 目录结构

```
.
├── back/                 # 后端
│   ├── api/              # 推荐/LLM配置 API
│   ├── engine/           # 推荐引擎(编排/评分/embedding/熔断)
│   ├── db/               # 数据库(建表/迁移/向量/连接)
│   ├── sync/             # 定时同步(内容/行为)
│   ├── adapters/         # 外部接口适配
│   ├── models/           # BGE 模型(不入库)
│   └── main.py           # 入口
├── front/                # 前端(React + Vite + nginx)
├── Dockerfile
├── docker-compose.yml
├── docker-entrypoint.sh
├── docker-build.sh
├── start.sh              # 一键启动脚本
└── 代码逻辑文档.md        # 详细设计与踩坑记录
```

## 详细文档

见 [代码逻辑文档.md](./代码逻辑文档.md)，包含：
- 整体架构与推荐全链路
- 各模块详解
- 数据库表结构
- 定时同步机制
- 冷启动/降级/容错策略
- Docker 部署踩坑记录
- 性能测试与优化
