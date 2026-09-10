# -*- coding: utf-8 -*-
"""往已有内容页末尾追加一个块（目前只有虚拟助教用到）。

移植自教学工具 skill 的 `avatar.py` 的 `add_avatar_to_page`（SYSU-SAM）。
skill 版改页面前会把旧内容存一份到 `~/.learnhouse/backups/`；后端这边不需要，
因为上游的 `update_activity` 只要带 content 就会自动存一条活动版本
（`services/courses/activities/versioning.py`），老师在「内容页版本回滚」里能捞回来。
"""
from fastapi import HTTPException, Request
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.courses.activities import Activity, ActivitySubTypeEnum, ActivityUpdate
from src.services.courses.activities.activities import update_activity

from . import avatar as avatar_mod
from .markdown import inline_nodes


async def append_avatar_embed(
    request: Request,
    activity_uuid: str,
    script: str,
    current_user,
    db_session: AsyncSession,
    title: str | None = None,
    page_url: str | None = None,
    org_config: dict | None = None,
    height: int = avatar_mod.DEFAULT_HEIGHT,
):
    """把讲稿变成数字人链接，追加到内容页末尾。

    先算链接再动页面：讲稿有问题（空的、只剩念不出来的内容）在 `build_url` 就抛错，
    页面一个字都不会被改。RBAC 由 `update_activity` 里的 `check_resource_access` 负责。
    """
    built = avatar_mod.build_url(script, title=title, page_url=page_url, org_config=org_config)

    activity = (await db_session.execute(
        select(Activity).where(Activity.activity_uuid == activity_uuid)
    )).scalars().first()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")

    # 按**活动类型**判断能不能追加，不看 content 长什么样：
    # 一个还没写过正文的内容页，content 就是 `{}`（既不是 doc 也不是别的），
    # 照 content 判断会把这种页面误判成「不是内容页」而拒掉 —— 而这恰恰是老师
    # 最想加虚拟助教的场景（新建一页，只放一个数字人）。
    sub = activity.activity_sub_type
    sub = sub.value if hasattr(sub, "value") else str(sub)
    if sub != ActivitySubTypeEnum.SUBTYPE_DYNAMIC_PAGE.value:
        raise HTTPException(
            status_code=400,
            detail=("活动「%s」不是富文本内容页（类型 %s），不能往里追加虚拟助教。"
                    "整页嵌入的视频、PDF、作业请新建一页。" % (activity.name, sub)))

    doc = activity.content if isinstance(activity.content, dict) else {}
    nodes = list(doc.get("content") or []) if doc.get("type") == "doc" else []
    before = len(nodes)
    if title:
        nodes.append({"type": "heading", "attrs": {"level": 2}, "content": inline_nodes(title)})
    nodes.append(avatar_mod.embed_node(built["url"], height=height))

    await update_activity(
        request, ActivityUpdate(content={"type": "doc", "content": nodes}),
        activity_uuid, current_user, db_session)

    return {
        "activity_uuid": activity_uuid,
        "activity_name": activity.name,
        "embed_url": built["url"],
        "title": built["title"],
        "line_count": built["line_count"],
        "url_length": built["url_length"],
        "encoding": built["encoding"],
        "page_url": built["page_url"],
        "page_url_source": built["page_url_source"],
        "nodes_before": before,
        "nodes_after": len(nodes),
        "version_saved": bool(activity.content),
    }
