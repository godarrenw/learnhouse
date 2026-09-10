"""教学工具 · 作业工具（SYSU-SAM 扩展）。

业务逻辑移植自 learnhouse-agent 的 skill/learnhouse/：aiquiz.py（spec 校验与
LLM 出题提示词）、assignments.py（build_task_contents / copy_assignments /
shift_due）、similarity.py（查重）、tools.py（随堂测与结果统计）、
versions.py（内容页版本）。

原实现是走 HTTP API 的命令行客户端；这里全部改成后端进程内直接操作数据库，
并复用上游的 service 函数（create_activity / create_assignment /
create_assignment_task / clone_course / restore_activity_version），
以便沿用上游的 RBAC 与用量统计。
"""
