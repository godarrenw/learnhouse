"""作业查重：同一道题内两两比对学生答案，给出高相似的学生对。

移植自 skill/learnhouse/similarity.py。

**相似度只是线索，不是抄袭的结论。** 高相似可能来自同一份参考资料、同一个模板，
或者题目答案空间本来就小。结果里始终带这句免责说明，前端要原样显示。

比对口径：
- 文本题（简答 / 填空 / 编程）：归一化后取字符 3-gram Jaccard 与 difflib 比值的大者
- 文件题：先比 sha256（完全相同是最硬的证据），PDF 用 pypdf 抽文本后再比文字
- 客观题（选择 / 数值）跳过：答案本来就该一样
"""

import difflib
import hashlib
import io
import logging
import re

from fastapi import Request
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.courses.activities import Activity
from src.db.courses.assignments import (
    AssignmentTask,
    AssignmentTaskSubmission,
    AssignmentUserSubmission,
)
from src.db.organizations import Organization
from src.db.users import PublicUser, User
from src.services.courses.transfer.storage_utils import read_file_content

from .quickquiz import _display_name, _load_assignment

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 0.8
MIN_LENGTH = 15          # 归一化后短于这个长度的答案不参与比对
NGRAM = 3                # 字符 n-gram 的 n
SNIPPET_CHARS = 120      # 结果里带的片段长度

TEXT_TYPES = ("SHORT_ANSWER", "FORM", "CODE")
FILE_TYPES = ("FILE_SUBMISSION",)
SKIP_TYPES = ("QUIZ", "NUMBER_ANSWER")

DISCLAIMER = (
    "相似度只是线索，不是抄袭的结论。高相似可能来自同一份参考资料、同一个模板，"
    "或者题目答案空间本来就小。请老师逐对打开原文自行判断。"
)

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[，。！？；：、（）《》「」“”‘’【】,.!?;:()<>\[\]\"'`~—\-_/\\|]+")


# ---------------------------------------------------------------- 文本相似度


def normalize(text) -> str:
    """比对前的归一化：去标点、去空白、英文转小写。

    这样「计算机 数控（CNC）」和「计算机数控cnc」会被当成同一串，
    避免排版差异把明显相同的答案拆开。
    """
    if text is None:
        return ""
    s = _PUNCT.sub("", str(text))
    s = _WS.sub("", s)
    return s.lower()


def _ngrams(s: str, n: int = NGRAM) -> set:
    if len(s) < n:
        return {s} if s else set()
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def jaccard(a: str, b: str, n: int = NGRAM) -> float:
    """字符 n-gram 的 Jaccard 系数，0~1。"""
    ga, gb = _ngrams(a, n), _ngrams(b, n)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / float(len(ga | gb))


def ratio(a: str, b: str) -> float:
    """difflib 比值。autojunk=False，否则长文本里的高频字符会被当噪声丢掉。"""
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def similarity(a: str, b: str) -> float:
    """两段**已归一化**文本的相似度：两种算法取大值。"""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return max(jaccard(a, b), ratio(a, b))


def common_snippet(a: str, b: str, limit: int = SNIPPET_CHARS) -> str:
    """两段原文里最长的那段公共文字，给老师一眼看出「重的是哪里」。"""
    if not a or not b:
        return ""
    m = difflib.SequenceMatcher(None, a, b, autojunk=False).find_longest_match(
        0, len(a), 0, len(b)
    )
    piece = a[m.a:m.a + m.size]
    return piece[:limit] + ("…" if len(piece) > limit else "")


# ---------------------------------------------------------------- 提交内容抽取


def answer_text(atype: str, task_submission, contents=None):
    """把一条 task_submission 转成可比对的纯文本；不适合比对的返回 None。"""
    if task_submission is None:
        return None
    if atype == "SHORT_ANSWER":
        v = (
            task_submission.get("answer")
            if isinstance(task_submission, dict)
            else task_submission
        )
        return None if v is None else str(v)
    if atype == "CODE":
        if isinstance(task_submission, dict):
            return task_submission.get("source_code")
        return str(task_submission)
    if atype == "FORM":
        if not isinstance(task_submission, dict):
            return None
        parts = [
            str(s.get("answer") or "") for s in (task_submission.get("submissions") or [])
        ]
        joined = " ".join(p for p in parts if p)
        return joined or None
    return None


def correct_answers(atype: str, contents) -> list[str]:
    """题目自带的标准答案，用来把「答对了」剔出比对池。"""
    contents = contents or {}
    if atype == "SHORT_ANSWER":
        return [str(x) for x in (contents.get("correct_answers") or [])]
    if atype == "FORM":
        out = []
        for q in contents.get("questions") or []:
            blanks = [str(b.get("correctAnswer") or "") for b in (q.get("blanks") or [])]
            if blanks:
                out.append(" ".join(blanks))
        # 填空题各空答案连起来就是一份「全对」的答案
        return [" ".join(out)] if out else []
    return []


def extract_file_text(filename: str, blob: bytes) -> tuple[str, str]:
    """从提交的文件里抽文本，返回 (文本, 抽取方式)。

    只支持 PDF（pypdf，后端已有依赖）和纯文本类文件。docx 需要 python-docx，
    后端没这个依赖，也不为查重单独加，抽不出来时只按 sha256 比对。
    """
    lower = (filename or "").lower()
    if lower.endswith(".pdf"):
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(blob))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
            if text.strip():
                return text, "pypdf"
            return "", "none"
        except Exception as e:  # 坏 PDF / 加密 PDF 不该让整次查重挂掉
            logger.warning("查重：PDF 抽文本失败 %s（%s）", filename, type(e).__name__)
            return "", "none"
    if lower.endswith((".txt", ".md", ".csv", ".py", ".js", ".ts", ".java", ".c", ".cpp")):
        try:
            return blob.decode("utf-8", "replace"), "plaintext"
        except Exception:
            return "", "none"
    return "", "none"


def _submission_file_path(
    org_uuid: str,
    course_uuid: str,
    activity_uuid: str,
    assignment_uuid: str,
    task_uuid: str,
    filename: str,
) -> str:
    """提交文件在内容存储里的相对路径，与 uploads/sub_file.py 的写入路径一致。"""
    return (
        f"content/orgs/{org_uuid}/courses/{course_uuid}/activities/{activity_uuid}"
        f"/assignments/{assignment_uuid}/tasks/{task_uuid}/subs/{filename}"
    )


# ---------------------------------------------------------------- 主流程


async def check_assignment(
    request: Request,
    assignment_uuid: str,
    current_user: PublicUser,
    db_session: AsyncSession,
    threshold: float = DEFAULT_THRESHOLD,
    min_length: int = MIN_LENGTH,
) -> dict:
    """对一份作业查重，返回高相似的学生对。"""
    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        threshold = DEFAULT_THRESHOLD
    threshold = min(1.0, max(0.1, threshold))
    try:
        min_length = max(1, int(min_length))
    except (TypeError, ValueError):
        min_length = MIN_LENGTH

    assignment, course = await _load_assignment(
        request, assignment_uuid, current_user, db_session
    )

    org = (await db_session.execute(
        select(Organization).where(Organization.id == assignment.org_id)
    )).scalars().first()
    activity = (await db_session.execute(
        select(Activity).where(Activity.id == assignment.activity_id)
    )).scalars().first()

    tasks = list((await db_session.execute(
        select(AssignmentTask)
        .where(AssignmentTask.assignment_id == assignment.id)
        .order_by(AssignmentTask.id)
    )).scalars().all())

    names: dict[int, str] = {}
    for us, user in (await db_session.execute(
        select(AssignmentUserSubmission, User)
        .outerjoin(User, AssignmentUserSubmission.user_id == User.id)
        .where(AssignmentUserSubmission.assignment_id == assignment.id)
    )).all():
        names[us.user_id] = _display_name(user, us.user_id)

    rows: list[dict] = []
    notes: list[str] = []

    for t in tasks:
        atype = (
            t.assignment_type.value
            if hasattr(t.assignment_type, "value")
            else t.assignment_type
        )
        if atype in SKIP_TYPES:
            notes.append("跳过客观题「%s」（%s）：答案本来就该一样" % (t.title, atype))
            continue
        if atype not in TEXT_TYPES and atype not in FILE_TYPES:
            notes.append("跳过题型 %s 的「%s」：不支持查重" % (atype, t.title))
            continue

        corrects = [normalize(x) for x in correct_answers(atype, t.contents)]
        subs = (await db_session.execute(
            select(AssignmentTaskSubmission)
            .where(AssignmentTaskSubmission.assignment_task_id == t.id)
        )).scalars().all()

        for s in subs:
            uid = s.user_id
            row = {
                "task_uuid": t.assignment_task_uuid, "task_title": t.title,
                "assignment_type": atype, "user_id": uid,
                "user_name": names.get(uid, str(uid)),
                "sha256": None, "filename": None, "extract_method": None,
                "size": None, "text": "",
            }
            payload = s.task_submission

            if atype in FILE_TYPES:
                filename = None
                if isinstance(payload, dict):
                    filename = payload.get("fileUUID") or payload.get("file_uuid")
                if not filename or not org or not activity:
                    continue
                path = _submission_file_path(
                    org.org_uuid, course.course_uuid, activity.activity_uuid,
                    assignment.assignment_uuid, t.assignment_task_uuid, str(filename),
                )
                blob = read_file_content(path)
                if blob is None:
                    notes.append("学生 %s 的文件读不到，跳过" % row["user_name"])
                    continue
                row["sha256"] = hashlib.sha256(blob).hexdigest()
                row["size"] = len(blob)
                row["filename"] = str(filename)
                text, how = extract_file_text(str(filename), blob)
                row["extract_method"] = how
                if how == "none":
                    notes.append(
                        "学生 %s 的文件 %s 抽不出文本（格式不支持），"
                        "这一份只按 sha256 比对" % (row["user_name"], row["filename"])
                    )
                row["text"] = text or ""
            else:
                text = answer_text(atype, payload, t.contents)
                if text is None:
                    continue
                row["text"] = text

            row["norm"] = normalize(row["text"])
            row["correct_answers"] = corrects
            rows.append(row)

    # 剔掉太短的和「答对了所以本来就一样」的
    skipped, pool = [], []
    for r in rows:
        norm = r.get("norm") or ""
        if len(norm) < min_length:
            if r.get("sha256"):
                pool.append(r)  # 文件题即使抽不出文本，也要参与 sha256 比对
            else:
                skipped.append({
                    "user_name": r["user_name"], "task_title": r["task_title"],
                    "reason": "答案太短（归一化后 %d 字，阈值 %d）" % (len(norm), min_length),
                })
            continue
        if any(ca and similarity(norm, ca) >= threshold for ca in r.get("correct_answers") or []):
            skipped.append({
                "user_name": r["user_name"], "task_title": r["task_title"],
                "reason": "与标准答案高度一致，答对的人写的本来就一样",
            })
            continue
        pool.append(r)

    by_task: dict[str, list[dict]] = {}
    for r in pool:
        by_task.setdefault(r["task_uuid"], []).append(r)

    pairs, identical, compared = [], [], {}
    for group in by_task.values():
        title = group[0]["task_title"]
        compared[title] = len(group)

        # 完全相同的文件（最硬的证据，单独报）
        by_hash: dict[str, list[dict]] = {}
        for r in group:
            if r.get("sha256"):
                by_hash.setdefault(r["sha256"], []).append(r)
        same_file_pairs = set()
        for h, members in by_hash.items():
            if len(members) > 1:
                identical.append({
                    "task_title": title, "sha256": h, "size": members[0].get("size"),
                    "users": [m["user_name"] for m in members],
                    "user_ids": [m["user_id"] for m in members],
                    "filenames": [m.get("filename") for m in members],
                })
                for i in range(len(members)):
                    for j in range(i + 1, len(members)):
                        same_file_pairs.add(
                            tuple(sorted((members[i]["user_id"], members[j]["user_id"])))
                        )

        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                ra, rb = group[i], group[j]
                key = tuple(sorted((ra["user_id"], rb["user_id"])))
                na, nb = ra.get("norm") or "", rb.get("norm") or ""
                same_file = key in same_file_pairs
                if not na or not nb:
                    # 抽不出文本的文件，只有 sha256 相同才报
                    if same_file:
                        pairs.append(_pair(
                            ra, rb, 1.0, None, None, title, True,
                            "文件 sha256 完全相同（文本没抽出来）",
                        ))
                    continue
                j_score = jaccard(na, nb)
                r_score = ratio(na, nb)
                score = max(j_score, r_score)
                if score >= threshold or same_file:
                    pairs.append(_pair(
                        ra, rb, score, j_score, r_score, title, same_file,
                        common_snippet(ra["text"], rb["text"]),
                    ))

    pairs.sort(key=lambda p: (-p["similarity"], p["task_title"]))

    return {
        "assignment_uuid": assignment.assignment_uuid,
        "title": assignment.title,
        "course_uuid": course.course_uuid,
        "threshold": threshold,
        "min_length": min_length,
        "pairs": pairs,
        "identical_files": identical,
        "compared": compared,
        "skipped": skipped,
        "notes": notes,
        "disclaimer": DISCLAIMER,
    }


def _pair(ra, rb, score, j_score, r_score, title, same_file, snippet) -> dict:
    return {
        "task_title": title,
        "user_a": ra["user_name"], "user_a_id": ra["user_id"],
        "user_b": rb["user_name"], "user_b_id": rb["user_id"],
        "similarity": round(float(score), 4),
        "jaccard": None if j_score is None else round(float(j_score), 4),
        "ratio": None if r_score is None else round(float(r_score), 4),
        "same_file": bool(same_file),
        "snippet": snippet,
    }
