# -*- coding: utf-8 -*-
"""把作业渲染成 Markdown（题目 + 参考答案）。

移植自教学工具 skill 的 `tools.py` 的 `_assignment_markdown`。

**故意不复用作业工具（assign-tools）的模块**：那条线在自己的分支上还在动，
两边互相 import 会把两个功能的发布节奏绑死。这里只读 `assignment` 和
`assignmenttask` 两张表，读的是上游的表结构，不会随对方重构而碎。

渲染出来的 Markdown **含参考答案**，并在正文最上方明确标了一行警告。
导出接口因此按「课程 update 权限」判，不按 read —— 能拿到答案的人必须是
能改这门课的人。

反向导入**不还原作业**：题目、评分方式、提交记录这些不是 Markdown 能表达的，
硬塞回去只会做出一个形似而神不似的壳。导出包的 README 里指向作业工具的学期复用。
"""
from src.db.courses.assignments import AssignmentTaskTypeEnum

#: 任务类型 → 渲染分支。上游枚举变了这里会落到 default 分支，不会炸。
_KIND_LABEL = {
    AssignmentTaskTypeEnum.QUIZ.value: "选择题",
    AssignmentTaskTypeEnum.FORM.value: "填空题",
    AssignmentTaskTypeEnum.CODE.value: "编程题",
    AssignmentTaskTypeEnum.SHORT_ANSWER.value: "简答题",
    AssignmentTaskTypeEnum.NUMBER_ANSWER.value: "数值题",
    AssignmentTaskTypeEnum.FILE_SUBMISSION.value: "文件提交",
    AssignmentTaskTypeEnum.CUSTOM.value: "自定义题",
    AssignmentTaskTypeEnum.OTHER.value: "其他",
}


def _enum_value(v):
    return v.value if hasattr(v, "value") else str(v) if v is not None else ""


def _option_label(index: int) -> str:
    """0 → A，1 → B……超过 26 个选项就退回数字，别把字母表转圈。"""
    return chr(ord("A") + index) if index < 26 else str(index + 1)


def _quiz_block(contents: dict, out: list):
    for q in contents.get("questions") or []:
        out += [str(q.get("questionText", "")), ""]
        right = []
        for i, opt in enumerate(q.get("options") or []):
            mark = _option_label(i)
            out.append("- %s. %s" % (mark, opt.get("text", "")))
            if opt.get("assigned_right_answer"):
                right.append(mark)
        out += ["", "**参考答案**：%s" % ("、".join(right) if right else "（没有标正确选项）"), ""]


def _form_block(contents: dict, out: list):
    for q in contents.get("questions") or []:
        out += [str(q.get("questionText", "")), ""]
        answers = [str(b.get("correctAnswer", "")) for b in (q.get("blanks") or [])]
        out += ["**参考答案**：%s" % ("；".join(answers) if answers else "（没有填参考答案）"), ""]


def _short_answer_block(contents: dict, out: list):
    out += [str(contents.get("prompt", "")), ""]
    accepted = contents.get("correct_answers") or []
    out += ["**参考答案**：%s（匹配方式 %s）"
            % ("；".join(str(a) for a in accepted) if accepted else "（没有填参考答案）",
               contents.get("match_mode", "case_insensitive")), ""]


def _number_answer_block(contents: dict, out: list):
    out += [str(contents.get("prompt", "")), ""]
    out += ["**参考答案**：%s %s（容差 ±%s）"
            % (contents.get("correct_value"), contents.get("unit", "") or "",
               contents.get("tolerance", 0)), ""]


def _code_block(contents: dict, out: list):
    lang = contents.get("language") or ""
    starter = contents.get("starter_code", "") or ""
    solution = contents.get("solution_code", "") or ""
    out += ["**初始代码**：", "```%s" % lang, starter, "```", ""]
    if solution.strip():
        out += ["**参考解法**：", "```%s" % lang, solution, "```", ""]
    else:
        out += ["**参考解法**：（没有填）", ""]


def render_assignment_markdown(assignment, tasks) -> str:
    """一份作业 → Markdown 全文。`tasks` 按显示顺序传进来。

    `assignment` 与 `tasks` 都是 SQLModel 行对象，这里只读字段不碰会话。
    """
    title = getattr(assignment, "title", None) or "作业"
    out = ["# %s" % title, ""]

    description = getattr(assignment, "description", None)
    if description:
        out += [str(description), ""]

    meta = []
    due = getattr(assignment, "due_date", None)
    if due:
        meta.append("截止 %s" % due)
    meta.append("计分方式 %s" % (_enum_value(getattr(assignment, "grading_type", "")) or "未设置"))
    meta.append("已发布" if getattr(assignment, "published", False) else "未发布")
    if getattr(assignment, "show_correct_answers", False):
        meta.append("批改后向学生展示正确答案")
    out += ["> [!info] " + "；".join(meta), ""]

    out += ["> [!warning] 下面的**参考答案是给老师看的**。"
            "这份导出不要直接发给学生，先把答案行删掉。", ""]

    if not tasks:
        out += ["（这份作业还没有题目）", ""]

    for i, task in enumerate(tasks, 1):
        kind = _enum_value(getattr(task, "assignment_type", ""))
        label = _KIND_LABEL.get(kind, kind or "未知题型")
        out.append("## 第 %d 题 · %s（%s，满分 %s）"
                   % (i, getattr(task, "title", "") or label, label,
                      getattr(task, "max_grade_value", "")))
        out.append("")

        task_desc = getattr(task, "description", None)
        if task_desc:
            out += [str(task_desc), ""]

        contents = getattr(task, "contents", None) or {}
        if not isinstance(contents, dict):
            contents = {}

        before = len(out)
        if kind == AssignmentTaskTypeEnum.QUIZ.value:
            _quiz_block(contents, out)
        elif kind == AssignmentTaskTypeEnum.FORM.value:
            _form_block(contents, out)
        elif kind == AssignmentTaskTypeEnum.SHORT_ANSWER.value:
            _short_answer_block(contents, out)
        elif kind == AssignmentTaskTypeEnum.NUMBER_ANSWER.value:
            _number_answer_block(contents, out)
        elif kind == AssignmentTaskTypeEnum.CODE.value:
            _code_block(contents, out)
        elif kind == AssignmentTaskTypeEnum.FILE_SUBMISSION.value:
            out += ["（学生上传文件作答，没有标准答案）", ""]
        else:
            out += ["（题型 %s 的内容这里不解析，请到网页上查看）" % (kind or "未知"), ""]

        if len(out) == before:
            # 题干是空的（`contents` 里什么都没有）。不写这一句的话导出来只有一个
            # 光秃秃的标题，老师会以为是导出坏了，而不是题目本来就没录完。
            out += ["（这道题还没有录入内容）", ""]

        hint = getattr(task, "hint", None)
        if hint:
            out += ["> [!info] 提示：%s" % hint, ""]

    return "\n".join(out).rstrip() + "\n"
