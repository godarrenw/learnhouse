# Cloudflare Tunnel + 媒体域名 上线手册

配套设计文档：`/Volumes/D/code/learnhouse-agent/TUNNEL_MEDIA_DESIGN.md`（结论与代码依据都在那里，本文只讲怎么做）
本地验证记录：`TUNNEL_LOCAL_TEST.md`
涉及文件：`extra/nginx.prod.conf`（两个 server 块）、`cf/` 下四个 Cloudflare API 脚本。
**compose 与 `.env` 都不用改** —— 隧道复用 NAS 上已有的 SZ_NAS，那个 cloudflared 容器
不在本 compose 里。

目标：`learn.sysu-sam.com` 走 Cloudflare Tunnel 对校外开放，NAS 不开任何公网入站端口；
视频 / PDF / 音频这类重媒体分流到只在校园网可解析的 `media.sysu-sam.com`，
既省 CF 流量、也避开自助版条款对视频分发的限制。

分两个阶段做，中间可以停。阶段一之后校外就能用了。

---

## 0. 需要用户提供的东西

**这些不到位就别开始。**

| # | 东西 | 状态 | 说明 |
|---|---|---|---|
| 1 | **Cloudflare 凭据** | ✅ 已就位 | `~/.learnhouse/cf.env`（权限 600），`cf/lib.sh` 读它。目前是 Global API Key |
| 2 | **DSM 管理员账号密码** | ⬜ 待提供 | acme.sh 的 `synology_dsm` 钩子把 media 证书装进 DSM 要用；开了两步验证还要 OTP 或信任设备，见 §5.2。**阶段二才需要** |
| 3 | **NAS 的 SSH / ContainerManager 访问** | ⬜ 待提供 | 跑 `deploy.sh`、看 `intelligent_mayer` 的日志、加 DSM 反代规则 |
| 4 | **一个无课时间窗口** | ⬜ 待安排 | 阶段一切 DNS 有 1~5 分钟解析切换；阶段二重建 nginx 约 10 秒 |
| 5 | **三条待核实信息的答案** | ⬜ 待确认 | 见 §0.1。第 (b) 条影响阶段二整体可行性 |
| 6 | **给老师的告知**（100 MB 上传限制） | ⬜ 待发 | 阶段一上线当天，文案见 §7 |

> ⚠️ **凭据卫生**：`cf.env` 里目前是 **Global API Key**，权限覆盖整个账号下所有 zone。
> 建议尽快换成限定范围的 API Token（`Zone:DNS:Edit` + `Zone:Cache Rules:Edit` +
> `Account:Cloudflare Tunnel:Edit`，zone 限定 sysu-sam.com），换完把 `cf/lib.sh` 里
> `cf_api` 的两个 `X-Auth-*` 头改成 `Authorization: Bearer`。
> 另外：**这个 Global Key 在本次准备过程中因为一次命令展开失败被打进了会话日志**，
> 建议到 CF 控制台 Roll 一次。

### 0.1 开工前先问清楚的三件事

**（a）DSM 反向代理转发到 8088 时保不保留原始 Host？**
在 DSM「控制面板 → 登录门户 → 高级 → 反向代理」看那条 learn 规则，或上线后在 nginx 日志里看 `$http_host`。
若 DSM 把 Host 改写成 `localhost` 或 IP，阶段二的 `server_name` 匹配会全部落到 learn 块，
分流静默不生效（不会成环，配置里用的是正向白名单）。真是这样就要在 DSM 侧把
「传递原始主机头 / Preserve Host」打开。

**（b）校内 Chrome 会不会弹「允许访问本地网络」？**
见 §3 第 5 条。**这条如果成立，会影响阶段二的整体可行性**，请在阶段二动手前实测一次。

**（c）校园 DNS 能不能做 split-horizon？**
如果学校网络中心愿意在校园 DNS 上把 `learn.sysu-sam.com` 解析到 `172.25.5.162`（校外仍走 CF），
那么校内全程走局域网、没有延迟损失、也没有 100 MB 上传限制，**整个 media 域名方案可以不做**。
这是技术上最优解，值得先问一句再动手。

---

## 阶段零：备份与开关确认（不改任何东西）

1. `learn` 那条 A 记录的原值 `deploy/cf/dns-switch.sh` 会在改动前自动备份成 JSON，
   不必再截图。当前值记录在案：**A `learn.sysu-sam.com` → `172.25.5.162`，
   灰云，TTL 300，id `567ab86655cbb8df2963776284ae9a1a`**。
2. NAS 上留一份 nginx 配置的时间戳副本：
   ```sh
   cp /volume1/docker/learnhouse/extra/nginx.prod.conf \
      /volume1/docker/learnhouse/extra/nginx.prod.conf.bak-$(date +%Y%m%d-%H%M)
   ```
   （目录里已经有一个 `.bak-20260910-1647`，别覆盖它。）
3. 跑一次 `sh /volume1/docker/learnhouse/backup.sh`，确认退出码 0、三份归档都在。
4. 确认仓库里 `extra/nginx.prod.conf` 顶部的总闸是 **off**：
   ```
   map $host $media_split_enabled {
       default  "off";
   }
   ```
   阶段一必须是 off，否则隧道一通就会把视频 302 到还不存在的 media 域名。

---

## 阶段一：把 learn 接进现有隧道

**不新建隧道、不新建容器、不改 compose、不改 nginx。** NAS 上已经有一个 cloudflared
容器（容器名 `intelligent_mayer`，镜像 `cloudflared:latest`，客户端 2024.11.1）在跑
隧道 **SZ_NAS**（id `f8b7e1c1-6077-4fc4-9a55-c4bc1678d325`），chat / wandb / overleaf
都走它，配置是 CF 远程托管的（`source=cloudflare`，改完自动下发，容器不用重启）。

learn 只要搭这趟车：给它的 ingress 加一条，再把 DNS 换成隧道 CNAME。两件事都写成了
脚本，放在 `deploy/cf/`，**不带 `CONFIRM=yes` 时只做只读预演**。

### 1.1 CF 侧准备（已完成）

这两项已经建好了，不影响任何现有流量，切换后即刻生效：

| 对象 | 值 | id |
|---|---|---|
| `media.sysu-sam.com` A 记录 | `172.25.5.162`，**灰云**，TTL 300 | `0638e5498ac79869bf9f72e199388795` |
| Cache Rule（Bypass） | 见下 | ruleset `130e45ebbb9a40799478387d5d1bd4ea` / rule `904d95075e004f69ba10142f7f6dd514` |

Cache Rule 的表达式**带了 `http.host` 限定**，只作用于 learn，不会波及同一个 zone 里的
chat / wandb / overleaf：

```
(http.host eq "learn.sysu-sam.com" and (starts_with(http.request.uri.path, "/content/")
 or starts_with(http.request.uri.path, "/api/")))
   -> set_cache_settings { cache: false }
```

它是必需的：后端对所有 `/content/` 内容都下发 `Cache-Control: public, max-age=86400`，
**包括非公开课程的图片**。橙云之后没有这条规则，CF 边缘会缓存并向任何拿到 URL 的人分发。

### 1.2 加 ingress

```sh
cd deploy/cf
./tunnel-add-learn.sh                  # 预演：打印改前 / 改后的 ingress 对照，不改任何东西
CONFIRM=yes ./tunnel-add-learn.sh      # 真改
```

它会：把当前配置原样备份到 `deploy/cf/backups/`（该目录已 gitignore）→ 若 ingress 里
已有 `learn.sysu-sam.com` 就直接退出（幂等）→ 在末尾那条 catch-all（`http_status:404`）
**之前**插入一条，其余条目一字不动 → PUT 回去 → 再 GET 一次确认 version 递增。

插入的规则：

```json
{ "hostname": "learn.sysu-sam.com",
  "service": "http://172.25.5.162:8088",
  "originRequest": { "httpHostHeader": "learn.sysu-sam.com" } }
```

`httpHostHeader` 是关键：不设的话源站看到的 Host 是 `172.25.5.162:8088`，
Next.js Server Actions 会拒绝 origin 与 x-forwarded-host 不一致的 POST。
后端是 HTTP，用不上 `noTLSVerify`。

**这一步做完还没有任何流量变化** —— DNS 还指着 172.25.5.162，隧道里那条 ingress
是闲置的。可以先做，第二天再切 DNS。

### 1.3 切 DNS（这一步才切流量）

```sh
CONFIRM=yes ./dns-switch.sh
```

把 `learn` 的「灰云 A → 172.25.5.162」换成「橙云 CNAME →
`f8b7e1c1-6077-4fc4-9a55-c4bc1678d325.cfargotunnel.com`」。用先删再建两步，
不用 PATCH 改类型。两步之间有几百毫秒空窗，正好在这一瞬刷新的用户会失败一次，
所以要在无课窗口做。

**建议前一天先把 A 记录 TTL 从 300 降到 60**（在 CF 面板改，或改完再跑脚本）：
这样万一要回滚，生效时间从 5 分钟缩到 1 分钟。降 TTL 本身不影响任何流量。

切完验一下：

```sh
dig +short learn.sysu-sam.com          # 应返回 CF 的公网 IP，不再是 172.25.5.162
dig @1.1.1.1 +short learn.sysu-sam.com # 换两个公共解析器各查一次，见下
dig @8.8.8.8 +short learn.sysu-sam.com
curl -sI https://learn.sysu-sam.com/ | head -5    # 应能看到 cf-ray 头
```

> ⚠️ **为什么要换解析器各查一次。** 删和建之间那几百毫秒里 `learn` 在 CF 权威上
> 是不存在的，返回 NXDOMAIN。**NXDOMAIN 会被递归解析器负缓存，时长取 SOA 的
> minimum（CF 默认 1800 秒），比 A 记录那 300 秒的 TTL 长得多。** 恰好在那个瞬间
> 查询过的解析器，最长半小时内都会认为 learn 不存在。
> 概率很低，但后果和普通的 TTL 等待不是一个量级，所以切完立刻多查几个解析器确认。
> 真踩到了只能等负缓存过期，或者联系那个解析器方清缓存 —— 没有别的干净解法
> （改成 PATCH 原地改记录也不行：A 记录一旦 proxied 指向私网 IP 就是 502）。

### 1.4 SSL/TLS 模式

CF 面板 → SSL/TLS → Overview → 加密模式选 **Full**。
隧道段已由 CF 加密，源站是 HTTP。Flexible 也能跑但不推荐。
这个设置是 **zone 级**的，chat / wandb / overleaf 现在也在同一个 zone 下正常跑，
说明现值已经可用；改之前先看一眼当前是什么，别为了 learn 把别人搞坏。

### 1.5 顺带确认

- Security → WAF：确认没有托管规则会拦 `POST /api/v1/auth/login` 这类。免费版默认不会。
- 别开 Rocket Loader / Auto Minify（会动 Next.js 的脚本）。

### 1.6 事实备忘

- **校园网出口公网 IP：`202.116.81.57`**（SZ_NAS 与 BJ_2 两条隧道的连接来源都是它）。
  本期没有用到，记在这里备用：日后若要在 nginx 或 CF 侧做「校内 / 校外」判定，
  这是最直接的依据（例如对该 IP 放行大文件上传、或跳过校园网提示）。
  注意它可能随学校出口策略变动，用之前先复核。
- zone 是 **Free 计划**。所以 100 MB 请求体上限、100 秒源站超时都按免费版算，
  见 §3。

### 1.7 阶段一验收

| # | 测试 | 期望 |
|---|---|---|
| 1 | 手机关 WiFi 走 4G 打开 `https://learn.sysu-sam.com` | 页面正常、图片正常 |
| 2 | 校外登录学生账号 | 成功，cookie 正常写入 |
| 3 | 校外打开课程页、作业页，提交一个小于 10 MB 的作业 | 正常 |
| 4 | 校外播放视频 | 能播。**这是过渡状态**，记下卡顿情况当作阶段二的基线。注意 §1.1 的 Cache Rule 把 `/api/*` 也 Bypass 了，所以视频的**每个 Range 请求都回源**、CF 不缓存任何分片 —— 每次 seek 都是一次完整的隧道往返。这是刻意的（视频不该进 CF 缓存），记基线时别把它算到隧道本身头上 |
| 5 | 校内打开同一页面并记首屏耗时 | 与改造前对比，量化 CF 带来的延迟 |
| 6 | 教师上传一个大于 100 MB 的视频 | 预期 413。确认失败长什么样，然后把 §7 的替代方案交给老师 |
| 7 | 连续输错 6 次密码 | 只锁自己这个 IP，换台设备仍能登录 |
| 8 | 看后端日志里的客户端 IP | 是真实公网 IP，不是 `172.20.0.x` |
| 9 | 无痕窗口访问一个**非公开**课程的图片直链 | 401/403，且响应头 `cf-cache-status` 是 `BYPASS`（验 §1.1 的 Cache Rule） |
| 10 | 打开一门课的白板 `/collab` | WebSocket 正常 |
| 11 | **`https://chat.sysu-sam.com`、`wandb`、`overleaf` 各开一次** | 全部正常。确认改 SZ_NAS 的 ingress 没有波及同一条隧道上的其它服务 |

第 11 条不要省。这次动的是别人也在用的那条隧道。

### 1.8 阶段一回滚

**一步就够**：

```sh
cd deploy/cf
CONFIRM=yes ./dns-rollback.sh          # 不给参数时自动用最新的那份备份
```

DNS 一切回来，流量立刻回到 DSM 反代直连 8088，与改造前完全一致。
生效时间等于切换前那条 A 记录的 TTL（备份文件里能看到，默认 300 秒）。

隧道里那条 learn 的 ingress **留着不用管** —— 没有 DNS 指向它就是闲置的，
而且下次再切过去时不用重加。确实要清干净（比如彻底放弃这个方案）再跑：

```sh
CONFIRM=yes ./tunnel-rollback.sh backups/tunnel-f8b7e1c1-…-<时间>.json
```

**注意**：`tunnel-rollback.sh` 是把整份配置恢复成快照。如果这期间别人给 SZ_NAS
加了新的 hostname，恢复会把那些一起抹掉。脚本会在执行前打印「将被移除的 hostname」，
看清楚再确认。这也是为什么日常回滚只用 `dns-rollback.sh`。

---

## 阶段二：media 域名 + 媒体分流

**前置**：阶段一稳定跑几天（**不要拖到几周**——让全部视频长期经 CF 与自助版条款有冲突）；
media 证书就绪（§5）；DSM 反代规则加好（§6）；§0.1 的 (a) (b) 都已确认。

### 2.1 DNS（已完成）

`media.sysu-sam.com` → **A** → `172.25.5.162` → **灰云（DNS only）**，TTL 300，
记录 id `0638e5498ac79869bf9f72e199388795`。已在阶段一准备时建好。
灰云是必须的：橙云会让 CF 尝试回源到一个私网地址，必然失败。

> 这条记录把内网地址公开在 DNS 里。内网地址对外无意义，属于可接受的轻微信息泄露；
> 在意的话可以改让校园 DNS 做 split-horizon，不建公共记录。

### 2.2 打开总闸

在仓库 `extra/nginx.prod.conf` 顶部把总闸改成 on，只有一行：

```nginx
map $host $media_split_enabled {
    default  "on";           # 阶段二开启
}
```

提交、推分支、然后 `TARGET=prod ./deploy.sh`。

**必须 `up -d --force-recreate nginx`，不能 reload 或 restart**（`deploy.sh` 已经是这么做的）：
这个文件是单文件 bind-mount，Docker 钉的是宿主机上那个 inode，tar 解包写的是新 inode，
运行中的容器看到的还是旧的。

**cloudflared 完全不用动。** 它是 NAS 上的独立容器（`intelligent_mayer`），
按 `http://172.25.5.162:8088` 回源，也就是走宿主机映射端口 —— nginx 容器重建、
IP 变化都影响不到它。重建 nginx 的那几秒里隧道会回源失败，之后自动恢复。

**窗口期内不要对 `intelligent_mayer` 做 `docker pull` 或重建**：它用的是浮动 tag
`cloudflared:latest`，而且还扛着 chat / wandb / overleaf。

### 2.3 阶段二验收

| # | 测试 | 期望 |
|---|---|---|
| 1 | 校内播放视频，看 DevTools Network | 先 302 到 media 域名，最终 206 来自 media，响应里**没有 `cf-ray`** |
| 2 | 校内拖进度条 seek | Range 请求正常，能跳 |
| 3 | 校内打开 PDF 活动与 PDF 块 | iframe 正常显示 |
| 4 | 校外打开同一课程页 | 文字、图片、缩略图、头像**全部正常**；只有视频区域超时/报错 |
| 5 | 校外提交作业、看批改、看公告 | 全部正常（没被分流） |
| 6 | 教师在校外下载学生提交的文件 | 正常（提交文件刻意不分流，它要 cookie） |
| 7 | 直接访问 `https://media.sysu-sam.com/` | 404，不暴露任何页面 |
| 8 | 无痕窗口直接访问**非公开**课程的 media 直链 | 401，鉴权仍生效 |
| 9 | `curl -I -H 'Range: bytes=0-1023' https://media.sysu-sam.com/content/…/video/….mp4` | 206 + `Content-Range` |
| 10 | **校内用 Chrome 首次播放视频** | 观察有没有「允许访问本地网络」权限弹窗（见 §3 第 5 条）。点允许后能正常播放；若被拦，先别推广，回头看 §3 第 5 条的两个缓解 |
| 11 | 校内 Safari / Firefox 播同一个视频 | 正常。用来区分「是不是只有 Chromium 系受影响」 |

第 1、2、3、9 条在本地已经用真实上游验过一遍（`TUNNEL_LOCAL_TEST.md`），
校内这次主要是确认证书、DSM 反代、Host 传递这三段。

### 2.4 阶段二回滚

把总闸改回 `off`，重新 `deploy.sh`；或者直接在 NAS 上：

```sh
cp extra/nginx.prod.conf.bak-<日期> extra/nginx.prod.conf
sudo docker-compose -p learnhouse-nas up -d --force-recreate nginx cloudflared
```

`media` 的 DNS 记录和 DSM 反代规则留着不删，无害。

---

## 3. 一定要知道的五条限制

1. **100 MB 请求体上限。** Cloudflare Free / Pro 是硬限制（Business 200 MB，Enterprise 才可调）。
   橙云之后，所有经 `learn.sysu-sam.com` 的上传超过 100 MB 一律 413，
   nginx 里 `client_max_body_size 6G` 完全无用。替代方案见 §7。
2. **100 秒源站响应超时。** CF 代理对源站单次响应有 100 秒上限，超时返回 **524**。
   AI 出题、AI 生图这类长请求经 learn 域名可能踩到。目前后端的 AI 调用是流式的（首字节很快到达），
   风险不大，但上线后要留意有没有 524。真踩到了就把那类接口也走校内直连。
3. **CF 会缓存带鉴权的内容** —— 靠 §1.5 的 Cache Rule 挡住，**那条规则不是可选项**。
4. **自助版条款对视频分发有限制。** CF 的 self-serve 条款限制用 CDN 分发视频和大比例非 HTML 内容，
   免费账号有被警告或限速的先例。**阶段一让全部视频经过 CF 是过渡状态，不应长期停留**，
   这也是阶段二紧接着排的原因。

5. **浏览器对「公网页面访问内网地址」的限制（阶段二特有，务必先核实）。**
   橙云之后 `learn.sysu-sam.com` 解析到 CF 的公网 IP，页面属于 **public** 地址空间；
   而 `media.sysu-sam.com` 指向 `172.25.5.162`，属于 **private**。
   Chromium 系（Chrome / Edge）近年在推 Local Network Access：公网页面访问本地网络地址
   需要用户点一次「允许」，拒绝就直接被拦。真要生效的话，影响是双重的：
   校内用户第一次播视频 / 开 PDF 会弹权限框，而且 `useCampusNetwork` 的探测本身也会被拦，
   **把校内用户误判成校外**。

   **这条我没有实测过，具体从哪个版本默认开启也不确定，所以阶段二开始前必须先核实一次**：
   在校内用当前版 Chrome 打开一个会 302 到 media 的视频，看有没有权限弹窗；
   或者到 `chrome://flags` 搜 Local Network Access 看当前状态。

   两个缓解办法：
   - **（首选）走设计文档 §9.3 的校园 DNS split-horizon**：让校园 DNS 把
     `learn.sysu-sam.com` 也解析到 `172.25.5.162`。两端同属 private 地址空间，
     这个限制就不存在了，而且校内全程走局域网、没有 100 MB 上传限制。
     **如果这条限制被证实存在，§9.3 就不再是「更优解」，而是必要项。**
   - 接受一次性弹窗，并在提示文案里加一句「如果浏览器询问是否允许访问本地网络，请选择允许」
     （`feat/tunnel-web` 分支的 `CampusOnlyNotice.tsx` 与 i18n 文案）。

WebSocket（`/collab` 白板）经隧道没有问题。

---

## 4. 真实客户端 IP 与限流

不用做任何事，但要知道为什么。

链路：CF 边缘（写入 `CF-Connecting-IP`，并把客户端 IP 放进 `X-Forwarded-For`）→ cloudflared
→ 外层 nginx（`$proxy_add_x_forwarded_for` 是**追加**，第一个仍是真实客户端）→ app 容器内 nginx → :9000。
后端 `rate_limiting.py` 只在直连 IP 是私网时才信任 XFF，取链上第一个 —— 所以登录限流与账号锁定
在隧道后仍按真实 IP 生效，不会全校连坐。阶段一验收第 7、8 条就是验这个。

链路（按复用 SZ_NAS 的实际拓扑）：CF 边缘（写入 `CF-Connecting-IP`，并把客户端 IP
放进 `X-Forwarded-For`）→ NAS 上的 cloudflared 容器 → **宿主机 `172.25.5.162:8088`**
→ 外层 nginx（`$proxy_add_x_forwarded_for` 是追加，第一个仍是真实客户端）
→ app 容器内 nginx → :9000。

**不要**在 nginx 里加这种写法：

```nginx
# ❌ 别加，而且这条路是关死的
set_real_ip_from 172.20.0.0/24;
real_ip_header CF-Connecting-IP;
```

cloudflared 和 DSM 反向代理**都是打宿主机的 8088**，进到 nginx 时 `$remote_addr`
都是网桥网关 `172.20.0.1`，**在 nginx 这一层根本区分不开**。所以无论把
`set_real_ip_from` 写成 /24 还是任何 /32，都必然连 DSM 那条路径一起放行，
校园网用户就能自己伪造 `CF-Connecting-IP` 绕开登录限流。
（早先「给 cloudflared 钉静态 IP 再只信任那个 /32」的说法是基于「cloudflared 在同一个
compose 网络里」的假设，复用外部隧道后不成立，已作废。）

不写也没关系：后端信任 XFF 链首位，而 CF 会把真实客户端 IP 放在那里。

---

## 5. media.sysu-sam.com 的证书

`media` 的 A 记录指向私网 IP，**HTTP-01 验证不可能通过**（CA 从公网到不了 172.25.5.162）。
只能走 DNS-01。

**动手前先看一眼现状**：DSM → 控制面板 → 安全性 → 证书，看 learn 那张证书的签发者和签发方式。

- 已经是 acme.sh / DNS-01 → 给现有证书加一个 SAN `media.sysu-sam.com`，或者直接换成通配符。
- 是手工上传的商业证书 → 按下面上 acme.sh。

### 5.1 签通配符证书

在 **NAS 本机**跑最省事（续期的 cron 也就留在那台机器上）。

```sh
# 一次性安装
curl https://get.acme.sh | sh -s email=<你的邮箱>
export PATH="$HOME/.acme.sh:$PATH"

# Cloudflare API Token（见下方权限）
export CF_Token="<API Token>"
export CF_Account_ID="<账号 ID，Cloudflare 首页右下角>"
export CF_Zone_ID="<sysu-sam.com 的 Zone ID，域名 Overview 页右下角>"

acme.sh --issue --dns dns_cf -d sysu-sam.com -d '*.sysu-sam.com' --server letsencrypt
```

**API Token 需要的权限**（Cloudflare → My Profile → API Tokens → Create Token → Custom）：

| 类型 | 权限 | 范围 |
|---|---|---|
| Zone | **DNS → Edit** | Include → Specific zone → `sysu-sam.com` |
| Zone | **Zone → Read** | 同上 |

`Zone:Read` 是 acme.sh 用来查 Zone ID 的。如果按上面那样**已经显式导出了 `CF_Zone_ID` 和
`CF_Account_ID`**，理论上只留 `DNS:Edit` 也能跑通 —— 两种都行，先按「两项都给」做，
跑通了再收紧。acme.sh 的 dnsapi 文档随版本变，签之前对一下它 wiki 上 `dns_cf` 那一节。

> 这个 Token 与阶段一那条隧道 token 是两回事，互不相关。
> 隧道 token 从 Zero Trust 页面拿，不需要 API Token。
> 如果将来要用脚本管隧道（本方案不需要），才会用到 `Account → Cloudflare Tunnel → Edit`。

### 5.2 部署进 DSM

```sh
export SYNO_Username="<DSM 管理员账号>"
export SYNO_Password="<密码>"
export SYNO_Hostname="localhost"     # 在 NAS 本机跑就是 localhost
export SYNO_Scheme="http"
export SYNO_Port="5000"
export SYNO_Certificate="sysu-sam.com wildcard"   # DSM 证书列表里显示的描述
export SYNO_Create=1                              # 允许新建一张证书条目

acme.sh --deploy -d sysu-sam.com --deploy-hook synology_dsm
```

**开了两步验证的话**还要 `SYNO_DID`（浏览器里「信任此设备」后的 cookie）或
`SYNO_TOTP_SECRET`（DSM 的 OTP 密钥）。这两样只有用户拿得到，**属于 §0 清单第 3 项**。

装好后 acme.sh 会自己建续期 cron；续期时会重新跑一次 deploy hook。
**上线后第一次续期（约 60 天）要盯一眼**，DSM 的部署钩子是最容易悄悄失效的一环。

---

## 6. DSM 反向代理

learn 现有那条规则 **保留不动** —— 校内直连和回滚都靠它。

新增一条：

| 项 | 值 |
|---|---|
| 来源协议 / 主机名 / 端口 | HTTPS ／ `media.sysu-sam.com` ／ 443 |
| 目标协议 / 主机名 / 端口 | HTTP ／ `localhost` ／ **8088** |
| 自定义标头 | 建议加 `WebSocket`（DSM 的一键项）以外，把「保留原始主机头」打开 |

两条规则指向同一个后端，由外层 nginx 的 `server_name` 区分。
证书选 §5 签出来的那张通配符。

---

## 7. 给老师的告知（阶段一上线当天发）

> 学堂从今天起校外也能访问了（`https://learn.sysu-sam.com`），校内用法不变。
>
> **一个变化：从校外网页上传单个大于 100 MB 的文件会失败。** 这是我们用的公网通道的硬性限制，
> 改不了。三个办法：
>
> 1. **在校园网内上传**（推荐）。校内不走这条通道，没有大小限制。
> 2. **把长视频切成 100 MB 以内的分段**再上传。
> 3. 需要经常从校外传大文件的话找管理员，用命令行工具直连上传（`lh` CLI 走
>    `http://172.25.5.162:8088`，需要连校园网或校园 VPN）。
>
> 学生提交作业一般远小于 100 MB，不受影响。

阶段二上线后追加一条：

> 校外**看不了视频和 PDF 讲义**，页面其它内容（文字、图片、作业、公告、批改）都正常。
> 要看视频请连校园网或校园 VPN。这是为了不把课程视频放到公网上。

---

## 8. 一页速查

| 事情 | 命令 / 位置 |
|---|---|
| **紧急回滚（第一手段）** | `cd deploy/cf && CONFIRM=yes ./dns-rollback.sh`，流量立刻回到 DSM 直连 |
| 看隧道通没通 | NAS 上 `sudo docker logs --tail 40 intelligent_mayer`，找 `Registered tunnel connection`；或 Zero Trust 里 SZ_NAS 是否 HEALTHY |
| 看隧道当前 ingress | `cd deploy/cf && ./tunnel-add-learn.sh`（不带 CONFIRM，纯只读，会打印完整列表） |
| 加 / 撤 learn 的 ingress | `CONFIRM=yes ./tunnel-add-learn.sh` / `CONFIRM=yes ./tunnel-rollback.sh <备份>` |
| 切 / 回滚 DNS | `CONFIRM=yes ./dns-switch.sh` / `CONFIRM=yes ./dns-rollback.sh` |
| 开 / 关媒体分流 | `extra/nginx.prod.conf` 顶部 `$media_split_enabled` 那一行 → `deploy.sh`（只重建 nginx，隧道不用动） |
| 分流没生效 | NAS 上 `curl -I -H 'Host: learn.sysu-sam.com' http://172.25.5.162:8088/content/…/video/….mp4`，看有没有 302 |
| 怀疑 Host 没传到 | 同上但走 `https://learn.sysu-sam.com`。若直连 IP 有 302 而走域名没有，说明 Host 丢了：查隧道 ingress 的 `httpHostHeader`（走隧道时）或 DSM 反代的「保留原始主机头」（走 DSM 时） |
| 校园网出口 IP | `202.116.81.57`（备用，见 §1.6） |

### 切换前检查清单

切 DNS 之前逐条过一遍：

- [ ] NAS 上 `sudo docker logs --tail 20 intelligent_mayer` 无报错，隧道连接正常；
      API 侧 SZ_NAS 状态为 healthy
- [ ] NAS 上 `curl -sI -H 'Host: learn.sysu-sam.com' http://172.25.5.162:8088/` 返回 200
      —— 这就是隧道将要打的源站
- [ ] `extra/nginx.prod.conf` 顶部总闸确认是 **off**（阶段一不做媒体分流）
- [ ] 当天跑过 `backup.sh` 且退出码 0
- [ ] `media.sysu-sam.com` A 记录与 Cache Rule 都在（id 见 §1.1）
- [ ] `./tunnel-add-learn.sh` 预演过，改后 ingress 对照无误；已用 `CONFIRM=yes` 执行
- [ ] 窗口期内**不对 `intelligent_mayer` 做 pull / 重建**（浮动 tag，且它扛着另外三个服务）
- [ ] 老师的 100 MB 上传告知已发（§7）
- [ ] （可选，推荐）前一天把 learn 的 A 记录 TTL 从 300 降到 60，回滚生效从 5 分钟缩到 1 分钟
- [ ] 切完立刻回归 chat / wandb / overleaf 三个站点（阶段一验收第 11 条）
- [ ] 切完用 `dig @1.1.1.1` 与 `dig @8.8.8.8` 各查一次 learn。若出现 NXDOMAIN，
      说明踩到了删建之间的空窗被负缓存，见 §1.3 的说明
