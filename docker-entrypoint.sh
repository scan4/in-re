#!/bin/bash
# Docker 首次启动：初始化数据库 + 导入默认配置
set -e

echo "===== 数据库初始化 ====="

# 等待 PG 就绪
until pg_isready -h postgres -U pei -d recommend_agent 2>/dev/null; do
  echo "  等待 postgres..."
  sleep 2
done

# 创建 pgvector 扩展
python3 -c "
import psycopg2
conn = psycopg2.connect('$PGPOOL_DSN')
conn.autocommit = True
conn.cursor().execute('CREATE EXTENSION IF NOT EXISTS vector')
print('  pgvector extension OK')
conn.close()
"

# 建表
python3 -c "
import asyncio
from db.schema_v3 import get_schema_sql
import psycopg2
conn = psycopg2.connect('$PGPOOL_DSN')
conn.cursor().execute(get_schema_sql())
conn.commit()
conn.close()
print('  Schema created')
"

# 导入样例用户行为数据（旧表 content_index 迁移已废弃，全新部署不需要）
python3 -c "
import asyncio
from db.migrate_v3 import insert_user_behaviors
asyncio.run(insert_user_behaviors())
print('  Sample user behaviors imported')
"

# 生成 BGE 向量 + IVFFlat 索引
python3 -c "
import asyncio
from db.populate_vectors import populate_vectors, build_ivfflat_index
asyncio.run(populate_vectors())
build_ivfflat_index()
print('  Vectors populated + IVFFlat index created')
"

echo "===== 初始化完成，启动服务 ====="
exec python3 main.py
