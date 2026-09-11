# deploy/ —— 生产部署配置

这里是先进智造学堂线上环境（群晖 NAS 172.25.5.162）的部署配置，纳入版本管理是为了
「NAS 上跑的到底是什么」有据可查、可复原。**本目录不会自动同步到 NAS**，改完要人工上传。

## 三个环境的关系

| | 在哪 | 是什么 |
|---|---|---|
| **本仓库** | `/Volumes/D/code/learnhouse`，分支 `sysu-sam` | **唯一真相源**。源码 + 本目录的部署配置 |
| **本地预发** | `/Volumes/D/code/learnhouse-local` | 生产的本地复刻，端口 18088，数据从生产备份恢复并脱敏 |
| **生产** | NAS `172.25.5.162:/volume1/docker/learnhouse`，端口 8088 | 真实课程与学生 |

改动的流向是 **仓库 → 本地预发验证 → 生产**，不能跳过中间那步，也不要反向：
生产目录不再手工编辑，NAS 上的文件由 `deploy.sh` 从仓库同步过去。

本地预发环境（`learnhouse-local`）**不是本仓库的一部分**，它是一个独立的工作目录，
有自己的 `.env`、数据卷、`make up / restore / smoke` 一套脚手架和脱敏脚本，
这些都与生产部署无关，所以没有并进来。并进本目录的只有它写的两份部署产物：
`DEPLOY.md` 和 `deploy.sh`。

两边的 compose 有意保持不同：本地那份是复刻生产用的（项目名 `learnhouse-local`、
端口 18088、网段 172.21、`platform: linux/arm64`），本目录这份是生产用的。
**不要互相覆盖。**

升级或改动的完整闭环见 `../docs/sysu-sam/DEVELOPING.md` 的「跟上游升级」一节。

## 与 NAS 目录的对应关系

NAS 上的部署根目录是 `/volume1/docker/learnhouse`，compose 项目名 `learnhouse-nas`，
对外唯一端口 8088。

| 本仓库 | NAS 上的路径 | 说明 |
|---|---|---|
| `deploy/docker-compose.yml` | `/volume1/docker/learnhouse/docker-compose.yml` | 5 个服务：app / nginx / ssr-fwd / db / redis |
| `deploy/extra/nginx.prod.conf` | `/volume1/docker/learnhouse/extra/nginx.prod.conf` | 外层 nginx，挂进 nginx 容器的 `conf.d/default.conf` |
| `deploy/backup.sh` | `/volume1/docker/learnhouse/backup.sh` | 由 `/etc/crontab` 每日 02:00 触发 |
| `deploy/deploy.sh` | 不上传，在本机跑 | 部署脚本（**骨架，未在生产跑过**），流程见 `DEPLOY.md` |
| `deploy/DEPLOY.md` | 不上传 | 部署流程说明 |
| `deploy/cf/*.sh` | 不上传，在本机跑 | Cloudflare 侧脚本（隧道 ingress、DNS 切换与回滚）。默认只预演，要 `CONFIRM=yes` 才动手。见 `cf/README.md` 与 `TUNNEL_RUNBOOK.md` |
| `deploy/TUNNEL_RUNBOOK.md` | 不上传 | 隧道 + 媒体域名的上线手册 |
| `deploy/TUNNEL_LOCAL_TEST.md` | 不上传 | nginx 媒体分流的本地验证记录 |
| `deploy/REHEARSAL.md` | 不上传 | 2026-09-10 演练记录，含查出的缺陷与尚未验到的项 |
| `deploy/docker-compose.rehearsal.yml` | 不上传 | 演练栈的 override，生产不加载 |
| `deploy/.env.example` | `/volume1/docker/learnhouse/.env` | **只有键名和非敏感值**，真实密钥永不进仓库 |
| 无（不进仓库） | `/volume1/docker/learnhouse/data/content` | 课程图片/视频，体积大，靠 DSM 快照或 Hyper Backup |
| 无（不再需要） | `/volume1/docker/learnhouse/patches/` | 见下面「patches 目录的去向」 |
| 无（不进仓库） | `/volume1/docker/learnhouse/backups/` | backup.sh 的产出，保留 14 天 |

## 这份配置与线上现状的差异

`git log --oneline -- deploy/` 里有两个提交，请分清：

1. **基线提交**：从 NAS 原样拉下来的配置，就是当前线上跑的东西
   （镜像 `ghcr.io/learnhouse/app:1.3.6` + 5 条 patch bind-mount）。
2. **切换到自建镜像**（当前 HEAD 的状态，**尚未部署到线上**）：
   - 镜像换成 `ghcr.io/godarrenw/learnhouse:sysu-sam`
   - 删掉 5 条 patch bind-mount —— 改动已经在源码里，见 `docs/sysu-sam/PATCHES.md`
   - `nginx.prod.conf` 删掉针对 `3bdcaw90zbhgi.js` / `1xclx_yg371wb.js` 的 no-cache location。
     那段存在的唯一理由是补丁改编译产物却不改文件名；自建镜像里 chunk 文件名是内容哈希，
     内容变了名字就变，immutable 缓存不再有害。

想知道切换要动哪几行，直接 `git diff` 这两个提交。

## 切到自建镜像的步骤

前提：`ghcr.io/godarrenw/learnhouse` 已经是 **public**（fork 是公开仓库，包跟着公开），
NAS 不用登录就能拉。2026-09-10 实测匿名取 manifest 返回 200：

```sh
TOK=$(curl -s "https://ghcr.io/token?scope=repository:godarrenw/learnhouse:pull&service=ghcr.io" \
      | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
curl -s -o /dev/null -w '%{http_code}\n' \
  https://ghcr.io/v2/godarrenw/learnhouse/manifests/sysu-sam \
  -H "Authorization: Bearer $TOK" -H 'Accept: application/vnd.oci.image.index.v1+json'
```

哪天把仓库或包转成 private，NAS 上就要
`docker login ghcr.io -u godarrenw -p <带 read:packages 的 PAT>`。

步骤：
1. `sh /volume1/docker/learnhouse/backup.sh` —— 先备份，确认输出的字节数不是 0
2. 上传本目录的 `docker-compose.yml` 和 `extra/nginx.prod.conf`（**不要动 `.env`**）
3. `/usr/local/bin/docker compose pull && /usr/local/bin/docker compose up -d`
4. 等 app 容器 healthy（首次要跑迁移，`start_period` 给了 180s），然后核对补丁生效：
   ```sh
   D=/usr/local/bin/docker
   $D exec learnhouse-app-nas grep -c 'PATCH(nas)' /app/api/src/services/ai/courseplanning.py
   $D exec learnhouse-app-nas grep -rl '先进智造学堂' /app/web/.next/static/chunks/ | head
   $D exec learnhouse-app-nas grep -rl 'meta?slim=true' /app/web/.next/static/chunks/ | head
   ```
   三条都要有输出。
5. 确认无误后，NAS 上的 `patches/` 目录可以留着当历史存档，但不再被任何挂载引用。

回滚：把基线提交的 `docker-compose.yml` 和 `nginx.prod.conf` 传回去，`up -d` 即可。
`patches/` 只要没删就还在原位。

## patches 目录的去向

`patches/README.md` 是 AGPL-3.0 第 5(a) 条要求的「修改说明」和第 13 条要求的
「向使用者提供修改后源码」。切到自建镜像后，这个义务由本仓库本身履行 ——
`godarrenw/learnhouse` 的 `sysu-sam` 分支就是修改后的完整源码，
每个补丁一个 commit，映射见 `docs/sysu-sam/PATCHES.md`。

平台页脚的源码获取指引应指向本仓库地址。

## 备份要点

`backup.sh` 每天产出三份，保留 14 天：

- `backups/db-<时间>.dump` —— `pg_dump -Fc`，脚本会校验文件头是 `PGDMP`，无效就删掉并报错
- `backups/redis-<时间>.tar.gz` —— **Redis 不是纯缓存**：注册邀请码（TTL 365 天）和 AI 会话
  只存在 Redis，Postgres 里没有。丢了它等于已发出的邀请码全部失效
- `backups/config-<时间>.tar.gz` —— `.env` / `docker-compose.yml` / `patches` / `extra`

**课程图片与视频（`data/content`）不在上述备份内**，体积太大，需要 DSM 的快照或
Hyper Backup 覆盖 docker 共享文件夹。

还原数据库：
```sh
docker exec -i learnhouse-db-nas pg_restore -U learnhouse -d learnhouse --clean < db-xxx.dump
```
还原 Redis：停 redis 容器 → 把归档里的 `data/` 覆盖回卷 → 启动。

## 不要用官方 `learnhouse update`

官方 update 命令会把 `content` 迁到 named volume，破坏本部署的 bind-mount
（上游 `docs/self-hosting/maintenance/updates.mdx`）。升级流程见
`docs/sysu-sam/DEVELOPING.md` 的「跟上游升级」一节。
