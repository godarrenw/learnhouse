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
3. `services/ext/learning/common.rbac_check_course`：调用者对这门具体课程有 read 权限，
   写操作要 update

另外每个带 `course_uuid` 的接口都核对课程确实属于 `org_id` 那个组织，不属于就按 404 处理
（返回 403 会泄露这门课存在）。

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
48 passed
```

（48 条里包含骨架代理的 `test_health.py`，学情自己 24 条。）

覆盖到的点：矩阵取值与状态、没绑用户组时的 note、CSV 带 BOM、迟交判定、进度分母含未发布活动、
单人明细、学生不存在 404、最近事件按组织隔离、时区转换、中文姓名不加空格、
体检的六种结论（空页 / 未发布活动 / 作业壳没记录 / 作业没题 / 截止日期已过 / 作业未发布）、
一键发布必须带 confirm、有 error 的活动不会被发布，以及路由层的 org_id 必填、跨组织 404、
课程级权限不通过时 403。

```
$ uv run ruff check src/routers/ext src/services/ext src/tests/ext
All checks passed!
```

---

## 前端端到端

`apps/web/tests/ext/learning.e2e.ts`（配置 `tests/ext/playwright.e2e.config.ts`）。

仓库本身没有 Playwright 依赖（`bun test tests` 跑的是纯逻辑单测），所以运行器要外挂。
**文件名是 `.e2e.ts` 不是 `.spec.ts`，两个文件头上都有 `// @ts-nocheck`**，两件事都是必须的：

- bun 的测试发现会把 `*.spec.ts` 当单测收进 `bun test tests`，而那里没有 `@playwright/test`，
  整个仓库的单测会红（实测：`263 pass, 1 fail, 1 error`）
- `next build` 会按 tsconfig 的 `include: ["**/*.ts"]` 对这两个文件做类型检查，
  同样因为找不到 `@playwright/test` 报 TS2307，生产镜像会构建失败

跑法（`bunx playwright test` 不行 —— bunx 解析到的是 `playwright` 核心包，没有 `test` 子命令；
带 `--package=@playwright/test` 也解析不到配置文件里的 import）：

```sh
# 找一个仓库外的目录装运行器，别装进 apps/web，避免动 package.json / bun.lock
mkdir -p /tmp/lh-pw && cd /tmp/lh-pw && bun add -d @playwright/test@1.56.0
bunx playwright install chromium        # 只需一次

cd <repo>/apps/web
NODE_PATH=/tmp/lh-pw/node_modules /tmp/lh-pw/node_modules/.bin/playwright \
  test -c tests/ext/playwright.e2e.config.ts
```

本次结果：`2 passed`。

跑之前要起本地栈（本次用的端口）：

```
apps/api  uv run uvicorn app:app --port 9003     # 连 learnhouse-local 的 Postgres/Redis
apps/web  bun run dev --port 3003
```

以 `user1@example.local` 登录，走完四个 Tab，截图在 `docs/sysu-sam/QA/learning/`：

| 截图 | 内容 |
|---|---|
| `01-gradebook.png` | 成绩册：三名学生 × 一份作业，已批 / 待批·迟交 / 未交三种状态分别是绿 / 琥珀 / 灰 |
| `02-gradebook-sorted.png` | 点「总分」表头排序，箭头方向图标出现 |
| `03-missing.png` | 缺交名单，顶部有按作业筛选的下拉 |
| `04-progress.png` | 学习进度表，完成度 + 最近学习时间 |
| `05-progress-detail.png` | 点「明细」弹出的单人抽屉，列出完成的活动与时间，底部带分母说明 |
| `06-lint.png` | 课程体检，按 error / warn / info 着色，右上角是危险操作按钮 |
| `07-lint-confirm.png` | 「一键发布未发布活动」的二次确认（`ConfirmDanger`，红色 warning 档） |
| `08-mobile.png` | 400px 窄屏，不横向溢出，Tab 条横向滚动 |

用例里还断言了导出 CSV 真的触发下载、文件名以 `gradebook-` 开头、内容前三字节是 UTF-8 BOM。

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
