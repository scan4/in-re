"""
数据库建表脚本 V3 — 字段严格对齐 API 接口文档，不额外扩充。
每张表只保留：API 返回字段 + 内部 id(主键) + status + sync_at(同步时间)
"""
SCHEMA_V3 = """

-- ============================================================
-- 1. 课程表 — 对应 atjCourses 接口
--    字段完全按文档, Text2/Texts3/Texts4 是「必须」
-- ============================================================
DROP TABLE IF EXISTS courses CASCADE;
CREATE TABLE courses (
    origin_id   VARCHAR(64)   NOT NULL UNIQUE,      -- API: id (必须)
    num_xs      VARCHAR(64),                        -- API: numXs
    name        VARCHAR(256),                       -- API: name
    texts1      TEXT,                               -- API: texts1 (课程受众)
    texts2      TEXT,                               -- API: Texts2 (必须, 课程收益)
    texts3      TEXT,                               -- API: Texts3 (必须, 授课形式)
    texts4      TEXT,                               -- API: Texts4 (必须, 课程大纲)
    -- 以下为内部运维字段
    id          SERIAL PRIMARY KEY,
    status      VARCHAR(16)   NOT NULL DEFAULT 'active',
    has_vector  BOOLEAN       NOT NULL DEFAULT FALSE,  -- 是否已生成向量
    content_hash VARCHAR(64),                          -- 内容指纹(MD5), 增量同步判断
    sync_at     TIMESTAMP     NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_courses_status ON courses(status);


-- ============================================================
-- 2. 培训班表 — 对应 atjTraining 接口
--    snum/name/startApply/endApply/startStudy/endStudy/limits/training 是「必须」
-- ============================================================
DROP TABLE IF EXISTS training_classes CASCADE;
CREATE TABLE training_classes (
    origin_id   VARCHAR(64)   NOT NULL UNIQUE,      -- API: id (必须)
    snum        VARCHAR(64),                        -- API: snum (必须)
    name        VARCHAR(256),                       -- API: name (必须)
    classify    VARCHAR(128),                       -- API: classify
    start_apply VARCHAR(32),                        -- API: startApply (必须)
    end_apply   VARCHAR(32),                        -- API: endApply (必须)
    start_study VARCHAR(32),                        -- API: startStudy (必须)
    end_study   VARCHAR(32),                        -- API: endStudy (必须)
    limits      INTEGER,                            -- API: limits (必须)
    regions     VARCHAR(256),                       -- API: regions
    places      VARCHAR(256),                       -- API: places
    training    TEXT,                               -- API: training (必须)
    certif      VARCHAR(32),                        -- API: certif
    deleted     VARCHAR(16)   DEFAULT '正常',       -- API: deleted
    -- 内部运维
    id          SERIAL PRIMARY KEY,
    status      VARCHAR(16)   NOT NULL DEFAULT 'active',
    has_vector  BOOLEAN       NOT NULL DEFAULT FALSE,  -- 是否已生成向量
    content_hash VARCHAR(64),                          -- 内容指纹(MD5), 增量同步判断
    sync_at     TIMESTAMP     NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_training_status ON training_classes(status);


-- ============================================================
-- 3. 技能岗位表 — 对应 atjSkills 接口
--    全部字段标记为「必须」
-- ============================================================
DROP TABLE IF EXISTS skill_positions CASCADE;
CREATE TABLE skill_positions (
    origin_id   VARCHAR(64)   NOT NULL UNIQUE,      -- API: id (必须)
    trade       VARCHAR(128),                       -- API: trade (必须)
    grade       VARCHAR(128),                       -- API: grade (必须)
    codes       VARCHAR(64),                        -- API: codes (必须)
    name        VARCHAR(256),                       -- API: name (必须)
    years       VARCHAR(32),                        -- API: years (必须)
    salary      VARCHAR(64),                        -- API: salary (必须)
    degree      VARCHAR(64),                        -- API: degree (必须)
    major       VARCHAR(128),                       -- API: major (必须)
    working     VARCHAR(128),                       -- API: working (必须)
    -- 内部运维
    id          SERIAL PRIMARY KEY,
    status      VARCHAR(16)   NOT NULL DEFAULT 'active',
    has_vector  BOOLEAN       NOT NULL DEFAULT FALSE,  -- 是否已生成向量
    content_hash VARCHAR(64),                          -- 内容指纹(MD5), 增量同步判断
    sync_at     TIMESTAMP     NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_skill_status ON skill_positions(status);


-- ============================================================
-- 4. 测评量表表 — 对应 atjScales 接口
--    name/ptimes/texts1/values 是「必须」
--    2026-08-03: 新增 productId/pnums/ptimes；vals → values 改名
-- ============================================================
DROP TABLE IF EXISTS assessment_scales CASCADE;
CREATE TABLE assessment_scales (
    origin_id   VARCHAR(64)   NOT NULL UNIQUE,      -- API: id (必须)
    product_id  INTEGER,                            -- API: productId (新增)
    name        VARCHAR(256),                       -- API: name (必须)
    tags        VARCHAR(128),                       -- API: tags
    pnums       INTEGER,                            -- API: pnums (新增)
    ptimes      INTEGER,                            -- API: ptimes (必须)
    texts1      TEXT,                               -- API: texts1 (必须, 测评介绍)
    vals        TEXT,                               -- API: values (必须, 适用人群, 原名 vals)
    -- 内部运维
    id          SERIAL PRIMARY KEY,
    status      VARCHAR(16)   NOT NULL DEFAULT 'active',
    has_vector  BOOLEAN       NOT NULL DEFAULT FALSE,  -- 是否已生成向量
    content_hash VARCHAR(64),                          -- 内容指纹(MD5), 增量同步判断
    sync_at     TIMESTAMP     NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_scale_status ON assessment_scales(status);


-- ============================================================
-- 5. 职业规划方案表 — 对应 atjCareer 接口
--    2026-08-03: 字段大改 (name→title, texts1→details, 新增9个字段)
-- ============================================================
DROP TABLE IF EXISTS career_plans CASCADE;
CREATE TABLE career_plans (
    origin_id   VARCHAR(64)   NOT NULL UNIQUE,      -- API: id (必须)
    customId    VARCHAR(64),                        -- API: customId (必须, 单位ID)
    staffId     VARCHAR(64),                        -- API: staffId (必须, 个人ID)
    name        TEXT,                               -- API: title (必须, 职业规划名称)
    crouds      TEXT,                               -- API: crouds (必须, 使用人群)
    emphasis    TEXT,                               -- API: emphasis (必须, 规划重点)
    actions     TEXT,                               -- API: actions (关键行动)
    tools       TEXT,                               -- API: tools (测评工具)
    details     TEXT,                               -- API: details (必须, 详细规划, 原名 texts1)
    position    TEXT,                               -- API: position (岗位信息, 内容较长用TEXT)
    remarks     TEXT,                               -- API: remarks (备注信息)
    addTime     VARCHAR(32),                        -- API: addTime (必须, 添加时间)
    raw_data    JSONB,                              -- 全量原始数据兜底
    -- 内部运维
    id          SERIAL PRIMARY KEY,
    status      VARCHAR(16)   NOT NULL DEFAULT 'active',
    has_vector  BOOLEAN       NOT NULL DEFAULT FALSE,  -- 是否已生成向量
    content_hash VARCHAR(64),                          -- 内容指纹(MD5), 增量同步判断
    sync_at     TIMESTAMP     NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_career_status ON career_plans(status);


-- ============================================================
-- 6. 资讯表 — 接口文档标注"接口未就绪"
--    现阶段只存 origin_id + title，等接口就绪后再补字段
-- ============================================================
DROP TABLE IF EXISTS news CASCADE;
CREATE TABLE news (
    origin_id   VARCHAR(64)   NOT NULL UNIQUE,      -- 唯一标识
    title       VARCHAR(256),                       -- 标题
    raw_data    JSONB,                              -- 全量原始数据兜底(就绪后有更多字段时也是先存在这里)
    -- 内部运维
    id          SERIAL PRIMARY KEY,
    status      VARCHAR(16)   NOT NULL DEFAULT 'active',
    has_vector  BOOLEAN       NOT NULL DEFAULT FALSE,  -- 是否已生成向量
    content_hash VARCHAR(64),                          -- 内容指纹(MD5), 增量同步判断
    sync_at     TIMESTAMP     NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_news_status ON news(status);


-- ============================================================
-- 7. 用户行为记录表 — 统一存储浏览/搜索/学习
-- ============================================================
DROP TABLE IF EXISTS user_behaviors CASCADE;
CREATE TABLE user_behaviors (
    origin_id     VARCHAR(64)   UNIQUE,             -- API: id (行为记录唯一标识, 去重用)
    user_id       VARCHAR(64)   NOT NULL,           -- API: ausers
    user_name     VARCHAR(64),                      -- API: anames
    behavior_type VARCHAR(32)   NOT NULL,           -- browsing / search / learning
    content       TEXT          NOT NULL,           -- API: contents
    extra_info    JSONB,                            -- 扩展信息(学习时长等)
    event_time    TIMESTAMP     NOT NULL DEFAULT NOW(),
    -- 内部运维
    id            SERIAL PRIMARY KEY,
    created_at    TIMESTAMP     NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_behav_user  ON user_behaviors(user_id);
CREATE INDEX idx_behav_type  ON user_behaviors(behavior_type);
CREATE INDEX idx_behav_name  ON user_behaviors(user_name);


-- ============================================================
-- 8. 字段重要性分级配置表（和 API 无关，是推荐引擎的配置）
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
INSERT INTO field_importance (table_name, field_name, field_label, importance, description, weight) VALUES
('courses', 'name',    '课程名称',   5, '课程名称是最核心匹配字段', 2.0),
('courses', 'texts1',  '课程受众',   4, '受众群体决定推荐范围', 1.5),
('courses', 'texts3',  '授课形式',   3, '线上/线下影响推荐', 1.0),
('courses', 'texts2',  '课程收益',   4, '学习后能获得什么', 1.5),
('courses', 'texts4',  '课程大纲',   4, '大纲是内容核心', 1.5),
('courses', 'num_xs',  '课程编号',   1, '仅作文本参考', 0.3),
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
('training_classes', 'limits',     '限制人数',   1, '非匹配关键字段', 0.2),
('skill_positions', 'name',     '岗位名称',   5, '岗位名称是核心', 2.0),
('skill_positions', 'trade',    '所属行业',   5, '行业直接决定相关性', 2.0),
('skill_positions', 'grade',    '所属产业',   3, '产业分类', 1.0),
('skill_positions', 'major',    '专业要求',   5, '专业是否对口', 2.0),
('skill_positions', 'degree',   '学历要求',   4, '学历是否匹配', 1.5),
('skill_positions', 'working',  '经验要求',   3, '经验要求', 1.0),
('skill_positions', 'years',    '工作年限',   2, '年限参考', 0.5),
('skill_positions', 'salary',   '岗位薪资',   1, '薪资属于次要', 0.3),
('assessment_scales', 'name',      '量表名称',   5, '名称是核心', 2.0),
('assessment_scales', 'texts1',    '测评介绍',   5, '介绍文本是最丰富的匹配源', 2.0),
('assessment_scales', 'values',    '适用人群',   5, '适用人群决定推荐给谁', 2.0),
('assessment_scales', 'tags',      '标签标识',   3, '辅助标签', 0.8),
('assessment_scales', 'pnums',     '题目总数',   1, '非匹配关键字段', 0.2),
('assessment_scales', 'ptimes',    '平均用时',   1, '非匹配关键字段', 0.2),
('career_plans', 'name',    '方案名称',   5, '名称是核心', 2.0),
('career_plans', 'content', '方案内容',   5, '内容文本是匹配关键', 2.0),
('news', 'title',     '资讯标题',   5, '标题是核心', 2.0),
('news', 'summary',   '资讯摘要',   4, '摘要辅助匹配', 1.5),
('news', 'content',   '资讯正文',   5, '正文是最丰富的匹配源', 2.0),
('news', 'category',  '资讯分类',   4, '分类指引大方向', 1.5),
('news', 'source',    '来源',      1, '非匹配关键字段', 0.2);


-- ============================================================
-- 9. 向量缓存表 — 存储 BGE 生成的内容向量，供 pgvector 检索
-- ============================================================
DROP TABLE IF EXISTS content_vectors CASCADE;
CREATE TABLE content_vectors (
    id            SERIAL PRIMARY KEY,
    content_id    VARCHAR(64)   NOT NULL UNIQUE,  -- 对应各内容表的 origin_id
    content_type  VARCHAR(32)   NOT NULL,         -- course / training / skill / scale / career / news
    embedding     VECTOR(512)   NOT NULL,         -- BGE 512 维向量
    cached_at     TIMESTAMP     NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_content_vectors_type ON content_vectors(content_type);
CREATE INDEX idx_content_vectors_content_id ON content_vectors(content_id);


-- ============================================================
-- 10. 同步日志表 — 记录每次定时同步的结果
-- ============================================================
DROP TABLE IF EXISTS sync_log CASCADE;
CREATE TABLE sync_log (
    id             SERIAL PRIMARY KEY,
    api_type       VARCHAR(32)   NOT NULL,          -- courses / training / skills / ...
    status         VARCHAR(16)   NOT NULL,          -- success / failed
    records_count  INTEGER       NOT NULL DEFAULT 0,
    error_message  TEXT,
    duration_ms    INTEGER       NOT NULL DEFAULT 0,
    started_at     TIMESTAMP     NOT NULL DEFAULT NOW(),
    finished_at    TIMESTAMP     NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_sync_log_type ON sync_log(api_type);
CREATE INDEX idx_sync_log_time ON sync_log(started_at);


-- ============================================================
-- 11. 用户画像表 — 用户个性化画像
-- ============================================================
DROP TABLE IF EXISTS user_profile CASCADE;
CREATE TABLE user_profile (
    user_id                 VARCHAR(64)   NOT NULL PRIMARY KEY,
    base_tags               JSONB         NOT NULL DEFAULT '{}',  -- {name, education, major, college, skills, age_group}
    behavior_tags           JSONB         NOT NULL DEFAULT '{}',  -- 用户行为标签
    preferred_content_types JSONB         NOT NULL DEFAULT '[]',  -- 偏好内容类型
    last_active_at          TIMESTAMP     NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMP     NOT NULL DEFAULT NOW()
);


-- ============================================================
-- 12. 用户可见内容权限表 — 用户级内容权限隔离
-- ============================================================
DROP TABLE IF EXISTS user_content_visible CASCADE;
CREATE TABLE user_content_visible (
    user_id       VARCHAR(64)   NOT NULL,
    origin_id     VARCHAR(64)   NOT NULL,
    content_type  VARCHAR(32)   NOT NULL,            -- course / training / skill / scale / career
    synced_at     TIMESTAMP     NOT NULL DEFAULT NOW(),
    -- 主键必须包含 content_type！否则不同内容类型的 origin_id（都从1独立编号）
    -- 会互相冲突，导致部分类型权限被 ON CONFLICT DO NOTHING 静默跳过
    PRIMARY KEY (user_id, content_type, origin_id)
);
CREATE INDEX idx_ucv_user ON user_content_visible(user_id);
CREATE INDEX idx_ucv_type ON user_content_visible(content_type);


-- ============================================================
-- 13. 推荐日志表 — 记录推荐曝光/点击反馈
-- ============================================================
DROP TABLE IF EXISTS recommend_log CASCADE;
CREATE TABLE recommend_log (
    id           SERIAL PRIMARY KEY,
    user_id      VARCHAR(64)   NOT NULL,
    trace_id     VARCHAR(64),
    event_type   VARCHAR(16),                        -- exposure / click
    content_id   VARCHAR(64),
    content_type VARCHAR(32),
    position     INTEGER,
    event_time   TIMESTAMP     NOT NULL DEFAULT NOW(),
    created_at   TIMESTAMP     NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_rlog_user ON recommend_log(user_id);
CREATE INDEX idx_rlog_time ON recommend_log(event_time);

"""


def get_schema_sql() -> str:
    return SCHEMA_V3
