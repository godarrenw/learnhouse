"""教学工具（ext）的业务逻辑层。

路由层 `src/routers/ext/` 只做 HTTP 与依赖注入，真正的逻辑放在这里，
每个工具一个子模块（例如 `src/services/ext/gradebook.py`）。

约定与上游一致：写操作的 service 函数开头先做权限检查，且必须带 org_id
（防跨组织 IDOR）。组织级检查用 `src.routers.ext.deps.verify_teacher`，
课程级再用上游的 `authorization_verify_based_on_roles_and_authorship`。

本包目前是空的，等各工具代理往里加。
"""
