# 作业工具 QA 记录

教学工具 · 作业工具（`key = assign`）：AI 出题、随堂测、查重、学期复用、内容页版本回滚。
分支 `feat/assign-tools`。截图与脚本在 `docs/sysu-sam/QA/assign/`。

## 一、接口清单

全部挂在 `/api/v1/ext/assign` 下。权限两道门：骨架的 `deps.require_teacher` 先做组织级
判断（Admin / Maintainer / Instructor，看 `dashboard.action_access`），课程级再由各
service 调 `check_resource_access` 收窄。

**每个接口都要带 `?org_id=<org.id>`** —— 这是 `require_teacher` 把 `org_id` 声明成
query 参数带来的硬要求，前端的 `services/ext/assign.ts` 统一在 URL 里拼上。

### 只读接口为什么也按 update 判

凡是会返回名单、成绩、他人提交内容、未发布草稿的接口，**哪怕它是只读的**，课程级
那道门都按 `AccessAction.UPDATE` 判，也就是按「能改这门课的人」判。理由是公开课程的
READ 对任何登录用户都成立，用 READ 判等于把数据开放给了不该看的人 —— Instructor
角色尤其不该看到别人课的编辑历史。

按这个口径判 UPDATE 的有：`results`、`similarity`、`versions`、`versions/{n}/markdown`、
`diff`、以及 `restore` 的 `confirm=false` 预览分支（它返回完整 diff，和上面几个是同一类
东西，不能因为「只是预览」就放低门槛）。版本那几个接口内部还会经过上游
`get_activity_versions` 自带的一道 READ，留着无妨：更严的这道先过。

**一个例外是 `clone-term` 读源课程，仍然按 READ 判。** 它不会泄露调用者本来看不到的
东西：能 READ 一门课就能看它的章节与内容页，摘要里多出的只是作业标题和截止日期；
而克隆产出的是调用者自己组织里的新课程，上游 `clone_course` 内部还有 READ + 建课权限
+ 组织成员三道检查。收紧到 UPDATE 会把「新老师复用同事的课」这种正当用法一并挡掉，
不划算。目标侧（`shift-due` 改截止日期）按 UPDATE 判。

| 方法 | 路径 | 做什么 |
|---|---|---|
| POST | `/spec/validate` | 校验一份作业 spec，返回每题预览与警告。纯本地，不联网不写库 |
| GET | `/spec/template?types=` | 按题型返回带注释的 spec 模板 |
| GET | `/llm/models` | 列出配置端点上可用的模型 id |
| POST | `/courses/{course_uuid}/activities/{activity_uuid}/draft` | 读内容页正文调大模型出题，返回已校验的 spec（**不落库**） |
| POST | `/courses/{course_uuid}/chapters/{chapter_id}/from-spec` | 按 spec 建作业（壳活动 + assignment + 每道题） |
| POST | `/courses/{course_uuid}/chapters/{chapter_id}/quick-quiz` | 建随堂测 |
| GET | `/assignments/{uuid}/results` | 每题答对率与学生名单 |
| GET | `/assignments/{uuid}/similarity?threshold=&min_length=` | 查重，返回相似学生对 |
| POST | `/courses/{course_uuid}/clone-term` | 克隆课程 + 复制作业记录与题目 + 顺延截止 |
| POST | `/courses/{course_uuid}/shift-due` | 批量顺延截止日期 |
| GET | `/activities/{uuid}/versions` | 版本列表与当前版本号 |
| GET | `/activities/{uuid}/versions/{n}/markdown` | 某个版本的 Markdown 全文 |
| GET | `/activities/{uuid}/diff?a=&b=` | 两版之间的 unified diff（任一侧留空 = 当前内容） |
| POST | `/activities/{uuid}/restore` | 回滚到某个版本 |

三个危险接口（`clone-term` / `shift-due` / `restore`）用同一个约定：
**`confirm=false` 只返回将要发生什么的摘要，一个字都不写；`confirm=true` 才真的执行。**
前端向导的「确认摘要」那一步用的就是前者，摘要和执行走同一段代码，不会两边算得不一样。

## 二、几个容易踩的接口事实

- `solution_reveal` 的合法值是 `NEVER` / `ON_SUBMISSION` / `AFTER_GRADING`。
  写成 `ON_SUBMIT` 后端会 422，spec 校验会专门提示这一条。
- spec 里的 `formative` 对应后端字段 `ungraded`，不是 `formative`。
  形成性作业与自动判分互斥，上游 `create_assignment` 会把 `auto_grading` 归零。
- `POST /courses/{uuid}/clone` **不复制** assignment / assignmenttask 两张表
  （上游 `clone_course` 全函数没有一次 Assignment 写入），所以学期复用要自己补作业记录。
  这里按（章节顺序，活动顺序）配对源课程与新课程的活动 —— 克隆保序且一一对应，
  比按活动名匹配更准（同名活动不会歧义）。
- `restore_activity_version` 上游自带「先把当前内容存成新版本再回滚」，
  所以回滚不会丢当前稿，不用另写备份。

## 三、LLM 配置

走骨架的 `get_ext_config`，也就是「组织配置的 ext 段 → 环境变量 → 默认值」三层回退：

| ext 段的键 | 环境变量 | 是什么 |
|---|---|---|
| `llm_base_url` | `LEARNHOUSE_EXT_LLM_BASE_URL` | OpenAI 兼容端点，形如 `https://example.com/v1` |
| `llm_api_key` | `LEARNHOUSE_EXT_LLM_API_KEY` | API key |
| `llm_model` | `LEARNHOUSE_EXT_LLM_MODEL` | 默认模型 id，请求里可以用 `model` 覆盖 |

同一台机器上可能跑多个组织，所以组织配置能盖过环境变量，这一条有单测钉着
（`test_org_config_overrides_env`）。

**key 建议只用环境变量配。** 它虽然也能写进组织配置，但那份 JSON 会随组织配置下发到
前端；组织配置里只放端点和模型更稳妥。三个环境变量键已经加进 `deploy/.env.example`
（只有键名，没有值）。

三者都不填时，只有 AI 出题不可用（接口返回 503，前端把模型下拉禁用并给出提示），
其余四个 Tab 照常。

请求走 `httpx.AsyncClient(trust_env=False)`，绕开系统代理 —— 端点可能在内网，
或者本机装了会劫持出网请求的代理。

## 四、验证证据

### 4.1 后端单测

`apps/api/src/tests/ext/test_assign_tools.py`，61 条；连骨架与学情的 ext 测试一起 117 条全过：

```
$ cd apps/api && uv run pytest src/tests/ext -q
117 passed
$ uv run ruff check src/
All checks passed!
```

用例不依赖开发机上的 `apps/api/.env`：AI 出题相关的用例用 `llm_configured` fixture
显式设死端点，把 `.env` 挪走再跑一样是全过（试过）。

覆盖到的行为（挑要紧的说）：

- spec 校验：缺 name、`due_date` 格式、`ON_SUBMIT` 笔误提示、选择题没标正确答案、
  注释键被忽略、多选自动识别、模板本身能过校验
- AI 出题：模型说 `publish=true` 也强制改回草稿；模型多出题型会警告；
  连续两次输出解析不出 JSON 才放弃（断言真的重试了一次）；
  正文太短拒绝；内容页不属于该课程返回 400；没配模型返回 503；
  模型自己发明的枚举值（`grading_type: MIXED` 等）被改回默认值并写进警告；
  没配端点 / 没配模型都返回 503；组织配置的 ext 段能盖过环境变量
- 建作业：三张表都建出来了、`publish` 覆盖生效、章节不属于课程拒绝、
  **spec 有错时一个活动都不会建**（校验在建任何东西之前完成）
- 随堂测：默认 `ungraded=True` + `solution_reveal=ON_SUBMISSION` + `auto_grading` 被归零；
  计分模式下 `NEVER`；答对率按题统计（1 对 1 错 → 50%）；文件题标为需人工
- 查重：归一化把标点空格吃掉；找出近似的一对而不误报第三个人；
  客观题跳过、太短跳过、答对标准答案的两个人不算互抄；同 sha256 文件单独报
- 学期复用：`confirm=false` 不新建课程；参数冲突拒绝；
  `confirm=true` 复制作业与题目、顺延日期、新课程未发布、**学生提交没有被复制**
- 批量顺延：试算不改库、执行才改；`only_future` 跳过已过期；日期解析失败跳过
- 版本：列表带当前版本号、按版本取 Markdown、两版 diff 行数正确、
  和「当前」比较、试算不写库、**回滚后旧稿被存成了新版本**（断言查得到）
- 权限：三个只读的版本接口与回滚预览都断言了「问的是 UPDATE 不是 READ」，
  另有四条走真实 RBAC 的用例，User 角色调 versions / diff / results / similarity
  一律 403。这几条不是摆设 —— 把守卫去掉重跑，它们会红

LLM 调用在测试里只 mock 了 `chat_completion` 这一个联网入口。

### 4.2 手动真调一次 AI 出题

对本地预发栈（`learnhouse-local`）里真实的内容页 + 真实的 LLM 端点各跑了一次：

| 项 | 值 |
|---|---|
| 内容页 | 《1.1 什么是自动化？数字化？》（正文 3457 字） |
| 端点 | `http://43.134.78.71:8000/v1` |
| 模型 | `deepseek-v4-flash` |
| 尝试次数 | 1（一次就出了合法 JSON） |
| 结果 | 4 道选择题 + 1 道简答题，校验通过 |

一次真实的发现：**模型会自己发明枚举值**，两次都把 `grading_type` 填成了 `MIXED`。
这个字段和题目内容毫无关系，为它整份 spec 报废不划算，所以 `draft` 在校验前会把
`grading_type` / `solution_reveal` / `due_date` 三个字段的非法取值改回默认值，
并在警告里写明「原值是什么」。截图 `2-ai-preview.png` 里那条黄色提示就是它。

### 4.3 前端 E2E（apps/e2e 套件里的 spec）

`apps/e2e/features/ext/tests/03-assign-tools.spec.ts`，8 条用例，和骨架、学情的 ext
用例跑在同一个套件里（一起 18 条全过）。

夹具在 `features/ext/assign-api.ts`，**全部走 REST API 建、跑完删**，不碰数据库，
所以对着自己 boot 的干净实例或 `E2E_SKIP_BOOT=1` 指向的本地预发栈都能跑，
也不会在共享的预发栈里留垃圾。它造出来的东西：一门带随机后缀的课 + 一个章节、
一个改过两次因而有历史版本的富文本内容页、一份 2099-03-01 截止的作业、
一份形成性随堂测（顺带把 `quick-quiz` 接口也验了），以及一份学生交的卷。

```
$ cd apps/e2e
$ E2E_SKIP_BOOT=1 \
  E2E_BASE_URL=http://localhost:3005 \
  E2E_API_URL=http://localhost:9005/api/v1 \
  E2E_ADMIN_EMAIL=user1@example.local E2E_ADMIN_PASSWORD='LocalDev#2026' \
  E2E_STUDENT_EMAIL=user2@example.local E2E_STUDENT_PASSWORD='LocalDev#2026' \
  bun run test features/ext
  ...
  18 passed (38.2s)
```

七条用例分别钉住：

| 用例 | 钉住的性质 |
|---|---|
| 五个 Tab 都挂出来了 | 注册表条目生效，工具页不是空壳 |
| AI 出题 | 内容页下拉来自课程结构树；**真调大模型**出题并渲染成可编辑预览（题干断言 `toBeEditable`）；没配端点时是明确禁用 + 一句人话 |
| 随堂测 | 形成性默认勾上；学生全选对 → 那道题答对率 100%；导出 CSV 按钮可用 |
| 查重 | 后端的免责说明原样出现在页面上（断言含「不是抄袭的结论」）—— 这是产品口径不是装饰 |
| 学期复用 | 摘要回显新课名与顺延后的 2099-08-30；**并回查课程数没变**，证明 confirm=false 真的没写库 |
| 版本回滚 | 至少两个历史版本；点最老那一版能 diff 出第一稿的正文；两栏与合并两种视图都在 |
| 越权 | 普通成员（User 角色）拿自己的 token 直调 versions / diff / results / similarity，四个都 403 |
| 窄屏 | 400px 下 `scrollWidth <= clientWidth`，不横向溢出 |

学生那一段是**可选**的：本地预发库是邀请制，`createStudent` 会 403。设了
`E2E_STUDENT_EMAIL/PASSWORD` 就复用已有账号交一份卷，没设就只验题目清单渲染，
并在用例的 annotation 里写明跳过了哪一段。`beforeAll` 会打印这一轮走的是哪条路，
不会静默降级。

顺手截的图（跑的时候加 `EXT_SHOTS=1`，写到 `docs/sysu-sam/QA/assign/`）：

| 截图 | 内容 |
|---|---|
| `1-ai-setup.png` | AI 出题设置：内容页下拉、题量、题型多选、模型下拉 |
| `2-ai-preview.png` | 真调大模型出题后的可编辑预览 |
| `3-quiz-results.png` | 随堂测结果：1/1 已交、答对率 100%、导出 CSV 按钮 |
| `4-similarity.png` | 查重：阈值滑块 + 免责说明 |
| `5-clone-summary.png` | 学期复用向导第三步的确认摘要 |
| `6-versions-diff.png` | 两栏 diff |
| `7-versions-unified.png` | unified diff |
| `8-mobile.png` | 400px 窄屏 |

### 4.4 类型检查与 lint

dev 用的 Turbopack 不做类型检查，页面能渲染不等于 `bun run build` 能过，所以两个
workspace 都单独跑了一次，都是退出码 0：

```
$ cd apps/web && bunx tsc --noEmit -p .      # 退出码 0，无输出
$ cd apps/e2e && bun run typecheck           # 退出码 0，无输出
```

跑 `apps/web` 那条之前 `next-env.d.ts` 必须存在（`next dev` / `next build` 生成，
被 gitignore）。缺了它会冒出 23 个上游图片模块的假报错，和本次改动无关。

`bun run lint:strict` 在本分支上报 35 个 error，**全部落在上游文件**
（`services/courses/transfer.ts`、`components/Dashboard/Boards/Extensions/*`、
Analytics 系列等），和基线持平，没有新增。作业工具自己的文件单独跑：

```
$ npx eslint --max-warnings=0 components/SysuTools/tools/assign services/ext/assign.ts
（无输出，0 error 0 warning）
```

## 五、没做 / 做不了的

1. **查重的相似对没有端到端验过。** 找出「两个学生答得像」需要至少两个学生各交一份
   长答案，而本地预发库是邀请制，e2e 只能复用一个已有学生账号。所以 e2e 只验了
   免责说明与阈值控件，相似度算法本身、剔除标准答案、同 sha256 文件这些由 pytest
   用造出来的提交覆盖。随堂测的答对率则已经是端到端真数据（学生真交卷、页面真显示
   100%）。
2. **文件题查重只支持 PDF 与纯文本。** PDF 走后端已有的 `pypdf`；docx 需要
   `python-docx`，后端没有这个依赖，也不为查重单独加。抽不出文本的文件只按 sha256
   比对，结果的 `notes` 里会逐个点名说明。
3. **编程题（`code`）的判分依赖 Judge0**，本实例是否配置未验证。spec 支持这种题型，
   但没在预发栈上试过，用之前先在测试课程上试一次。
4. **没有加 alembic 迁移**，作业工具全部复用上游已有的表。
5. **e2e 的夹具会被同一套实例上别的用例改到。** 有一次和别的 ext 用例一起跑时，
   我造的内容页被另一条用例追加了内容，多出两个版本，于是「点第一行版本」那条断言
   挂了。改成点**最老**那一版（v1 的内容是稳定的）之后就稳了。真正的隔离要靠
   每条用例自己的组织，那超出本次范围。

## 六、和骨架的接口（已经接完）

骨架已经合入 `sysu-sam`（学情合入后是 `d20e8c19`），本分支 rebase 上去后接了这四处，
上面第四节的验证证据都是 rebase **之后**重新跑的：

1. `apps/api/src/routers/ext/__init__.py` 的 `SUBMODULES` 里加了一行
   `("assign_tools", "/assign")`，`src/router.py` 一个字没改（临时挂载已经删掉）。
2. `require_teacher` 换成骨架的 `src/routers/ext/deps.require_teacher`，
   本模块原来的占位实现 `services/ext/assign_tools/auth.py` 已删。
   连带的影响是所有接口都要带 `?org_id=`，前端 `services/ext/assign.ts` 统一拼上了。
3. LLM 配置从「只读环境变量」换成骨架的 `get_ext_config`（组织配置 → 环境变量）。
4. registry 与两个语言包的文案由 `docs/sysu-sam/QA/assign/register.py` 写入
   （幂等，重复跑不会重复插）。它留在仓库里是为了万一 rebase 冲突把这两处冲掉，
   重跑一次就能补回来。

## 七、本地复现环境

端口自行错开（骨架占 9001/3001，我用 9005/3005）。

```sh
# 后端：连预发栈的 Postgres/Redis（socat 转发容器 lh-db-fwd-15432 / lh-redis-fwd-16379 共用）
cd apps/api
cat > .env <<'EOF'
LEARNHOUSE_SQL_CONNECTION_STRING=postgresql://learnhouse:learnhouse@127.0.0.1:15432/learnhouse
LEARNHOUSE_REDIS_CONNECTION_STRING=redis://127.0.0.1:16379/learnhouse
LEARNHOUSE_REDIS_URL=redis://127.0.0.1:16379
LEARNHOUSE_PORT=9005
LEARNHOUSE_DOMAIN=localhost
LEARNHOUSE_TENANCY=single
LEARNHOUSE_ALLOWED_ORIGINS=http://localhost:3005,http://127.0.0.1:3005
LEARNHOUSE_CONTENT_DELIVERY_TYPE=filesystem
LEARNHOUSE_EXT_LLM_BASE_URL=http://43.134.78.71:8000/v1
LEARNHOUSE_EXT_LLM_MODEL=deepseek-v4-flash
EOF
# key 不写进任何文件，只在启动这一条命令里传
LEARNHOUSE_EXT_LLM_API_KEY=$LH_LLM_KEY uv run uvicorn app:app --host 127.0.0.1 --port 9005

# 前端
cd apps/web && bun run dev --port 3005      # .env.local 指向 http://localhost:9005/api/v1/
```

后台入口在左侧菜单「教学工具」→「作业工具」，路径 `/dash/tools/assign`。
注意单租户模式下带 `/orgs/<slug>` 前缀的路径会 404，要走 `/dash/...`。

Apple Silicon 上 `greenlet` 不在 `uv.lock` 的 marker 里（它认 `aarch64`，
macOS 报的是 `arm64`），跑 pytest 前要 `uv pip install greenlet`，
然后一律用 `uv run --no-sync`，**不要动 `pyproject.toml` / `uv.lock`**。

---

## AI 出题真实链路验证（集成代理，2026-09-10）

之前几轮 e2e 都因为本地栈没配大模型端点而走了降级分支（断言模型下拉禁用 +
有提示文案），**AI 出题的真实链路一直没被端到端验证过**。这次补上了。

配置写在 `apps/api/.env`（gitignore，不进仓库）：端点指向自研中转服务
`http://43.134.78.71:8000/v1`，key 从 shell 环境变量取、不落盘到任何提交物，
模型 `deepseek-v4-flash`。

### 直接调接口

`GET /ext/assign/llm/models` 真实返回 64 个模型，deepseek 系列五个都在。

`POST /ext/assign/courses/{uuid}/activities/{uuid}/draft`，用《1.1 什么是自动化？
数字化？》这一页（正文 3457 字）出 2 道题：

| 字段 | 值 |
| --- | --- |
| HTTP | 200 |
| 用时 | 7.18s |
| model | deepseek-v4-flash |
| endpoint | http://43.134.78.71:8000/v1 |
| attempts | 1（一次成功，没有重试） |
| page_chars | 3457 |
| validation.ok | true |

出的两道题分别是选择题与简答题，题目内容确实取自正文（选择题问的是「自动化
系统可以划分为哪三个技术层级」）。

### e2e 走真出题分支

`03-assign-tools.spec.ts` 的「AI 出题读得到课程结构，出的题落在可编辑的预览里」
这条会自己判断模型下拉是否可用。配好之后重跑，这条从 **0.76s 变成 5.1s**，
说明真的走了大模型分支而不是那个 return。8 条全过。

截图要带 `EXT_SHOTS=1` 才会写（`maybeShot` 里的开关），这一轮八张全部按真出题
的结果重出了。`2-ai-preview.png` 里题干、四个选项、正确答案的勾选、简答题的
可接受答案都渲染出来了，且题干可编辑；选择题问的是「数控机床中，负责解释加工
程序并产生指令的是哪一部分」，答案勾在「控制系统」上——确实是从正文里出的题，
不是夹具里写死的。

### 一个使用上的注意

出题要求内容页有实质正文。我第一次拿的活动正文是 0 字，接口返回 400 并说清了
原因（「这一页的正文太短（0 字）……确认它是一个富文本内容页，而不是视频或
PDF 活动」）。这个错误提示是好的，直接告诉了老师该怎么办。

