# Cloudflare 侧的四个脚本

给 `learn.sysu-sam.com` 上隧道用的。**全部默认只做预演**，不带 `CONFIRM=yes` 时
只读 API、打印将要发生的改动、然后以退出码 1 停下。

完整背景和上线流程在 `../TUNNEL_RUNBOOK.md`，这里只讲这几个脚本本身。

## 凭据

读 `~/.learnhouse/cf.env`（权限 600，**不在本仓库里，也永远不要放进来**），三个键：

```
CF_API_EMAIL / CF_API_KEY / CF_ACCOUNT_ID
```

目前是 Global API Key，权限覆盖整个账号。建议换成限定范围的 API Token
（`Zone:DNS:Edit` + `Zone:Cache Rules:Edit` + `Account:Cloudflare Tunnel:Edit`，
zone 限定 sysu-sam.com），换完把 `lib.sh` 里 `cf_api` 的两个 `X-Auth-*` 头改成
`Authorization: Bearer ${CF_API_TOKEN}` 即可，其余不用动。

本机访问外网要走 Surge，`lib.sh` 里 `CF_PROXY` 默认 `http://127.0.0.1:6152`；
在能直连的机器上跑就 `CF_PROXY= ./xxx.sh`。

**写脚本时注意**：凭据只在 `cf_api` 函数内展开成 curl 的参数。
不要把凭据拼进 shell 变量再 eval，也不要开 `set -x` —— 那样密钥会进日志。
（这个教训是真踩出来的：一次命令展开失败，zsh 把整条带 `X-Auth-Key:` 的命令打进了报错。）

## 四个脚本

| 脚本 | 干什么 | 影响流量 |
|---|---|---|
| `tunnel-add-learn.sh` | 给 SZ_NAS 隧道的 ingress 加一条 `learn.sysu-sam.com → http://172.25.5.162:8088` | ❌ 不影响，DNS 还没切 |
| `dns-switch.sh` | 把 learn 的灰云 A 记录换成橙云隧道 CNAME | ✅ **这一步才切流量** |
| `dns-rollback.sh` | 把 learn 换回原来的灰云 A 记录 | ✅ 回滚流量，**出问题时的第一手段** |
| `tunnel-rollback.sh` | 把隧道配置整份恢复成某个备份 | ❌ 不影响（DNS 已回滚的前提下） |

执行顺序：`tunnel-add-learn.sh` → `dns-switch.sh`。
回滚顺序：`dns-rollback.sh`，隧道里那条 ingress 留着无害，不急着撤。

```sh
./tunnel-add-learn.sh                 # 预演
CONFIRM=yes ./tunnel-add-learn.sh     # 执行
```

## backups/

三个脚本在改动前都会把当前状态原样存成 JSON 放进 `backups/`（已 gitignore）。
`dns-rollback.sh` 不给参数时会自动挑最新的一份 `dns-learn-*.json` 并打印出来确认。

备份文件里没有密钥（隧道配置里只有主机名和内网地址），不入库只是没必要，
不是因为敏感。

## 几个设计上的选择

- **DNS 用「先删 A 再建 CNAME」两步，不用 PATCH 改类型。** CF 对同名记录改类型的行为
  在不同 API 版本里不一致，删加两步的结果是确定的。代价是两步之间有几百毫秒空窗。
- **隧道配置 PUT 时只带 `config`**，不带 `version` / `source` / `tunnel_id`，那些是
  服务端维护的。脚本改完会 GET 一次打印 version，确认它递增了。
- **`tunnel-add-learn.sh` 是幂等的**：ingress 里已经有 learn 就直接退出，不重复插入。
- **新规则插在末尾 catch-all（`http_status:404`）之前**，其余条目一字不动、顺序不变。
  万一末尾不是 catch-all，脚本会追加到最后并打印提醒，让人工确认。
- **`tunnel-rollback.sh` 会打印「将被移除的 hostname」**。SZ_NAS 上还跑着
  chat / wandb / overleaf，如果备份之后别人加了新服务，整份恢复会把它们抹掉。
  这也是为什么日常回滚只用 `dns-rollback.sh`。

## 已经建好的 CF 对象

这两个在准备阶段就建了，不影响任何现有流量：

| 对象 | 值 | id |
|---|---|---|
| `media.sysu-sam.com` A 记录 | `172.25.5.162`，灰云，TTL 300 | `0638e5498ac79869bf9f72e199388795` |
| Cache Rule ruleset（`http_request_cache_settings` entrypoint） | 见下 | `130e45ebbb9a40799478387d5d1bd4ea` |
| ↳ 里面那条规则 | Bypass cache | `904d95075e004f69ba10142f7f6dd514` |

Cache Rule 的表达式带了 `http.host` 限定，只作用于 learn，不会波及同一个 zone 里的
chat / wandb / overleaf / blog 等：

```
(http.host eq "learn.sysu-sam.com" and (starts_with(http.request.uri.path, "/content/")
 or starts_with(http.request.uri.path, "/api/")))
   -> set_cache_settings { cache: false }
```

要撤掉它：`PUT /zones/<zone>/rulesets/phases/http_request_cache_settings/entrypoint`
body `{"rules":[]}`。撤之前想清楚 —— 没有这条规则，橙云后 CF 会缓存非公开课程的图片
并向任何拿到 URL 的人分发。
