# 生产部署前只读预检（2026-09-11）

一条 SSH 连接跑完全部只读检查，退出码 0，未做任何写操作。
NAS 密码只在 shell 的环境变量里，未落任何文件。本文所有内容已脱敏（`.env` 只列键名，不含值）。

## 结论先说

**可以部署，但第二步的两条指令要先改。**

1. **不要跑 `alembic upgrade head`。** 生产库根本没有 `alembic_version` 表 ——
   这个部署用的不是 alembic，而是应用启动时的 `SQLModel.metadata.create_all`。
   对一个已有 61 张表的库从零跑 69 个迁移，轻则全部报「表已存在」，重则执行到破坏性操作。
   详见下面「阻断项 1」。
2. **DSM 反向代理那条验证做不了。** 在 NAS 内部带不带 `Host` 头结果完全一样，
   这个测法分辨不出任何东西。详见「阻断项 2」。

其余全部正常：五个容器 healthy、备份新鲜、磁盘充裕、生产配置与仓库基线逐字节一致。

## 阻断项 1：生产不用 alembic

```
$ psql -At -c "select version_num from alembic_version;"
ERROR:  relation "alembic_version" does not exist

$ psql -At -c "select count(*) from information_schema.tables where table_schema='public';"
61

$ psql -At -c "... table_name ilike '%checkin%';"
（空）
```

61 张表在，`alembic_version` 不在。对照源码，建表走的是
`apps/api/src/core/events/database.py:398` 的
`await conn.run_sync(SQLModel.metadata.create_all)`，在应用 lifespan 启动时执行。
仓库里那 69 个 `apps/api/migrations/versions/*` 在这条 all-in-one 镜像路径上没被用到。

**含义**：新功能的表不需要任何迁移命令，app 一起来 `create_all` 就会把新增的
SQLModel 表建出来。部署后的正确校验是**查表是否存在**，不是查 alembic 版本：

```sh
docker exec learnhouse-db-nas psql -U learnhouse -d learnhouse -At \
  -c "select table_name from information_schema.tables
      where table_schema='public' and table_name ilike '%checkin%';"
```

有输出即成功。若为空，去看 app 启动日志里 `create_all` 是否报错，
**不要**用 `alembic upgrade head` 去「补」—— 那会把一个健康的库推向未知状态。

> `create_all` 只建新表，不会改已有表的列。如果 sam1checkin01 涉及**修改现有表**，
> 那 `create_all` 帮不上忙，需要单独评估，这种情况下更不能盲跑 alembic。

## 阻断项 2：Host 头这个测法无效

```
curl -sI -H 'Host: learn.sysu-sam.com' http://127.0.0.1:8088/   → HTTP/1.1 200
curl -sI                               http://127.0.0.1:8088/   → HTTP/1.1 200
```

两次响应头**逐行相同**（含 `set-cookie: LH_org=default` 等）。API 探测也一样，
带不带 Host 都是 200。原因是外层 nginx 用 `$http_host` 透传、后端单租户模式
（`LEARNHOUSE_TENANCY=single`）根本不靠 Host 分流。

所以这条命令证明不了「DSM 反向代理是否保留原始 Host」——
DSM 的反向代理在 8088 **之前**，从 NAS 内部打 127.0.0.1:8088 完全绕过了它。
要验只能从**外部**打 `https://learn.sysu-sam.com` 看后端拿到的 Host，
或去 DSM 控制面板看反代条目的配置。两者本次都没做（一个要外网可达，一个要 GUI）。

好消息是这一项不影响本次部署：新旧镜像在 Host 处理上没有任何差异。

## 系统与容量

| 项 | 值 | 判断 |
|---|---|---|
| 型号 / 内核 | Synology R1000 923+，Linux 4.4.302 x86_64 | 确认是 amd64，镜像架构对得上 |
| Docker | 24.0.2 | |
| docker-compose | **v2.20.1** | 与文档不符，见下面「要改的文档」 |
| /volume1 可用 | 5,040,164,212 KB（约 4.7 TB，已用 33%） | 充裕 |
| 内存 | 总 3,983,740 KB，可用 1,536,244 KB | 紧 |
| Swap | 总 4,489,140 KB，空闲 2,719,676 KB（已用约 1.7 GB） | 紧 |
| 负载 | 0.31 / 0.30 / 0.31，已开机 65 天 | 空闲 |

NAS 上还跑着 sharelatex、rustdesk（hbbs/hbbr）、lobe-chat ×2、cloudflared 等无关容器。
内存只有 4 GB 且已用掉 1.7 GB swap，**拉镜像和重建时要留意**：
新镜像要与旧镜像共存一段时间（拉完到删掉旧的之间），磁盘没问题，内存峰值需要盯。

## 五个容器

全部 running，四个有 healthcheck 的都 healthy，`ssr-fwd` 无 healthcheck（设计如此）。

```
learnhouse-app-nas      running  healthy   ghcr.io/learnhouse/app:1.3.6
learnhouse-nginx-nas    running  healthy   nginx:alpine
learnhouse-db-nas       running  healthy   pgvector/pgvector:pg16
learnhouse-redis-nas    running  healthy   redis:7.2.3-alpine
learnhouse-ssr-fwd-nas  running  nohealth  alpine/socat:1.8.0.0
```

app 与 nginx 已 Up 30 小时，redis 3 天。

当前 app 镜像：`ghcr.io/learnhouse/app:1.3.6`，image id `96af6d79f226`，657 MB，4 天前拉取。
容器实际跑的镜像层 `sha256:96af6d79f226373971e2edb3509896ec2bc7459ecc50765107c59478dbf0d903`。

七条 bind-mount 全部在位（1 个 content + 6 个补丁），与 compose 一致：

```
data/content              => /app/api/content
patches/generator.py      => /app/api/src/services/ai/image/generator.py
patches/courseplanning.py => /app/api/src/services/ai/courseplanning.py
patches/magic_login.py    => /app/api/src/services/auth/magic_login.py
patches/web/zh.json       => /app/web/locales/zh.json
patches/web/zh.chunk.js   => /app/web/.next/static/chunks/3bdcaw90zbhgi.js
patches/web/assign.chunk.js => /app/web/.next/static/chunks/1xclx_yg371wb.js
```

## 生产配置 vs 仓库基线：没有人改过

与仓库基线提交 `7ecc3f84`（NAS 现状原样快照）逐字节比对：

| 文件 | NAS 字节数 | 结果 |
|---|---|---|
| `docker-compose.yml` | 5262 | **逐字节一致** |
| `extra/nginx.prod.conf` | 1868 | **逐字节一致** |
| `backup.sh` | 2214 | **逐字节一致** |

也就是说自 2026-09-10 16:47 之后没有人手工改过这三样，仓库基线可信。

目录里另有几个历史备份文件（`docker-compose.yml.bak*` ×3、`.env.bak*` ×2），
以及一个 `._docker-compose.yml`（163 字节，macOS 用 tar/AFP 写入时留下的 AppleDouble
伴随文件，无害）。**`.env` 的修改时间是 09-10 17:04**，比 compose 晚，
说明最近有人动过 `.env`，同目录留了 `.env.bak-20260910-1704`。

## 备份

```
-rw------- root  1,600,719  Sep 11 02:00  db-2026-09-11-0200.dump
-rw------- root    430,907  Sep 11 02:00  redis-2026-09-11-0200.tar.gz
-rw------- root    163,468  Sep 11 02:00  config-2026-09-11-0200.tar.gz
```

最新一份是**今天 02:00**，三件齐全，db dump 1.6 MB。cron 确认在位：

```
0 2 * * * root /volume1/docker/learnhouse/backup.sh >> .../backups/backup.log 2>&1
```

注意 `backups/` 下的文件是 **root 属主、600 权限**，读要 sudo。
这与 `deploy.sh` 里回滚走 `remote_sudo` 的写法一致。

## .env 键名（仅键名，无值）

共 50 个键。与仓库 `.env.example` 对照，生产**没有**的键：

- `LEARNHOUSE_ENV`、`LEARNHOUSE_SAAS`、`LEARNHOUSE_SELF_HOSTED`、`LEARNHOUSE_COOKIE_DOMAIN`
- `LEARNHOUSE_AI_IMAGE_MODEL` / `LEARNHOUSE_AI_TTS_MODEL`（用代码里的默认值）
- `LEARNHOUSE_GEMINI_API_KEY`（本分支的补丁让生图复用 `LEARNHOUSE_AI_*`，本就不需要）
- Tinybird 三件套（分析看板未配置，`/analytics/dashboard/*` 返回 503 属预期）

生产独有、`.env.example` 里没写的：`LEARNHOUSE_REDIS_URL`、`COLLAB_TRUST_PROXY`、
`LEARNHOUSE_PGBOUNCER`、`HTTP_PORT`、`NEXT_PUBLIC_LEARNHOUSE_DEFAULT_ORG`。

**本次要追加的新键（`LEARNHOUSE_EXT_*`）目前一个都不存在**，
`NEXT_PUBLIC_LEARNHOUSE_HEAVY_MEDIA_URL` 也不存在，与「先不设」的安排一致。
追加时只 append，不碰已有 50 个键中的任何一个。

## 与演练环境的差异

演练在本机隔离栈（`learnhouse-reh`）上做，与生产的差别按影响大小排：

| | 演练栈 | 生产 NAS | 影响 |
|---|---|---|---|
| 架构 | arm64（Mac） | **amd64** | 镜像必须是 amd64，CI 出的正是 amd64 |
| 内存 | Mac 充裕 | **4 GB 且已用 1.7 GB swap** | 冷启跑 `create_all` 会慢很多，240s 超时是否够**未知** |
| 数据 | 空库冷启，61 张表现建 | **真实数据，61 张表** | 生产不会重跑建表，启动应更快；但迁移/建新表是第一次 |
| 执行通道 | 本地 `bash -c` | **SSH + sudo** | `sshpass`、herestring 喂 sudo、tar 流过 SSH、单连接等待——**全部未验** |
| 镜像来源 | 本机已有，走 `image inspect` | **`docker-compose pull` 拉 ghcr** | 拉取耗时、网络、磁盘峰值**未验** |
| compose | v5.0.1 | **v2.20.1** | 见下 |
| 补丁挂载 | 无 | **7 条 bind-mount 仍在位** | 切自建镜像后 compose 会删掉其中 6 条 |
| 端口 | 28088 | 8088（DSM 反代在前） | 健康检查打 127.0.0.1:8088 |
| 其他负载 | 无 | 6 个无关容器 | 内存竞争 |
| 磁盘预检 | 跳过 | 会执行 | 5 TB 可用，不会卡 |

## 要改的文档

`DEPLOY.md` 和 `deploy.sh` 里写着「生产是 compose v1，没有 `docker compose` 子命令」，
**这是错的**：`/usr/local/bin/docker-compose --version` 返回 `v2.20.1-6047-g6817716`。

实际影响不大 —— `deploy.sh` 调的就是 `/usr/local/bin/docker-compose`，v2 同样接受
`-p` 与 `-f`。但有两点要记下：

- v2.20 **不支持 `!override`**（该标签要 ≥ 2.24）。生产不加载
  `docker-compose.rehearsal.yml`，所以不受影响；但今后别把 `!override` 写进生产那份。
- `REHEARSAL.md` 里「compose v1 与 v2 的差异」那条未验项可以划掉一半：
  两边都是 v2，只是小版本不同（2.20 vs 5.0）。

## 本次执行的命令

一条 SSH 连接，远端脚本 base64 传入后以 `sudo -S sh` 执行，全部只读：
`uname` / `docker --version` / `df` / `/proc/meminfo` / `uptime` / `docker ps` /
`docker inspect` / `docker images` / `ls` / `grep /etc/crontab` / `curl -sI 本机 8088` /
`docker exec db psql -At select`（三条 select）/ `grep -oE '^[A-Za-z0-9_]+=' .env`（只取键名）/
`cat` 三个配置文件。

唯一的 stderr 是 `Could not chdir to home directory /var/services/homes/SAM-IPA518`，
该账号没有 home 目录，不影响任何命令。
