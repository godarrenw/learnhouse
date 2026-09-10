# 教学工具骨架 QA

- 环境：本地预发（learnhouse-local，容器全跑，端口 18088），后端从源码起在 `:9001`，
  前端 `next dev` 在 `:3001`，数据库/Redis 经两个 socat 容器转出到宿主机 `15432` / `16379`
- 日期：2026-09-10
- 分支：`feat/skeleton`
- 账号：管理员 `user1@example.local`（Admin，role_id=1）、普通成员 `user2@example.local`
  （User，role_id=4）。两者都是脱敏后的本地账号，密码统一 `LocalDev#2026`，非生产凭据
- 生产 NAS：全程未触碰

## 自动化结果

| 项 | 命令 | 结果 |
| --- | --- | --- |
| 后端单测 | `uv run pytest src/tests/ext/ -q` | 12 passed |
| 上游路由回归 | `uv run pytest src/tests/test_root_router.py src/tests/test_router_saas_mount.py src/tests/test_app_lifespan.py -q` | 6 passed |
| 后端 lint | `uv run ruff check src/routers/ext src/services/ext src/tests/ext src/router.py` | All checks passed |
| 前端 lint | `bun run lint:strict` | 35 error，全部是基线上游既有；新代码 0 error |
| 前端类型检查 | `bunx tsc --noEmit -p .`（apps/web） | 通过，exit 0 |
| e2e 类型检查 | `bun run typecheck`（apps/e2e） | 通过，exit 0 |
| e2e | `bun run test features/ext` | 6 passed |

前端 lint 说明：改动前基线就有 35 个 error（`no-undef` 的 React、Analytics 的
`Cannot create components during render` 等，全在上游文件里）。我引入过 1 个
（CSV 的字面量 BOM 触发 `no-irregular-whitespace`），已改成 `﻿` 转义修掉。
按路径过滤 `SysuTools|dash/tools|services/ext`，error 数为 0。

## e2e 用例

`apps/e2e/features/ext/tests/01-skeleton.spec.ts`，6 条全过：

教师视角（Admin 会话）

1. 左侧菜单出现「教学工具」入口
2. 概览页按注册表渲染工具卡片（`sysu-tools-grid` + `sysu-tool-card-example`）
3. 示例工具页拿到 `/ext/health` 的数据（断言 `ok`、工具列表含 `health`、角色回显）
4. 未知工具 `/dash/tools/no-such-tool` 走 404，不渲染卡片网格

普通成员视角（User 会话）

5. 学生端顶栏没有「教学工具」入口
6. 直接访问 `/dash/tools` 被拦，页面渲染 403 文案，卡片网格不存在

## 手工核对

- [x] 视觉与 UI_GUIDE 一致：页头三件套（面包屑胶囊 + `text-3xl sm:text-4xl` H1 +
      灰色副标题 + DashTabBar）、卡片 `bg-white nice-shadow rounded-xl`、
      表格是手写 `<table>` 且表头 `uppercase tracking-wider`
- [x] 后台没有涂组织主题色，没有 `dark:` 变体
- [x] 中英文案都有（`locales/ext/zh.json`、`en.json`），页面文案全部走 `t()`
- [x] 零物理方向 class（`bun run lint:strict` 的 `rtl/no-physical-direction` 未报新问题）
- [x] 窄屏 390px 不横向溢出（截图 05，已人工核对）
- [x] User 被拦时渲染的是上游 403 错误页而不是空白（截图 04，已人工核对）
- [x] 后端 `/ext/health` 匿名调用返回 `{"detail":"Authentication required"}`
- [x] OpenAPI 里能看到 `/api/v1/ext/health`

## 截图

`docs/sysu-sam/QA/skeleton/` 下五张：

| 文件 | 内容 |
| --- | --- |
| `01-overview-admin.png` | 管理员看到的概览页与左侧菜单入口 |
| `02-example-tool.png` | 示例工具页，`/ext/health` 的真实返回 |
| `03-unknown-tool-404.png` | 未知工具 404 |
| `04-user-denied.png` | User 角色访问 `/dash/tools` 被拦 |
| `05-overview-mobile.png` | 390px 窄屏 |

## 改到的上游文件

都用 `SYSU-SAM` 注释块包住了。

| 文件 | 改了什么 |
| --- | --- |
| `apps/api/src/router.py` | 文件末尾挂 `ext_router` 到 `/ext` |
| `apps/web/lib/i18n.ts` | 引入 `locales/ext/*` 并并进 `common` 的 `ext` key |
| `apps/web/lib/query/keys.ts` | 加 `ext` 顶层 query key 分组 |
| `apps/web/lib/dashboard-menu-items.ts` | 加「教学工具」条目（学生端顶栏的后台下拉） |
| `apps/web/lib/dashboard-search/registry.ts` | 引入并展开 `tools/page.search` |
| `apps/web/components/Dashboard/Menus/DashLeftMenu.tsx` | PC 左侧菜单加一个 `MenuLink` |
| `apps/web/components/Dashboard/Menus/DashMobileMenu.tsx` | 移动端胶囊与抽屉各加一项 |
| `apps/web/.gitignore` | 忽略 `next dev` 生成的 `AGENTS.md` / `CLAUDE.md` |
| `apps/e2e/core/instance.ts` | 加 `E2E_STUDENT_EMAIL/PASSWORD`，复用已有成员账号 |
| `apps/e2e/global-setup.ts` | 同上；登录选择器改中英兼容 |
| `apps/e2e/core/auth.ts` | 登录选择器改中英兼容 |

后三条是为本地预发环境改的：组织开了邀请制，harness 原本的「新建学生账号」会 403；
界面被组织配置锁成中文，写死的英文 accessible name 匹配不上。

## 未做 / 已知问题

- **e2e 位置与简报不一致**。PHASE3_BRIEF 写的是 `apps/web/tests/ext/`，实际放在了
  `apps/e2e/features/ext/`。原因：`apps/web` 下没有任何 e2e 基建（`bun test tests`
  是 22 个纯逻辑单测），而 `apps/e2e` 已经有完整的 Playwright 工程，包含登录会话复用、
  onboarding 抑制、`E2E_SKIP_BOOT` 指向已有实例。在 web 下另起一套等于重复造轮子。
- **`/ext/health` 的 `ext_version` 是写死的 `1.0.0`**，没有和 `pyproject.toml` 联动。
  它只是给示例页显示用的，不做版本协商。
- **只覆盖组织级权限**。课程级的第二道门（`/courses/{uuid}/rights`）由各工具自己收窄，
  骨架没有提供统一封装 —— 各工具的资源模型差别太大，硬封会限制后面的实现。
- **没有 `loading.tsx`**。`/dash/tools` 及其子路由全是客户端取数，Next 的
  `loading.tsx` 约定只对服务端取数有意义，各工具组件内部已有骨架屏。
- **深色模式未做**，按 UI_GUIDE 2.5 的结论这是有意的。
- 本机 Apple Silicon 需要 `uv pip install greenlet` 才能跑异步 DB 测试，
  详见 `docs/sysu-sam/EXT_TOOLS.md`。这是环境问题，`uv.lock` 未改。
