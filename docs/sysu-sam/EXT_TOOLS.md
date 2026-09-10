# 教学工具（ext）扩展点

后台左侧菜单的「教学工具」是一块公共骨架，所有部署方自建的教学功能都挂在它下面。
这份文档写给**要往里加工具的人**：加一个工具要动哪几个文件、共用件有哪些、
权限怎么判、测试怎么写。

骨架本身的实现不用改。如果你觉得非改不可，先说一声——那说明扩展点设计漏了东西。

前置阅读：`docs/sysu-sam/DEVELOPING.md`（新代码放哪、改上游文件的注释规范）、
`/Volumes/D/code/learnhouse-agent/UI_GUIDE.md`（视觉与工程规范，尤其第 0 节和 3.9 模板）。

---

## 一分钟版：加一个工具

假设你的工具叫「成绩册」，key 定为 `gradebook`。

**前端**

1. 写组件 `apps/web/components/SysuTools/tools/Gradebook/Gradebook.tsx`，
   默认导出，props 类型 `SysuToolProps`。
2. 在 `apps/web/components/SysuTools/registry.ts` 的 `SYSU_TOOLS` 里加一个条目。
3. 在 `apps/web/locales/ext/zh.json` 与 `en.json` 的 `tools.gradebook` 下加文案。
4. 需要新接口就在 `apps/web/services/ext/gradebook.ts` 里封装，
   query key 加进 `apps/web/lib/query/keys.ts` 的 `ext` 分组。

**后端**

5. 写 `apps/api/src/routers/ext/gradebook.py`，导出 `router`。
6. 在 `apps/api/src/routers/ext/__init__.py` 的 `SUBMODULES` 里加 `"gradebook"`。
7. 业务逻辑放 `apps/api/src/services/ext/gradebook.py`，测试放
   `apps/api/src/tests/ext/test_gradebook.py`。

**验收**

8. e2e 用例放 `apps/e2e/features/ext/tests/`，QA 记录写
   `docs/sysu-sam/QA/<你的功能>.md`。

路由、左侧菜单、移动端菜单、Tab 条、权限过滤都是骨架按注册表自动生成的，
**这几个上游文件你都不用碰**。

---

## 前端扩展点

### 注册表条目

`apps/web/components/SysuTools/registry.ts`：

```ts
{
  key: 'gradebook',                       // 路由段 /dash/tools/gradebook，全局唯一
  titleKey: 'ext.tools.gradebook.title',  // i18n key，不是文案
  descKey: 'ext.tools.gradebook.description',
  icon: BookOpenCheck,                    // lucide-react（页面内容一律 Lucide）
  component: lazy(() => import('./tools/Gradebook/Gradebook')),
  minRole: 'instructor',
  courseScoped: true,                     // 需要先选课程时才写
}
```

`minRole` 三档：

| 值 | 谁能看到 | 判断依据 |
| --- | --- | --- |
| `instructor` | Admin / Maintainer / Instructor | `rights.dashboard.action_access`，与后端 `require_teacher` 同口径 |
| `maintainer` | Admin / Maintainer | `rights.usergroups.action_update` |
| `admin` | 组织管理员 | `canManageOrg` |

权限不足时，工具既不出现在概览卡片和 Tab 条里，直接访问 `/dash/tools/<key>` 也会 404
（不是 403 —— 不泄露「有这么个工具但你看不到」）。

`component` **必须** `lazy()`。概览页会把注册表整个引进来，同步 import 会把所有工具的
代码塞进首屏。

### courseScoped 的契约

写了 `courseScoped: true` 之后：

- 路由页会在页头下自动渲染 `CourseSelect`（选课下拉，记住上次选择）。
- 选中的课程 uuid 通过 `courseUuid` prop 传给你的组件。
- 未选课时 `courseUuid` 是 `undefined`。这时**不要发请求**，渲染一句
  `t('ext.common.course_required')` 就行。

**不要自己再写一个选课下拉**，否则五个工具会有五种选法。

### 共用组件

从 `@components/SysuTools/shared` 引：

| 组件 | 干什么 |
| --- | --- |
| `ToolPageHeader` | 页头三件套（面包屑 + H1 + 副标题 + Tab 条）。路由页已经渲染了，工具组件里不用再写 |
| `CourseSelect` | 选课下拉。由路由页按 `courseScoped` 渲染，一般你不用直接引 |
| `DataTable` | 表格。骨架屏 / 空态 / 刷新遮罩三态内置 |
| `ExportCsvButton` | 导出 CSV，自带 UTF-8 BOM（不加的话 Excel 打开中文列名乱码） |
| `ConfirmDanger` | 危险操作确认，包的是上游 `ConfirmationModal` |
| `getExtConfig` | 读组织配置的 ext 段，见下一节 |

`DataTable` 用法：

```tsx
const columns: DataTableColumn<Row>[] = [
  { key: 'name', header: t('ext.tools.gradebook.student'),
    cell: (r) => <span className="font-semibold text-gray-800 text-sm">{r.name}</span> },
  { key: 'actions', header: t('ext.common.actions'), align: 'end',
    cell: (r) => <ConfirmDanger … /> },
]

<DataTable
  columns={columns}
  rows={rows}
  rowKey={(r) => r.uuid}
  isInitialLoading={!data && isFetching}
  isRefreshing={!!data && isFetching}
/>
```

`cell` 返回 `null` / `undefined` / `''` 会自动画成灰色的「—」，不用自己判空。

`header` 的类型是 `React.ReactNode`，可以塞徽标之类的东西。要可点排序的表头，
传 `onHeaderClick` 和 `sortDirection`，箭头图标（ArrowUp / ArrowDown）和
`cursor-pointer select-none hover:text-gray-700` 由 DataTable 自己加，
`aria-sort` 也会一并设好，不用手拼：

```tsx
{
  key: 'score',
  header: t('ext.tools.gradebook.score'),
  cell: (r) => r.score,
  onHeaderClick: () => toggleSort('score'),
  sortDirection: sortKey === 'score' ? sortDir : null,
}
```

### 组织级配置（ext 段）

需要给管理员配的东西（虚拟助教页面地址、AI 接口地址……）放**组织配置 JSON 的
`ext` 段**，也就是 `OrganizationConfig.config["ext"][<key>]`。这块是自由 dict，
上游不认识它，不会被上游的配置校验或迁移动到。

后端三层回退：

```python
from src.services.ext.config import get_ext_config

url = await get_ext_config(
    db_session, org_id,
    key="avatar_page_url",
    env_var="LEARNHOUSE_EXT_AVATAR_PAGE_URL",   # 可选
    default="",
)
```

顺序固定：**组织配置的 ext 段 → 环境变量 → 默认值**。同一台机器可能跑多个组织，
组织级设置必须能盖过环境变量；环境变量是「这台部署统一这么配」的兜底。

前端：

```ts
import { getExtConfig } from '@components/SysuTools/shared'
const org = useOrg() as any
const avatarUrl = getExtConfig(org, 'avatar_page_url', '')
```

前端读不到环境变量，只有两级（组织配置 → fallback）。**凡是前端也要用的配置，
都必须写进组织配置的 ext 段**，别只设环境变量。

两个边界都测了（`src/tests/ext/test_config.py`）：空字符串算「没配」会继续回退
（管理员清空输入框的语义就是恢复默认），但 `False` 和 `0` 是有效取值，不会被
当成没配。

环境变量命名统一 `LEARNHOUSE_EXT_<KEY 大写>`。

### i18n

文案放 `apps/web/locales/ext/zh.json` 与 `en.json`，**两份都要写**。

这两个文件不是独立的 i18next namespace，而是在 `lib/i18n.ts` 里并进 `common` 的
`ext` 顶层 key，所以组件里照常 `t('ext.tools.gradebook.title')` 就能用。

为什么不直接往 `locales/zh.json` 里插：那是上游的地盘，两个 4000 多条的大文件，
rebase 时必冲突。

只维护中英两份，其他 20 种语言由 `fallbackLng: 'en'` 兜底。

**`lib/i18n.ts` 里那段合并逻辑有个顺序坑**：ext 的 bundle 必须在主语言包
`addResourceBundle` **之后**再加。提前加会让 `hasResourceBundle(code, 'common')`
提前变成 true，主语言包就永远不会加载，整个后台变英文。骨架里已经写对了，别去动它。

### 命令面板

`apps/web/app/orgs/[orgslug]/dash/tools/page.search.ts` 里追加一条：

```ts
{
  id: 'dash.tools.gradebook',
  titleKey: 'ext.tools.gradebook.title',
  descriptionKey: 'ext.search.gradebook.description',
  keywordsKey: 'ext.search.gradebook.keywords',
  icon: BookOpen,          // 这里用 @phosphor-icons/react（搜索元数据是 Phosphor 的地盘）
  href: '/dash/tools/gradebook',
  group: 'content',
}
```

`lib/dashboard-search/registry.ts` 已经把整个数组引进去了，不用再改。

---

## 后端扩展点

### 子路由

`apps/api/src/routers/ext/gradebook.py`：

```python
from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.users import PublicUser
from src.routers.ext.deps import require_teacher

router = APIRouter()


@router.get(
    "/gradebook/{course_uuid}",
    tags=["ext"],
    summary="Read the gradebook for a course",
    description="…",                       # summary/description/responses 是必填的，OpenAPI 对外可见
    responses={200: {...}, 403: {...}},
)
async def api_read_gradebook(
    *,
    course_uuid: str,
    org_id: int,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: PublicUser = Depends(require_teacher),
):
    return await read_gradebook(db_session, current_user, org_id, course_uuid)
```

然后在 `apps/api/src/routers/ext/__init__.py` 的 `SUBMODULES` 里加 `"gradebook"`。
需要统一前缀的话写成元组 `("gradebook", "/gradebook")`，路由装饰器里就不用重复写了。

`src/router.py` 已经把整个 `ext_router` 挂在 `/api/v1/ext` 上，**不要再去改它**。
挂载时统一加了 `require_authenticated_user`（拒绝匿名、拒绝 API token）。

### 权限：两道门

**第一道（组织级）**：`require_teacher`，放行 Admin / Maintainer / Instructor。

它的实现就是查角色 rights 里的 `dashboard.action_access`。这不是近似而是精确等价：
`src/services/setup/setup.py` 里四个内置全局角色中，Admin(1) / Maintainer(2) /
Instructor(3) 这一位是 True，User(4) 是 False；超级管理员由底层直接放行。
前端 `useAdminStatus().isAdmin` 读的也是这一位，所以前后端口径完全一致。

**它把 `org_id` 声明成了 query 参数**，所以挂了这个依赖的接口，调用方必须带
`?org_id=<id>`。前端 `useOrg()` 里就有 `org.id`。

服务层里想手动检查用 `verify_teacher(user, org_id, db_session)`，签名一样，
不走 FastAPI 依赖注入。

**第二道（课程级）**：`require_teacher` 只管「你是这个组织的老师」，管不了
「这门课是不是你的」。凡是按课程取数的接口都必须再收窄一次，用上游的

```python
await authorization_verify_based_on_roles_and_authorship(
    request, current_user.id, "read", course_uuid, db_session)
```

写操作的 service 函数开头**必须**做这道检查，**且必须传 org_id**——上游注释写明了
这是防跨组织 IDOR 的。前端对应的判断是 `useCourseRights(courseuuid)`。

**课程级那道用 `update` 还是 `read`：凡是会返回名单、成绩、他人提交内容这类
「他人数据」的接口，哪怕它是只读的，也要按 `update` 判 —— 按「能改这个资源的人」
判，而不是「能看这个资源的人」。** 理由：公开课程的 `read` 对任何登录用户都成立，
按 `read` 判等于把全班数据开放给选了这门课的人。

这不是理论风险。学情工具把判定改回 `read` 跑一遍新用例，四个只读接口对 User
角色全部返回 200；改成 `update` 后 403（`test_learning.py`）。签到的
`test_regular_user_cannot_read_records` 守的是同一个面。成绩册、缺交名单、
学习进度、课程体检、查重结果、随堂测结果、版本历史都属于这一类。

**一个要知道的副作用**：内置 Instructor 角色是 `courses.action_update=false` +
`action_update_own=true`，所以 Instructor 只有在自己是这门课的作者/维护者/贡献者
时才过得了这道门。帮别人代课又不在课程作者列表里的 Instructor 会被拦。这是有意
的取舍；如果实际教学中太紧，要改的是**把代课老师加进课程作者列表**，而不是把
判定放回 `read`。

#### `require_teacher` 与 `verify_teacher`：两种形态怎么选

`src/routers/ext/deps.py` 里同一套判定有两个入口，**判定逻辑完全相同**
（都是查 `dashboard.action_access`），差别只在 `org_id` 从哪来：

| | `require_teacher`（依赖形态） | `verify_teacher`（服务层调用） |
|---|---|---|
| 用法 | `Depends(require_teacher)` | `await verify_teacher(user, org_id, db_session)` |
| `org_id` 来源 | 调用方在 query 里传 `?org_id=` | 服务端自己从资源反查 |
| 适合 | 接口不带任何资源 id，组织是唯一上下文 | 接口带 `course_uuid` / `<资源>_uuid`，能反查出组织 |

**怎么选：接口路径里已经有资源 id 的，用 `verify_teacher` 从资源反查组织；
只有拿不到资源 id 时才用依赖形态让调用方传。**

理由是让调用方传 `org_id` 会多出一个必须校验的自由变量。传进来的 `org_id`
和资源实际所属的组织未必一致，服务端还得再比一次；漏了这一比，攻击者就能拿
自己有教师权限的组织 id 去操作别的组织的资源——正是上游注释里反复强调的那个
跨组织 IDOR。从资源反查则不存在这个自由度：组织是资源自己说了算的。

签到是全部走反查的范例，两道门连着做（`src/services/ext/checkin/checkin.py`
的 `rbac_check_teacher`）：

```python
await authorization_verify_if_user_is_anon(current_user.id)
await verify_teacher(current_user, org_id, db_session)          # 组织级
await authorization_verify_based_on_roles_and_authorship(       # 课程级
    request, current_user.id, "update", course_uuid, db_session)
```

学情走的是依赖形态 + 服务层再核对课程属于该组织，两条路都可以，**关键是
课程级那道不能漏，也不能用 read**。学生端可以另开一道更松的门（登录 + 是本组织
成员即可），`org_id` 同样反查。

### 业务逻辑与模型

- 逻辑放 `src/services/ext/<tool>.py`，路由层只做 HTTP 与依赖注入。
- 新表放 `src/db/ext/<tool>.py`，四件套约定（Base / table / Create / Update / Read、
  `<entity>_uuid` 对外主键、`org_id` 外键带 `ondelete="CASCADE"`、日期是字符串）
  照抄 `src/db/usergroups.py`。
- 迁移走 alembic，revision 消息带 `[sysu-sam]` 前缀。
- **不要加 `require_plan(...)`**，本地部署没有 SaaS 套餐概念。

---

## 测试

### 后端 pytest

放 `apps/api/src/tests/ext/`，直接用 `src/tests/conftest.py` 已有的 fixture
（`db` / `org` / `other_org` / `admin_user` / `regular_user` / `course` …）。

跑法：

```sh
cd apps/api
uv run pytest src/tests/ext/ -q
uv run ruff check src/routers/ext src/services/ext src/tests/ext
```

`src/tests/ext/test_health.py` 里有现成的范例：怎么造一个 Instructor 角色的用户、
怎么断言跨组织被 403。**每个工具至少要有一条「普通 User 被 403」和一条
「跨组织被 403」**。

> **本机环境提醒（Apple Silicon）**：`greenlet` 在 `uv.lock` 里的 marker 排除了
> arm64 macOS，不装它所有异步 DB 测试都会 `ValueError: the greenlet library is
> required`。修法是 `uv pip install greenlet`（只装进 venv，**不要**改 pyproject
> 或 uv.lock，CI 跑的是 linux x86_64 不受影响）。

### Lint 验收标准

`sysu-sam` 基线上 `bun run lint:strict` 本来就有 **35 个上游 error**
（`no-undef` 的 React、Analytics 的 `Cannot create components during render` 等），
它们不是你造成的，也不该由你顺手去修。

所以验收标准是两条，不是「零 error」：

1. **你的新目录 0 error** —— 按路径过滤确认：

   ```sh
   bun run lint:strict 2>&1 | grep error | grep "SysuTools\|dash/tools\|services/ext"
   ```

2. **全仓 error 计数不高于基线**（35）—— 看结尾那行 `✖ N problems (M errors, …)`，
   M 不能变大。

warning 不计入（`lint:strict` 没有 `--max-warnings`，warning 不会让它失败），
但新代码尽量别新增。

**类型检查也要跑**，`lint:strict` 只是 eslint，不做类型检查：

```sh
cd apps/web && bunx tsc --noEmit -p .     # 必须 exit 0
cd apps/e2e && bun run typecheck          # 必须 exit 0
```

这条不能省：push 到 `sysu-sam` 会触发 `build-image.yml`，Dockerfile 里的
`next build` 会跑 tsc，一个类型错误就是全组的镜像构建挂掉。

**跑 web 的 tsc 之前，`apps/web/next-env.d.ts` 必须存在。** 它是 next 生成的、
而且被 gitignore，所以干净 checkout 上没有；缺了会报 23 个
`TS2307: Cannot find module 'public/xxx.png'`，全落在上游文件里，很容易被误判成
自己的改动引入的。跑过一次 `next dev` 或 `next build` 就会有；也可以手工建：

```
/// <reference types="next" />
/// <reference types="next/image-types/global" />
```

镜像构建里 `next build` 自己会生成，所以 CI 不受影响，这纯粹是本地验证的前提。

### 前端 e2e

放 `apps/e2e/features/ext/tests/`，复用已有的 Playwright 基建，**不要另起一套**
（`apps/web` 下没有 e2e 基建，`bun test tests` 那套只跑纯逻辑单测）。

对着自己起的 dev 服务跑：

```sh
cd apps/e2e
E2E_SKIP_BOOT=1 \
E2E_BASE_URL=http://localhost:3001 \
E2E_API_URL=http://localhost:9001/api/v1 \
E2E_ADMIN_EMAIL=user1@example.local \
E2E_ADMIN_PASSWORD='LocalDev#2026' \
E2E_STUDENT_EMAIL=user2@example.local \
E2E_STUDENT_PASSWORD='LocalDev#2026' \
bun run test features/ext
```

端口按 PHASE3_BRIEF 自行错开（后端 9001-9009、前端 3001-3009）。

**e2e 用例必须自己收尾，不要在共用的本地库里留痕。** 本地预发栈是所有代理共用
的一份数据，用例建的课程、章节、活动、作业都要在 `finally` 里删掉。

这条是内容工具踩出来的：它第一版用例是「导出这门课再原样导回这门课」，而导入
一律新建章节，跑三轮就把库里那门课从 7 章撑到 896 章，连接池被打满，**表现出来
却是前端登录失效**，很容易被误判成鉴权坏了。留痕的代价不是脏数据本身，是让别人
花时间去查一个根本不存在的 bug。

两个已经踩过的坑，骨架里已经修好，你直接用就行：

- `E2E_STUDENT_EMAIL` / `E2E_STUDENT_PASSWORD` 是骨架新加的。本地复刻库的组织开了
  邀请制，`global-setup` 原本的「新建一个学生账号」会被 403 顶回来；设了这两个变量
  就改成复用已有账号。`user2@example.local` 本来就是 User 角色。
- 登录选择器改成了中英兼容的正则。组织配置把界面锁成中文，原来写死的英文
  accessible name 一个都匹配不上。

### 本地环境

后端从源码起时要连 `learnhouse-local` 的 Postgres/Redis，但那套 compose 没把它们
映射到宿主机。骨架起了两个 socat 转发容器（一次性的，还在跑就不用再起）：

```sh
NET=learnhouse-local_learnhouse-network-local
docker run -d --name lh-db-fwd-15432    --network $NET -p 15432:5432 \
  alpine/socat:1.8.0.0 "TCP-LISTEN:5432,fork,reuseaddr" "TCP:learnhouse-db-local:5432"
docker run -d --name lh-redis-fwd-16379 --network $NET -p 16379:6379 \
  alpine/socat:1.8.0.0 "TCP-LISTEN:6379,fork,reuseaddr" "TCP:learnhouse-redis-local:6379"
```

然后 `apps/api/.env` 里连 `127.0.0.1:15432` / `127.0.0.1:16379`。
`.env` 与 `.env.local` 都是 gitignore 的，不会进仓库。

工具链版本：`uv` 要 0.12 以上（0.10 装不了 3.14.7），`bun` 要 1.4 以上
（1.3 读不了这个 lockfile 格式）。

---

## QA 文档模板

每个功能在 `docs/sysu-sam/QA/<功能名>.md` 留一份，脱敏。骨架的在
`docs/sysu-sam/QA/skeleton.md`，照抄结构即可：

```markdown
# <功能名> QA

- 环境：本地预发（learnhouse-local，端口 18088），后端源码 :90xx，前端 dev :30xx
- 日期：YYYY-MM-DD
- 账号：管理员 user1@example.local；普通成员 user2@example.local（均已脱敏）

## 自动化

| 项 | 命令 | 结果 |
| --- | --- | --- |
| 后端单测 | `uv run pytest src/tests/ext/... -q` | N passed |
| 后端 lint | `uv run ruff check ...` | All checks passed |
| 前端 lint | `bun run lint:strict` | 新代码 0 error |
| e2e | `bun run test features/ext` | N passed |

## 手工核对

- [ ] 视觉与 UI_GUIDE 一致（页头三件套、卡片 nice-shadow、表格样式）
- [ ] 中英文案都有
- [ ] 窄屏（390px）不横向溢出
- [ ] 普通 User 看不到入口，直接访问被拦

## 截图

`docs/sysu-sam/QA/<功能名>/` 下。

## 未做 / 已知问题

写清楚，别藏。
```

---

## 改上游文件的规矩

骨架已经把该改的都改完了（清单见 `docs/sysu-sam/QA/skeleton.md`）。
你如果**还是**需要改某个上游文件，改动包一层注释：

```
/* --- SYSU-SAM: 干什么 --- */
…
/* --- /SYSU-SAM --- */
```

JSX 里要写成 `{/* --- SYSU-SAM --- */}`，裸的 `/* */` 会被当成文本渲染出来。
