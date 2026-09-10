"""作业 spec：题型转换、校验与模板。

移植自 skill/learnhouse/assignments.py 的 `build_task_contents` 与
skill/learnhouse/aiquiz.py 的 `validate_spec` / `spec_template`。
纯函数，不碰数据库、不联网，可以放心反复调用。
"""

import re
import uuid
from typing import Any

KIND_TO_TYPE = {
    "quiz": "QUIZ",
    "short_answer": "SHORT_ANSWER",
    "number_answer": "NUMBER_ANSWER",
    "file": "FILE_SUBMISSION",
    "form": "FORM",
    "code": "CODE",
}
TYPE_TO_KIND = {v: k for k, v in KIND_TO_TYPE.items()}

GRADING_TYPES = ("NUMERIC", "PERCENTAGE", "ALPHABET", "PASS_FAIL", "GPA_SCALE")
MATCH_MODES = ("exact", "case_insensitive", "contains", "regex")

# 上游 SolutionRevealEnum（db/courses/assignments.py）只有这三个值。
# 早期文档里写的 ON_SUBMIT 是错的，传进去后端会 422。
SOLUTION_REVEALS = ("NEVER", "ON_SUBMISSION", "AFTER_GRADING")

# Judge0 语言 id（取自前端 CodePlayground/languages.ts）
CODE_LANGUAGES = {
    "python": 71, "python3": 71, "javascript": 63, "node": 63, "typescript": 74,
    "java": 62, "cpp": 54, "c++": 54, "c": 50, "rust": 73, "go": 60, "php": 68,
    "ruby": 72, "kotlin": 78, "csharp": 51, "c#": 51, "swift": 83, "scala": 81,
    "perl": 85, "r": 80, "dart": 90, "haskell": 61, "lua": 64,
}

KIND_LABELS = {
    "quiz": "选择题", "short_answer": "简答题", "number_answer": "数值题",
    "file": "文件提交题", "form": "填空题", "code": "编程题",
}

DEFAULT_TITLES = {
    "quiz": "选择题", "short_answer": "简答题", "number_answer": "数值题",
    "file": "文件提交", "form": "填空题", "code": "编程题",
}

# 命令行/前端上允许的题型简写
KIND_ALIASES = {
    "short": "short_answer", "shortanswer": "short_answer",
    "number": "number_answer", "num": "number_answer", "numberanswer": "number_answer",
    "choice": "quiz", "single": "quiz", "multiple": "quiz",
    "fill": "form", "blank": "form",
    "upload": "file", "file_submission": "file",
}


class SpecError(ValueError):
    """作业描述（spec）写错了，用中文说清哪一项不对。"""


def _q_uuid() -> str:
    return f"question_{uuid.uuid4()}"


def _o_uuid() -> str:
    return f"option_{uuid.uuid4()}"


def _b_uuid() -> str:
    return f"blank_{uuid.uuid4()}"


def normalize_kinds(kinds) -> list[str]:
    """把外部给的题型列表规范成库里认的 kind，顺手校验。"""
    out: list[str] = []
    for k in kinds or []:
        k = str(k).strip().lower()
        if not k:
            continue
        k = KIND_ALIASES.get(k, k)
        if k not in KIND_TO_TYPE:
            raise SpecError(
                "不认识的题型「%s」。可选：%s（也认简写 short / number / fill）"
                % (k, "、".join(KIND_TO_TYPE))
            )
        if k not in out:
            out.append(k)
    return out


# ---------------------------------------------------------------- contents 构造


def build_task_contents(kind: str, **spec) -> dict:
    """把老师友好的题目描述转成后端 `AssignmentTask.contents` 结构（自动补 UUID）。

    quiz:          questions=[{'text','options':[...],'answer':'2' 或 ['2','3'],'multiple':False}]
    short_answer:  prompt, answers=[...], match_mode='case_insensitive', explanation=''
    number_answer: prompt, value, tolerance=0, unit='', explanation=''
    file:          无
    form:          questions=[{'text':'CNC 是 __ 的缩写','blanks':[{'answer','placeholder','hint'}]}]
    code:          language, starter_code, solution_code, tests=[...], grading_mode
    """
    kind = (kind or "").lower()
    if kind not in KIND_TO_TYPE:
        raise SpecError("未知题型「%s」，可选：%s" % (kind, "、".join(KIND_TO_TYPE)))

    if kind == "file":
        return {}

    if kind == "quiz":
        questions = spec.get("questions") or []
        if not questions:
            raise SpecError("quiz 题必须给 questions")
        out = []
        for q in questions:
            text = q.get("text") or q.get("questionText") or ""
            opts_in = q.get("options") or []
            answer = q.get("answer")
            if answer is None:
                answer = q.get("answers")
            right: set[str] = set()
            if isinstance(answer, (list, tuple, set)):
                right = {str(a) for a in answer}
            elif answer is not None:
                right = {str(answer)}
            options = []
            for i, opt in enumerate(opts_in):
                if isinstance(opt, dict):
                    otext = opt.get("text", "")
                    ok = bool(opt.get("correct", opt.get("assigned_right_answer", False)))
                else:
                    otext = str(opt)
                    ok = otext in right or str(i) in right
                options.append({
                    "optionUUID": _o_uuid(), "text": otext, "fileID": "", "type": "text",
                    "assigned_right_answer": ok,
                })
            n_right = sum(1 for o in options if o["assigned_right_answer"])
            if n_right == 0:
                raise SpecError("题目「%s」没有标出正确答案" % text)
            # 答案个数说了算：标了两个及以上正确项就必须是多选，否则学生永远做不对
            rtype = "multiple" if (n_right >= 2 or q.get("multiple")) else "single"
            out.append({
                "questionUUID": _q_uuid(), "questionText": text,
                "response_type": rtype, "options": options,
            })
        mode = spec.get("grading_mode", "all_or_nothing")
        if mode not in ("all_or_nothing", "partial_credit"):
            raise SpecError("quiz grading_mode 只能是 all_or_nothing / partial_credit")
        return {"questions": out, "grading_mode": mode}

    if kind == "short_answer":
        answers = spec.get("answers") or spec.get("correct_answers") or []
        if isinstance(answers, str):
            answers = [answers]
        if not answers:
            raise SpecError("short_answer 必须给 answers")
        mode = spec.get("match_mode", "case_insensitive")
        if mode not in MATCH_MODES:
            raise SpecError("match_mode 只能是：%s" % "、".join(MATCH_MODES))
        c: dict[str, Any] = {
            "prompt": spec.get("prompt", ""),
            "correct_answers": [str(a) for a in answers],
            "match_mode": mode,
        }
        if spec.get("explanation"):
            c["explanation"] = spec["explanation"]
        return c

    if kind == "number_answer":
        if "value" not in spec and "correct_value" not in spec:
            raise SpecError("number_answer 必须给 value")
        raw = spec.get("value", spec.get("correct_value"))
        try:
            correct_value = float(raw)
        except (TypeError, ValueError):
            raise SpecError("number_answer 的 value「%s」不是一个数字" % raw)
        try:
            tolerance = float(spec.get("tolerance", 0) or 0)
        except (TypeError, ValueError):
            raise SpecError("number_answer 的 tolerance「%s」不是一个数字" % spec.get("tolerance"))
        c = {
            "prompt": spec.get("prompt", ""),
            "correct_value": correct_value,
            "tolerance": tolerance,
            "unit": spec.get("unit", "") or "",
        }
        if spec.get("explanation"):
            c["explanation"] = spec["explanation"]
        return c

    if kind == "form":
        questions = spec.get("questions") or []
        if not questions:
            raise SpecError("form 题必须给 questions")
        out = []
        for q in questions:
            text = q.get("text") or q.get("questionText") or ""
            blanks_in = q.get("blanks") or []
            blanks = []
            for b in blanks_in:
                if isinstance(b, dict):
                    ans = b.get("answer", b.get("correctAnswer", ""))
                    ph = b.get("placeholder", "填写答案")
                    hint = b.get("hint", "")
                else:
                    ans, ph, hint = str(b), "填写答案", ""
                blank = {"blankUUID": _b_uuid(), "placeholder": ph, "correctAnswer": str(ans)}
                if hint:
                    blank["hint"] = hint
                blanks.append(blank)
            if not blanks:
                raise SpecError("填空题「%s」至少要有一个空" % text)
            out.append({"questionUUID": _q_uuid(), "questionText": text, "blanks": blanks})
        return {"questions": out}

    # code
    lang = spec.get("language", "python")
    lang_id = spec.get("language_id") or CODE_LANGUAGES.get(str(lang).lower())
    if not lang_id:
        raise SpecError(
            "不认识的语言「%s」，可选：%s" % (lang, "、".join(sorted(set(CODE_LANGUAGES))))
        )
    tests = []
    for i, t in enumerate(spec.get("tests") or spec.get("test_cases") or []):
        tests.append({
            "id": t.get("id") or str(uuid.uuid4()),
            "label": t.get("label") or ("测试 %d" % (i + 1)),
            "stdin": t.get("stdin", ""),
            "expectedStdout": t.get("expected", t.get("expectedStdout", "")),
            "hidden": bool(t.get("hidden", False)),
            "weight": int(t.get("weight", 1) or 1),
        })
    mode = spec.get("grading_mode", "equal_weight")
    if mode not in ("equal_weight", "binary", "custom_weights"):
        raise SpecError("code grading_mode 只能是 equal_weight / binary / custom_weights")
    return {
        "language_id": int(lang_id),
        "starter_code": spec.get("starter_code", ""),
        "solution_code": spec.get("solution_code", ""),
        "grading_mode": mode,
        "test_cases": tests,
        "allow_student_run": bool(spec.get("allow_student_run", True)),
        "show_test_details_on_fail": bool(spec.get("show_test_details_on_fail", True)),
        "show_hidden_test_count": bool(spec.get("show_hidden_test_count", True)),
        "require_passing_to_submit": bool(spec.get("require_passing_to_submit", False)),
    }


# ---------------------------------------------------------------- 校验


def strip_comments(obj):
    """去掉 `_` 开头的注释键，返回干净的副本。"""
    if isinstance(obj, dict):
        return {k: strip_comments(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [strip_comments(x) for x in obj]
    return obj


def _quiz_warnings(idx: int, task: dict) -> list[str]:
    """挑 build_task_contents 不会报错、但老师大概率写错了的地方。"""
    warns = []
    for qi, q in enumerate(task.get("questions") or []):
        text = q.get("text") or q.get("questionText") or ""
        opts = q.get("options") or []
        answer = q.get("answer", q.get("answers"))
        if answer is None:
            has_correct = any(
                isinstance(o, dict) and o.get("correct", o.get("assigned_right_answer"))
                for o in opts
            )
            if not has_correct:
                warns.append(
                    "第 %d 题第 %d 小问「%s」既没写 answer，选项里也没标 correct"
                    % (idx, qi + 1, text[:20])
                )
            continue
        wanted = {str(a) for a in (answer if isinstance(answer, (list, tuple, set)) else [answer])}
        texts = [o if isinstance(o, str) else o.get("text", "") for o in opts]
        for a in wanted:
            in_text = a in texts
            as_index = a.isdigit() and 0 <= int(a) < len(texts)
            if not in_text and not as_index:
                warns.append(
                    "第 %d 题第 %d 小问「%s」的答案「%s」既不在选项文本里，"
                    "也不是合法下标 —— 这道题学生永远做不对"
                    % (idx, qi + 1, text[:20], a)
                )
            elif in_text and as_index and texts[int(a)] != a:
                warns.append(
                    "第 %d 题第 %d 小问的答案「%s」有歧义：它既是某个选项的文本，"
                    "又能当成下标解释成「%s」。请把 options 改写成 "
                    '{"text": …, "correct": true} 的形式'
                    % (idx, qi + 1, a, texts[int(a)])
                )
    return warns


def summarize(kind: str, contents: dict) -> str:
    """一道题压成一行人能读的话，用来念给老师听。"""
    if kind == "quiz":
        bits = []
        for q in contents.get("questions") or []:
            right = [o["text"] for o in q["options"] if o["assigned_right_answer"]]
            bits.append(
                "%s（%s，%d 选 %d，答案：%s）"
                % (
                    q["questionText"],
                    "多选" if q["response_type"] == "multiple" else "单选",
                    len(q["options"]), len(right), "／".join(right),
                )
            )
        return "；".join(bits)
    if kind == "short_answer":
        return "%s（答案：%s，匹配方式 %s）" % (
            contents.get("prompt", ""),
            "／".join(contents.get("correct_answers") or []),
            contents.get("match_mode"),
        )
    if kind == "number_answer":
        return "%s（答案：%s±%s %s）" % (
            contents.get("prompt", ""), contents.get("correct_value"),
            contents.get("tolerance"), contents.get("unit") or "",
        )
    if kind == "form":
        return "；".join(
            "%s（答案：%s）"
            % (q["questionText"], "／".join(b["correctAnswer"] for b in q["blanks"]))
            for q in (contents.get("questions") or [])
        )
    if kind == "file":
        return "学生上传文件，只能人工批改"
    if kind == "code":
        return "编程题，%d 个测试用例" % len(contents.get("test_cases") or [])
    return ""


def validate_spec(raw: dict) -> dict:
    """校验一份 spec 并给出预览。

    顶层字段检查 → 逐题调 `build_task_contents` → 汇总成每题一行的摘要。
    校验不通过抛 SpecError；通过返回带 tasks / summary / warnings 的字典。
    """
    if not isinstance(raw, dict):
        raise SpecError("spec 必须是一个 JSON 对象（{…}），现在是 %s" % type(raw).__name__)
    s = strip_comments(raw)

    problems = []
    name = s.get("name") or s.get("title")
    if not name:
        problems.append("缺 name（作业标题）")
    gt = s.get("grading_type", "NUMERIC")
    if gt not in GRADING_TYPES:
        problems.append("grading_type「%s」不对，可选：%s" % (gt, "、".join(GRADING_TYPES)))
    due = s.get("due_date")
    if due and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(due)):
        problems.append("due_date「%s」格式不对，要 YYYY-MM-DD" % due)
    sr = s.get("solution_reveal", "NEVER")
    if sr not in SOLUTION_REVEALS:
        hint = "（想写的是 ON_SUBMISSION 吧？）" if str(sr).upper() == "ON_SUBMIT" else ""
        problems.append(
            "solution_reveal「%s」不对%s，可选 %s" % (sr, hint, " / ".join(SOLUTION_REVEALS))
        )
    tasks = s.get("tasks") or []
    if not tasks:
        problems.append("tasks 是空的，作业至少要有一道题")
    if problems:
        raise SpecError("spec 有问题：\n  · " + "\n  · ".join(problems))

    out_tasks, previews, warnings = [], [], []
    for i, t in enumerate(tasks):
        t = dict(t)
        kind = (t.pop("kind", None) or t.pop("type", None) or "").lower()
        if kind not in KIND_TO_TYPE:
            raise SpecError(
                "第 %d 道题的 kind 不对：「%s」。可选：%s"
                % (i + 1, kind or "(空)", "、".join(KIND_TO_TYPE))
            )
        meta = {k: t.pop(k, None) for k in ("title", "description", "hint", "max_grade_value")}
        mine = _quiz_warnings(i + 1, t) if kind == "quiz" else []
        warnings.extend(mine)
        try:
            contents = build_task_contents(kind, **t)
        except SpecError as e:
            extra = ("\n  线索：" + "\n  线索：".join(mine)) if mine else ""
            raise SpecError(
                "第 %d 道题（%s）没通过校验：%s%s"
                % (i + 1, KIND_LABELS.get(kind, kind), e, extra)
            )
        title = meta.get("title") or DEFAULT_TITLES[kind]
        try:
            max_grade = int(meta.get("max_grade_value") or 100)
        except (TypeError, ValueError):
            raise SpecError("第 %d 道题的 max_grade_value 不是整数" % (i + 1))
        if max_grade < 0:
            raise SpecError("第 %d 道题的 max_grade_value 不能是负数" % (i + 1))
        out_tasks.append({
            "index": i + 1, "kind": kind, "type": KIND_TO_TYPE[kind], "title": title,
            "description": meta.get("description") or "",
            "hint": meta.get("hint") or "",
            "max_grade_value": max_grade,
            "contents": contents,
        })
        previews.append({
            "index": i + 1, "kind": kind, "kind_label": KIND_LABELS.get(kind, kind),
            "title": title, "summary": summarize(kind, contents),
        })

    result = {
        "ok": True,
        "name": name,
        "task_count": len(out_tasks),
        "total_max_grade": sum(t["max_grade_value"] for t in out_tasks),
        "publish": bool(s.get("publish", True)),
        "grading_type": gt,
        "due_date": due,
        "solution_reveal": sr,
        "summary": previews,
        "tasks": out_tasks,
        "warnings": warnings,
    }
    if result["publish"]:
        result["warnings"] = warnings + [
            "spec 里 publish 是 true：建出来学生立刻能看到。"
            "AI 出的题建议先留草稿，老师过目后再发布。"
        ]
    return result


# ---------------------------------------------------------------- 模板


def spec_template(kinds=None) -> dict:
    """返回一份带注释的 spec 模板。以 `_` 开头的键都是注释，校验时会被忽略。"""
    kinds = normalize_kinds(kinds or ["quiz", "short_answer", "number_answer"])

    samples = {
        "quiz": {
            "kind": "quiz",
            "title": "选择题",
            "_comment": "options 用 {text, correct} 字典写，别只写字符串 —— "
                        "写字符串时答案会先按文本匹配、再按下标匹配，"
                        "答案恰好是 '1' '2' 这种数字时会歧义",
            "questions": [
                {
                    "text": "数控机床的三大组成部分不包括下列哪一项？",
                    "options": [
                        {"text": "控制系统", "correct": False},
                        {"text": "伺服驱动系统", "correct": False},
                        {"text": "冷却水塔", "correct": True},
                        {"text": "机械本体", "correct": False},
                    ],
                },
            ],
            "grading_mode": "all_or_nothing",
        },
        "short_answer": {
            "kind": "short_answer",
            "title": "简答题",
            "prompt": "CNC 的中文全称是什么？",
            "answers": ["计算机数控", "计算机数字控制"],
            "match_mode": "contains",
            "_comment": "match_mode: exact / case_insensitive / contains / regex。"
                        "中文简答建议 contains，避免学生多写几个字就判错",
            "explanation": "Computer Numerical Control。",
        },
        "number_answer": {
            "kind": "number_answer",
            "title": "数值题",
            "prompt": "主轴转速 1200 r/min、每齿进给 0.1 mm、4 齿刀具，进给速度是多少 mm/min？",
            "value": 480,
            "tolerance": 1,
            "unit": "mm/min",
            "_comment": "tolerance 是允许的绝对误差；有单位就写在 unit 里，别写进 value",
        },
        "form": {
            "kind": "form",
            "title": "填空题",
            "_comment": "每个空一个 blank，题干里用 __ 标出空的位置",
            "questions": [
                {
                    "text": "增材制造中最常见的金属工艺是 __ 和 __。",
                    "blanks": [
                        {"answer": "选区激光熔化", "placeholder": "工艺一"},
                        {"answer": "电子束熔化", "placeholder": "工艺二"},
                    ],
                },
            ],
        },
        "file": {
            "kind": "file",
            "title": "提交实验报告",
            "description": "上传 PDF，命名为「学号-姓名-实验一」。",
            "_comment": "文件题只能人工批改，自动判分给不了分",
        },
        "code": {
            "kind": "code",
            "title": "编程题",
            "language": "python",
            "starter_code": "def solve(n):\n    pass\n",
            "solution_code": "def solve(n):\n    return n * 2\n",
            "tests": [{"stdin": "3", "expected": "6", "label": "基本用例"}],
            "_comment": "编程题判分依赖 Judge0，本实例是否配置未验证，用之前先在测试课程上试",
        },
    }

    return {
        "_说明": "这是一份作业 spec 模板。以 _ 开头的键都是注释，会被忽略。",
        "name": "第 X 章随堂练习",
        "description": "根据本节内容出的练习题。",
        "due_date": None,
        "_due_date": "格式 YYYY-MM-DD，不设截止就留 null",
        "grading_type": "NUMERIC",
        "_grading_type": "可选 " + " / ".join(GRADING_TYPES),
        "publish": False,
        "_publish": "保持 false。先让老师在网页上看一眼题目和答案，确认了再发布",
        "auto_grading": True,
        "show_correct_answers": False,
        "allow_retries": False,
        "max_retries": 0,
        "formative": False,
        "_formative": "true 表示形成性练习、不计入成绩（对应后端 ungraded）",
        "solution_reveal": "NEVER",
        "_solution_reveal": "可选 " + " / ".join(SOLUTION_REVEALS),
        "tasks": [samples[k] for k in kinds],
    }
