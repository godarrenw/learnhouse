# Cloudflare Tunnel + 媒体域名 上线手册

配套设计文档：`/Volumes/D/code/learnhouse-agent/TUNNEL_MEDIA_DESIGN.md`（结论与代码依据都在那里，本文只讲怎么做）
本地验证记录：`TUNNEL_LOCAL_TEST.md`
涉及文件：`docker-compose.yml`（新增 cloudflared 服务）、`extra/nginx.prod.conf`（两个 server 块）、`.env`（新增 `CF_TUNNEL_TOKEN`）

目标：`learn.sysu-sam.com` 走 Cloudflare Tunnel 对校外开放，NAS 不开任何公网入站端口；
视频 / PDF / 音频这类重媒体分流到只在校园网可解析的 `media.sysu-sam.com`，
既省 CF 流量、也避开自助版条款对视频分发的限制。

分两个阶段做，中间可以停。阶段一之后校外就能用了。

---

## 0. 需要用户提供的东西

**这些不到位就别开始。**

| # | 东西 | 用在哪 | 权限 / 细节 |
|---|---|---|---|
| 1 | **Cloudflare 账号登录**（能进 Zero Trust） | 建隧道、拿 token、改 DNS、加 Cache Rule | 手工操作，无法脚本化 |
| 2 | **Cloudflare API Token** | acme.sh 用 DNS-01 签 `*.sysu-sam.com` 证书 | 权限见 §5.1。**只有第 5 步需要**，阶段一用不到 |
| 3 | **DSM 管理员账号密码** | acme.sh 的 `synology_dsm` 部署钩子把证书装进 DSM | 若开了两步验证，还要 OTP 或「信任设备」配置，见 §5.2 |
| 4 | **NAS 的 SSH / ContainerManager 访问** | 改 `.env`、跑 `deploy.sh`、看容器日志 | 现有部署流程已有 |
| 5 | **一个无课时间窗口** | 阶段一改 DNS 时有 1~5 分钟解析切换；阶段二重建 nginx 约 10 秒 | 建议避开上课与作业截止时段 |
| 6 | **两条待核实信息的答案** | 决定阶段二是否会静默失效 | 见 §0.1 |
| 7 | **给老师的告知**（100 MB 上传限制） | 阶段一上线当天 | 文案见 §7 |

### 0.1 开工前先问清楚的两件事

**（a）DSM 反向代理转发到 8088 时保不保留原始 Host？**
在 DSM「控制面板 → 登录门户 → 高级 → 反向代理」看那条 learn 规则，或上线后在 nginx 日志里看 `$http_host`。
若 DSM 把 Host 改写成 `localhost` 或 IP，阶段二的 `server_name` 匹配会全部落到 learn 块，
分流静默不生效（不会成环，配置里用的是正向白名单）。真是这样就要在 DSM 侧把
「传递原始主机头 / Preserve Host」打开。

**（b）校园 DNS 能不能做 split-horizon？**
如果学校网络中心愿意在校园 DNS 上把 `learn.sysu-sam.com` 解析到 `172.25.5.162`（校外仍走 CF），
那么校内全程走局域网、没有延迟损失、也没有 100 MB 上传限制，**整个 media 域名方案可以不做**。
这是技术上最优解，值得先问一句再动手。

---

## 阶段零：备份与开关确认（不改任何东西）

1. **截图备份 Cloudflare DNS 现有记录**，尤其 `learn` 那条 A 记录的值和 TTL —— 回滚要用。
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

## 阶段一：只上隧道

改动：`.env` 加一个键 + compose 加一个服务 + CF 控制台若干步。**不动前端，不建 media 域名。**

### 1.1 NAS 上填 token 之前，先在 CF 建隧道

Zero Trust 控制台 → **Networks → Tunnels → Create a tunnel** → 选 **Cloudflared** →
命名 `learnhouse-nas` → 创建后页面上会给一条 `cloudflared service install <一长串 token>`。
**只要那串 token**，别照着页面的安装命令在 NAS 上装系统服务 —— 我们用容器。

> token 等于隧道的凭据。泄露了就回这个页面 **Refresh token**，旧的立刻作废。
> 它只写进 NAS 上的 `.env`（权限 600），不进 git。

### 1.2 NAS 上写 .env

```sh
# 追加一行，注意 .env 是 600 权限，要 sudo
CF_TUNNEL_TOKEN=<粘贴 token>
```

对着仓库 `.env.example` 末尾那一段核一遍键名。

### 1.3 部署 compose 与 nginx 配置

```sh
TARGET=prod ./deploy.sh
```

`deploy.sh` 会同步 `extra/` 与 `docker-compose.yml` 并重建 `learnhouse-app / ssr-fwd / nginx`。
**它不会起 cloudflared**（脚本的 `SERVICES` 里没有这个名字），所以接着手工来一次：

```sh
ssh <nas> 'cd /volume1/docker/learnhouse && sudo docker-compose -p learnhouse-nas pull cloudflared'
ssh <nas> 'cd /volume1/docker/learnhouse && sudo docker-compose -p learnhouse-nas up -d cloudflared'
ssh <nas> 'sudo docker logs --tail 40 learnhouse-cloudflared-nas'
```

日志里出现四条 `Registered tunnel connection`（CF 默认建四条到不同边缘）就算连上了，
Zero Trust 的 Tunnels 列表里那条也会变成 **HEALTHY**。

> cloudflared 镜像里没有 shell 也没有 curl，**没有 healthcheck**。
> 不要把 `learnhouse-cloudflared-nas` 加进 `deploy.sh` 的 `HEALTHY_CONTAINERS`，
> 加了预检就永远过不了。

### 1.4 CF 控制台：DNS 与 Public hostname（有顺序）

**顺序错了创建会失败。**

1. **先删** DNS 面板里 `learn` 的 A 记录（第 0 步已截图备份）。
2. 回到 Tunnel → **Public Hostnames → Add a public hostname**：
   - Subdomain `learn`，Domain `sysu-sam.com`，Path 留空
   - Type `HTTP`，URL **`learnhouse-nginx-nas:80`**
     （容器名，和 cloudflared 在同一个 Docker 网络。**不要填 8088**，那是宿主机映射端口，容器网络里不存在）
   - 展开 **Additional application settings → HTTP Settings → HTTP Host Header** 填
     **`learn.sysu-sam.com`**。这一项是关键：容器内 nginx 与 Next.js Server Actions 都按 Host 判定，
     不填的话 Host 会是 `learnhouse-nginx-nas`，Server Actions 的 POST 会被拒。
   - 其余默认。后端是 HTTP，不要开 `noTLSVerify`。
3. 保存后 CF 会自动生成 `learn` 的 **橙云 CNAME** → `<tunnel-id>.cfargotunnel.com`。
4. **SSL/TLS → Overview → 加密模式选 `Full`。** 隧道段已由 CF 加密，源站是 HTTP。
   Flexible 也能跑但不推荐。

### 1.5 Cache Rules（**必做，不是可选**）

后端对所有 `/content/` 内容都下发 `Cache-Control: public, max-age=86400`，
**包括非公开课程的图片**。橙云之后 CF 边缘会缓存并向任何拿到 URL 的人分发，等于绕过鉴权。

Caching → **Cache Rules → Create rule**：

- 名称：`LearnHouse bypass auth content`
- 表达式（用 Edit expression 直接贴）：
  ```
  starts_with(http.request.uri.path, "/content/") or starts_with(http.request.uri.path, "/api/")
  ```
- Then → **Cache eligibility: Bypass cache**
- 保存并确认规则是 **启用** 状态、排在其它缓存规则前面。

### 1.6 顺带确认

- Security → WAF：确认没有托管规则会拦 `POST /api/v1/auth/login` 这类。免费版默认不会，看一眼即可。
- 别开 Cloudflare 的 Rocket Loader / Auto Minify（会动 Next.js 的脚本）。

### 1.7 阶段一验收

| # | 测试 | 期望 |
|---|---|---|
| 1 | 手机关 WiFi 走 4G 打开 `https://learn.sysu-sam.com` | 页面正常、图片正常 |
| 2 | 校外登录学生账号 | 成功，cookie 正常写入 |
| 3 | 校外打开课程页、作业页，提交一个小于 10 MB 的作业 | 正常 |
| 4 | 校外播放视频 | 能播。**这是过渡状态**，记下卡顿情况当作阶段二的基线 |
| 5 | 校内打开同一页面并记首屏耗时 | 与改造前对比，量化 CF 带来的延迟 |
| 6 | 教师上传一个大于 100 MB 的视频 | 预期 413。确认失败长什么样，然后把 §7 的替代方案交给老师 |
| 7 | 连续输错 6 次密码 | 只锁自己这个 IP，换台设备仍能登录 |
| 8 | 看后端日志里的客户端 IP | 是真实公网 IP，不是 `172.20.0.x` |
| 9 | 无痕窗口访问一个**非公开**课程的图片直链 | 401/403，而且响应头里 `cf-cache-status` 是 `BYPASS`（验第 1.5 步） |
| 10 | 打开一门课的白板 `/collab` | WebSocket 正常（隧道透传 WS 没问题） |

### 1.8 阶段一回滚

1. CF DNS 删掉 `learn` 的 CNAME，按第 0 步的截图重建 A 记录，**灰云**（DNS only）。
2. `sudo docker-compose -p learnhouse-nas stop cloudflared`
3. DNS 生效约 1~5 分钟（TTL 用 Auto 即可）。

Public hostname 和隧道本身可以留着不删，没有流量就是闲置的。

---

## 阶段二：media 域名 + 媒体分流

**前置**：阶段一稳定跑几天（**不要拖到几周**——让全部视频长期经 CF 与自助版条款有冲突）；
media 证书就绪（§5）；DSM 反代规则加好（§6）；§0.1(a) 已确认。

### 2.1 DNS

DNS 面板新建：`media` → **A** → `172.25.5.162` → **Proxy status 必须是 DNS only（灰云）**。
橙云会让 CF 尝试回源到一个私网地址，必然失败。

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

**nginx 重建之后 cloudflared 要跟着重建**（它按名字解析 nginx，nginx 换了容器 IP 会变，
compose 不会自动连带重建依赖方）：

```sh
ssh <nas> 'cd /volume1/docker/learnhouse && sudo docker-compose -p learnhouse-nas up -d --force-recreate cloudflared'
```

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

## 3. 一定要知道的四条限制

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

WebSocket（`/collab` 白板）经隧道没有问题。

---

## 4. 真实客户端 IP 与限流

不用做任何事，但要知道为什么。

链路：CF 边缘（写入 `CF-Connecting-IP`，并把客户端 IP 放进 `X-Forwarded-For`）→ cloudflared
→ 外层 nginx（`$proxy_add_x_forwarded_for` 是**追加**，第一个仍是真实客户端）→ app 容器内 nginx → :9000。
后端 `rate_limiting.py` 只在直连 IP 是私网时才信任 XFF，取链上第一个 —— 所以登录限流与账号锁定
在隧道后仍按真实 IP 生效，不会全校连坐。阶段一验收第 7、8 条就是验这个。

**不要**在 nginx 里加这种写法：

```nginx
# ❌ 别加
set_real_ip_from 172.20.0.0/24;
real_ip_header CF-Connecting-IP;
```

DSM 反向代理是从网桥网关 `172.20.0.1` 进来的，也落在这个网段。加了以后，校园网用户经 DSM 访问时
可以自己伪造 `CF-Connecting-IP` 绕开登录限流。真要用 CF 的头，必须先给 cloudflared 钉一个静态地址
再只信任那个 /32，`extra/nginx.prod.conf` 里写了完整办法。

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
| 看隧道通没通 | `sudo docker logs --tail 40 learnhouse-cloudflared-nas`，找 `Registered tunnel connection` |
| 隧道 token 换了 | 改 NAS 上 `.env` 的 `CF_TUNNEL_TOKEN` → `up -d --force-recreate cloudflared` |
| 开 / 关媒体分流 | `extra/nginx.prod.conf` 顶部 `$media_split_enabled` 那一行 → `deploy.sh` → 重建 nginx **和** cloudflared |
| 分流没生效 | `curl -I -H 'Host: learn.sysu-sam.com' http://172.25.5.162:8088/content/…/video/….mp4`，看有没有 302 |
| 怀疑 Host 被 DSM 改写 | 同上但走 `https://learn.sysu-sam.com`，若无 302 而直连 IP 有，就是 Host 没传过来 |
| 紧急全量回滚 | CF DNS 换回 A 记录（灰云）+ `stop cloudflared` + 总闸改 off |
