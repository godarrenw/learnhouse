# 学情工具 QA 记录

功能：教学工具里的「学情」一条（`key=learning`），页内四个 Tab —— 成绩册 / 缺交 / 学习进度 / 课程体检。
分支 `feat/learning`。业务逻辑移植自 `learnhouse-agent/skill/learnhouse/` 的
`progress.py`（成绩册、缺交、课程概览）、`trail.py`（学习进度）、`tools.py` 的 `lint_course()`。

与 skill 版本最大的差别：后端在容器内可以直接查库，**学习进度不再需要 SSH 到 NAS**，
skill 里那一整套 sshpass / pexpect / NAS 密码全部没有了。

---

## 接口清单

全部挂在 `/api/v1/ext/learning` 下，权限三层，缺一不可：

1. `router.py` 挂载时的 `require_authenticated_user`：拒匿名、拒 API token
2. `routers/ext/deps.require_teacher`：调用者在 `?org_id=` 那个组织里必须是
   Admin / Maintainer / Instructor（判据是 `dashboard.action_access`）
3. `services/ext/learning/common.rbac_check_course`：调用者必须**能改这门具体课程**
   （作者 / 课程维护者 / Admin / Maintainer）。四个只读接口也判 update，不判 read

另外每个带 `course_uuid` 的接口都核对课程确实属于 `org_id` 那个组织，不属于就按 404 处理
（返回 403 会泄露这门课存在）。

**为什么只读接口也判 update**：这四个接口吐的是学生姓名、邮箱、成绩和学习记录。
课程的 `read` 权限门槛很低 —— 公开课程对组织里任何登录用户都成立，绑定用户组的成员
也算，按 read 判等于让一个选了课的人就能把全班成绩拉走。所以四个只读接口和
`fix-publish` 用同一道门。

**这个收紧的代价**（显式记录，别以后当 bug 来查）：本地库内置的 Instructor 角色是
`courses.action_update=false` + `action_update_own=true`，所以一个 Instructor 只有在
**自己是这门课的作者 / 维护者 / 贡献者**时才看得到它的学情；帮别人代课、又没被加进
课程作者列表的 Instructor 会被拦。宁可少给，也不能让选课的人拿到全班数据。
两种情况都有 pytest 钉着（`test_instructor_needs_authorship_on_the_course`）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/ext/learning/courses/{course_uuid}/gradebook?org_id=&format=` | 成绩册矩阵。`format=csv` 返回 UTF-8 BOM 的 CSV |
| GET | `/ext/learning/courses/{course_uuid}/missing?org_id=&assignment_uuid=&format=` | 缺交名单，可按单份作业筛选 |
| GET | `/ext/learning/courses/{course_uuid}/progress?org_id=&student=&format=` | 学习进度；给了 `student`（user_uuid 或 user_id）返回单人明细 |
| GET | `/ext/learning/recent?org_id=&days=&limit=` | 组织范围内最近 N 天的学习事件 |
| GET | `/ext/learning/courses/{course_uuid}/lint?org_id=` | 课程体检 |
| POST | `/ext/learning/courses/{course_uuid}/lint/fix-publish?org_id=` | 一键发布未发布活动，body 必须带 `{"confirm": true}` |

几个口径，改代码前先读：

- **成绩册的学生集合** = 绑定这门课的用户组成员 ∪ 有提交记录的人。没绑用户组时只剩后者，
  返回体带 `note` 说明，前端会把这句话显示在表格上方。
- **分数**走上游的 `compute_assignment_grade()`，满分是该作业所有题目 `max_grade_value` 之和、
  读的时候现算，所以百分比和 `display_grade` 与学生在活动页看到的完全一致。
  形成性作业（`ungraded`）不给分数，单元格显示「不计分」。
- **迟交**：服务端从不主动写 `LATE`（过截止时刻的提交直接被 403 拒掉），所以迟交只可能出现在
  老师事后延长截止日期的场合，由「提交时间 vs 截止时刻」自己算。规则与服务端
  `_is_assignment_past_due()` 一致：**只有日期没有时间的 due_date，整个当天都算按时**。
- **进度的分母** = `select count(*) from chapteractivity where course_id = ?`，即课程下挂在
  章节里的活动总数，**含未发布的活动**。这是后端 trail 服务自己的算法，换别的会和学生看到的
  百分比对不上。返回体里带 `denominator_note` 明说了这一点，前端显示在进度页与明细抽屉里。
- **时间**：库里的 `creation_date` / `update_date` 是 `str(datetime.now())` 写下的无时区字符串，
  生产容器 TZ 是 UTC。接口统一按 UTC 解析、转成展示时区、输出带 offset 的 ISO 8601
  （`2026-09-08T19:30:31.402905+08:00`）。展示时区默认 UTC+8，可用
  `LEARNHOUSE_EXT_TIMEZONE_OFFSET` 改。

---

## 后端测试

`apps/api/src/tests/ext/test_learning.py`，跑在 conftest 的内存 SQLite 上，数据全部自己造
（三名学生 + 一个绑课的用户组 + 一份 100 分作业 + 提交 + trail 记录）。

```
$ uv run pytest src/tests/ext -q
56 passed
```

（56 条里包含骨架代理的 `test_health.py`，学情自己 33 条。）

覆盖到的点：矩阵取值与状态、没绑用户组时的 note、CSV 带 BOM、迟交判定、进度分母含未发布活动、
单人明细、学生不存在 404、最近事件按组织隔离、时区转换、中文姓名不加空格、
体检的六种结论（空页 / 未发布活动 / 作业壳没记录 / 作业没题 / 截止日期已过 / 作业未发布）、
一键发布必须带 confirm、有 error 的活动不会被发布，以及路由层的 org_id 必填、跨组织 404、
课程级权限不通过时 403。

**越权回归**（这批用例在改成 update 之前是红的，实测四个只读接口对 User 角色都返回 200）：
`test_student_cannot_read_class_data_of_public_course` 逐个验 gradebook / missing /
progress / lint 对**公开课程**必须 403，`test_student_cannot_trigger_fix_publish` 验写操作，
`test_course_owner_still_passes` 保证没把老师自己挡住，
`test_instructor_needs_authorship_on_the_course` 钉住 Instructor 的作者边界。

```
$ uv run ruff check src/routers/ext src/services/ext src/tests/ext
All checks passed!
```

---

## 前端端到端

用例在 `apps/e2e/features/ext/tests/02-learning.spec.ts`，复用 `apps/e2e` 已有的
Playwright 工程：会话由 `global-setup` 登录一次存成 storageState，onboarding 遮罩由
`core/fixtures.ts` 预置，版本跟着 apps/e2e 钉在 `@playwright/test` 1.49.1。

```sh
# 先把演示数据灌进本地栈 —— 干净的库里四个 Tab 全是空态，用例会失败
docker exec -i learnhouse-db-local psql -U learnhouse -d learnhouse \
  < docs/sysu-sam/QA/learning/seed-demo-data.sql

cd apps/e2e
bun install && bun run install-browsers        # 首次

E2E_SKIP_BOOT=1 \
E2E_BASE_URL=http://localhost:3003 \
E2E_API_URL=http://localhost:9003/api/v1 \
E2E_ADMIN_EMAIL=user1@example.local \
E2E_ADMIN_PASSWORD='<本地预发栈管理员密码>' \
E2E_STUDENT_EMAIL=user2@example.local \
E2E_STUDENT_PASSWORD='<同上>' \
bun run test features/ext
```

`E2E_STUDENT_*` 必须给：本地复刻库的组织开了邀请制，harness 自己建学生会被 403 顶回来，
`user2@example.local` 是现成的 User 角色账号，正好当反面用例。

前端跑之前要起本地栈（socat 转发容器 `lh-db-fwd-15432` / `lh-redis-fwd-16379` 是共用的，
别重复起）：

```
apps/api  uv run --no-sync uvicorn app:app --port 9003
apps/web  bun run dev --port 3003
```

本次结果 **15 passed**（骨架 6 条 + 学情 9 条）。按 Tab 拆条而不是一条走完 ——
合成一条的话成绩册那步一挂，后面三个 Tab 就再也跑不到，报告里只看得见第一个错。

| 用例 | 断言 | 截图 |
|---|---|---|
| 成绩册三状态 | 已批 / **待批·迟交** / 未交都要在。迟交是最容易写错的一档：服务端从不主动写 LATE，它是靠「提交时间 vs 截止时刻」算出来的，只断言「已批」盖不住 | `01-gradebook.png` |
| 导出 CSV | 真的触发下载、文件名 `gradebook-*`、落盘文件前三字节是 UTF-8 BOM。拿不到落盘路径就算失败，不做 if 保护悄悄跳过 | — |
| 表头排序 | 点「总分」后 `aria-sort` 变成 ascending/descending —— 只「点得动」不算数 | `02-gradebook-sorted.png` |
| 缺交名单 | 筛选下拉可见，且名单里真的有人被列成「未交」 | `03-missing.png` |
| 学习进度 + 明细 | 进度表可见；明细抽屉打得开，里面写了百分比的分母口径 | `04-progress.png`、`05-progress-detail.png` |
| 课程体检 | 三级计数与结论列表可见；点「一键发布」先弹二次确认 | `06-lint.png`、`07-lint-confirm.png` |
| 窄屏 | 400px 下实测 `scrollWidth - clientWidth <= 1`，只截图的话这条永远不会失败 | `08-mobile.png` |
| 概览最近动态 | 概览页的最近学习卡片至少有一条事件，且没把工具网格挤掉 | `09-overview-recent.png` |
| 普通成员被拦 | User 角色直接访问 `/dash/tools/learning` 看不到工具，页面是无权限/404 | — |

Apple Silicon 上后端跑测试前要 `uv pip install greenlet`（不改 pyproject / uv.lock），
并且一律 `uv run --no-sync`。

### 演示数据

本地预发库是从生产备份脱敏恢复的，里面一条作业、一个用户组都没有，四个 Tab 全是空态，
截不出有意义的图。所以另外造了一份演示数据（脚本见下），只在 `learnhouse-local` 上跑，
**没有碰生产**：

- 用户组「2026 秋 智能制造 1 班」，挂到课程 *AI-Driven Advanced Manufacturing*
- 三名学生：张小明（按时交、批 86 分）、李小红（过截止日期才交、待批）、王大力（没交）
- 一份 100 分作业（两道题各 50 分），截止日期 2026-09-05
- 学习记录：张小明看完 6 个活动，李小红 2 个，王大力没进过课

数据用固定 id（9001 起）插入，重跑幂等；要清掉就按这些 id 删。

---

## 已知问题与未做项

0. **`bun test tests` 与 `bunx tsc --noEmit` 都是干净的**：`263 pass, 0 fail`；
   `tsc` 对 `components/SysuTools/**`、`services/ext/**`、`tests/ext/**` 零报错。
1. **`bun run lint:strict` 在 `sysu-sam` 上本来就不过** —— 35 条 error 全在上游文件里
   （`components/Utils/ClientComp.tsx`、`Dashboard/Analytics/**`、`Boards/Extensions/**` 等），
   与本功能无关，本分支一个字都没改这些文件。学情自己的文件在 `bun run lint` 下零 error、零 warning，
   `bunx tsc --noEmit` 对本功能的文件零报错。
2. **四个 Tab 的表格全部用共享的 `DataTable`**。最初它的 `header` 是 `string`、也没有表头
   点击回调，塞不进 UI_GUIDE 3.4 要求的方向图标，所以曾经自带过一个 `SortableTable.tsx`；
   骨架代理已经把 `header` 放宽成 `React.ReactNode` 并加了 `onHeaderClick` / `sortDirection`
   （commit 33537025），rebase 后那个本地副本已删除，成绩册与学习进度改用共享组件。
3. **四个子 Tab 用组件内 state 切换，不改 URL**。`/dash/tools/[tool]` 的动态段已经被工具 key 占了，
   工具内部再占一段会和它打架。代价是命令面板只能搜到工具本身，搜不到单个 Tab；
   刷新页面会回到第一个 Tab。
4. **课程体检的图片检查在媒体目录不可达时会跳过**。判据是 `content/orgs/` 这一层存不存在：
   不存在说明整棵内容树不可达（从源码起服务、或者只恢复了数据库没恢复媒体文件），
   此时逐张图去 `os.path.exists` 会把每一张都判成「不存在」、刷出一屏假 error，所以只报一条 info。
   内容走对象存储（s3api）时同理，也只报 info。skill 版本靠 HTTP 404 探测的做法没有照搬。
5. **`/ext/learning/recent` 还没有前端入口**。它是组织级的（不属于任何一门课），
   而学情工具是 `courseScoped: true`，页内没有合适的位置放它。接口本身可用、有 pytest 覆盖，
   后续可以做成教学工具概览页上的一块「最近动态」。
6. **已经 rebase 到含骨架的 `sysu-sam`（33537025）**，冲突全部取骨架版本，只把学情自己的注册
   重新贴回六处共享文件：`routers/ext/__init__.py` 的 `SUBMODULES`、`SysuTools/registry.ts`、
   `lib/query/keys.ts`、`dash/tools/page.search.ts`、`locales/ext/{zh,en}.json`。
   rebase 后 pytest / ruff / bun test / tsc / lint / playwright 全部重跑通过。
7. **`/dash/tools/**` 在单组织模式下的路径是 `/dash/tools/<key>`**，不是
   `/orgs/<slug>/dash/tools/<key>`。端到端用例用 `LH_E2E_ORG_SLUG` 兼容两种部署模式。

---

## 集成时的改动（集成代理，2026-09-10）

合入 sysu-sam 时做了三处调整，都不影响功能：

**1. e2e 迁到 `apps/e2e/features/ext/tests/02-learning.spec.ts`。**
原来在 `apps/web/tests/ext/` 下自带一套 playwright 配置，但 `@playwright/test`
不是 apps/web 的依赖，只能靠 `bunx playwright` 临时拉包跑；实测在干净环境下
临时包解析不到配置里的 import，直接 `MODULE_NOT_FOUND`，等于这条 e2e 跑不起来。
迁到 apps/e2e 之后复用那边已有的基建：会话由 global-setup 登录一次存成
storageState、onboarding 遮罩由 fixtures 预置、版本钉在 @playwright/test 1.49.1，
也不再需要 `@ts-nocheck`。

迁移时用例被合成了一条「四个 Tab 都能打开并出数据」，路上掉了几个实质断言
（迟交状态、`aria-sort`、缺交名单真的有人、明细里的分母说明、窄屏的溢出实测），
后来做权限修正时一并补回并按 Tab 拆开 —— 合成一条的话成绩册那步一挂，
后面三个 Tab 就再也跑不到。集成方新加的「概览页最近动态」那条保留。

**2. 三个不该进仓库的文件已移除**：`apps/web/AGENTS.md`、`apps/web/CLAUDE.md`
（`next dev` 每次启动都会重新生成）、`apps/web/test-results/.last-run.json`
（playwright 运行产物）。骨架的 .gitignore 本来就挡了前两个，但对已跟踪的文件
无效，所以要 `git rm --cached`。同时把 `/test-results/` 和 `/playwright-report/`
补进 .gitignore。

**3. `GET /ext/learning/recent` 接上了前端入口**（lead 指定的集成范围内改动）。
教学工具概览页顶部新增「最近学习动态」卡片，组织级、不用选课，列最近 7 天最多
8 条学习事件。数据取不到时整块不渲染（学情工具没装、或当前角色 403），
不影响下面的工具网格。对应 e2e 是「概览页显示最近学习动态卡片」那条，截图 `09-overview-recent.png`。

### 集成验证结果

| 项 | 结果 |
| --- | --- |
| 后端 pytest ext | 56 passed |
| 后端 ruff | All checks passed |
| 前端 tsc | exit 0 |
| e2e tsc | exit 0 |
| 前端 lint | 35 error，与基线持平；ext 新目录 0 |
| e2e | 15 passed（骨架 6 + 学情 9） |

验证环境：本地预发栈，后端 :9008、前端 :3008（避开其他代理占用的 9001-9007 / 3001-3007）。

### 给后续代理的提醒

跑 `bunx tsc --noEmit -p .` 之前，`apps/web/next-env.d.ts` 必须存在。它是 next 生成的
且被 gitignore，干净 checkout 上没有，缺了会报 23 个 `TS2307: Cannot find module
'public/xxx.png'` 的假错误，全在上游文件里。跑过一次 `next dev` 或 `next build`
就会有；也可以手工建，内容就是两行 `/// <reference types="next" />` 和
`/// <reference types="next/image-types/global" />`。镜像构建里 `next build`
自己会生成，所以 CI 不受影响。

