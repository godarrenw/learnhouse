"""教学工具扩展路由（SYSU-SAM）。

`src/router.py` 只挂载 `ext_router` 一个东西，前缀 `/ext`。每个工具在本目录下
放一个子模块，导出名为 `router` 的 `APIRouter`，然后把模块名加进下面的
`SUBMODULES` 列表——**只需要加一行**，不用再动 `src/router.py`。

子路由自己的路径前缀写在自己的 `@router.get("/xxx")` 里，或者在 `SUBMODULES`
里用 `("模块名", "/前缀")` 的形式指定。例如::

    SUBMODULES = [
        "health",
        ("gradebook", "/gradebook"),
    ]

写成裸字符串时不加前缀，子模块自己在路由装饰器里写全路径。

权限：`src/router.py` 在挂载时统一加了 `require_authenticated_user`（拒绝匿名
和 API token）。教师身份的判断用 `deps.require_teacher`。
"""

from importlib import import_module
from typing import Sequence, Tuple, Union

from fastapi import APIRouter

# 每加一个工具，在这里加一行。顺序即挂载顺序。
SUBMODULES: Sequence[Union[str, Tuple[str, str]]] = [
    "health",
    ("learning", "/learning"),
    ("assign_tools", "/assign"),
    ("content_tools", "/content"),
    ("checkin", "/checkin"),
    "media_sign",
]

ext_router = APIRouter()


def enabled_tools() -> list[str]:
    """当前构建里挂上的 ext 子模块名，供 `/ext/health` 回显。"""
    return [m if isinstance(m, str) else m[0] for m in SUBMODULES]


def include_all() -> APIRouter:
    """导入并挂载 `SUBMODULES` 里的每个子路由，返回 `ext_router`。

    幂等：重复调用不会重复挂载（`src/router.py` 只调一次，但测试里可能会再调）。
    """
    if getattr(ext_router, "_sysu_sam_mounted", False):
        return ext_router

    for entry in SUBMODULES:
        name, prefix = (entry, "") if isinstance(entry, str) else entry
        module = import_module(f"{__name__}.{name}")
        ext_router.include_router(
            module.router,
            prefix=prefix,
            tags=["ext"],
        )

    ext_router._sysu_sam_mounted = True  # type: ignore[attr-defined]
    return ext_router


__all__ = ["ext_router", "include_all", "enabled_tools", "SUBMODULES"]
