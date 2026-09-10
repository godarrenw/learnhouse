# 内容工具 · 验收记录

分支 `feat/content-tools`。覆盖 Markdown 导入导出、编辑器粘贴 bilibili 链接、
虚拟助教、邀请码二维码四件事。

本文只记**真跑过**的结果。没跑的一律写在最后「还没验的」一节里，不含糊过去。

---

## 1. 后端自动化测试

```sh
cd apps/api
uv sync
uv run pytest src/tests/ext -q
uv run ruff check src/services/ext src/routers/ext src/tests/ext
```

| 项 | 结果 |
|---|---|
| pytest（`src/tests/ext` 全量，含骨架与学情的用例） | 165 passed |
| ruff | All checks passed |

本分支贡献 109 条：96 条纯逻辑（不碰库不碰网），13 条用 conftest 的内存 SQLite
真跑 service 调用（导入导出往返 7 条、虚拟助教追加 6 条）。

**greenlet 已经修好了。** 原先 `uv sync` 装不上它（marker 在 Apple Silicon 的
macOS 上把它跳过），而 SQLAlchemy 的 async 引擎运行时必须要它，症状是所有碰
数据库的测试报 `ValueError: the greenlet library is required`、纯逻辑测试却全过，
看起来像"某几个测试写坏了"。现在 `greenlet>=3.3.1` 已经显式钉进
`apps/api/pyproject.toml`，`uv sync` 一次就有，**不用再加 `--no-sync`**。
跑法和说明也写进了 `docs/sysu-sam/DEVELOPING.md`。

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

### 安全相关的三处（集成审查要求）

**一、短链跳转白名单。** `resolve_b23_link` 是**服务端**发起的请求，跟的是第三方
返回的 Location。一条被做过手脚的短链可以把服务端引到内网地址上去（SSRF）。
现在入口地址和**每一跳**都必须落在 `b23.tv` / `bilibili.com` / `m.bilibili.com` /
`www.bilibili.com` / `player.bilibili.com` 或它们的子域上，跳出去就中止并报错。
测试钉死了两件事：子域算通过（`space.bilibili.com`），而 `bilibili.com.evil.com`
这种后缀相似但不是子域的**不算**通过；`127.0.0.1`、`169.254.169.254`、`localhost`
一律拒。另有一条打桩测试模拟"第一跳被引到元数据服务地址"，断言中止。

**二、zip 解压大小按实际字节计。** 原来用 `ZipInfo.file_size` 预检总大小，
但那是压缩包自己写的数字 —— 伪造成 1 就能绕过闸门，然后 `zf.read()` 一把把几个 G
解进内存（zip 炸弹）。现在改成 `zf.open()` 流式读、边读边数，超出剩余额度立刻中止。
两条测试：一条把上限临时调小验证按实际字节计，一条确认伪造的 `file_size` 骗不过去。

**三、导出按课程 update 权限判，不按 read。** 导出包里含作业的**参考答案**，
能拿到答案的人必须是能改这门课的人，"能看这门课"不够。

### 导入节流：把「上千页打爆连接池」降级成「慢但不崩」

**问题**：上游 `update_activity` 每写一次 content 就
`asyncio.create_task(_trigger_course_embedding(...))` 重建向量索引，而**那个任务
自己新开一个 db session**。导入 N 个页面就是 N 个 session 一起抢连接池，
而池子是 5 + 10。导一门几十页的课没事，页数一多必然打满，症状是后续请求全 500 ——
表现得像鉴权坏了，很难往「导入把连接池占光了」上想。这个坑是我在跑 e2e 时
真踩到的（见下面「坑二」）。

**做法**：上游没有留跳过索引的开关，但它把在飞的任务放在模块级的
`_embedding_tasks` 集合里，那是唯一能观测到并发度的地方。所以每写完一页就把
在飞的任务数压回 `MAX_INFLIGHT_INDEX_TASKS = 3` 以下，压不住就 `asyncio.wait`
等它跑完几个。取 3 是给同时进来的正常请求留余量。

**上游哪天把这个私有变量改名了怎么办**：`getattr` 拿不到就退回按页数节流
（每 10 页歇 0.5 秒），不会炸。另有一条测试专门断言「现在还能读到那个集合」，
它一挂就说明节流退化成了兜底，该去看上游改成什么了。

**实测（100 页）**

| 项 | 值 |
|---|---|
| 页数 | 100（5 章 × 20 页，合成包 35 KB） |
| 耗时 | 94.1 秒 |
| 每页平均 | 0.94 秒 |
| 连接池报错 | 0 |
| 5xx 响应 | 0 |

复现方式：合成一个 100 页的 zip 打到
`POST /api/v1/ext/content/courses/<uuid>/import-md?org_id=1`，跑完把建出来的
5 个章节和 100 个活动删掉。**慢是预期的** —— 节流就是拿时间换稳定，
一页一秒对「一学期导一次」这个使用频率是可以接受的。

没有做「关掉节流跑一遍作对照」：那等于再把共用的本地库打爆一次，
上一次已经影响到别的代理了。失败形态的证据在下面「坑二」里有实录。


### 作业导出（完整版）

`services/ext/content_tools/assignments_md.py`。**故意不复用作业工具的模块** ——
那条线还在动，互相 import 会把两个功能的发布节奏绑死。这里只读 `assignment` 和
`assignmenttask` 两张上游表。

六种题型各有渲染分支：选择题（列选项并标出正确项，超过 26 个选项退回数字标号）、
填空题、简答题（含匹配方式）、数值题（含单位与容差）、编程题（初始代码 + 参考解法）、
文件提交（说明没有标准答案）。认不出的题型不炸，写一句"请到网页上查看"。
没填答案的说"没有填参考答案"而不是留空；题干整个是空的（本地库里就有这种数据）
写一句"这道题还没有录入内容"，免得老师以为导出坏了。

正文最上方有一行 `> [!warning]` 说明这份导出含参考答案、发给学生前先删。
README 里也单列了一节。**反向导入仍不还原作业**，README 指向作业工具的学期复用。

真实数据核对过：本地库里那份「第一次作业：数字孪生案例分析」（2 道题）用真表行
渲染了一遍，标题、描述、截止时间、计分方式、发布状态、每题的题型标签与满分都对；
`_assignments_by_activity` 也正确地把 `activity_id=9` 映射到了这份作业。
那两道题的 `contents` 在库里就是 `{}`，所以走的是"还没有录入内容"分支 —— 不是解析失败。


---

## 1b. 前端自动化测试与类型检查

```sh
cd apps/web && bun install --frozen-lockfile
bun test tests            # 275 pass / 0 fail（其中本分支新增 12 条）
bunx tsc --noEmit -p .    # exit 0
cd ../e2e && bun run typecheck   # exit 0
```

**跑 tsc 之前 `apps/web/next-env.d.ts` 必须存在**（`next dev` / `next build` 会生成，
它被 gitignore）。缺了会冒出二十几个"找不到 public/*.png 模块"的假报错，
和本分支无关但很唬人。

新增 `tests/ext/content-tools-paste.test.mjs`，12 条覆盖粘贴规则的触发条件。
这个判断错了有两种后果、都很难被发现：放宽了会把老师正常的文字粘贴吃掉，
收紧了功能等于没做。所以专门测它。

命中：六种 bilibili 形态、官方 iframe 整段、首尾空白、抖音/腾讯/YouTube。
不命中：非视频站链接、**bilibili App 的分享文案**（`【某某公开课】 链接 分享自B站`，
吃掉的话老师的文案就没了）、多行内容、正文里恰好提到 bilibili、
不带协议头的裸域名、`javascript:` 伪协议、空内容、不含视频站的 iframe。

整套 bun test 里的 `rtl-guard.test.mjs` 会扫全仓库的物理方向 class，它过了，
说明本分支的新组件没有写 `ml-/pl-/text-left` 这类禁用写法。

`bunx tsc --noEmit -p .` 与 `apps/e2e` 的 `bun run typecheck` 都 exit 0。
这一条必须过：push 到 sysu-sam 会触发镜像构建里的 `next build`，
一个类型错误就能把全组的构建带红，而 eslint 不做类型检查。

---

## 1c. 端到端（本地预发环境，真跑）

- 环境：本地复刻栈 learnhouse-local（Postgres/Redis 经 socat 转到 15432 / 16379），
  后端从源码起在 :9002，前端 dev 在 :3002
- 日期：2026-09-10
- 账号：管理员 user1@example.local；普通成员 user2@example.local（均已脱敏）

```sh
cd apps/e2e
E2E_SKIP_BOOT=1 \
E2E_BASE_URL=http://localhost:3002 \
E2E_API_URL=http://localhost:9002/api/v1 \
E2E_ADMIN_EMAIL=user1@example.local E2E_ADMIN_PASSWORD='…' \
E2E_STUDENT_EMAIL=user2@example.local E2E_STUDENT_PASSWORD='…' \
bun run test features/ext --workers=1
```

`--workers=1` 不是必须，但并行跑的时候几个用例会抢同一门课的数据，
串行更容易复现问题。

**14 passed**（骨架 6 条 + 学情 3 条 + 内容工具 5 条）。rebase 到最新 sysu-sam
之后重跑过一遍，学情那三条没被影响。截图在 `docs/sysu-sam/QA/content/`。

| 用例 | 验到了什么 | 截图 |
|---|---|---|
| 四个分段都能切开 | 导入 / 导出 / 虚拟助教 / 说明 都渲染出来 | 01–04 |
| 导出再导回去 | 下载出真名 zip → 喂回导入 → 章节数和页面数都 > 0，跳过项每条都有理由 | 05 |
| 编辑器粘贴 | 粘一条 bilibili 视频页链接 → 出现 `player.bilibili.com` 的 iframe | 06 |
| 虚拟助教 | 追加成功 → 学生端那一页里有 `lh-avatar` 的 iframe，且 hash 里讲稿还在 | 08、09 |
| 邀请码二维码 | 弹窗画出 SVG，且写出了带 `inviteCode=` 的注册链接 | 07 |

**用例不留痕**：导入建出来的**活动和章节**都在 `finally` 里删掉，虚拟助教改过的
页面内容和发布状态也在 `finally` 里还原。跑完再查库，章节数和活动数与跑之前
完全一致。这条不是洁癖 —— 见下面「跑测试时踩的坑」的第一、四条。

### 跑测试时踩的四个坑

**一、导出再导入同一门课会指数级膨胀。**
第一版用例是「导出这门课 → 原样导回这门课」，而导入一律**新建**章节，
于是每跑一次章节数翻一倍。跑了三轮之后，「电脑维修从入门到精通」从 7 个章节
涨到 **896 个**、2667 个活动，把本地复刻库拖垮了。已经用一条按课程 + 创建时间
限定的事务清理干净（删前确认过这 2667 个活动没有一个挂在要保留的 7 个章节上），
课程回到 7 章 21 个活动的原样。用例现在会在 `finally` 里删掉自己建的章节。

**二、连接池被打满。**
膨胀之后跑导出导入，后端报
`QueuePool limit of size 5 overflow 10 reached`，随后 `/orgs/slug/default` 和
`/users/session` 全 500，前端退化成「选择一个组织以继续」，看起来像登录失效。
根因是 `update_activity` 每次带 content 都会起一个后台任务重建向量索引，
而那个任务**自己新开一个 db session**；导入 N 个页面就并发 N 个 session。
课程正常大小（21 个页面）时不会触发，膨胀到几千个页面时必然打满。
**这是导入功能在超大课程上的一个真实上限，写在下面「已知问题」里。**

**四、删章节不会删活动，我一度报了个假的「零残留」。**
第一版收尾只调了 `DELETE /chapters/{id}`，章节数确实回到了原样，
于是我以为库是干净的。实际上删章节只断开 `chapteractivity` 的关联，
**活动本身还挂在课程上变成孤儿**：那门课的章节数一直是 7，活动数却从 21 涨到了
247。已经把 226 个孤儿活动连同它们的块和版本一起清掉，课程回到 7 章 21 活动；
用例改成**先删活动再删章节**（顺序反了活动就找不着了），重跑后查库确认真的零残留。

这条比前三条更值得记：假的「已清理」比明摆着的脏数据更危险，
因为没人会再去查一遍。

**三、跨源时 Content-Disposition 和统计头读不到。**
前后端不同源（3002 对 9002）时，浏览器默认只让 JS 读几个 simple header，
`Content-Disposition` 和我自己加的 `X-Export-*` 全部读不到，**而且不报任何错**：
表现是下载的文件名变成兜底的 `course.zip`、统计数字全是 0。
全局 CORS 中间件（`src/core/middleware/cors.py`）没有配 `expose_headers`，
那是上游共用代码，所以改成在导出这条响应上单独声明
`Access-Control-Expose-Headers`。用例里加了一条断言：文件名不能是兜底值。

### e2e 里发现并修掉的两个功能缺陷

1. **还没写过正文的内容页加不了虚拟助教。** 新建的内容页 `content` 存的是 `{}`，
   既不是 doc 也不是别的。原来的实现按 content 长相判断，把这种页面当成
   「不是内容页」拒掉 —— 而这恰恰是老师最想加虚拟助教的场景（新建一页只放一个
   数字人）。改成按活动类型判断，并给这条加了单测。
2. **粘贴扩展压不过 Link。** 原来 `priority: 1000`，但
   `@tiptap/extension-link` 自己声明的就是 1000，打平按数组顺序排，Link 在前面。
   它选区为空时会让路（所以光标状态下一直是好的），但**选中一段文字再粘链接时
   会被它接管**。改成 1100。

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

在骨架的 `routers/ext/__init__.py` 里注册为 `("content_tools", "/content")`，
实际路径是 `/api/v1/ext/content/*`，六个接口挂载后都验过在。

权限两道门。组织级用骨架的 `deps.require_teacher`（Admin / Maintainer /
Instructor）——**它把 org_id 声明成 query 参数，所以这些接口调用方都要带
`?org_id=<id>`**，漏了直接 422。课程级由业务层再收窄：建章节、建活动、写内容、
传图片最终都会落到上游 service 的 `check_resource_access`，导出也在服务层显式
查了一次 READ，越权拿不到 200。

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

三层回退走骨架的共用模块 `src/services/ext/config.py` 的 `get_ext_config`，
不再自己写一套：组织配置的 `ext` 段 → 环境变量 `LEARNHOUSE_EXT_AVATAR_PAGE_URL`
→ 内置默认值 `https://blog.sysu-sam.com/@zhuyizhang/lh-avatar`。
接口返回的 `source` 字段说明这次是从哪一层取到的，配错了知道去哪儿改。

前端用共用的 `getExtConfig(org, 'avatar_page_url', '')`，读到就直接用、读不到才去问
后端。**前端读不到环境变量**，所以这个地址应当写进组织配置的 ext 段；只设环境变量
的话后端能用、前端界面上显示不出来。

`avatar.py` 现在是纯函数模块（切句、编码、`normalize_page_url` 校验），
不碰数据库；地址解析在 `activities.resolve_avatar_page_url`。

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

### 工具页

`components/SysuTools/tools/Content/ContentTools.tsx`，注册表里 key 是 `content`，
`courseScoped: true`（选课下拉由路由页统一渲染，工具自己不再写一个）。

内部四个分段用本地 state 而不是路由段：外层 Tab 条已经被「工具之间切换」占用，
再嵌一层会让面包屑和命令面板都变复杂。

| 分段 | 做什么 |
|---|---|
| 导入 Markdown | 拖拽或点选 zip，前端先挡掉非 zip 和超过 50 MB 的；结果摘要给三个数字，并**逐条列出**没还原的内容与需要人工确认的告警 |
| 导出 Markdown | 下载压缩包，显示章节/文件/图片/提醒四个计数；页面上直接写明导出是有损的 |
| 虚拟助教 | 选一个富文本内容页（视频、PDF、作业会被滤掉，本来也追加不了）→ 写讲稿 → 追加，结果里给预览链接和「已自动存了一版可以回滚」的说明 |
| 说明 | 四条：编辑器粘贴、邀请码二维码、导入导出的边界、虚拟助教的原理 |

导出和二维码这两个接口都要 Bearer token，所以不能 `window.open` 一个链接或者
`<img src>` —— 那样带不了 header，会 401。一律 fetch 成 Blob / 文本再用。

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

## 7. 已知问题与还没验的

### 已知问题

**超大课程导入会打满连接池。** 见上面「坑二」。上游 `update_activity` 每写一次
content 就起一个后台任务重建向量索引，那个任务自己新开 db session，导入 N 个页面
就是 N 个并发 session，而池子是 5 + 10。正常规模的课（几十个页面）跑下来没问题，
上千个页面会把后端打到 500。没有在本次范围内修，因为要动的是上游的索引任务，
影响面比内容工具大得多。真要用它导一门超大课，建议先分批或临时调大池子。

**导入不覆盖，所以重复导入会得到重复章节。** 这是有意的设计（不冲掉老师手改过的
内容），但界面上只写了「章节和页面一律新建」，没有做「同名章节合并」或者
「导入前预览差异」。老师连点两次会得到两份，需要自己删。

### 还没验的

- 抖音、腾讯视频的 iframe 在真实浏览器里到底能不能渲染。目前一律标
  `confirmed: false`，就是因为无头浏览器里没渲染出来，需要人工看一眼
- 虚拟助教**真的出声**。e2e 只验到学生端那一页里有正确的 iframe、hash 里讲稿还在；
  语音合成要真人开着音箱听
- 导入一门**带真图片**的课，确认图片落到存储层并在页面里显示。本地复刻库里
  手边这几门课的内容页没有图片块，单测里是打桩验的
- 生产环境上的表现。按第三阶段的规矩，本阶段没有碰过生产
