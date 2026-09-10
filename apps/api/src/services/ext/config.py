"""教学工具（ext）的配置读取。

部署方的配置统一放在组织配置 JSON blob 的 `ext` 段里，也就是
`OrganizationConfig.config["ext"][<key>]`。这块是自由 dict，上游不认识它，
所以不会被上游的配置校验或迁移动到。

三层回退，顺序固定：

    组织配置的 ext 段  →  环境变量  →  内置默认值

为什么是这个顺序：同一台机器上可能跑多个组织，组织级的设置必须能盖过
环境变量；环境变量则是"这台部署统一这么配"的兜底，省得每个组织都手填。

用法::

    from src.services.ext.config import get_ext_config

    url = await get_ext_config(
        db_session, org_id,
        key="avatar_page_url",
        env_var="LEARNHOUSE_EXT_AVATAR_PAGE_URL",
        default="",
    )

前端对应的读法是 `getExtConfig(org, 'avatar_page_url', '')`
（`@components/SysuTools/shared`），读的是同一段 JSON。前端读不到环境变量，
所以**凡是前端也要用的配置，都应该写进组织配置的 ext 段**，环境变量只当
后端兜底。
"""

import os
from typing import Any, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.organization_config import OrganizationConfig

# 组织配置 JSON 里属于部署方的那一段。
EXT_CONFIG_SECTION = "ext"


async def get_ext_config_section(db_session: AsyncSession, org_id: int) -> dict:
    """取某个组织的整个 ext 配置段。没有就返回空 dict。"""
    statement = select(OrganizationConfig).where(OrganizationConfig.org_id == org_id)
    row = (await db_session.execute(statement)).scalars().first()
    if not row or not isinstance(row.config, dict):
        return {}
    section = row.config.get(EXT_CONFIG_SECTION)
    return section if isinstance(section, dict) else {}


async def get_ext_config(
    db_session: AsyncSession,
    org_id: int,
    key: str,
    env_var: Optional[str] = None,
    default: Any = None,
) -> Any:
    """按「组织配置 → 环境变量 → 默认值」的顺序取一个配置项。

    空字符串算"没配"（管理员把输入框清空，语义就是回退到默认），
    但 `False` 和 `0` 是有效取值，不会被当成没配。
    """
    section = await get_ext_config_section(db_session, org_id)
    value = section.get(key)
    if value is not None and value != "":
        return value

    if env_var:
        env_value = os.environ.get(env_var)
        if env_value is not None and env_value != "":
            return env_value

    return default
