# 作业工具 QA 记录

教学工具 · 作业工具（`key = assign`）：AI 出题、随堂测、查重、学期复用、内容页版本回滚。
分支 `feat/assign-tools`。截图与脚本在 `docs/sysu-sam/QA/assign/`。

## 一、接口清单

全部挂在 `/api/v1/ext/assign` 下。权限两道门：骨架的 `deps.require_teacher` 先做组织级
判断（Admin / Maintainer / Instructor，看 `dashboard.action_access`），课程级再由各
service 调 `check_resource_access` 收窄。

**每个接口都要带 `?org_id=<org.id>`** —— 这是 `require_teacher` 把 `org_id` 声明成
query 参数带来的硬要求，前端的 `services/ext/assign.ts` 统一在 URL 里拼上。

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

`apps/api/src/tests/ext/test_assign_tools.py`，52 条；连骨架自己的 ext 测试一起 74 条全过：

```
$ cd apps/api && uv run pytest src/tests/ext -q
74 passed
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

### 4.3 前端走查（带断言，不只是截图）

本地起后端 9005（连预发栈的 Postgres/Redis）+ 前端 3005，用管理员账号登录后
走完五个 Tab。脚本 `docs/sysu-sam/QA/assign/shots.mjs`（配 `login.mjs` 存登录态）
在仓库根目录跑，**任何一条断言不成立就非零退出**：

```
$ node docs/sysu-sam/QA/assign/login.mjs
$ node docs/sysu-sam/QA/assign/shots.mjs
  ok   五个分段 Tab 都在
  ok   AI 出题的内容页下拉拉到了课程结构
  ok   模型下拉拉到了 /ext/assign/llm/models 的结果
  ok   AI 出题返回了至少一道可编辑的题
  ok   出完题后出现了「一键布置」
  ok   随堂测默认勾着「形成性」
  ok   随堂测表单默认给了一道题
  ok   查重有阈值滑块
  ok   查重结果原样显示了后端的免责说明
  ok   学期复用摘要回显了新课程名
  ok   只试算，没有真的复制课程
  ok   版本列表拉到了历史版本
  ok   diff 视图出来了
  ok   400px 窄屏没有横向溢出
  ok   除上游 analytics 外没有失败请求（实际 0 条）
全部断言通过
```

被忽略的那一条失败请求是上游的 `POST /api/v1/analytics/events` 400（本地没配 PostHog），
和作业工具无关。顺带截下的图：

| 截图 | 内容 |
|---|---|
| `1-ai-setup.png` | AI 出题设置：内容页下拉（真实课程结构）、题量、题型多选、模型下拉（真实模型列表） |
| `2-ai-preview.png` | 真调大模型出题后的可编辑预览 + 字段被改回默认值的警告 |
| `3-quiz-form.png` | 随堂测快速表单 |
| `4-quiz-results.png` | 随堂测结果面板 |
| `5-similarity.png` | 查重：阈值滑块 + 结果区 |
| `6-clone-summary.png` | 学期复用向导第三步的确认摘要（`confirm=false` 真跑出来的） |
| `7-versions-diff.png` | 版本列表（预发栈里这一页有 v1–v5，当前 v6） |
| `8-versions-unified.png` | unified diff 视图 |
| `9-mobile-ai.png` | 400px 窄屏，脚本断言了 `scrollWidth <= clientWidth`，没有横向溢出 |

### 4.4 类型检查与 lint

`npx tsc --noEmit` 在整个 `apps/web` 上退出码 0，无任何输出 —— dev 用的 Turbopack
不做类型检查，页面能渲染不等于 `bun run build` 能过，所以这一步单独跑了一次
（把骨架脚手架临时拷进来补齐 `registry.ts` / `types.ts` / `shared/` 之后跑的）。

`bun run lint:strict` 在本分支上报 35 个 error，**全部落在上游文件**
（`services/courses/transfer.ts`、`components/Dashboard/Boards/Extensions/*`、
Analytics 系列等），是既有欠债。作业工具自己的文件单独跑：

```
$ npx eslint --max-warnings=0 components/SysuTools/tools/assign services/ext/assign.ts
（无输出，0 error 0 warning）
```

## 五、没做 / 做不了的

1. **随堂测结果与查重没有真实数据可看。** 预发栈里 `assignmenttasksubmission` 表是空的
   （0 行），所以 `4-quiz-results.png` 与 `5-similarity.png` 拍到的是空态。
   这两块的计算逻辑由 pytest 用造出来的提交覆盖（答对率 50%、找出近似的一对、
   同 sha256 文件），不是没验，是没有生产数据可拍。
2. **文件题查重只支持 PDF 与纯文本。** PDF 走后端已有的 `pypdf`；docx 需要
   `python-docx`，后端没有这个依赖，也不为查重单独加。抽不出文本的文件只按 sha256
   比对，结果的 `notes` 里会逐个点名说明。
3. **编程题（`code`）的判分依赖 Judge0**，本实例是否配置未验证。spec 支持这种题型，
   但没在预发栈上试过，用之前先在测试课程上试一次。
4. **没有加 alembic 迁移**，作业工具全部复用上游已有的表。
5. **接入骨架的两处改动还没落进分支**，见下一节 —— 这条分支是在骨架合入
   `sysu-sam` 之前开的。
6. **随堂测的结果面板没有导出 CSV。** 骨架给了 `ExportCsvButton`，接上去很便宜，
   但需求里没写，就没加。
7. **没有往 `apps/e2e` 的 playwright 套件里加 spec。** 上面 4.3 那份走查是带断言的
   独立脚本，能当验收跑，但它不在 `playwright test` 套件里 —— 套件的 global-setup
   会自起一套实例，而这条分支的走查依赖预发栈里的真实课程与版本历史。
   骨架合入后，`apps/e2e/features/ext/tests/` 是约定位置，把这份走查改写成
   跟着套件跑的 spec 是一件待办。

## 六、和骨架的接口（已经接完）

骨架已经合入 `sysu-sam`（`33537025`），本分支 rebase 上去后接了这四处，
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

```sh
# 后端：连预发栈的 Postgres/Redis（socat 已把 5432/6379 转到宿主机 15432/16379）
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
