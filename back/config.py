"""环境变量配置"""
import os
from dotenv import load_dotenv

load_dotenv()

# 服务
API_PORT = int(os.getenv("API_PORT", "8000"))

# PostgreSQL
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql:///recommend_agent"
)

# 外部业务接口
JWT_TOKEN = os.getenv("JWT_TOKEN", "")
EXTERNAL_API_BASE = os.getenv(
    "EXTERNAL_API_BASE",
    "https://tytmp.com/lscdp/public/index.php/apis/Index/"
)

# 大模型 (DeepSeek)
LLM_PLATFORM = os.getenv("LLM_PLATFORM", "deepseek")
LLM_API_ENDPOINT = os.getenv("LLM_API_ENDPOINT", "https://api.deepseek.com/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash")
LLM_TIMEOUT_MS = int(os.getenv("LLM_TIMEOUT_MS", "5000"))

# 同步间隔 (分钟)
SYNC_INTERVAL_CONTENT = int(os.getenv("SYNC_INTERVAL_CONTENT", "30"))
SYNC_INTERVAL_BEHAVIOR = int(os.getenv("SYNC_INTERVAL_BEHAVIOR", "5"))

# 日志
LOG_LEVEL = os.getenv("LOG_LEVEL", "info")
