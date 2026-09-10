# 内容工具 · 验收记录

分支 `feat/content-tools`。覆盖 Markdown 导入导出、编辑器粘贴 bilibili 链接、
虚拟助教、邀请码二维码四件事。

本文只记**真跑过**的结果。没跑的一律写在最后「还没验的」一节里，不含糊过去。

---

## 1. 后端自动化测试

```sh
cd apps/api
uv sync
uv pip install greenlet          # 见下面「环境坑」
uv run --no-sync pytest src/tests/ext/test_content_tools.py -q
uv run --no-sync ruff check src/services/ext src/routers/ext src/tests/ext
```

| 项 | 结果 |
|---|---|
| pytest（`src/tests/ext` 全量，含骨架的 12 条） | 92 passed |
| ruff | All checks passed |

本分支贡献 80 条：73 条纯逻辑（不碰库不碰网），7 条用 conftest 的内存 SQLite
真跑 service 调用。

**环境坑（其他代理也会踩）**：`uv sync` 装不上 `greenlet`，但 SQLAlchemy 的
async 引擎必须要它，缺了所有碰数据库的测试都报
`ValueError: the greenlet library is required`。这不是本分支引入的 ——
`src/tests/services/test_activities_service.py` 在干净的 sysu-sam 上同样 21 个
ERROR。手工 `uv pip install greenlet` 之后那 21 条也全过了。后续跑测试要加
`--no-sync`，否则 `uv run` 会把 greenlet 再卸掉。

### 测了什么

**Markdown ⇄ TipTap**
- 十种块级语法各自映射到哪个 TipTap 节点（标题、段落、有序/无序列表、代码块、
  表格、分割线、info/warning 提示框、翻转卡）
- 连续翻转卡排成网格、行内 bold/italic/code/link 的 marks
- 段落遇到块级起始就断开
- 往返：md → tiptap → md → tiptap，两次节点类型序列一致，关键文字不丢
- 不认识的节点导出成 `<!-- blockVideo -->`，`strip_lost_nodes` 把它剥掉
  （不剥的话学生会看到一行字面的 HTML 注释）

**bilibili 七种形态**（前六种离线跑，第七种见下一节）

| 形态 | 输入 | 输出 |
|---|---|---|
| 视频页 | `bilibili.com/video/BV1GJ411x7h7` | `player.bilibili.com/player.html?bvid=BV1GJ411x7h7&p=1&autoplay=0&high_quality=1` |
| 带分 P | 同上 `?p=2&spm_id_from=333.788` | 同上，`p=2` |
| 手机版 | `m.bilibili.com/video/BV…` | 同视频页 |
| av 号 | `bilibili.com/video/av170001` | `?aid=170001&p=1&…` |
| 已经是播放器 | `player.bilibili.com/…?bvid=…&page=1&danmaku=0` | 归一化后与视频页一致 |
| 官方 iframe 整段 | `<iframe src="//player.bilibili.com/…&p=3">` | `p=3` |

抖音、腾讯视频原样返回并标 `confirmed: false`；YouTube/Vimeo 能转但同样标
未确认（国内网络打不开）。离线模式下 b23 短链**直接报错而不是静默返回原链接** ——
短链塞进 iframe 是放不出播放器的，静默失败等于给老师一个空白框。

**zip 安全闸**：`../../etc/passwd`、绝对路径、超过 2000 个条目、不是 zip、
空包，五种都是 400。macOS 的 `__MACOSX/._x` 资源分叉被忽略。图片相对路径
逃出压缩包（`../../../etc/passwd`、`/etc/passwd`、`https://…`）一律拿不到东西。

**虚拟助教**：断句、念不出来的内容（代码块/图片/表格/分隔线）被跳过、
超长句按逗号切、段末停顿、Markdown 标记洗掉、短讲稿明文 `j=` 长讲稿 gzip `s=`、
编码解码往返、同一份讲稿每次生成的链接完全一致（gzip `mtime=0`）、
页面地址三层取值顺序、非 http 地址报错、
**embed 节点原样保留链接不做任何归一化**（hash 一动讲稿就没了）。

**导入导出真跑一遍**（SQLite）：一个含「内容页 + 整页嵌入 + PDF 占位 + 一张图」
的 zip 导进去，验证章节名剥掉了序号前缀、页面节点是
`heading/paragraph/bulletList/blockImage/calloutInfo`、发布状态沿用 front matter、
PDF 逐条进 `skipped` 而不是静默丢、缺图只记警告不让整页失败、
再导出来 README 有目录和「只能还原内容页和整页嵌入」的说明、
导出的包再解析回去结构一致、课程不存在报 404。

---

## 1b. 前端自动化测试与类型检查

```sh
cd apps/web
bun install --frozen-lockfile
bun test tests            # 275 pass / 0 fail（其中本分支新增 12 条）
bunx tsc --noEmit
```

新增 `tests/ext/content-tools-paste.test.mjs`，12 条覆盖粘贴规则的触发条件。
这个判断错了有两种后果、都很难被发现：放宽了会把老师正常的文字粘贴吃掉，
收紧了功能等于没做。所以专门测它。

命中：六种 bilibili 形态、官方 iframe 整段、首尾空白、抖音/腾讯/YouTube。
不命中：非视频站链接、**bilibili App 的分享文案**（`【某某公开课】 链接 分享自B站`，
吃掉的话老师的文案就没了）、多行内容、正文里恰好提到 bilibili、
不带协议头的裸域名、`javascript:` 伪协议、空内容、不含视频站的 iframe。

整套 bun test 里的 `rtl-guard.test.mjs` 会扫全仓库的物理方向 class，它过了，
说明本分支的新组件没有写 `ml-/pl-/text-left` 这类禁用写法。

`bunx tsc --noEmit` 在本分支新增的四个前端文件上零报错。全仓库确实有若干
`Cannot find module 'public/*.png'`，那是直接跑 tsc（不经 next build）时的
图片模块解析问题，干净树上同样存在。

---

## 2. 手工验的两件事

### b23.tv 短链真解析（联网）

`resolve_b23_link` 只读 Location 头，绕过系统代理，最多跟 3 跳。真跑：

```
短链   : https://b23.tv/BV1GJ411x7h7
跳转到 : https://www.bilibili.com/video/BV1GJ411x7h7
播放器 : https://player.bilibili.com/player.html?bvid=BV1GJ411x7h7&p=1&autoplay=0&high_quality=1

短链   : https://b23.tv/av170001
跳转到 : https://www.bilibili.com/video/av170001
播放器 : https://player.bilibili.com/player.html?aid=170001&p=1&autoplay=0&high_quality=1
```

自动化测试里这一跳是打桩的（`monkeypatch` 掉 `resolve_b23_link`），只验后半程的
归一化，避免测试依赖外网。

### 二维码编码器与第三方库逐格比对

`qrgen.py` 是纯标准库手写的（byte 模式 / 纠错等级 M / 版本 1–10），没有第三方依赖。
为了确认它算得对，在项目外的临时 venv 里装了 `qrcode==8.2`，同版本同掩码逐格比对：

| 内容 | 版本 | 掩码 | 尺寸 | 差异格数 |
|---|---|---|---|---|
| `https://learn.example.com/signup?code=ABCD1234` | 4 | 2 | 33×33 | 0 |
| `先进智造学堂 注册链接` | 3 | 6 | 29×29 | 0 |
| `a` | 1 | 5 | 21×21 | 0 |
| `x` × 180 | 9 | 0 | 53×53 | 0 |
| `https://sam.sysu.edu.cn/signup?invite=INV-2026-0001` | 4 | 5 | 33×33 | 0 |

五个用例、四个版本，**全部逐格一致，连自动选出来的掩码号都一样**。
第三方库没有装进 `apps/api`，只在 `scratchpad` 的一次性 venv 里用过。

测试里另有一个独立的回读解码器（去掩码 → 之字形取数据位 → 解 byte 模式载荷），
不依赖任何库，掩码、格式信息、码字交织哪一步错了都会露出来。

---

## 3. 接口

挂载前缀 `/ext/content`（由骨架代理在 `routers/ext/__init__.py` 里挂）。
**教师身份闸是挂载时统一加的**，本模块的路由不再各自判角色；课程级权限落在
上游 service 的 `check_resource_access`，越权拿不到 200。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/courses/{course_uuid}/import-md` | multipart zip → 建章节/页面/上传图片 |
| GET | `/courses/{course_uuid}/export-md` | → zip 下载 |
| POST | `/embed/resolve` | `{url}` → `{embed_url, provider, confirmed, source_url}` |
| POST | `/activities/{activity_uuid}/avatar` | `{script, title?, page_url?}` → 页尾追加虚拟助教 |
| GET | `/avatar/config` | 读页面托管地址与它的来源层 |
| GET | `/qr.svg?text=` | SVG 二维码 |

短链解析是同步 urllib，在 async 路由里走 `run_in_threadpool`，不阻塞事件循环。

### 导入 zip 的三条硬上限

| 项 | 上限 |
|---|---|
| 压缩包本身 | 50 MB |
| 解压后总大小 | 200 MB |
| 条目数 | 2000 |
| 单张图片 | 20 MB |

超了一律 400，不静默截断。全程在内存里处理，不往磁盘解压。

### 虚拟助教页面地址的取值顺序

组织配置的 `ext` 段 → 环境变量 `LEARNHOUSE_EXT_AVATAR_PAGE_URL` → 内置默认值
`https://blog.sysu-sam.com/@zhuyizhang/lh-avatar`。返回值里的 `source` 字段说明
这次是从哪一层取到的。

组织配置读的是 `organizationconfig` 表的 `config` 列（一个自由 dict），
不是 `Organization` 表 —— 那张表根本没有 config 字段。走自由 dict 的好处是
部署方加的 `ext` 段不会被上游的 pydantic 模型剪掉。**但目前还没有任何 UI 能写这个
字段**，所以实际生效的是环境变量和默认值这两层；等骨架或作业工具定下组织设置
ext 段的写入口，这一层自动就活了，代码不用改。

---

## 4. 前端

### 编辑器粘贴视频链接

`components/Objects/Editor/Extensions/SysuBilibiliPaste/`。挂进
`Editor.tsx` 的扩展数组，用 `SYSU-SAM` 注释包住。

触发条件刻意做得很窄，避免误伤正常粘贴：剪贴板里**只有一条**链接（去掉首尾空白后
不含任何空白字符），且指向认识的视频站点；或者是一整段 `<iframe …>` 嵌入代码。
其余情况一律交回 TipTap 默认行为。有文件的粘贴让给 `PasteFileHandler`。

**优先级 1000**（默认 100）。必须压过 Link 扩展 —— TipTap 的 Link 默认
`linkOnPaste: true`，会抢先把链接变成超链接文本。ProseMirror 按插件顺序问
`handlePaste`，TipTap 按扩展 priority 从高到低排插件。

解析失败回落成普通链接 + 错误 toast，不让老师白粘一次。站点标了
`confirmed: false` 时插入照常，但给一句「这个站点没实测过，请自己预览一下」。

**已知行为**：解析要走一次后端往返（约 1 秒），播放器插在**回来那一刻的光标位置**，
不是粘贴时的位置。老师在这一秒里移动光标或打字，播放器会落在新位置。
这和仓库里已有的 `PasteFileHandler`（图片/视频/PDF 粘贴上传）是同一个行为，
为保持一致没有改。

**渲染端确认**：`EmbedObjectsComponent.tsx` 对非 YouTube 地址是
`src={embedUrl}` 原样透传，不做 URL 重建，所以虚拟助教链接 hash 里的讲稿不会被剪掉。

### 邀请码二维码

`components/SysuTools/tools/content/InviteQrButton.tsx`，挂在
`OrgAccess.tsx` 邀请码表格每一行的「注册链接」那一格里，用 `SYSU-SAM` 注释包住。
弹窗显示二维码 + 注册链接全文 + 下载 SVG。

二维码是 fetch 后端接口拿到 SVG 文本再内联渲染的，**不是** `<img src="…/qr.svg">` ——
那个接口要 Bearer token，`<img>` 带不了，会 401 出一个碎图。

---

## 5. lint 基线（重要）

`bun run lint:strict` 在**未改动的 sysu-sam 上就是失败的**：

```sh
cd apps/web && bun install --frozen-lockfile && bun run lint:strict
```

| 树 | 结果 |
|---|---|
| 骨架分支原样 | ✖ 943 problems (35 errors, 908 warnings) |
| 本分支 | ✖ 944 problems (35 errors, 909 warnings) |

**error 数一个没涨**，那 35 个全在上游文件里（analytics 图表组件、Boards 拖拽
hook、`services/courses/transfer.ts` 等）。

多出来的 1 个 warning 交代清楚：它在 `Editor.tsx`，规则是 `react-hooks/refs`。
这个文件基线上就有 40 条同规则的告警 —— 它把 session / activity 包成 ref 再用
`getAccessToken()` 这样的 callback 读，规则会对**每一个用到该 callback 的地方**
各报一条。上游自己的 `PasteFileHandler.configure({ getAccessToken })` 就占了一条，
我的粘贴扩展复用同一个 accessor，于是多一条。

不绕开它是有理由的：改成把 token 当普通值传，就得把它加进扩展数组的 `useMemo`
依赖，session 刷新时整个编辑器扩展会重建。为了少一条告警去换一个真的会闪的编辑器，
不划算。org id 那个参数确实是按普通值传的（`orgId: sysuOrgId`），因为它是个数字、
不会频繁变。

**我自己新写的文件全部 0 问题**，可以单独复核：

```sh
cd apps/web && bunx eslint components/SysuTools \
  components/Objects/Editor/Extensions/SysuBilibiliPaste \
  services/ext lib/query/keys.ts "app/orgs/[orgslug]/dash/tools"
# 无输出
```

「lint:strict 必须过」这条验收标准在当前基线上没人能满足。已同步给 team-lead，
建议要么由集成代理统一修掉这 35 个 error，要么把标准改成「不新增 error」。

---

## 6. 范围决定：作业导出只留占位

skill 的 `export-md` 会把作业的题目和参考答案一起渲染成 Markdown。本次**没有移植
这一段**，作业活动只导出一个占位 md 并在 README 的「导出时的提醒」里逐条列出。

理由：作业的题目结构、学期复用、克隆复制是作业工具（assign-tools）那条线的范围，
两边各写一份读取逻辑迟早会漂。导出包里说明了「作业请用作业工具里的学期复用功能搬」。

这是一个主动的范围决定，不是漏做。如果需要补，接口和目录约定都留着位置，
在 `transfer.py` 的 `TYPE_ASSIGNMENT` 分支加就行。

---

## 7. 还没验的

以下几项**没有跑过**，等骨架合入、工具页做完之后补，截图放
`docs/sysu-sam/QA/content/`：

- 本地预发环境上真起前后端，在编辑器里真粘一条 bilibili 链接，断言出现
  `blockEmbed`（playwright）。粘贴规则的**匹配条件**已有 12 条 bun 单测覆盖，
  但「真的插进了编辑器、真的压过了 Link 的 linkOnPaste」只能在浏览器里验
- 工具页三个 Tab（导入 Markdown / 导出 Markdown / 虚拟助教）的端到端
- 邀请码页二维码弹窗的端到端与截图
- 虚拟助教追加到真页面后，学生端活动页里那个 iframe 真的能出声
- 导入一门带真图片的课，确认图片在存储层落盘并在页面里显示
- 抖音、腾讯视频的 iframe 在浏览器里到底能不能渲染（目前一律标 `confirmed: false`，
  就是因为无头浏览器里没渲染出来，需要人工看一眼）
