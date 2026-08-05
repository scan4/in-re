"""
新版数据库表结构 — 分内容类型建表 + 字段重要性配置 + 用户行为表

架构思路：
1. 每种内容类型独立一张表，保留原始接口字段
2. 每张表的字段定义重要性分级（1-5级），LLM 据此打分
3. 用户行为独立存储，供 LLM 理解用户画像
"""

# ─── 表结构 SQL ───

SCHEMA_SQL = """

-- ============================================================
-- 1. 字段重要性分级配置表
--    每张表的每个字段定义 importance (1-5, 5最重要)
-- ============================================================

DROP TABLE IF EXISTS field_importance CASCADE;
CREATE TABLE field_importance (
    id              SERIAL PRIMARY KEY,
    table_name      VARCHAR(64)   NOT NULL,    -- 表名: courses / training_classes / ...
    field_name      VARCHAR(64)   NOT NULL,    -- 字段名
    field_label     VARCHAR(128)  NOT NULL,    -- 字段中文名
    importance      INTEGER       NOT NULL DEFAULT 3 CHECK (importance BETWEEN 1 AND 5),
    description     TEXT,                      -- 说明
    weight          FLOAT         NOT NULL DEFAULT 1.0,  -- 打分权重系数
    UNIQUE(table_name, field_name)
);

-- ── 预置字段重要性数据 ──

-- 课程 (courses)
INSERT INTO field_importance (table_name, field_name, field_label, importance, description, weight) VALUES
('courses', 'name',    '课程名称',   5, '课程名称是最核心匹配字段', 2.0),
('courses', 'texts1',  '课程受众',   4, '受众群体决定推荐范围', 1.5),
('courses', 'texts3',  '授课形式',   3, '线上/线下影响推荐', 1.0),
('courses', 'texts2',  '课程收益',   4, '学习后能获得什么', 1.5),
('courses', 'texts4',  '课程大纲',   4, '大纲是内容核心', 1.5),
('courses', 'num_xs',  '课程编号',   1, '仅作文本参考', 0.3);

-- 培训班 (training_classes)
INSERT INTO field_importance (table_name, field_name, field_label, importance, description, weight) VALUES
('training_classes', 'name',       '班级名称',   5, '名称是最核心匹配字段', 2.0),
('training_classes', 'classify',   '所属类别',   4, '类别影响推荐精准度', 1.2),
('training_classes', 'training',   '培训内容',   5, '培训内容直接决定匹配', 2.0),
('training_classes', 'regions',    '适用区域',   3, '地域影响推荐', 1.0),
('training_classes', 'places',     '培训地点',   2, '具体地点', 0.5),
('training_classes', 'certif',     '是否有证书', 2, '辅助筛选', 0.5),
('training_classes', 'start_apply','报名开始',   2, '时效性', 0.5),
('training_classes', 'end_apply',  '报名截止',   2, '时效性', 0.5),
('training_classes', 'start_study','学习开始',   2, '时效性', 0.5),
('training_classes', 'end_study',  '学习截止',   2, '时效性', 0.5),
('training_classes', 'limits',     '限制人数',   1, '非匹配关键字段', 0.2);

-- 技能岗位 (skill_positions)
INSERT INTO field_importance (table_name, field_name, field_label, importance, description, weight) VALUES
('skill_positions', 'name',     '岗位名称',   5, '岗位名称是核心', 2.0),
('skill_positions', 'trade',    '所属行业',   5, '行业直接决定相关性', 2.0),
('skill_positions', 'grade',    '所属产业',   3, '产业分类', 1.0),
('skill_positions', 'major',    '专业要求',   5, '专业是否对口', 2.0),
('skill_positions', 'degree',   '学历要求',   4, '学历是否匹配', 1.5),
('skill_positions', 'working',  '经验要求',   3, '经验要求', 1.0),
('skill_positions', 'years',    '工作年限',   2, '年限参考', 0.5),
('skill_positions', 'salary',   '岗位薪资',   1, '薪资属于次要', 0.3);

-- 测评量表 (assessment_scales)
INSERT INTO field_importance (table_name, field_name, field_label, importance, description, weight) VALUES
('assessment_scales', 'name',      '量表名称',   5, '名称是核心', 2.0),
('assessment_scales', 'texts1',    '测评介绍',   5, '介绍文本是最丰富的匹配源', 2.0),
('assessment_scales', 'values',    '适用人群',   5, '适用人群决定推荐给谁', 2.0),
('assessment_scales', 'tags',      '标签标识',   3, '辅助标签', 0.8),
('assessment_scales', 'pnums',     '题目总数',   1, '非匹配关键字段', 0.2),
('assessment_scales', 'ptimes',    '平均用时',   1, '非匹配关键字段', 0.2);

-- 职业规划方案 (career_plans)
INSERT INTO field_importance (table_name, field_name, field_label, importance, description, weight) VALUES
('career_plans', 'name',    '方案名称',   5, '名称是核心', 2.0),
('career_plans', 'content', '方案内容',   5, '内容文本是匹配关键', 2.0);

-- 资讯 (news)
INSERT INTO field_importance (table_name, field_name, field_label, importance, description, weight) VALUES
('news', 'title',     '资讯标题',   5, '标题是核心', 2.0),
('news', 'summary',   '资讯摘要',   4, '摘要辅助匹配', 1.5),
('news', 'content',   '资讯正文',   5, '正文是最丰富的匹配源', 2.0),
('news', 'category',  '资讯分类',   4, '分类指引大方向', 1.5),
('news', 'source',    '来源',      1, '非匹配关键字段', 0.2);


-- ============================================================
-- 2. 课程表
-- ============================================================

DROP TABLE IF EXISTS courses CASCADE;
CREATE TABLE courses (
    id              SERIAL PRIMARY KEY,
    origin_id       VARCHAR(64)   NOT NULL UNIQUE,      -- 外部接口原始 ID
    num_xs          VARCHAR(64),                        -- 课程编号
    name            VARCHAR(256)  NOT NULL,             -- 课程名称
    texts1          TEXT,                               -- 课程受众
    texts2          TEXT,                               -- 课程收益
    texts3          TEXT,                               -- 授课形式
    texts4          TEXT,                               -- 课程大纲
    status          VARCHAR(16)   NOT NULL DEFAULT 'active',
    created_at      TIMESTAMP     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP     NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_courses_name ON courses(name);
CREATE INDEX idx_courses_status ON courses(status);


-- ============================================================
-- 3. 培训班表
-- ============================================================

DROP TABLE IF EXISTS training_classes CASCADE;
CREATE TABLE training_classes (
    id              SERIAL PRIMARY KEY,
    origin_id       VARCHAR(64)   NOT NULL UNIQUE,
    snum            VARCHAR(64),                        -- 班级编号
    name            VARCHAR(256)  NOT NULL,             -- 班级名称
    classify        VARCHAR(128),                       -- 所属类别
    start_apply     VARCHAR(32),                        -- 报名开始日期
    end_apply       VARCHAR(32),                        -- 报名截止日期
    start_study     VARCHAR(32),                        -- 学习开始日期
    end_study       VARCHAR(32),                        -- 学习截止日期
    limits          INTEGER,                            -- 限制人数
    regions         VARCHAR(256),                       -- 适用区域
    places          VARCHAR(256),                       -- 培训地点
    training        TEXT,                               -- 培训内容
    certif          VARCHAR(32),                        -- 是否有证书
    deleted         VARCHAR(16)   DEFAULT '正常',       -- 正常/停用
    status          VARCHAR(16)   NOT NULL DEFAULT 'active',
    created_at      TIMESTAMP     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP     NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_training_name ON training_classes(name);
CREATE INDEX idx_training_status ON training_classes(status);


-- ============================================================
-- 4. 技能岗位表
-- ============================================================

DROP TABLE IF EXISTS skill_positions CASCADE;
CREATE TABLE skill_positions (
    id              SERIAL PRIMARY KEY,
    origin_id       VARCHAR(64)   NOT NULL UNIQUE,
    trade           VARCHAR(128)  NOT NULL,             -- 所属行业
    grade           VARCHAR(128),                       -- 所属产业
    codes           VARCHAR(64),                        -- 岗位编号
    name            VARCHAR(256)  NOT NULL,             -- 岗位名称
    years           VARCHAR(32),                        -- 工作年限
    salary          VARCHAR(64),                        -- 岗位薪资
    degree          VARCHAR(64),                        -- 学历要求
    major           VARCHAR(128),                       -- 专业要求
    working         VARCHAR(128),                       -- 经验要求
    status          VARCHAR(16)   NOT NULL DEFAULT 'active',
    created_at      TIMESTAMP     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP     NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_skill_name ON skill_positions(name);
CREATE INDEX idx_skill_trade ON skill_positions(trade);
CREATE INDEX idx_skill_major ON skill_positions(major);
CREATE INDEX idx_skill_status ON skill_positions(status);


-- ============================================================
-- 5. 测评量表表
-- ============================================================

DROP TABLE IF EXISTS assessment_scales CASCADE;
CREATE TABLE assessment_scales (
    id              SERIAL PRIMARY KEY,
    origin_id       VARCHAR(64)   NOT NULL UNIQUE,
    product_id      INTEGER,                            -- 产品 ID
    name            VARCHAR(256)  NOT NULL,             -- 产品名称
    tags            VARCHAR(128),                       -- 标识
    pnums           INTEGER,                            -- 题目总数
    ptimes          INTEGER,                            -- 平均用时（分钟）
    texts1          TEXT,                               -- 测评介绍
    vals            TEXT,                               -- 适用人群
    status          VARCHAR(16)   NOT NULL DEFAULT 'active',
    created_at      TIMESTAMP     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP     NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_scale_name ON assessment_scales(name);
CREATE INDEX idx_scale_status ON assessment_scales(status);


-- ============================================================
-- 6. 职业规划方案表
-- ============================================================

DROP TABLE IF EXISTS career_plans CASCADE;
CREATE TABLE career_plans (
    id              SERIAL PRIMARY KEY,
    origin_id       VARCHAR(64)   NOT NULL UNIQUE,
    name            VARCHAR(256)  NOT NULL,             -- 方案名称
    content         TEXT,                               -- 方案内容
    status          VARCHAR(16)   NOT NULL DEFAULT 'active',
    created_at      TIMESTAMP     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP     NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_career_name ON career_plans(name);
CREATE INDEX idx_career_status ON career_plans(status);


-- ============================================================
-- 7. 资讯表
-- ============================================================

DROP TABLE IF EXISTS news CASCADE;
CREATE TABLE news (
    id              SERIAL PRIMARY KEY,
    origin_id       VARCHAR(64)   NOT NULL UNIQUE,
    title           VARCHAR(256)  NOT NULL,             -- 资讯标题
    summary         TEXT,                               -- 资讯摘要
    content         TEXT,                               -- 资讯正文
    category        VARCHAR(128),                       -- 资讯分类
    source          VARCHAR(128),                       -- 来源
    publish_time    TIMESTAMP,                          -- 发布时间
    status          VARCHAR(16)   NOT NULL DEFAULT 'active',
    created_at      TIMESTAMP     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP     NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_news_title ON news(title);
CREATE INDEX idx_news_category ON news(category);
CREATE INDEX idx_news_status ON news(status);


-- ============================================================
-- 8. 用户行为记录表（替代原先的 behavior_* 存到 content_index）
-- ============================================================

DROP TABLE IF EXISTS user_behaviors CASCADE;
CREATE TABLE user_behaviors (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR(64)   NOT NULL,             -- 用户ID
    user_name       VARCHAR(64),                        -- 用户姓名
    behavior_type   VARCHAR(32)   NOT NULL,             -- browsing/search/learning
    content         TEXT          NOT NULL,             -- 行为内容文本
    extra_info      JSONB,                              -- 额外信息（学习时长等）
    event_time      TIMESTAMP     NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMP     NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_behav_user ON user_behaviors(user_id);
CREATE INDEX idx_behav_type ON user_behaviors(behavior_type);
CREATE INDEX idx_behav_name ON user_behaviors(user_name);


-- ============================================================
-- 9. 推荐日志表（保留，增加字段）
-- ============================================================

-- recommend_log 保留原有结构，如果不存在则创建
CREATE TABLE IF NOT EXISTS recommend_log (
    id              BIGSERIAL PRIMARY KEY,
    user_id         VARCHAR(64)   NOT NULL,
    user_name       VARCHAR(64),
    trace_id        VARCHAR(64)   NOT NULL,
    event_type      VARCHAR(16)   NOT NULL,             -- exposure / click
    content_id      VARCHAR(64),
    content_type    VARCHAR(32),
    position        INTEGER,
    score           FLOAT,
    event_time      TIMESTAMP     NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMP     NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_log_user ON recommend_log(user_id);
CREATE INDEX IF NOT EXISTS idx_log_trace ON recommend_log(trace_id);


-- ============================================================
-- 10. 同步日志表（保留原结构）
-- ============================================================

-- sync_log 保留原有，不再重建


-- ============================================================
-- 11. 用户画像表（保留原结构，不再依赖旧标签体系）
-- ============================================================

-- user_profile 表保留原有结构

"""


def get_schema_sql() -> str:
    """获取建表 SQL"""
    return SCHEMA_SQL


# ─── 表名 → 内容类型映射 ───
TABLE_NAME_MAP = {
    "course": "courses",
    "training": "training_classes",
    "skill": "skill_positions",
    "scale": "assessment_scales",
    "career": "career_plans",
    "news": "news",
}
