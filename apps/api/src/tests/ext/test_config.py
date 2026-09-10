"""ext 配置读取的三层回退。

回退顺序是各工具都要依赖的契约（虚拟助教地址、AI 接口配置都走它），
所以每一层和边界都钉死。
"""

from datetime import datetime

import pytest

from src.db.organization_config import OrganizationConfig
from src.services.ext.config import get_ext_config, get_ext_config_section

ENV_VAR = "LEARNHOUSE_EXT_TEST_KEY"


async def _set_org_config(db, org, config: dict) -> None:
    row = OrganizationConfig(
        org_id=org.id,
        config=config,
        creation_date=str(datetime.now()),
        update_date=str(datetime.now()),
    )
    db.add(row)
    await db.commit()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)


class TestGetExtConfigSection:
    async def test_empty_when_no_config_row(self, db, org):
        assert await get_ext_config_section(db, org.id) == {}

    async def test_empty_when_no_ext_section(self, db, org):
        await _set_org_config(db, org, {"general": {"color": "#007A3D"}})
        assert await get_ext_config_section(db, org.id) == {}

    async def test_returns_section(self, db, org):
        await _set_org_config(db, org, {"ext": {"avatar_page_url": "https://a.example"}})
        assert await get_ext_config_section(db, org.id) == {
            "avatar_page_url": "https://a.example"
        }


class TestGetExtConfig:
    async def test_org_config_wins(self, db, org, monkeypatch):
        monkeypatch.setenv(ENV_VAR, "from-env")
        await _set_org_config(db, org, {"ext": {"k": "from-org"}})
        assert await get_ext_config(db, org.id, "k", ENV_VAR, "from-default") == "from-org"

    async def test_falls_back_to_env(self, db, org, monkeypatch):
        monkeypatch.setenv(ENV_VAR, "from-env")
        await _set_org_config(db, org, {"ext": {}})
        assert await get_ext_config(db, org.id, "k", ENV_VAR, "from-default") == "from-env"

    async def test_falls_back_to_default(self, db, org):
        await _set_org_config(db, org, {"ext": {}})
        assert await get_ext_config(db, org.id, "k", ENV_VAR, "from-default") == "from-default"

    async def test_empty_string_counts_as_unset(self, db, org, monkeypatch):
        """管理员把输入框清空 = 回退，不是"配了个空串"。"""
        monkeypatch.setenv(ENV_VAR, "from-env")
        await _set_org_config(db, org, {"ext": {"k": ""}})
        assert await get_ext_config(db, org.id, "k", ENV_VAR, "from-default") == "from-env"

    async def test_false_is_a_real_value(self, db, org):
        """False / 0 是有效取值，不能被当成没配。"""
        await _set_org_config(db, org, {"ext": {"flag": False, "count": 0}})
        assert await get_ext_config(db, org.id, "flag", None, True) is False
        assert await get_ext_config(db, org.id, "count", None, 99) == 0

    async def test_no_env_var_given(self, db, org):
        await _set_org_config(db, org, {"ext": {}})
        assert await get_ext_config(db, org.id, "k", None, "from-default") == "from-default"

    async def test_other_org_does_not_leak(self, db, org, other_org):
        await _set_org_config(db, org, {"ext": {"k": "org-a"}})
        assert await get_ext_config(db, other_org.id, "k", None, "fallback") == "fallback"
