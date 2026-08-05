"""
数据迁移 V3 — 旧 content_index → 新表（严格对齐 API 字段）+ 补齐必须字段
"""
import json
import asyncio
import logging
from datetime import datetime
from sqlalchemy import text
from db.connection import get_db_session

logger = logging.getLogger(__name__)

# ── 必须字段默认值（用于补齐空数据）──
COURSE_DEFAULTS = {
    "texts2": "掌握相关职业技能知识",   # 课程收益
    "texts3": "线上录播",               # 授课形式
    "texts4": "基础知识/进阶技能/实战案例", # 课程大纲
}
TRAINING_DEFAULTS = {
    "snum": None,      # 班级编号，放 None 让生成逻辑来填
    "start_apply": "2026-08-01",
    "end_apply": "2026-12-31",
    "start_study": "2027-01-15",
    "end_study": "2027-06-30",
    "limits": 50,
    "training": "待补充培训内容",
}


async def migrate_and_fill():
    db = get_db_session()
    async with db as session:
        # 1. 拉取旧数据
        r = await session.execute(
            text("SELECT content_id, content_type, title, raw_data FROM content_index WHERE status='active' AND content_type NOT LIKE 'behavior_%'")
        )
        rows = r.fetchall()
        logger.info(f"待迁移: {len(rows)} 条")

        counts = {}
        for row in rows:
            cid, ctype, title, raw_str = row[0], row[1], row[2], row[3]
            raw = json.loads(raw_str) if isinstance(raw_str, str) else raw_str or {}

            if ctype == "course":
                await _insert_course(session, raw, cid, title)
            elif ctype == "training":
                await _insert_training(session, raw, cid, title)
            elif ctype == "skill":
                await _insert_skill(session, raw, cid, title)
            elif ctype == "scale":
                await _insert_scale(session, raw, cid, title)
            elif ctype == "career":
                await _insert_career(session, raw, cid, title)
            elif ctype == "news":
                await _insert_news(session, raw, cid, title)
            else:
                continue
            counts[ctype] = counts.get(ctype, 0) + 1

        await session.commit()
        logger.info(f"迁移完成: {counts}")
    return counts


async def _insert_course(session, raw, fallback_id, fallback_title):
    oid = str(raw.get("id", fallback_id))
    name = raw.get("name") or fallback_title
    # 过滤掉 name 为 None 或 test 的脏数据
    if not name or name.strip() in ("None", "test", ""):
        return
    await session.execute(text("""
        INSERT INTO courses (origin_id, num_xs, name, texts1, texts2, texts3, texts4)
        VALUES (:oid, :num, :name, :t1, :t2, :t3, :t4)
        ON CONFLICT (origin_id) DO UPDATE SET
            num_xs=EXCLUDED.num_xs, name=EXCLUDED.name,
            texts1=EXCLUDED.texts1, texts2=EXCLUDED.texts2,
            texts3=EXCLUDED.texts3, texts4=EXCLUDED.texts4, sync_at=NOW()
    """), {
        "oid": oid,
        "num": str(raw.get("numXs", "")) or None,
        "name": name,
        "t1": raw.get("texts1", "") or None,
        "t2": raw.get("Texts2", "") or COURSE_DEFAULTS["texts2"],
        "t3": raw.get("Texts3", "") or COURSE_DEFAULTS["texts3"],
        "t4": raw.get("Texts4", "") or COURSE_DEFAULTS["texts4"],
    })


async def _insert_training(session, raw, fallback_id, fallback_title):
    oid = str(raw.get("id", fallback_id))
    name = raw.get("name") or fallback_title
    if not name or name.strip() == "None":
        return

    # 生成班级编号
    snum = raw.get("snum", "")
    if not snum:
        snum = f"B{oid.zfill(4)}"

    await session.execute(text("""
        INSERT INTO training_classes (origin_id, snum, name, classify, start_apply, end_apply,
            start_study, end_study, limits, regions, places, training, certif, deleted)
        VALUES (:oid, :sn, :n, :cl, :sa, :ea, :ss, :es, :li, :reg, :pl, :tr, :ce, :de)
        ON CONFLICT (origin_id) DO UPDATE SET
            snum=EXCLUDED.snum, name=EXCLUDED.name, classify=EXCLUDED.classify,
            start_apply=EXCLUDED.start_apply, end_apply=EXCLUDED.end_apply,
            start_study=EXCLUDED.start_study, end_study=EXCLUDED.end_study,
            limits=EXCLUDED.limits, regions=EXCLUDED.regions, places=EXCLUDED.places,
            training=EXCLUDED.training, certif=EXCLUDED.certif, deleted=EXCLUDED.deleted, sync_at=NOW()
    """), {
        "oid": oid, "sn": snum, "n": name,
        "cl": raw.get("classify", "") or None,
        "sa": raw.get("startApply", "") or TRAINING_DEFAULTS["start_apply"],
        "ea": raw.get("endApply", "") or TRAINING_DEFAULTS["end_apply"],
        "ss": raw.get("startStudy", "") or TRAINING_DEFAULTS["start_study"],
        "es": raw.get("endStudy", "") or TRAINING_DEFAULTS["end_study"],
        "li": int(raw.get("limits", 0)) if raw.get("limits") else TRAINING_DEFAULTS["limits"],
        "reg": raw.get("regions", "") or None,
        "pl": raw.get("places", "") or None,
        "tr": raw.get("training", "") or TRAINING_DEFAULTS["training"],
        "ce": raw.get("certif", "") or None,
        "de": raw.get("deleted", "正常"),
    })


async def _insert_skill(session, raw, fallback_id, fallback_title):
    oid = str(raw.get("id", fallback_id))
    name = raw.get("name") or fallback_title
    if not name or name.strip() == "None":
        return
    await session.execute(text("""
        INSERT INTO skill_positions (origin_id, trade, grade, codes, name, years, salary, degree, major, working)
        VALUES (:oid, :tr, :gr, :co, :n, :yr, :sa, :de, :ma, :wo)
        ON CONFLICT (origin_id) DO UPDATE SET
            trade=EXCLUDED.trade, grade=EXCLUDED.grade, codes=EXCLUDED.codes,
            name=EXCLUDED.name, years=EXCLUDED.years, salary=EXCLUDED.salary,
            degree=EXCLUDED.degree, major=EXCLUDED.major, working=EXCLUDED.working, sync_at=NOW()
    """), {
        "oid": oid, "tr": raw.get("trade", "") or None,
        "gr": raw.get("grade", "") or None,
        "co": str(raw.get("codes", "")) or None,
        "n": name, "yr": str(raw.get("years", "")) or None,
        "sa": str(raw.get("salary", "")) or None,
        "de": raw.get("degree", "") or None,
        "ma": raw.get("major", "") or None,
        "wo": raw.get("working", "") or None,
    })


async def _insert_scale(session, raw, fallback_id, fallback_title):
    oid = str(raw.get("id", fallback_id))
    name = raw.get("name") or fallback_title
    if not name or name.strip() == "None":
        return
    await session.execute(text("""
        INSERT INTO assessment_scales (origin_id, product_id, name, tags, pnums, ptimes, texts1, vals)
        VALUES (:oid, :pid, :n, :tg, :pn, :pt, :t1, :v)
        ON CONFLICT (origin_id) DO UPDATE SET
            product_id=EXCLUDED.product_id, name=EXCLUDED.name, tags=EXCLUDED.tags,
            pnums=EXCLUDED.pnums, ptimes=EXCLUDED.ptimes, texts1=EXCLUDED.texts1,
            vals=EXCLUDED.vals, sync_at=NOW()
    """), {
        "oid": oid, "pid": raw.get("productId") or raw.get("product_id"),
        "n": name, "tg": raw.get("tags", "") or None,
        "pn": int(raw.get("pnums", 0)) if raw.get("pnums") else None,
        "pt": int(raw.get("ptimes", 30)) if raw.get("ptimes") else 30,  # 默认30分钟
        "t1": raw.get("texts1", "") or "待补充测评介绍",
        "v": raw.get("values", "") or "适用于相关从业者",
    })


async def _insert_career(session, raw, fallback_id, fallback_title):
    oid = str(raw.get("id", fallback_id))
    name = raw.get("name") or fallback_title
    if not name or name.strip() == "None":
        return
    await session.execute(text("""
        INSERT INTO career_plans (origin_id, name, raw_data)
        VALUES (:oid, :name, :raw)
        ON CONFLICT (origin_id) DO UPDATE SET name=EXCLUDED.name, raw_data=EXCLUDED.raw_data, sync_at=NOW()
    """), {
        "oid": oid,
        "name": name,
        "raw": json.dumps(raw, ensure_ascii=False),
    })


async def _insert_news(session, raw, fallback_id, fallback_title):
    oid = str(raw.get("id", fallback_id))
    title = raw.get("name") or raw.get("title") or fallback_title
    if not title or title.strip() == "None":
        return
    await session.execute(text("""
        INSERT INTO news (origin_id, title, raw_data)
        VALUES (:oid, :title, :raw)
        ON CONFLICT (origin_id) DO UPDATE SET title=EXCLUDED.title, raw_data=EXCLUDED.raw_data, sync_at=NOW()
    """), {
        "oid": oid,
        "title": title,
        "raw": json.dumps(raw, ensure_ascii=False),
    })


async def insert_user_behaviors():
    """重新插入用户行为数据"""
    db = get_db_session()
    async with db as session:
        await session.execute(text("DELETE FROM user_behaviors"))

        behaviors = [
            # 李明 - 软件工程
            ("shty80002", "李明", "browsing", "Python自动化测试课程", None, "2026-07-20 10:00"),
            ("shty80002", "李明", "browsing", "Vue前端开发实战班", None, "2026-07-21 14:30"),
            ("shty80002", "李明", "search", "Java高级开发工程师岗位", None, "2026-07-22 09:15"),
            ("shty80002", "李明", "learning", "Python数据分析", '{"duration":3600}', "2026-07-23 15:00"),
            ("shty80002", "李明", "search", "软件架构师职业技能", None, "2026-07-25 11:00"),
            ("shty80002", "李明", "browsing", "程序员职业规划方案", None, "2026-07-26 16:20"),
            # 张华 - 建筑工程技术
            ("shty80003", "张华", "browsing", "建筑施工安全管理课程", None, "2026-07-19 08:30"),
            ("shty80003", "张华", "browsing", "工程测量技术培训班", None, "2026-07-20 10:00"),
            ("shty80003", "张华", "search", "CAD制图技能岗位", None, "2026-07-21 14:00"),
            ("shty80003", "张华", "learning", "建筑施工基础", '{"duration":5400}', "2026-07-22 09:00"),
            ("shty80003", "张华", "search", "二级建造师培训班", None, "2026-07-24 15:30"),
            ("shty80003", "张华", "browsing", "建筑行业职业规划", None, "2026-07-25 10:00"),
            # 王芳 - 护理学
            ("shty80004", "王芳", "browsing", "临床护理技能培训", None, "2026-07-18 09:00"),
            ("shty80004", "王芳", "browsing", "急救知识与技能课程", None, "2026-07-20 14:00"),
            ("shty80004", "王芳", "search", "医院感控管理岗位", None, "2026-07-22 10:30"),
            ("shty80004", "王芳", "learning", "护理学基础", '{"duration":4500}', "2026-07-23 08:00"),
            ("shty80004", "王芳", "browsing", "护理人员职业素养测评", None, "2026-07-26 09:00"),
            # 刘强 - 机械设计与制造
            ("shty80005", "刘强", "browsing", "数控编程CNC培训班", None, "2026-07-17 10:00"),
            ("shty80005", "刘强", "browsing", "焊接工艺与实操课程", None, "2026-07-19 13:00"),
            ("shty80005", "刘强", "search", "机械设计工程师岗位", None, "2026-07-21 09:30"),
            ("shty80005", "刘强", "learning", "CAD机械制图", '{"duration":3200}', "2026-07-22 14:00"),
            ("shty80005", "刘强", "search", "高级焊工技能培训", None, "2026-07-24 11:00"),
            ("shty80005", "刘强", "browsing", "制造业职业发展路径", None, "2026-07-26 15:00"),
            # 赵丽 - 会计学
            ("shty80006", "赵丽", "browsing", "财务分析与报表课程", None, "2026-07-18 14:00"),
            ("shty80006", "赵丽", "browsing", "税务筹划实务培训班", None, "2026-07-20 10:30"),
            ("shty80006", "赵丽", "search", "会计主管技能岗位", None, "2026-07-22 09:00"),
            ("shty80006", "赵丽", "learning", "Excel高级数据分析", '{"duration":2800}', "2026-07-23 16:00"),
            ("shty80006", "赵丽", "search", "注册会计师培训", None, "2026-07-25 10:00"),
            ("shty80006", "赵丽", "browsing", "财务人员职业规划", None, "2026-07-26 14:00"),
            # 高权忠 - 计算机应用技术
            ("1", "高权忠", "browsing", "人工智能基础课程", None, "2026-07-19 15:00"),
            ("1", "高权忠", "browsing", "大数据分析培训班", None, "2026-07-21 10:00"),
            ("1", "高权忠", "search", "算法工程师岗位", None, "2026-07-23 11:00"),
            ("1", "高权忠", "learning", "机器学习入门", '{"duration":4000}', "2026-07-24 09:00"),
            ("1", "高权忠", "search", "深度学习进阶培训", None, "2026-07-25 14:00"),
            ("1", "高权忠", "browsing", "IT行业职业发展测评", None, "2026-07-26 10:00"),
        ]

        for uid, uname, btype, content, extra, etime in behaviors:
            await session.execute(text(
                "INSERT INTO user_behaviors (user_id, user_name, behavior_type, content, extra_info, event_time) "
                "VALUES (:uid, :un, :bt, :ct, :ex, :et)"
            ), {
                "uid": uid, "un": uname, "bt": btype, "ct": content,
                "ex": json.dumps(extra) if extra else None,
                "et": datetime.fromisoformat(etime),
            })

        await session.commit()
        logger.info(f"插入 {len(behaviors)} 条用户行为")
    return len(behaviors)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    c = await migrate_and_fill()
    b = await insert_user_behaviors()
    print(f"Done: content={c}, behaviors={b}")


if __name__ == "__main__":
    asyncio.run(main())
