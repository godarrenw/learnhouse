# 上课签到 · 验证记录

分支 `feat/checkin`。本文记录做了什么、验了什么、以及**明确没做什么**。
截图在 `docs/sysu-sam/QA/checkin/`（本地预发环境，数据已脱敏）。

## 一、功能范围

教师在「教学工具 → 上课签到」里为某门课开一场签到，投屏页显示一个每隔
10-120 秒轮换的二维码和一组 6 位数字口令；学生扫码或输口令完成签到，
一场一个账号只能签一次。教师能看实时人数与名单、结束会话、导出 CSV、翻历史场次。

## 二、数据模型与迁移

迁移文件 `apps/api/migrations/versions/sam1checkin01_sysu_sam_checkin.py`，
revision `sam1checkin01`，down_revision `b1c2d3e4f5a6`（rebase 到骨架之后仍是唯一的
head——骨架没有加迁移）。

| 表 | 关键字段 |
|---|---|
| `checkin_session` | `session_uuid`、`org_id`、`course_id`、`created_by`、`title`、`status`(open/closed)、`refresh_seconds`(10-120，默认 20)、`code_length`(默认 6)、`secret`、`started_at`、`closed_at` |
| `checkin_record` | `session_id`、`user_id`、`checked_at`、`method`(qr/code)、`ip`、`user_agent`、`token_used`；唯一约束 `uq_checkin_record_session_user (session_id, user_id)` |

`secret` 是 32 字节随机数的 hex，只存服务端，**任何读模型和任何接口响应都不含它**
（`test_live_state_exposes_token_and_code_but_not_secret` 断言了这点）。

两个函数都先查表是否存在再动手，和仓库里其它迁移一致——生产库是从备份恢复的，
不能假设表一定不存在。

## 三、接口清单

全部挂在 `/api/v1/ext/checkin`，router 依赖是 `require_authenticated_user`。

### 教师端（需要对该课程有 update 权限）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/courses/{course_uuid}/sessions` | 建一场并立即开放。入参 `{title?, refresh_seconds}`；`title` 省略时取「第 N 次课」，N 是该课程已有场次数 + 1 |
| GET | `/courses/{course_uuid}/sessions` | 历史场次，新的在前，含每场已签人数 |
| GET | `/sessions/{session_uuid}/live` | 当前 token、口令、本窗口剩余秒数、已签人数、最新 20 条 |
| POST | `/sessions/{session_uuid}/close` | 结束，幂等 |
| GET | `/sessions/{session_uuid}/records` | 名单；`?format=csv` 返回带 UTF-8 BOM 的 CSV（课程 / 场次 / 姓名 / 邮箱 / 签到时间 / 方式 / IP） |

教师端每个接口过两道门：

1. **组织级**：骨架的 `src/routers/ext/deps.verify_teacher`，判 Admin / Maintainer /
   Instructor（口径就是 `rights.dashboard.action_access`，和前端
   `useAdminStatus().isAdmin` 一致）。用的是它的非依赖形态——依赖形态
   `require_teacher` 会强制调用方在 query 里带 `org_id`，而签到的每个接口都能从
   课程或会话反查出组织，没必要让前端多传一个可被篡改的参数。
2. **课程级**：对该课程有 `update` 权限。

**第二道刻意用 `update` 而不是 `read`**：课程公开时 `read` 对任何登录用户都成立，
按 `read` 判会让学生直接拉到全班名单和 IP。写这条测试时就是这么发现的
（`test_regular_user_cannot_read_records`）。所有教师端接口，包括三个只读的，
一律按「能改这门课的人」判。API token 一律拒绝。

### 学生端（任何本组织的登录用户）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/sessions/{session_uuid}/public` | 标题、课程、状态、刷新间隔、本人是否已签。**不含 token** |
| POST | `/sessions/{session_uuid}/check` | 入参 `{token?}` 或 `{code?}` |
| GET | `/my/open?course_uuid=` | 该课程当前开放中的会话，没有则返回 `null`。学生端入口条用 |

`check` 的四种明确结果，错误体是 `detail: {code, message}`，前端按 `code` 映射中英文案：

| 情况 | HTTP | `detail.code` |
|---|---|---|
| 成功 | 200 | — |
| 已签过 | 409 | `already_checked_in` |
| 口令过期或不正确 | 400 | `invalid_or_expired_code` |
| 会话已关闭 | 410 | `session_closed` |
| 提交过快 | 429 | `rate_limited` |

会话状态的判定**先于**「是否已签过」，所以关闭之后任何人再提交都拿 410。

## 四、动态码怎么算的

```
window = floor(now / refresh_seconds)
mac    = HMAC-SHA256(secret, "<session_uuid>:<window>")
token  = mac.hex()[:16]                      # 二维码里带的
code   = int(mac[-8:]) % 10**6，左补零        # 屏幕上的 6 位口令
```

口令和 token 由**同一个** mac 派生，所以服务端校验口令时能反查出它属于哪个窗口。
校验接受**当前窗口与上一窗口**，避免学生在窗口切换那一瞬提交失败。

二维码内容是 `https://<host>/checkin/<session_uuid>?t=<token>`，前端用仓库里已有的
`qrcode` 依赖渲染成内联 SVG，没有引新库。

## 五、防作弊：只做了两层，其余没做

**做了的：**

1. **登录态绑定**。签到记录的 `user_id` 取自会话，接口不接受客户端传入的身份，
   所以不可能替别人签。学生还必须是本组织成员（跨组织拿到 uuid 也签不上，
   `test_non_member_cannot_check_in`）。
2. **动态码 + 短窗口重放限制**。token/口令每 `refresh_seconds` 秒轮换，只接受当前和
   上一窗口；同一账号对同一个 token 只能占用一次（Redis `SET NX`，key 带 user_id，
   TTL = 2×refresh_seconds）。Redis 不可用时自动降级到数据库唯一约束
   `(session_id, user_id)`——效果一样是「一场一账号一次」，只是少一层快速拒绝。
3. 限流：每用户每秒最多提交一次。
4. IP 记录：优先 `CF-Connecting-IP`，其次 `X-Forwarded-For` 的第一个，
   最后落到直连地址。**这个头是无条件信任的**——隧道接上之后它由 Cloudflare 设置，
   可信；但直连 origin 时客户端可以随便伪造，所以这一列**只作审计参考，不作判定依据**。
   （上游的 `get_client_ip` 只在直连来源是内网地址时才信代理头，签到这里没有沿用，
   因为限流的 key 是 user_id 而不是 IP，IP 只进记录。）

**没做的，写清楚：**

- 网段/地理位置限制（不校验学生是不是真在教室的网里）
- 设备指纹、一机一号
- 课中随机抽查、二次点名
- 人脸/蓝牙/超声波这类物理在场证明
- 签到数据与成绩的联动

所以**代签仍然是可能的**：学生 A 把屏幕上的 6 位口令用微信发给不在场的 B，
B 在有效窗口内用自己的账号签上，系统看起来一切正常。这个功能挡的是「事后补签」
和「替别人签」，挡不住「本人远程签」。要挡后者需要上面没做的那几层。

### 一处偏离简报的地方

简报写的是「token 一次一用（Redis SET NX）」。**按字面做会坏事**：投屏上的二维码在
一个刷新窗口里会被全班同时扫，全局一次一用会让第二个扫码的人签不上。所以实现成
「每个用户对每个 token 一次」，key 是 `ext:checkin:token:{session}:{token}:{user_id}`。
防重放靠时间窗口，防重复签靠数据库唯一约束。已向 team-lead 报备。

## 六、验证证据

### 后端 pytest

`apps/api/src/tests/ext/test_checkin.py`，**36 条全过**；连同骨架的 ext 测试
一起跑是 **58 条全过**（`pytest src/tests/ext -q`）：

```
$ cd apps/api && uv run pytest src/tests/ext/test_checkin.py -q
....................................                                     [100%]
36 passed in 3.48s
```

覆盖：token/口令在窗口内稳定、跨窗口变化、不同场次不撞、上一窗口接受而上上个窗口
拒绝、口令走上一窗口也接受、倒计时秒数、IP 取值三种优先级、创建即开放、默认标题按
场次数递增、refresh_seconds 越界拒绝、live 不泄漏 secret、关闭幂等且清空 token、
历史倒序、404、扫码签到、口令签到、过期口令拒绝、缺凭证拒绝、重复签 409、
Redis 在场时 token 每人一次、关闭后 410、限流 429、public 视图隐藏 token 且反映
已签状态、开放场次查询、学生不能开场次、学生不能读名单、匿名不能签、
非本组织成员不能签、CSV 有 BOM/表头/中文/逗号转义。

环境注意：`apps/api` 的依赖里没有声明 `greenlet`，而 SQLAlchemy 的 asyncio 需要它，
新建的 venv 里跑测试会全部 error。本次是手动 `uv pip install greenlet` 补上的，
**没有改 pyproject.toml**（这是上游的遗漏，留给集成时决定要不要补进依赖）。

### alembic 往返

在一个一次性的 pgvector 容器里，先用 SQLModel 建出上游全部 61 张表（这个仓库的
迁移不是从空库开始的，上游靠 `create_all` 建表，迁移只负责补丁），
`alembic stamp b1c2d3e4f5a6` 之后：

```
upgrade   b1c2d3e4f5a6 -> sam1checkin01   两张表建出，唯一约束与外键 ON DELETE CASCADE 都在
downgrade sam1checkin01 -> b1c2d3e4f5a6   两张表清空为 0
upgrade   再来一次                          两张表回到 2
```

`\d checkin_record` 确认了 `uq_checkin_record_session_user` 唯一约束、
`ix_checkin_record_session` 索引、两个 `ON DELETE CASCADE` 外键。

### 前端 lint

我的文件 0 error 0 warning：

```
$ bunx eslint --max-warnings 0 components/SysuTools components/SysuCheckin \
    services/ext lib/query/keys.ts app/orgs/\[orgslug\]/dash/tools/checkin \
    app/orgs/\[orgslug\]/\(withmenu\)/checkin
（无输出）
```

两个被改动的上游文件（`course.tsx`、`activity.tsx`）改动前后都是 0 error。

`bun run lint:strict` 整体报 **35 个 error**，与 team-lead 给出的 sysu-sam 基线数
一致，即**没有新增**。逐条看下来全部落在既有的上游文件里（admin/embed 的 layout
缺 React 引用、analytics 图表组件的 "Cannot create components during render"、
PasswordStrengthIndicator 的正则转义等），本分支新增或改动的文件一条也没有。

### Playwright 端到端

用例在 **`apps/e2e/features/ext/tests/02-checkin.spec.ts`**（复用 `apps/e2e` 已有的
Playwright 工程：`core/fixtures` 抑制首屏引导弹窗、`core/sharedAuth` 复用管理员与
普通成员的会话，整轮只花几次登录，不会撞上 30 次 / 5 分钟 / IP 的登录限流）。
API 种子与读回封装在同目录的 `checkin.ts`。

**连同骨架自己的 6 条，`features/ext` 15 条全过**：

| 用例 | 证明了什么 | 截图 |
|---|---|---|
| 老师开一场签到，投屏页出二维码与六位口令 | 工具页能开会话并跳投屏；二维码是内联 SVG；口令是 6 位数字，且与服务端 `/live` 同一窗口派生 | `01-tool-form.png`、`02-present.png` |
| 扫码路径签到成功 | 带 token 打开落地页即自动签到成功 | `03-student-qr-ok.png` |
| 同一个账号再签一次落在「已经签过」 | 一场一账号一次 | `04-student-duplicate.png` |
| 名单里出现这个学生，CSV 能导出 | 人数不为 0；CSV 带 BOM、表头、该学生邮箱、方式 qr | — |
| 输口令也能签到 | 口令路径独立可用，人数增加到 2 | `05-student-code-ok.png` |
| 结束之后再提交拿 410 `session_closed` | 状态判定先于「是否已签过」 | — |
| 结束后的投屏页不再显示二维码与口令 | 关闭后不再发码 | `06-present-after-close.png` |
| 课程页顶部出现入口条，点进去是这场签到 | 学生端挂点生效 | `07-course-banner.png`、`08-student-form.png` |
| 未登录扫码 → 登录 → 回跳并自动签到 | `?next=` 原样带着 `?t=`，登录回来自动提交 | `09-anon-login-prompt.png`、`10-anon-after-login-ok.png` |

截图由用例自己写进 `docs/sysu-sam/QA/checkin/`，跑一遍就会刷新。

CSV 的 BOM 断言走原始字节，不看正文开头——`Response.text()` 按规范会把前导 BOM
吃掉，用文本判断会永远失败（第一次就是这么挂的）。

**怎么跑**（本地栈的 Postgres/Redis 没有映射到宿主机端口，socat 转发容器
`lh-db-fwd-15432`、`lh-redis-fwd-16379` 由骨架代理起好，共用）：

```sh
# 1. 建表（本地栈的库没有 alembic_version，先 stamp 再 upgrade）
cd apps/api
export LEARNHOUSE_SQL_CONNECTION_STRING=postgresql://learnhouse:learnhouse@127.0.0.1:15432/learnhouse
uv run --no-sync alembic stamp b1c2d3e4f5a6 && uv run --no-sync alembic upgrade head
# 验完 stamp 回去：本地库是几个功能分支共用的，停在 sam1checkin01 会让还没合入
# 本分支的人跑 upgrade head 报 Can't locate revision。表留着无害。
uv run --no-sync alembic stamp b1c2d3e4f5a6

# 2. 起后端与前端（端口自行错开，签到用 9004 / 3004）
uv run --no-sync uvicorn app:app --port 9004
cd ../web && bun run dev --port 3004

# 3. 跑 e2e
cd ../e2e && bun install && bun run install-browsers
E2E_SKIP_BOOT=1 \
E2E_BASE_URL=http://localhost:3004 \
E2E_API_URL=http://localhost:9004/api/v1 \
E2E_ADMIN_EMAIL=user1@example.local E2E_ADMIN_PASSWORD='LocalDev#2026' \
E2E_STUDENT_EMAIL=user2@example.local E2E_STUDENT_PASSWORD='LocalDev#2026' \
bunx playwright test features/ext
```

学生用本地库自带的 `user2@example.local`（User 角色），不新建账号——这套库开了
「需要邀请码才能加入」，`createStudent` 会被 403 顶回来。

### 类型检查

两个工程都 exit 0：

```
$ cd apps/web && bunx tsc --noEmit -p .      → 0
$ cd apps/e2e && bun run typecheck           → 0
```

`tsc` 这一关抓到两个 eslint 没抓到的真错：`outcome` 联合类型没窄化就读 `code`，
以及 `courseUuid` 可能是 `undefined`。

## 七、已知限制与待办

1. **已经 rebase 到骨架上并按骨架的约定改造完**（`33537025`）。具体接法：
   - `registry.ts` 里加一条 `key: 'checkin'`、`courseScoped: true`、
     `minRole: 'instructor'` 的条目，组件 `lazy` 导入；
   - 课程下拉不再由签到组件自己渲染，改由路由页的 `CourseSelect` 统一提供，
     组件从 `SysuToolProps.courseUuid` 收；
   - 后端在 `src/routers/ext/__init__.py` 的 `SUBMODULES` 里加
     `("checkin", "/checkin")` 一行，不再自己动 `src/router.py`；
   - 文案并进骨架的 `locales/ext/{zh,en}.json`，挂在 `tools.checkin` 下，
     组件里引用 `ext.tools.checkin.*`。
   `dash/tools/[tool]/page.tsx`、`ToolPageHeader`、`CourseSelect` 全部用骨架的原件，
   本分支一个字都没改。

2. **i18n 已经通了**。骨架的 `lib/i18n.ts` 把 `locales/ext/*.json` 并进 `common`
   的 `ext` 顶层 key，签到的 66 个 key 挂在 `tools.checkin` 下，中英一一对应
   （脚本比对过，两边键集合完全相同）。组件里仍保留 `defaultValue` 中文兜底。

3. **专注模式下没有签到入口条**。学生端入口条挂在课程页和活动页的**普通模式**。
   活动页的专注模式是 `fixed inset-0` 的独立布局，插横条会打乱它的排版，
   所以没挂。专注模式下的学生仍可从课程页进入，或者直接扫码。

4. **投屏页用轮询不用 SSE**。每秒一次 `GET /live`。投屏页只有教师一个人开着，
   这点请求量可以忽略；SSE 在 NAS 反代加后续 Cloudflare 隧道的链路上要额外处理
   缓冲和超时断连，收益不抵成本。

5. **迁移可能出现多头**。`sam1checkin01` 的 down_revision 是 `b1c2d3e4f5a6`。
   学情、作业工具如果也从同一个 head 开分支加迁移，合并后会有多个 head，
   需要集成时补一条 merge migration。

   另外：本地预发栈的库原本没有 `alembic_version` 行（它是从备份恢复的，表由
   `create_all` 建）。验证时 stamp 过一次，**验完已经 stamp 回 `b1c2d3e4f5a6`**，
   两张签到表留着不删——这样还没合入本分支的功能分支跑 `upgrade head` 不会报
   找不到 revision，而合入本分支的人跑一遍也是无害的（迁移会跳过已存在的表）。

6. **投屏页是深色的**。这是整个 fork 里唯一不用后台灰白配色的页面，理由是要在教室
   投影上从最后一排看清。用 `fixed inset-0` 盖住左侧菜单做到全屏无菜单，
   鉴权仍然复用 `/dash` 布局那一层。

7. 本次验证顺手修了一个自己写出来的 bug：学生端「回到课程」的链接原来直接拼
   `course_uuid`，而课程页的路径段是不带 `course_` 前缀的，会请求到
   `course_course_xxx` 然后 404。已改成 `.replace('course_', '')`，与仓库里
   `CommunitySidebar`、`CourseProgress` 等处的写法一致。
