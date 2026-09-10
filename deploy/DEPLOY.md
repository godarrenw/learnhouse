# 部署到生产的流程

本文与 `deploy.sh` 由本地预发环境（`/Volumes/D/code/learnhouse-local/`）的同名文件并入，
**并按自建镜像的部署模型改写过**。原稿写的是「把 `patches/` 同步到 NAS 覆盖镜像内文件」，
本仓库已经把补丁做成了源码（见 `../docs/sysu-sam/PATCHES.md`），所以：

- 同步清单里**没有 `patches/`**，仓库里也不存在这个目录
- 多了一步 `pull` 新镜像
- 「补丁是否生效」的校验从「挂载点文件名是否还在」变成「镜像内的源码是否含补丁」

> ⚠️ `deploy.sh` **没有在生产上跑过**，但已经在本机隔离演练栈上跑通了全链路
> （三次成功 + 一次故障注入验回滚），演练过程与查出的五个缺陷见 `REHEARSAL.md`。
> 那份记录末尾列了**还没验到的六项**，第一次真部署要盯着这几处。

## 两个模式

```sh
TARGET=prod  ./deploy.sh    # 部署到生产 NAS（默认）
TARGET=local ./deploy.sh    # 部署到本机演练栈，用于验证脚本本身
```

两个模式共用同一段流程代码，差异全部收敛在脚本开头 target 配置块里的几个变量和
三个执行原语（`remote` / `remote_sudo` / `sync_files`）。改流程只改一处。

演练模式另有两个开关，**都只在 `TARGET=local` 下生效**：
`ALLOW_DIRTY=1` 放行脏工作区，`DRY_IMAGE=<tag>` 把 app 镜像换成别的以注入故障。

## 第一次真部署的清单

按顺序做，前两步是手工的，**不能靠 `deploy.sh` 代劳**。

1. **先手工把新版 `backup.sh` 传上 NAS。**
   `deploy.sh` 第 2 步调的是 **NAS 上那份** `backup.sh`（`sh ${DEPLOY_DIR}/backup.sh`），
   而 `sync_files` 只同步 `extra/` 和 `docker-compose.yml`，**不包含 `backup.sh`**。
   NAS 上现在还是旧版：config 归档那行写死了 `patches`，一旦 `patches/` 不在就
   `tar` 非零退出、`set -e` 静默中止，`deploy.sh` 只会报「备份失败」且拿不到原因
   （2026-09-10 演练就栽在这里，见 `REHEARSAL.md`）。
   **不先换掉它，第一次部署必定卡在备份这一步。**

   ```sh
   tar -cf - backup.sh | ssh … 'tar -C /volume1/docker/learnhouse -xf -'
   ssh … 'sh /volume1/docker/learnhouse/backup.sh'    # 单独跑一次，确认出三份归档且退出码 0
   ```

   新版只打包实际存在的项，`patches/` 在不在都能正常跑完。

2. **确认 `.env` 齐全。** 对着 `.env.example` 核一遍键名，尤其是本分支新引入的
   AI 生图相关项（生图已改走 `LEARNHOUSE_AI_API_KEY` / `LEARNHOUSE_AI_BASE_URL`，
   不再需要 Gemini key）。`.env` 不由脚本同步。

3. **NAS 上的 `patches/` 不要删。** 它是回滚保险，见下面「失败回滚」一节。

4. 跑 `TARGET=prod ./deploy.sh`，全程盯着，重点看 `REHEARSAL.md` 末尾
   「还没验到的」那六项 —— 尤其是 `docker-compose pull` 的耗时，
   以及健康检查 240s 在这台 4G 内存且在用 swap 的 NAS 上够不够
   （生产 `start_period` 是 180s，冷启要跑迁移）。

## 基本约定

1. **改动全部在 git 仓库里。** 生产目录 `/volume1/docker/learnhouse/` 不再手工编辑。
   仓库是唯一真相源，NAS 上的文件由部署脚本从仓库同步过去。
2. 可部署的东西只有两类：`extra/`、`docker-compose.yml`。
   镜像本身由 GitHub Actions 构建，NAS 只负责 `pull`。
   `.env` **不由脚本同步** —— 它含密钥，只在 NAS 上手工维护，改动单独走。
3. 每次部署都留下可回滚的快照，靠现成的 `backup.sh` 产出的
   `backups/config-<时间>.tar.gz`（它已经打包了 `.env` / compose / patches / extra），
   不必另造一套快照机制。

## 流程

```
预检 → 备份 → 拉镜像 → 同步配置 → 重建受影响容器 → 健康检查 + 补丁校验 → (失败) 回滚 → 记录
```

### 1. 预检

- SSH 能连（`-o NumberOfPasswordPrompts=1`，同一时刻只开一条连接）
- `/volume1` 剩余空间 > 5GB（当前 4.7T 可用，基本不会卡在这里）
- 当前五个容器都在 running 且 healthy —— **本来就不健康时不要部署**，
  否则事后分不清是部署引入的还是原本就坏的
- 本地仓库工作区干净（`git status --porcelain` 为空），记下将要部署的 commit
- 本地 `docker-compose -f docker-compose.yml config -q` 验证语法，
  免得把一个语法错的 compose 推上去

### 2. 备份

直接调生产已有的 `sh /volume1/docker/learnhouse/backup.sh`。
它会产出 db dump、redis 归档、config 归档，并且自带「dump 不以 PGDMP 开头就删掉并报错」
的自检。脚本要检查它的退出码，非 0 立即中止部署。

记下这次 `config-<时间>.tar.gz` 的文件名，它就是回滚点。

### 3. 拉镜像

```sh
docker-compose pull learnhouse-app
```

镜像来自 `ghcr.io/godarrenw/learnhouse`，已是公开包，NAS 不用登录。
**建议用钉死 sha 的 tag**（`:sysu-sam-<sha7>`）而不是浮动的 `:sysu-sam`，
这样「NAS 上跑的是哪个 commit」一眼可查，回滚也只是换回上一个 tag。

拉完记下 image id，回滚时用得上。

### 4. 同步配置

用一条 SSH 连接的 tar 流推过去（这台 NAS 没开 SFTP 子系统，scp 不可用）：

```sh
tar -cf - extra docker-compose.yml | ssh … 'tar -C /volume1/docker/learnhouse -xf -'
```

**不需要 sudo**，也不需要先落 `/tmp` 中转（2026-09-10 在 NAS 上查实）：
部署目录 `/volume1/docker/learnhouse` 及其下的 `docker-compose.yml`、`extra`、`patches`
属主都是 `SAM-IPA518:users`，而该账号本身就在 `administrators` 组里，
普通用户身份直接解包覆盖即可。

例外是 `.env`（权限 600）和 `backups/`（里面的文件是 root 属主），读写都要 sudo。
这两样本来就不在同步清单里；回滚时解 `backups/` 里的归档仍然要走 sudo。

### 5. 重建受影响容器

**必须是 `up -d --force-recreate <服务>`，不能是 reload 或 restart。**

原因：`extra/nginx.prod.conf` 是**单文件 bind-mount**，Docker 钉的是宿主机上那个文件的
inode。`tar` 解包是「写新文件替换旧文件」，新文件是新 inode，运行中的容器看到的仍然是旧的
那个。`nginx -s reload` 同理，重读的还是容器里挂着的旧 inode。只有重建容器才会按路径重新挂载。

（换自建镜像后，patches 的单文件挂载没有了，但 nginx 这条还在，所以这条铁律依然适用。）

判断「受影响」：
- 只改了 `extra/nginx.prod.conf` → 重建 `nginx`
- 换了镜像 tag，或改了 compose 里 app 的段落 → 重建 `learnhouse-app`
  （连带 `ssr-fwd`，它是 `network_mode: service:learnhouse-app`，app 一重建它必须跟着重建）
- 改了 db/redis 段落 → 单独确认，这两个动一次风险高得多，不要顺手带上

生产上的命令是 **`docker-compose`（v1）**，不是 `docker compose`。
已确认：`/usr/local/bin/docker-compose` 是指向 ContainerManager 的软链，
而 `docker compose` 子命令在这台机器上不存在。

### 6. 健康检查 + 补丁校验

重建后轮询，任何一项在超时内没通过就判失败：

- `GET http://127.0.0.1:8088/api/v1/orgs/slug/default` → 200 且 JSON 里 `slug == "default"`
- `GET http://127.0.0.1:8088/` → 200
- `docker-compose ps` 里五个容器都 healthy

app 冷启要跑迁移，超时给到 240s（生产 `start_period` 是 180s）。

**换镜像的部署还要多跑一次补丁校验**，命令见 `../docs/sysu-sam/PATCHES.md`。
这一步替代了老流程里的「确认前端 chunk 挂载点文件名是否还在」——
那个问题（挂到不存在的文件名上不报错、补丁静默失效）在自建镜像模型下已经不存在了，
但「新镜像里补丁是不是真的编进去了」仍然要验。

### 7. 失败回滚

把第 2 步记下的 `config-<时间>.tar.gz` 解回 `/volume1/docker/learnhouse/`
（只解 `extra`、`docker-compose.yml`，**不要覆盖 `.env`**），
然后对同一批服务再做一次 `up -d --force-recreate`，重跑健康检查。
回滚后的健康检查再失败，就停下来报警，不要继续自动动作。

⚠️ 回滚到**切换自建镜像之前**的那份 compose 时要留意：那份 compose 里有 5 条
`./patches/...` 的 bind-mount，NAS 上的 `patches/` 目录必须还在，否则 Docker 会
按目录创建挂载点，app 起来但补丁全失效。所以 **NAS 上的 `patches/` 不要删**，
留着当回滚保险，本仓库 `README.md` 的「patches 目录的去向」一节也是这么写的。

### 8. 记录

追加一行到 NAS 上的 `deploy.log`：时间、本地 commit、镜像 tag、部署了哪些文件、
重建了哪些服务、健康检查结果、备份文件名。

## 尚未决定的事

- 是否把 `.env` 的**非密钥部分**也纳入仓库管理（例如站点名、AI 模型名）。
  好处是可追溯，代价是要拆成两个文件再在 NAS 上拼。
- 是否在部署前自动 diff 一次「NAS 上的现状 vs 仓库」，
  发现有人手工改过就中止。这个很有价值，但需要先把仓库和 NAS 对齐一次 ——
  目前仓库里的 `docker-compose.yml` 已经是自建镜像形态，与 NAS 现状不同，
  第一次部署本身就是那次对齐。
- 部署脚本要不要自己去 GitHub 查「这个 commit 的镜像构建成功了没」，
  而不是闷头 `pull` 一个可能还没推上去的 tag。
