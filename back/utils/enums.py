"""枚举常量定义"""

# 外部接口类型 → types 参数
API_TYPES: dict[str, str] = {
    "behavior": "atjBehavior",
    "courses":  "atjCourses",
    "training": "atjTraining",
    "skills":   "atjSkills",
    "scales":   "atjScales",
    "career":   "atjCareer",
}

# 内容类型枚举
CONTENT_TYPES = ["course", "training", "skill", "scale", "career", "news"]

# 接口类型 → 内容类型映射
API_TYPE_TO_CONTENT: dict[str, str] = {
    "courses":  "course",
    "training": "training",
    "skills":   "skill",
    "scales":   "scale",
    "career":   "career",
}

# 标签维度
TAG_CATEGORIES = [
    "industry",
    "education",
    "major",
    "skill",
    "age_group",
    "region",
    "content_type",
]

# 推荐事件类型
EVENT_TYPES = ["exposure", "click"]

# 推荐模式
MODEL_USED = ["llm", "rule"]
