# -*- coding: utf-8 -*-
"""课程体检：开课前把「学生打不开 / 看到半成品」的问题一次列全。

移植自 learnhouse-agent/skill/learnhouse/tools.py 的 `lint_course()`。
skill 版本靠 HTTP API 逐个取活动、并用 GET 图片地址的 404 判断图挂了；
后端可以直接查库，图片改成查 Block 表 + 本地内容目录（内容走 S3 时无法就地
确认，会降级成 image_uncertain 并说明原因）。

三级：
  error —— 学生一定会撞上的硬伤（空页、没题的作业、图挂了）
  warn  —— 大概率不是老师本意（活动没发布、截止日期已过、嵌入走 http）
  info  —— 只是提醒（课程可见性组合、绑了哪些用户组）
"""

import os
from datetime import datetime

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.courses.activities import Activity
from src.db.courses.assignments import Assignment, AssignmentTask
from src.db.courses.blocks import Block
from src.db.courses.chapter_activities import ChapterActivity
from src.db.courses.chapters import Chapter
from src.db.courses.course_chapters import CourseChapter
from src.db.organizations import Organization
from src.services.ext.learning.common import ROW_LIMIT, LearningError, linked_usergroups

# 一门大课里最多验多少张图，避免体检拖太久
MAX_IMAGE_CHECKS = 200


def _finding(level: str, code: str, message: str, **extra) -> dict:
    """一条体检结论。target_uuid 指向能跳过去修的那个对象。"""
    finding = {
        "level": level,
        "code": code,
        "message": message,
        "target_uuid": extra.pop("target_uuid", None),
        "target_type": extra.pop("target_type", None),
        "fix_hint": extra.pop("fix_hint", ""),
        "fixable": extra.pop("fixable", False),
    }
    finding.update(extra)
    return finding


def _is_empty_doc(doc: dict | None) -> bool:
    """TipTap 文档里有没有实际内容。只有空段落也算空页。"""
    if not doc:
        return True
    nodes = doc.get("content") or []
    for node in nodes:
        node_type = node.get("type")
        if node_type in (None, "paragraph"):
            inner = node.get("content") or []
            if any((c.get("text") or "").strip() for c in inner if isinstance(c, dict)):
                return False
            continue
        return False
    return True


def _content_delivery() -> str:
    try:
        from config.config import get_learnhouse_config

        return get_learnhouse_config().hosting_config.content_delivery.type
    except Exception:
        return "unknown"


# 媒体根目录。和上游 `services/utils/upload_content.py` 一样是相对当前工作目录的
# `content/`（容器里是 /app/api/content）。
CONTENT_ROOT = "content"


def _media_root_available() -> bool:
    """媒体根目录里到底有没有 orgs/ 这一层。

    没有的话说明整棵内容树不可达（从源码起服务、或者只恢复了数据库没恢复媒体），
    此时逐张图去 os.path.exists 会把每一张都判成「不存在」，刷出一屏假 error。
    这种情况只报一条 info，说明检查被跳过了。
    """
    return os.path.isdir(os.path.join(CONTENT_ROOT, "orgs"))


def _image_on_disk(org_uuid, course_uuid, activity_uuid, block_uuid, file_id, file_format) -> bool:
    path = os.path.join(
        CONTENT_ROOT,
        "orgs",
        str(org_uuid),
        "courses",
        str(course_uuid),
        "activities",
        str(activity_uuid),
        "dynamic",
        "blocks",
        "imageBlock",
        str(block_uuid),
        "%s.%s" % (file_id, file_format),
    )
    return os.path.exists(path)


async def _course_structure(db_session: AsyncSession, course_id: int):
    """按章节顺序、活动顺序取出整门课的结构。"""
    chapter_rows = await db_session.execute(
        select(Chapter, CourseChapter.order)
        .join(CourseChapter, CourseChapter.chapter_id == Chapter.id)  # type: ignore[arg-type]
        .where(CourseChapter.course_id == course_id)
    )
    chapters = sorted(chapter_rows.all(), key=lambda row: row[1] or 0)

    activity_rows = await db_session.execute(
        select(Activity, ChapterActivity.chapter_id, ChapterActivity.order)
        .join(ChapterActivity, ChapterActivity.activity_id == Activity.id)  # type: ignore[arg-type]
        .where(ChapterActivity.course_id == course_id)
        .limit(ROW_LIMIT)
    )
    by_chapter: dict[int, list] = {}
    for activity, chapter_id, order in activity_rows.all():
        by_chapter.setdefault(chapter_id, []).append((activity, order or 0))
    for items in by_chapter.values():
        items.sort(key=lambda pair: pair[1])
    return [(chapter, [a for a, _ in by_chapter.get(chapter.id, [])]) for chapter, _ in chapters]


async def lint_course(db_session: AsyncSession, course) -> dict:
    """跑一遍体检，返回结论列表与统计。不改任何数据。"""
    org = (
        await db_session.execute(
            select(Organization).where(Organization.id == course.org_id)
        )
    ).scalars().first()
    org_uuid = org.org_uuid if org else ""

    structure = await _course_structure(db_session, course.id)

    assignment_rows = await db_session.execute(
        select(Assignment).where(Assignment.course_id == course.id).limit(ROW_LIMIT)
    )
    assignments = list(assignment_rows.scalars().all())
    assignment_by_activity = {a.activity_id: a for a in assignments}

    task_counts: dict[int, int] = {}
    if assignments:
        task_rows = await db_session.execute(
            select(AssignmentTask.assignment_id).where(
                AssignmentTask.assignment_id.in_([a.id for a in assignments])  # type: ignore[union-attr]
            )
        )
        for (assignment_id,) in task_rows.all():
            task_counts[assignment_id] = task_counts.get(assignment_id, 0) + 1

    block_rows = await db_session.execute(
        select(Block).where(Block.course_id == course.id).limit(ROW_LIMIT)
    )
    blocks = {b.block_uuid: b for b in block_rows.scalars().all()}

    delivery = _content_delivery()
    media_root_ok = _media_root_available()
    today = datetime.now().strftime("%Y-%m-%d")

    findings: list[dict] = []
    stats = {
        "chapters": 0,
        "activities": 0,
        "pages": 0,
        "assignments": len(assignments),
        "images_checked": 0,
    }
    activity_errors: dict[str, int] = {}
    unpublished: list[Activity] = []
    checked_images = 0

    for chapter, activities in structure:
        stats["chapters"] += 1
        if not activities:
            findings.append(
                _finding(
                    "warn",
                    "empty_chapter",
                    "章节「%s」里一个活动都没有" % chapter.name,
                    target_uuid=chapter.chapter_uuid,
                    target_type="chapter",
                    fix_hint="去课程编辑页给这个章节加内容，或者把空章节删掉。",
                )
            )
        for activity in activities:
            stats["activities"] += 1
            where = "%s / %s" % (chapter.name, activity.name)
            errors = 0

            if not activity.published:
                unpublished.append(activity)
                findings.append(
                    _finding(
                        "warn",
                        "unpublished_activity",
                        "「%s」还没发布，学生在课程里看不到" % where,
                        target_uuid=activity.activity_uuid,
                        target_type="activity",
                        fixable=True,
                        fix_hint="确认内容没问题后，用「一键发布未发布活动」或在编辑页单独发布。",
                    )
                )

            atype = getattr(activity.activity_type, "value", activity.activity_type)
            subtype = getattr(
                activity.activity_sub_type, "value", activity.activity_sub_type
            )
            content = activity.content or {}

            # ---- 内容页：空页、断图、不安全嵌入 ----
            if atype == "TYPE_DYNAMIC" and subtype == "SUBTYPE_DYNAMIC_PAGE":
                stats["pages"] += 1
                if _is_empty_doc(content):
                    findings.append(
                        _finding(
                            "error",
                            "empty_page",
                            "「%s」是空页，里面没有任何正文" % where,
                            target_uuid=activity.activity_uuid,
                            target_type="activity",
                            fix_hint="补上内容，或者把这个活动删掉。",
                        )
                    )
                    errors += 1
                for node in content.get("content") or []:
                    if not isinstance(node, dict):
                        continue
                    node_type = node.get("type")
                    attrs = node.get("attrs") or {}
                    if node_type == "blockImage":
                        block_object = attrs.get("blockObject") or {}
                        block_uuid = block_object.get("block_uuid") or attrs.get("blockObject", {}).get("id")
                        file_object = block_object.get("content") or {}
                        file_id = file_object.get("file_id")
                        file_format = file_object.get("file_format")
                        if not block_uuid or not file_id or not file_format:
                            findings.append(
                                _finding(
                                    "error",
                                    "image_block_broken",
                                    "「%s」里有一个图片块缺字段（block_uuid / file_id），页面上会是个空框"
                                    % where,
                                    target_uuid=activity.activity_uuid,
                                    target_type="activity",
                                    fix_hint="在编辑页把这张图删掉重传。",
                                )
                            )
                            errors += 1
                            continue
                        if checked_images >= MAX_IMAGE_CHECKS:
                            continue
                        checked_images += 1
                        if block_uuid not in blocks:
                            findings.append(
                                _finding(
                                    "error",
                                    "image_missing",
                                    "「%s」里的图片 %s 没有对应的块记录，学生看不到"
                                    % (where, file_object.get("file_name") or file_id),
                                    target_uuid=activity.activity_uuid,
                                    target_type="activity",
                                    fix_hint="在编辑页把这张图删掉重传。",
                                )
                            )
                            errors += 1
                        elif delivery == "filesystem" and media_root_ok:
                            if not _image_on_disk(
                                org_uuid,
                                course.course_uuid,
                                activity.activity_uuid,
                                block_uuid,
                                file_id,
                                file_format,
                            ):
                                findings.append(
                                    _finding(
                                        "error",
                                        "image_missing",
                                        "「%s」里的图片 %s 在服务器上不存在"
                                        % (
                                            where,
                                            file_object.get("file_name") or file_id,
                                        ),
                                        target_uuid=activity.activity_uuid,
                                        target_type="activity",
                                        fix_hint="在编辑页把这张图删掉重传。",
                                    )
                                )
                                errors += 1
                        else:
                            findings.append(
                                _finding(
                                    "info",
                                    "image_uncertain",
                                    "「%s」里的图片没法就地确认还在不在（%s）"
                                    % (
                                        where,
                                        "媒体目录不可达"
                                        if delivery == "filesystem"
                                        else "内容存在对象存储 %s 上" % delivery,
                                    ),
                                    target_uuid=activity.activity_uuid,
                                    target_type="activity",
                                    fix_hint="打开这一页目视确认一下图片能显示。",
                                )
                            )
                    elif node_type == "blockEmbed":
                        url = attrs.get("embedUrl") or ""
                        if url and not url.lower().startswith("https://"):
                            findings.append(
                                _finding(
                                    "warn",
                                    "embed_not_https",
                                    "「%s」里嵌入的是 %s，不是 https，浏览器多半会拦掉"
                                    % (where, url[:80]),
                                    target_uuid=activity.activity_uuid,
                                    target_type="activity",
                                    fix_hint="把嵌入地址换成 https 开头的。",
                                )
                            )

            # ---- 整页嵌入活动 ----
            elif atype == "TYPE_DYNAMIC" and subtype == "SUBTYPE_DYNAMIC_EMBED":
                url = (content or {}).get("embed_url") or ""
                if not url:
                    findings.append(
                        _finding(
                            "error",
                            "embed_empty",
                            "「%s」是嵌入活动但没有地址，学生看到空白页" % where,
                            target_uuid=activity.activity_uuid,
                            target_type="activity",
                            fix_hint="在编辑页填上要嵌入的地址。",
                        )
                    )
                    errors += 1
                elif not url.lower().startswith("https://"):
                    findings.append(
                        _finding(
                            "warn",
                            "embed_not_https",
                            "「%s」嵌入的是 %s，不是 https" % (where, url[:80]),
                            target_uuid=activity.activity_uuid,
                            target_type="activity",
                            fix_hint="把嵌入地址换成 https 开头的。",
                        )
                    )

            # ---- 作业壳 ----
            elif atype == "TYPE_ASSIGNMENT":
                record = assignment_by_activity.get(activity.id)
                if not record:
                    findings.append(
                        _finding(
                            "error",
                            "assignment_shell_without_record",
                            "「%s」是个作业壳，但没有对应的作业记录 —— 学生点进去是空的" % where,
                            target_uuid=activity.activity_uuid,
                            target_type="activity",
                            fix_hint="删掉这个活动重新建一份作业。",
                        )
                    )
                    errors += 1
                else:
                    if not task_counts.get(record.id):
                        findings.append(
                            _finding(
                                "error",
                                "assignment_without_tasks",
                                "作业「%s」一道题都没有" % (record.title or activity.name),
                                target_uuid=record.assignment_uuid,
                                target_type="assignment",
                                fix_hint="去作业编辑页加题目。",
                            )
                        )
                        errors += 1
                    due = (record.due_date or "")[:10]
                    if due and due < today:
                        findings.append(
                            _finding(
                                "warn",
                                "due_date_passed",
                                "作业「%s」的截止日期 %s 已经过了"
                                % (record.title or activity.name, due),
                                target_uuid=record.assignment_uuid,
                                target_type="assignment",
                                fix_hint="新学期复用这门课时记得把截止日期顺延。",
                            )
                        )
                    if activity.published and not record.published:
                        findings.append(
                            _finding(
                                "warn",
                                "assignment_unpublished",
                                "「%s」这个活动已发布，但作业记录本身没发布，学生做不了" % where,
                                target_uuid=record.assignment_uuid,
                                target_type="assignment",
                                fix_hint="去作业编辑页把作业也发布出去。",
                            )
                        )
            if errors:
                activity_errors[activity.activity_uuid] = errors

    stats["images_checked"] = checked_images

    # ---- 课程级：可见性与用户组 ----
    if not course.published:
        findings.append(
            _finding(
                "warn",
                "course_unpublished",
                "课程还没发布（published=false）。课程列表里学生看不到它；"
                + (
                    "public=true，拿到直链倒是能进。"
                    if course.public
                    else "而且 public=false，学生走直链会 403。"
                ),
                target_uuid=course.course_uuid,
                target_type="course",
                fix_hint="课程设置里点发布。",
            )
        )
    if course.public and course.published:
        findings.append(
            _finding(
                "info",
                "course_open_to_all",
                "课程是公开的（public=true），组织里任何登录用户都能看",
                target_uuid=course.course_uuid,
                target_type="course",
            )
        )
    if not course.public:
        groups = await linked_usergroups(db_session, course.course_uuid, course.org_id)
        if not groups:
            findings.append(
                _finding(
                    "error",
                    "private_without_group",
                    "课程是私有的（public=false）但没有绑定任何用户组 —— 除了老师自己，没有学生能打开它",
                    target_uuid=course.course_uuid,
                    target_type="course",
                    fix_hint="去「用户组」建班，把这门课挂到组上。",
                )
            )
        else:
            findings.append(
                _finding(
                    "info",
                    "restricted_to_groups",
                    "课程仅对这些用户组可见：%s" % "、".join(g.name for g in groups),
                    target_uuid=course.course_uuid,
                    target_type="course",
                )
            )

    return {
        "course_uuid": course.course_uuid,
        "course_name": course.name,
        "public": bool(course.public),
        "published": bool(course.published),
        "stats": stats,
        "counts": {
            level: len([f for f in findings if f["level"] == level])
            for level in ("error", "warn", "info")
        },
        "fixable_count": len(
            [f for f in findings if f.get("fixable") and f["code"] == "unpublished_activity"]
        ),
        "findings": findings,
    }


async def fix_publish(db_session: AsyncSession, course, confirm: bool) -> dict:
    """把未发布的活动发布出去，**只发没有 error 级问题的活动**。

    把空页或没题的作业发出去，学生看到的是垃圾，比不发更糟，所以这类会被跳过
    并在 `skipped` 里说明原因。作业壳也一律跳过：只发活动不发作业记录，学生仍然
    做不了，反而正好造出体检自己会报的 assignment_unpublished。
    """
    if confirm is not True:
        raise LearningError("这个操作会真的改课程的发布状态，请求体里必须带 confirm: true")

    report = await lint_course(db_session, course)
    blocked = {
        f["target_uuid"]
        for f in report["findings"]
        if f["level"] == "error" and f["target_type"] == "activity"
    }

    structure = await _course_structure(db_session, course.id)
    published, skipped = [], []
    now = str(datetime.now())
    for chapter, activities in structure:
        for activity in activities:
            if activity.published:
                continue
            atype = getattr(activity.activity_type, "value", activity.activity_type)
            if atype == "TYPE_ASSIGNMENT":
                skipped.append(
                    {
                        "activity_uuid": activity.activity_uuid,
                        "name": activity.name,
                        "chapter": chapter.name,
                        "reason": "这是作业壳。只发活动学生仍然做不了，作业记录要在作业编辑页一起发布。",
                    }
                )
                continue
            if activity.activity_uuid in blocked:
                skipped.append(
                    {
                        "activity_uuid": activity.activity_uuid,
                        "name": activity.name,
                        "chapter": chapter.name,
                        "reason": "这个活动还有 error 级问题，发布出去学生只会看到半成品。",
                    }
                )
                continue
            activity.published = True
            activity.update_date = now
            db_session.add(activity)
            published.append(
                {
                    "activity_uuid": activity.activity_uuid,
                    "name": activity.name,
                    "chapter": chapter.name,
                }
            )
    if published:
        await db_session.commit()

    return {
        "course_uuid": course.course_uuid,
        "published": published,
        "skipped": skipped,
        "published_count": len(published),
        "skipped_count": len(skipped),
    }
