# QA：重媒体签名 URL + 隧道媒体分流

日期：2026-09-10 ｜ 分支 `feat/tunnel` ｜ 环境：本地预发 `/Volumes/D/code/learnhouse-local`
**全程没有触碰生产 NAS、Cloudflare 隧道配置、DNS。** 本地预发那五个容器一个没动。

## 这次要证的那一格

集成审查指出：单租户模式下 `LH_access` 恒为 host-only cookie，302 到媒体域名后
**非公开课程**的媒体必然 401/403，而 `<video>` / `<iframe>` 又发不出 `Authorization` 头。
方案改成限时签名 URL 之后，必须实证的是：

> **非公开课程 + 已登录用户 + 不带 cookie 的跨主机名请求 → 视频 / PDF 取得到。**

下面全部结果都是真实执行的，命令与输出照抄。

## 怎么搭的

| 件 | 做法 |
|---|---|
| 后端 | 从源码起（带本次补丁），`uvicorn app:app --port 9007`，连本地栈的 Postgres / Redis |
| 前端 | `bun run dev -p 3007`，`.env.local` 指向 `localhost:9007` |
| 「媒体域名」 | `http://127.0.0.1:9007` |
| 测试数据 | 现场新建的一门**非公开课程**（`public=false`）+ 一个真实视频活动 |

**媒体域名故意换主机名而不是换端口。** cookie 不区分端口 —— 用
`localhost:9007` 当媒体域名的话，浏览器照样会把 `localhost` 的 cookie 发过去，
测出来的「通过」是假的。换成 `127.0.0.1` 才是真正的 host-only 隔离。

本地栈的 Postgres / Redis 没有对宿主机暴露端口，复用了另一个代理已经建好的两个
socat 转发容器（`lh-db-fwd-15432` / `lh-redis-fwd-16379`），没有新建也没有删除它们。

不动任何现有课程的 `public` 位（其他代理在用），而是新建一门测试课，验完删掉。

## 一、后端矩阵（curl，无浏览器）

测试对象：非公开课程 `course_bfeda618…`（`public=false`），
视频活动 `activity_90f2bf5e…`，文件 16996 字节。

| # | 场景 | 期望 | 实测 |
|---|---|---|---|
| A1 | 非公开 + 匿名 + 无签名，`/api/v1/stream/video/…` | 拒绝 | **403** ✅ |
| A2 | 非公开 + 匿名 + 无签名，`/content/…/video/…` | 拒绝 | **401** ✅ |
| B | 匿名调 `GET /ext/media/sign` | 401 | **401** ✅ |
| C | 已登录调 `/ext/media/sign`，一次签两条路径 | 200 + 两条签名 | **200**，返回 `sig`(64 hex) / `exp` / `uid=1` ✅ |
| **D1** | **非公开 + 无 cookie + 有效签名，stream** | **200** | **200** ✅ |
| **D2** | 同上 + `Range: bytes=0-1023` | 206 | **206**，`content-range: bytes 0-1023/16996` ✅ |
| **D3** | **非公开 + 无 cookie + 有效签名，`/content/`** | **200** | **200**，`video/mp4`，16996 字节 ✅ |
| **D4** | 同上 + `Range: bytes=0-511` | 206 | **206**，`content-range: bytes 0-511/16996` ✅ |
| E1 | 把 `uid` 改成 2 | 拒绝 | **401** ✅ |
| E2 | 把 `exp` 往后推 1 小时 | 拒绝 | **401** ✅ |
| E3 | 拿 stream 的签名去访问同课程的 `/content/` | 拒绝 | **401** ✅ |
| F | 真过期的签名（TTL 60s，签发时间回拨 1 小时） | 拒绝 | **401** ✅ |
| G1 | **公开**课程 + 匿名 + **不签名**，`/content/` | 200 | **200** ✅ |
| G2 | 公开课程 + 匿名 + 不签名，stream | 200 | **200** ✅ |

D 组就是之前缺的那一格：**非公开课程，一个 cookie 都没有，仅凭签名，视频和 PDF
都取得到，而且 Range 正常** —— 这是播放器 seek 能用的前提。

G 组同样重要：没启用媒体域名时行为一字未变，公开课程仍然匿名可取。

### 一个需要说明的观察

单独试了「把签名参数挂到一个**不在白名单**的接口上」：

```
GET /api/v1/users/profile?sig=…&exp=…&uid=1   -> 200
```

`200` 不是漏洞。对照实验：**完全不带任何参数、匿名请求同一个接口也是 200**，
而且两次返回的都是 `{"id":0,"user_uuid":"user_anonymous","username":"anonymous"}`。
也就是说这个上游接口本来就允许匿名访问，而**签名在那里没有产生任何效果**，
身份仍然是匿名 —— 这正是设计意图：签名只在两个被打了补丁的媒体路由里换主语，
不会变成一张通用的身份凭据。

## 二、浏览器契约（Playwright + Chromium）

在**真实登录后的页面**里跑完整链路，验的是 hook 依赖的那套契约。

| 项 | 实测 |
|---|---|
| 登录后落点 | `http://localhost:3007/home` ✅ |
| 页面调 `/ext/media/sign`（同源，带 cookie） | **200** ✅ |
| 签名后的地址主机名 | **`127.0.0.1:9007`**（确实换到了媒体域名） ✅ |
| 跨源取媒体，`credentials: "omit"` | **200**，`video/mp4`，**16996 字节** ✅ |
| 同上 + `Range: bytes=0-999` | **206** ✅ |
| 对照：**不带签名**取同一条媒体 | **403** ✅ |
| 对照：**带 cookie 但不带签名** | **403** ✅ |

最后两行是这套方案存在理由的直接证据：**即使浏览器被明确要求带上 cookie
（`credentials: "include"`），跨主机名之后服务端仍然判定为匿名并拒绝。**
host-only cookie 跟不过去这件事，到此不再是推断而是实测。

`content-range` 响应头在浏览器里读不到（值为 `null`），因为这套 dev 环境前面
没有 nginx 补 `Access-Control-Expose-Headers`。生产的 `nginx.prod.conf` 里
已经暴露了 `Content-Length, Content-Range, Accept-Ranges`，播放器能读到。
状态码 206 本身不受影响，seek 功能不依赖 JS 读这个头。

### 没测到的

**React 组件的渲染路径没有在浏览器里跑通。** 测试课程的课程页返回 404
（新建课程的前端路由形态没查清，试过带 / 不带 `course_` 前缀、发布与未发布都不行），
所以没能真的渲染出播放器、看到 `<video src>` 指向媒体域名。

替代证据是上面那套契约测试 —— 它把 hook 里的每一步（换签名 → 拼 URL → 跨源取媒体
→ Range）都在真实登录态下走了一遍，只是由页面脚本执行而不是由 React 组件执行。
组件接线本身由 `tsc --noEmit`（0 错误）和代码审查覆盖。

**这是这次留下的唯一缺口**，上生产前建议在预发环境用一门真实课程补一次。

## 三、单元测试

```
$ uv run pytest src/tests/ext/test_media_sign.py -q
........................................                                 [100%]
40 passed in 0.08s
```

覆盖：白名单（8 条该签的、13 条不该签的）、签名往返、默认 TTL、TTL 越界、
过期、篡改 path / uid / exp / sig、跨路径复用、query 参数缺失、换密钥后签名必须变。

`ruff check` 对 `src/services/ext`、`src/routers/ext`、`src/tests/ext`、
`local_content.py`、`stream.py`、`router.py` 全绿。

前端 `tsc --noEmit` 除仓库既有的 `public/*.png` 模块解析问题外 0 错误；
`eslint` 对六个改动文件 0 error（3 个 warning 都是 `VideoBlockComponent` 既有的）。

## 四、Chromium Local Network Access 实测

阶段二的 go/no-go 项，结论：**Chrome 152 下不阻断、不弹窗。**
方法与证据见 `deploy/TUNNEL_RUNBOOK.md` §3 第 5 条。要点：

- 测试页必须真的从**公网 IP** 下载才有意义。用 `--host-resolver-rules` 把假域名
  指到私网会让页面自己落进 private 空间，private→private 不触发 LNA，是假阴性。
  所以直接导航到已有的 `https://blog.sysu-sam.com/`（CF Pages）再注入子资源请求，
  **没有发布或修改任何内容**。
- 三种载体（`fetch(no-cors)` / `<video>` / `<img>`）都失败在
  `net::ERR_CERT_COMMON_NAME_INVALID`，即 TCP + TLS 已经握到校验证书那一步，
  请求确实到达了私网主机。LNA 拦截会在建立连接之前给出专门的 `ERR_BLOCKED_BY_*`。
- 把 LNA 相关特性用命令行强制打开，结论相同。

**顺带查实**：`media.sysu-sam.com` 目前**没有可用证书**（DSM 在 443 上用的是
别的名字的证书）。这是那个 `ERR_CERT_COMMON_NAME_INVALID` 直接证明的，
所以 RUNBOOK §5 的 acme.sh 签通配符证书是阶段二的**硬前置**。

## 五、清理

- 测试课程已删（`{"detail":"Course deleted"}`，复核取课程 404），连带章节与活动
- 上传的测试视频、投放到 `apps/api/content/` 的样本文件全部删除，该目录已恢复成只有 `__init__.py`
- `apps/web/.env.local` 与 dev server 顺手生成的 `AGENTS.md` / `CLAUDE.md` 已删
- 9007 / 3007 两个进程已停
- 本地预发五个容器全程 `healthy`，未受影响；另一个代理的两个 socat 转发容器保持原样

## 六、遗留风险

1. **签名 URL 泄露 = 有效期内可读那一条媒体路径**，身份是签名人。签名 URL 方案固有。
   缓解：绑死单路径、只读、默认 6 小时、路径白名单收窄。
2. **签名参数会进 nginx access log**，等价于短期凭据落日志。本期未处理，
   `nginx.prod.conf` 里写了提示，要处理就在 `log_format` 里对 `sig` 脱敏。
3. **换密钥会让所有在途签名立刻失效**，表现是正在看的视频下一次 seek 变 403，
   刷新页面即恢复。换 `LEARNHOUSE_EXT_MEDIA_SIGN_SECRET` 或 JWT secret 时要知道这点。
4. **React 渲染路径未在浏览器验证**，见「没测到的」。
5. LNA 今天不拦不代表以后不拦。首选缓解仍是设计文档 §9.3 的校园 DNS split-horizon。
