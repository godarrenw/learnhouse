# -*- coding: utf-8 -*-
"""课程 ⇄ Markdown 目录树（打包成 zip 传输）。

移植自教学工具 skill 的 `tools.py` 的 `export_course_markdown` / `import_course_markdown`
（SYSU-SAM）。目录约定完全一致，所以 skill 导出的目录压成 zip 可以直接从这里导入：

    <课程名>/README.md            课程信息 + 目录
    <课程名>/assets/…             页内图片
    <课程名>/01-章节名/01-活动名.md

和 skill 版的两处差别：

1. **不走 HTTP**，直接调后端 service（`create_chapter` / `create_activity` /
   `update_activity` / `create_image_block`），图片字节用 `read_content` 从存储层读，
   不再拼媒体 URL 下载。
2. **不做本地备份**。导入是新建章节，不覆盖任何已有内容；虚拟助教那条覆盖路径由
   上游自带的活动版本机制兜底（`update_activity` 带 content 时会自动存一版）。

导出是**有损**的：只有内容页和整页嵌入能反向导入，托管视频、PDF、作业不能，
README 和返回值里都会逐条说明，不静默丢掉。
"""
import asyncio
import io
import logging
import mimetypes
import os
import re
import zipfile
from datetime import datetime

from fastapi import HTTPException, Request, UploadFile
from starlette.datastructures import Headers
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.courses.assignments import Assignment, AssignmentTask
from src.db.courses.activities import (
    Activity,
    ActivityCreate,
    ActivitySubTypeEnum,
    ActivityTypeEnum,
    ActivityUpdate,
)
from src.db.courses.chapter_activities import ChapterActivity
from src.db.courses.chapters import Chapter, ChapterCreate
from src.db.courses.course_chapters import CourseChapter
from src.db.courses.courses import Course
from src.db.organizations import Organization
from src.security.rbac import AccessAction, check_resource_access
from src.services.blocks.block_types.imageBlock.imageBlock import create_image_block
from src.services.courses.activities import activities as upstream_activities
from src.services.courses.activities.activities import create_activity, update_activity
from src.services.courses.chapters import create_chapter
from src.services.utils.upload_content import read_content

from .assignments_md import render_assignment_markdown
from .markdown import (
    front_matter,
    md_to_tiptap,
    parse_front_matter,
    scan_image_sources,
    strip_lost_nodes,
    tiptap_to_markdown,
)

logger = logging.getLogger(__name__)

_SAFE_RE = re.compile(r"[^\w一-鿿.\- ]+")

#: 导入 zip 的三条硬上限。超了直接 400，不静默截断。
MAX_ZIP_BYTES = 50 * 1024 * 1024          # 压缩包本身
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024  # 解压后总大小，防 zip 炸弹
MAX_ZIP_ENTRIES = 2000
#: 单张图片上限，和上游图片块的口径保持在同一量级
MAX_IMAGE_BYTES = 20 * 1024 * 1024

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")

#: 流式读 zip 条目时每次读多少
_ZIP_CHUNK = 64 * 1024

#: 导入时最多允许多少个「重建向量索引」的后台任务同时在飞。
#:
#: 为什么要限：上游 `update_activity` 每写一次 content 就
#: `asyncio.create_task(_trigger_course_embedding(...))`，而那个任务**自己新开一个
#: db session**。导入 N 个页面就是 N 个 session 一起抢连接池，而池子是 5 + 10。
#: 导一门几十页的课没事，导上千页必然打满，症状是后续请求全 500 ——
#: 表现得像鉴权坏了，很难往「导入把池子占光了」上想。
#: 压到 3 是留足余量给同时进来的正常请求。代价是导入变慢，但慢总比崩好。
MAX_INFLIGHT_INDEX_TASKS = 3

#: 万一上游把那个任务集合改名了，退回按页数节流：每这么多页歇一下。
_FALLBACK_PAUSE_EVERY = 10
_FALLBACK_PAUSE_SECONDS = 0.5


class TransferError(ValueError):
    """目录结构或 zip 本身的问题。路由会翻成 400。"""


def _slug(name, fallback="未命名"):
    """把课程名 / 章节名 / 活动名变成安全的目录或文件名。"""
    s = _SAFE_RE.sub("_", str(name or "").strip()) or fallback
    return s[:80].rstrip(". ")


# ------------------------------------------------------------ 取课程结构


async def _get_course(db_session: AsyncSession, course_uuid: str) -> Course:
    course = (await db_session.execute(
        select(Course).where(Course.course_uuid == course_uuid)
    )).scalars().first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


async def _get_org_uuid(db_session: AsyncSession, org_id: int) -> str:
    org = (await db_session.execute(
        select(Organization).where(Organization.id == org_id)
    )).scalars().first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org.org_uuid


async def _course_tree(db_session: AsyncSession, course_id: int):
    """按顺序取出 [(章节, [活动, …]), …]。含未发布的活动 —— 导出是给老师用的。"""
    chapters = (await db_session.execute(
        select(Chapter)
        .join(CourseChapter, Chapter.id == CourseChapter.chapter_id)  # type: ignore
        .where(CourseChapter.course_id == course_id)
        .order_by(CourseChapter.order)  # type: ignore
    )).scalars().all()

    tree = []
    for ch in chapters:
        activities = (await db_session.execute(
            select(Activity)
            .join(ChapterActivity, Activity.id == ChapterActivity.activity_id)  # type: ignore
            .where(ChapterActivity.chapter_id == ch.id)
            .order_by(ChapterActivity.order)  # type: ignore
        )).scalars().all()
        tree.append((ch, list(activities)))
    return tree



async def _assignments_by_activity(db_session: AsyncSession, course_id: int):
    """课程里的作业，按它挂靠的活动 id 索引：`{activity_id: (作业, [题目, …])}`。

    一次把作业和题目都捞出来，避免在导出循环里对每个活动各查一次。
    题目按 id 排序 —— 上游没有给 AssignmentTask 存显式的 order 字段，
    id 递增就是创建顺序，也是网页上的显示顺序。
    """
    assignments = (await db_session.execute(
        select(Assignment).where(Assignment.course_id == course_id)
    )).scalars().all()
    if not assignments:
        return {}

    tasks = (await db_session.execute(
        select(AssignmentTask)
        .where(AssignmentTask.assignment_id.in_([a.id for a in assignments]))  # type: ignore
        .order_by(AssignmentTask.id)  # type: ignore
    )).scalars().all()

    by_assignment: dict = {}
    for task in tasks:
        by_assignment.setdefault(task.assignment_id, []).append(task)

    return {
        a.activity_id: (a, by_assignment.get(a.id, []))
        for a in assignments
        if a.activity_id is not None
    }


# ------------------------------------------------------------ 导出


def _image_block_location(course_uuid: str, activity_uuid: str, block_object: dict):
    """从 blockObject 反推它在存储层的位置。

    路径规则来自 `services/blocks/utils/upload_files.py`：
        orgs/<org_uuid>/courses/<course_uuid>/activities/<activity_uuid>/
        dynamic/blocks/imageBlock/<block_uuid>/<file_id>.<file_format>

    返回 (directory, file_and_format)；字段缺了返回 None，调用方记一条提醒。
    """
    if not isinstance(block_object, dict):
        return None
    block_uuid = block_object.get("block_uuid")
    content = block_object.get("content") or {}
    file_id, file_format = content.get("file_id"), content.get("file_format")
    if not (block_uuid and file_id and file_format):
        return None
    directory = ("courses/%s/activities/%s/dynamic/blocks/imageBlock/%s"
                 % (course_uuid, activity_uuid, block_uuid))
    return directory, "%s.%s" % (file_id, file_format)


async def export_course_markdown(
    request: Request,
    course_uuid: str,
    current_user,
    db_session: AsyncSession,
    download_images: bool = True,
):
    """把一整门课导出成 Markdown 目录树，打包成 zip 字节返回。

    返回 `{filename, zip_bytes, summary}`。`summary` 里的 `notes` 逐条列出
    导出过程中的降级（图片读不到、活动类型不支持等），不静默丢。
    """
    course = await _get_course(db_session, course_uuid)
    # 按 UPDATE 判而不是 READ：导出包里含作业的题目和**参考答案**，
    # 能拿到答案的人必须是能改这门课的人，仅仅"能看这门课"不够。
    await check_resource_access(request, db_session, current_user, course.course_uuid, AccessAction.UPDATE)
    org_uuid = await _get_org_uuid(db_session, course.org_id)

    tree = await _course_tree(db_session, course.id)  # type: ignore
    assignments_by_activity = await _assignments_by_activity(db_session, course.id)  # type: ignore
    root = _slug(course.name, "课程")

    buf = io.BytesIO()
    notes, toc = [], []
    files_written, images_written = 0, 0
    seen_assets = set()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for ci, (ch, activities) in enumerate(tree, 1):
            ch_dir_name = "%02d-%s" % (ci, _slug(ch.name, "章节"))
            toc.append("## %d. %s" % (ci, ch.name))

            for ai, act in enumerate(activities, 1):
                fname = "%02d-%s.md" % (ai, _slug(act.name, "活动"))
                atype = act.activity_type.value if hasattr(act.activity_type, "value") else str(act.activity_type)
                sub = act.activity_sub_type.value if hasattr(act.activity_sub_type, "value") else str(act.activity_sub_type)
                content = act.content or {}
                kind, body = "unknown", ""

                if atype == "TYPE_DYNAMIC" and sub == "SUBTYPE_DYNAMIC_PAGE":
                    kind = "page"
                    doc = _deep_copy_doc(content)
                    if download_images:
                        n = await _pull_images_into_zip(
                            zf, root, course.course_uuid, act.activity_uuid, org_uuid,
                            doc, act.name, notes, seen_assets)
                        images_written += n
                    body = tiptap_to_markdown(doc)

                elif atype == "TYPE_DYNAMIC" and sub == "SUBTYPE_DYNAMIC_EMBED":
                    kind = "embed"
                    body = "[[EMBED:%s]]\n" % (content.get("embed_url") or "")

                elif atype == "TYPE_DYNAMIC" and sub == "SUBTYPE_DYNAMIC_MARKDOWN":
                    kind = "markdown_url"
                    body = "外链 Markdown：%s\n" % (content.get("markdown_url") or "")

                elif atype in ("TYPE_VIDEO", "TYPE_DOCUMENT") or sub in (
                        "SUBTYPE_VIDEO_HOSTED", "SUBTYPE_DOCUMENT_PDF"):
                    kind = "video" if "VIDEO" in "%s%s" % (atype, sub) else "pdf"
                    filename = content.get("filename") or "(未知文件名)"
                    body = ("# %s\n\n这是一个%s活动，原始文件没有随导出下载（可能很大）。\n\n"
                            "- 原始文件名：`%s`\n"
                            % (act.name, "托管视频" if kind == "video" else "PDF 讲义", filename))
                    notes.append("活动「%s」是%s，只导出了文件名，反向导入需要重新上传"
                                 % (act.name, "托管视频" if kind == "video" else "PDF 讲义"))

                elif atype == "TYPE_ASSIGNMENT":
                    kind = "assignment"
                    pair = assignments_by_activity.get(act.id)
                    if pair is None:
                        body = ("# %s\n\n这个作业壳没有对应的作业记录，"
                                "可能是建到一半没保存。\n" % act.name)
                        notes.append("活动「%s」是作业壳，但找不到对应的作业记录" % act.name)
                    else:
                        assignment, tasks = pair
                        body = render_assignment_markdown(assignment, tasks)
                        notes.append("作业「%s」导出了题目与**参考答案**，"
                                     "发给学生前请先删掉答案行" % (assignment.title or act.name))

                else:
                    body = ("# %s\n\n（未识别的活动类型 %s / %s，只导出了标题）\n"
                            % (act.name, atype, sub))
                    notes.append("活动「%s」的类型 %s/%s 不认识，只导出了标题" % (act.name, atype, sub))

                meta = front_matter({
                    "type": kind, "name": act.name,
                    "published": "true" if act.published else "false",
                    "activity_uuid": act.activity_uuid,
                    "activity_type": atype, "activity_sub_type": sub,
                })
                zf.writestr("%s/%s/%s" % (root, ch_dir_name, fname), meta + body)
                files_written += 1
                toc.append("- [%s](%s/%s) · %s%s" % (
                    act.name, ch_dir_name, fname, kind,
                    "" if act.published else "（未发布）"))
            toc.append("")

        readme = ["# %s" % course.name, ""]
        if course.description:
            readme += [course.description, ""]
        if getattr(course, "about", None):
            readme += [course.about, ""]
        readme += [
            "> [!info] 导出于 %s。course_uuid `%s`，public=%s，published=%s。"
            % (datetime.now().strftime("%Y-%m-%d %H:%M"), course.course_uuid,
               course.public, course.published),
            "", "## 目录", "",
        ] + toc
        if notes:
            readme += ["## 导出时的提醒", ""] + ["- %s" % n for n in notes] + [""]
        readme += [
            "## 关于反向导入", "",
            "「导入 Markdown」只能还原**内容页**和**整页嵌入**。",
            "托管视频、PDF、作业需要重新上传或重建 —— 前两者的原始文件不在这个包里，",
            "作业请用「作业工具」里的学期复用功能搬。", "",
            "## 这份导出含参考答案", "",
            "作业的 `.md` 里带着**参考答案**，是给老师备课和迁移用的。",
            "直接把整个压缩包发给学生等于发答案 —— 要分享请先把答案行删掉。", "",
        ]
        zf.writestr("%s/README.md" % root, "\n".join(readme))

    return {
        "filename": "%s.zip" % root,
        "zip_bytes": buf.getvalue(),
        "summary": {
            "course_uuid": course.course_uuid,
            "course_name": course.name,
            "chapters": len(tree),
            "files": files_written,
            "images": images_written,
            "notes": notes,
        },
    }


def _deep_copy_doc(content):
    """只复制我们要改的那一层：blockImage 的 blockObject.content.file_name。"""
    import copy
    return copy.deepcopy(content) if isinstance(content, dict) else {}


async def _pull_images_into_zip(zf, root, course_uuid, activity_uuid, org_uuid,
                                doc, activity_name, notes, seen_assets):
    """把内容页里的图片下载进 zip 的 assets/，并把节点里的文件名改成相对路径。

    改 `file_name` 是因为 `tiptap_to_markdown` 输出图片时取的就是这个字段，
    改完导出的 md 里就是 `![](../assets/xxx.png)`，导入时能按相对路径找回来。
    """
    count = 0
    for node in (doc.get("content") or []):
        if node.get("type") != "blockImage":
            continue
        blk = (node.get("attrs") or {}).get("blockObject") or {}
        loc = _image_block_location(course_uuid, activity_uuid, blk)
        if not loc:
            notes.append("「%s」里有个图片块缺字段，导出时留了个占位" % activity_name)
            continue
        directory, file_and_format = loc
        if file_and_format not in seen_assets:
            try:
                data = await read_content(directory, "orgs", org_uuid, file_and_format)
            except HTTPException as e:
                notes.append("图片 %s 读不到（%s），跳过"
                             % ((blk.get("content") or {}).get("file_name", file_and_format),
                                e.detail))
                continue
            except Exception as e:  # 存储层任何意外都不该让整门课导不出来
                logger.warning("export image read failed: %s", e)
                notes.append("图片 %s 读取出错，跳过"
                             % (blk.get("content") or {}).get("file_name", file_and_format))
                continue
            zf.writestr("%s/assets/%s" % (root, file_and_format), data)
            seen_assets.add(file_and_format)
            count += 1
        ct = blk.get("content")
        if isinstance(ct, dict):
            ct["file_name"] = "../assets/%s" % file_and_format
    return count


# ------------------------------------------------------------ 导入


def read_zip_tree(zip_bytes: bytes):
    """安全地把 zip 读成 `{相对路径: 字节}`。

    三道闸：条目数、解压后总大小、以及**每个条目名都必须是相对且不含 `..`**
    （zip-slip）。我们全程在内存里处理，不往磁盘解压，所以路径穿越只可能伤到
    zip 内部的逻辑路径，但仍然一律拒绝，免得后面某次改动落盘时踩雷。
    """
    if len(zip_bytes) > MAX_ZIP_BYTES:
        raise TransferError("压缩包超过 %d MB，太大了" % (MAX_ZIP_BYTES // 1024 // 1024))
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise TransferError("这不是一个有效的 zip 文件")

    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > MAX_ZIP_ENTRIES:
        raise TransferError("压缩包里有 %d 个文件，超过 %d 个的上限"
                            % (len(infos), MAX_ZIP_ENTRIES))

    tree = {}
    total = 0
    for info in infos:
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or os.path.isabs(name) or ".." in name.split("/"):
            raise TransferError("压缩包里有非法路径：%s" % info.filename[:120])
        if "/__MACOSX/" in "/" + name or os.path.basename(name).startswith("._"):
            continue          # macOS 打包时塞的资源分叉，忽略
        data = _read_entry_capped(zf, info, MAX_UNCOMPRESSED_BYTES - total)
        total += len(data)
        tree[name] = data
    if not tree:
        raise TransferError("压缩包是空的")
    return tree


def _read_entry_capped(zf: zipfile.ZipFile, info: zipfile.ZipInfo, remaining: int) -> bytes:
    """流式读一个条目，边读边数，超出剩余额度立刻中止。

    **不信 zip 头里声明的 `file_size`**：那是压缩包自己写的数字，伪造成 1 就能
    绕过「解压后总大小」这道闸，然后 `zf.read()` 一把把几个 G 解进内存
    （zip 炸弹）。所以按实际读出来的字节数计。
    """
    if remaining <= 0:
        raise TransferError("解压后超过 %d MB 的上限"
                            % (MAX_UNCOMPRESSED_BYTES // 1024 // 1024))
    chunks, read = [], 0
    with zf.open(info) as fh:
        while True:
            chunk = fh.read(_ZIP_CHUNK)
            if not chunk:
                break
            read += len(chunk)
            if read > remaining:
                raise TransferError(
                    "解压后超过 %d MB 的上限（压缩包声明的大小和实际读到的对不上，"
                    "可能是个 zip 炸弹）" % (MAX_UNCOMPRESSED_BYTES // 1024 // 1024))
            chunks.append(chunk)
    return b"".join(chunks)


def locate_course_root(tree: dict):
    """在 zip 里找到那个含 README.md 的课程目录，返回它的前缀（可能是空串）。"""
    roots = sorted({name.rsplit("/", 1)[0] if "/" in name else ""
                    for name in tree if name.rsplit("/", 1)[-1] == "README.md"})
    if not roots:
        raise TransferError("压缩包里没有 README.md，不像是「导出 Markdown」生成的目录")
    if len(roots) > 1:
        raise TransferError("压缩包里有多个课程目录（%s），一次只导一门课"
                            % "、".join(r or "(根目录)" for r in roots))
    return roots[0]


def plan_import(tree: dict):
    """把 zip 内容整理成 [(章节名, [(文件名, 头, 正文), …]), …]，纯函数，好单测。"""
    root = locate_course_root(tree)
    prefix = (root + "/") if root else ""
    chapters = {}
    for name, data in tree.items():
        if not name.startswith(prefix):
            continue
        rel = name[len(prefix):]
        parts = rel.split("/")
        if len(parts) != 2 or not parts[1].lower().endswith(".md"):
            continue                      # README.md、assets/ 里的图片都落在这里
        ch_dir, fn = parts
        if ch_dir == "assets":
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise TransferError("%s 不是 UTF-8 编码的文本" % rel)
        meta, body = parse_front_matter(text)
        chapters.setdefault(ch_dir, []).append((fn, meta, body))
    if not chapters:
        raise TransferError("压缩包里没找到任何章节目录（应该形如 `01-章节名/01-页面名.md`）")
    return root, [(d, sorted(chapters[d], key=lambda x: x[0])) for d in sorted(chapters)]


def _find_asset(tree: dict, root: str, chapter_dir: str, src: str):
    """把 md 里的图片引用解析成 zip 里的字节。找不到返回 None。

    md 在 `<root>/<章节目录>/x.md`，导出写的是 `../assets/xxx.png`，
    所以按「章节目录 + 相对路径」拼再规范化。绝对路径和 http(s) 一律不认 ——
    导入不联网，也不读服务器本地磁盘。
    """
    if src.startswith(("http://", "https://", "data:", "/")):
        return None
    base = "%s/%s" % (root, chapter_dir) if root else chapter_dir
    joined = os.path.normpath("%s/%s" % (base, src)).replace("\\", "/")
    if joined.startswith("..") or joined.startswith("/"):
        return None
    return tree.get(joined)



def _inflight_index_tasks():
    """上游存放「在飞的索引重建任务」的集合。取不到就返回 None。

    这是在读上游的模块级私有变量（`_embedding_tasks`）。之所以这么做而不是加
    参数：上游 `update_activity` 没有留跳过索引的开关，而这个集合恰好是唯一
    能观测到并发度的地方。上游哪天改名了，`getattr` 拿不到就退回按页数节流，
    不会炸。
    """
    tasks = getattr(upstream_activities, "_embedding_tasks", None)
    return tasks if isinstance(tasks, set) else None


async def _throttle_index_tasks(pages_done: int) -> None:
    """把在飞的索引任务数压到上限以下，压不住就等它们跑完几个。"""
    tasks = _inflight_index_tasks()
    if tasks is None:
        # 观测不到并发度，退回最朴素的按页数歇一下
        if pages_done and pages_done % _FALLBACK_PAUSE_EVERY == 0:
            await asyncio.sleep(_FALLBACK_PAUSE_SECONDS)
        return

    # 快照一份再等：这个集合会被 done callback 改，直接拿它去 asyncio.wait
    # 有可能在迭代期间被改动。
    pending = {t for t in tasks if not t.done()}
    while len(pending) > MAX_INFLIGHT_INDEX_TASKS:
        _done, pending = await asyncio.wait(
            pending, return_when=asyncio.FIRST_COMPLETED)


async def import_course_markdown(
    request: Request,
    course_uuid: str,
    zip_bytes: bytes,
    current_user,
    db_session: AsyncSession,
    publish=None,
):
    """把「导出 Markdown」的 zip 导回一门课（新建章节 + 新建页面）。

    只处理 `type: page` 和 `type: embed`：视频、PDF、作业**不还原**，会在返回的
    `skipped` 里逐条列出来。`publish` 不给就沿用每个 md 头里的 `published`。

    **不会覆盖已有内容**：章节一律新建，所以重复导入会得到重复的章节，
    而不是把老师手改过的东西冲掉。
    """
    course = await _get_course(db_session, course_uuid)
    # 建章节 / 建活动的 service 各自会再查一次 RBAC，这里先拦一道，
    # 免得权限不足的人也能把 zip 传上来触发一堆解析工作。
    await check_resource_access(request, db_session, current_user, course.course_uuid, AccessAction.CREATE)

    tree = read_zip_tree(zip_bytes)
    root, chapters = plan_import(tree)

    created_chapters, created_activities, skipped = [], [], []
    pages_done = 0

    for ch_dir, entries in chapters:
        ch_name = re.sub(r"^\d+-", "", ch_dir)
        ch = await create_chapter(
            request,
            ChapterCreate(name=ch_name, description="",
                          org_id=course.org_id, course_id=course.id),  # type: ignore
            current_user, db_session)
        created_chapters.append({"chapter_id": ch.id, "name": ch_name})

        for fn, meta, body in entries:
            kind = meta.get("type", "page")
            name = meta.get("name") or re.sub(r"^\d+-", "", fn[:-3])
            want_pub = (meta.get("published", "false").lower() == "true"
                        if publish is None else bool(publish))

            if kind == "page":
                body, lost = strip_lost_nodes(body)
                result = await _create_page(
                    request, ch.id, name, body, want_pub, tree, root, ch_dir,  # type: ignore
                    current_user, db_session)
                if lost:
                    result["warnings"].append(
                        "这一页有 %d 个导出时无法还原的节点（%s），已从正文里剥掉 —— "
                        "留着的话学生会看到一行字面的 HTML 注释。请到网页编辑器里手工补回"
                        % (len(lost), "、".join(sorted(set(lost)))))
                created_activities.append(result)
                pages_done += 1
                # 每写完一页就把在飞的索引任务压回上限以下，别让它们攒起来
                # 把连接池占光（上千页的课会打满 5+10 的池子）。
                await _throttle_index_tasks(pages_done)

            elif kind == "embed":
                m = re.search(r"\[\[EMBED:(\S+?)\]\]", body)
                if not m:
                    skipped.append({"file": fn, "name": name,
                                    "reason": "嵌入活动的 md 里没找到 [[EMBED:…]]"})
                    continue
                act = await create_activity(
                    request,
                    ActivityCreate(
                        name=name, chapter_id=ch.id,  # type: ignore
                        activity_type=ActivityTypeEnum.TYPE_DYNAMIC,
                        activity_sub_type=ActivitySubTypeEnum.SUBTYPE_DYNAMIC_EMBED,
                        content={"embed_url": m.group(1)}, details={},
                        published=want_pub),
                    current_user, db_session)
                created_activities.append({"activity_uuid": act.activity_uuid,
                                           "name": name, "type": "embed", "warnings": []})
            else:
                skipped.append({
                    "file": fn, "name": name, "type": kind,
                    "reason": {
                        "video": "托管视频要重新上传原始 mp4",
                        "pdf": "PDF 要重新上传原始文件",
                        "assignment": "作业请用「作业工具」里的学期复用功能搬",
                    }.get(kind, "不支持导入的类型 %s" % kind)})

    return {
        "course_uuid": course.course_uuid,
        "course_name": course.name,
        "chapters_created": created_chapters,
        "activities_created": created_activities,
        "skipped": skipped,
        "counts": {"chapters": len(created_chapters),
                   "activities": len(created_activities),
                   "skipped": len(skipped)},
    }


async def _create_page(request, chapter_id, name, body, publish, tree, root, ch_dir,
                       current_user, db_session):
    """建一个富文本页。

    顺序被图片块接口锁死：图片块要绑 activity_uuid，所以必须
    **先建空页拿 uuid → 再上传图片 → 最后写 content**。
    """
    act = await create_activity(
        request,
        ActivityCreate(
            name=name, chapter_id=chapter_id,
            activity_type=ActivityTypeEnum.TYPE_DYNAMIC,
            activity_sub_type=ActivitySubTypeEnum.SUBTYPE_DYNAMIC_PAGE,
            content={}, details={}, published=False),
        current_user, db_session)

    warnings = []
    image_blocks = {}
    for src in scan_image_sources(body):
        data = _find_asset(tree, root, ch_dir, src)
        if data is None:
            warnings.append("图片 %s 不在压缩包里，跳过了" % src)
            continue
        if len(data) > MAX_IMAGE_BYTES:
            warnings.append("图片 %s 有 %d MB，超过单张上限，跳过了"
                            % (src, len(data) // 1024 // 1024))
            continue
        basename = os.path.basename(src)
        if not basename.lower().endswith(IMAGE_EXTS):
            warnings.append("图片 %s 的扩展名不在允许列表里，跳过了" % src)
            continue
        # 带上 content-type：`upload_file_and_return_file_object` 会把它写进块的
        # file_type 字段，缺了就全变成 application/octet-stream。
        # 真正的类型校验走扩展名 + 魔数（security/file_validation.py），不看这个头。
        upload = UploadFile(
            file=io.BytesIO(data), filename=basename, size=len(data),
            headers=Headers({"content-type":
                             mimetypes.guess_type(basename)[0] or "application/octet-stream"}))
        try:
            block = await create_image_block(
                request, upload, act.activity_uuid, db_session, current_user)
        except HTTPException as e:
            warnings.append("图片 %s 上传失败（%s）" % (src, e.detail))
            continue
        image_blocks[src] = block.model_dump()

    doc = md_to_tiptap(body, image_blocks=image_blocks, warnings=warnings)
    await update_activity(
        request, ActivityUpdate(content=doc, published=bool(publish)),
        act.activity_uuid, current_user, db_session)

    return {"activity_uuid": act.activity_uuid, "name": name, "type": "page",
            "node_types": [n.get("type") for n in doc.get("content", [])],
            "warnings": warnings}
