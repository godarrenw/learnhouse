# 部署演练记录（2026-09-10）

在本机隔离演练栈上把 `deploy.sh` 整条链路跑通，并故意制造一次失败验证自动回滚。
**全程没有碰生产 NAS，没有 SSH，没有重建镜像。**

## 为什么不在 learnhouse-local 上演练

原计划的演练目标是 `/Volumes/D/code/learnhouse-local`，改成了新建的
`/Volumes/D/code/learnhouse-rehearsal`。原因：演练开始时那个栈的五个容器都在 Up 且
healthy，正被另一个代理使用。而演练会把**生产形态**的 `docker-compose.yml`
（项目名 `learnhouse-nas`、端口 8088、无 patches 挂载）同步过去再 force-recreate，
等于把人家正在用的环境拆掉，还会留下一批孤儿容器。

隔离栈与它零交叉：

| | learnhouse-local | learnhouse-rehearsal |
|---|---|---|
| compose 项目名 | `learnhouse-local` | `learnhouse-reh` |
| 端口 | 18088 | 28088 |
| 网段 | 172.21.0.0/24 | 172.22.0.0/24 |
| 数据 | 从生产备份恢复并脱敏 | 空库冷启，自建管理员 |

换目录不影响演练目的（验的是脚本逻辑），而且空库冷启动要跑数据库迁移，
正好压到健康检查 240s 超时那条路径。

## 演练栈怎么搭的

演练栈 = 生产 `docker-compose.yml` + 一层只写差异的
`docker-compose.rehearsal.yml`（容器名后缀 `-reh`、端口 28088、网段 172.22、
镜像换成本机构建的 `learnhouse-sysu-sam:local`）。生产那份仍是唯一真相源。

`.env` 由 `deploy/.env.example` 生成，密钥现随机生成，AI 与发信关闭。

> **`ports` 必须写 `!override`。** compose 合并 `ports` 是**追加**不是替换，
> 不加的话会同时尝试绑 8088 和 28088，第一次起栈就因为 8088 被别的项目占着而失败。

## 跑了什么

四轮，全部有真实输出：

| 轮次 | 场景 | 结果 |
|---|---|---|
| 1 | 成功路径（带 `ALLOW_DIRTY`） | 通过，`deploy.log` 记 `OK` |
| 2 | 成功路径 | 通过，`deploy.log` 记 `OK` |
| 3 | 故障注入 `DRY_IMAGE=nginx:alpine` | 重建失败 → 回滚 → 复检通过，记 `ROLLED_BACK` |
| 4 | 成功路径，干净工作区，不带 `ALLOW_DIRTY` | 通过，`deploy.log` 记 `OK` |

成功路径覆盖：预检（工作区干净 + compose 语法 + 目标可达 + 五容器 healthy）→
备份 → 确认镜像 → 同步 `extra`/compose → force-recreate → HTTP 健康检查
（`/` 返回 200 且 `orgs/slug/default` 的 JSON 里 `slug == default`）→
容器状态检查 → 镜像内补丁校验 5/5 → 写 `deploy.log`。

`deploy.log` 实际内容（路径已保留，无敏感信息）：

```
19:49:59  OK           commit=a7d44434  services=learnhouse-app ssr-fwd nginx  健康检查与补丁校验均通过
19:51:04  OK           commit=a7d44434  services=learnhouse-app ssr-fwd nginx  健康检查与补丁校验均通过
19:58:17  ROLLED_BACK  commit=a7d44434  services=learnhouse-app ssr-fwd nginx  回滚后健康检查通过
19:59:50  OK           commit=a7d44434  services=learnhouse-app ssr-fwd nginx  健康检查与补丁校验均通过
```

故障注入那轮的关键时序：

```
19:51:48  注入 nginx:alpine 作为 app 镜像，同步，force-recreate
19:57:27  dependency failed to start: container learnhouse-app-reh is unhealthy   ← 等了 5 分 39 秒
19:57:27  HTTP 检查未通过 → 回滚到 config-2026-09-10-1951.tar.gz
19:58:17  回滚后复跑健康检查通过，服务恢复
```

回滚后 `curl /api/v1/orgs/slug/default` 返回 200，五个容器全部 healthy，
仓库里被注入改写的 `docker-compose.rehearsal.yml` 由 trap 自动还原。

## 演练查出来的五个缺陷

前四个**生产同样会踩**，这是这次演练最大的收获。

### 1. backup.sh 会静默中止，调用方拿不到原因

config 归档那行写死了 `patches`：

```sh
tar -czf "$B/config-$TS.tar.gz" -C "$D" .env docker-compose.yml patches extra 2>/dev/null
```

切到自建镜像后 `patches/` 可能已经不在（补丁进了源码），`tar` 便以非零退出。
配合 `set -e`，脚本在这里中止 —— 后面的保留期清理、`chmod 600`、`[备份完成]`
全都不执行。而 `2>/dev/null` 把 `tar` 的报错吞了，调用方只看到「备份失败」，
db dump 和 redis 归档其实已经好了。

改为遍历候选清单只打包存在的项，并去掉那个 `2>/dev/null`。

### 2. 重建失败直接退出，不回滚

`dc up` 返回非零就 `die`，服务被留在半新半旧的状态没人收拾。
改为记下失败继续走健康检查与回滚。故障注入那轮正是靠这条才滚回来的。

### 3. 容器状态只采样一次，会把成功的部署判成重大故障

nginx 的 healthcheck 是 `interval: 30s` 且**没有 `start_period`**，
刚 `recreate` 完必然处于 `starting`，哪怕它已经在正常服务。
一次采样必然判失败并触发无谓回滚；回滚后再采样又是 `starting`，
于是升级成「回滚后仍失败，需人工介入」。演练第一轮就是这么挂的。

新增 `wait_containers()`：`starting` 视为未就绪继续等，最多 240s。
预检也改用它（120s），刚重建过的栈不该被判成「本来就坏」。

### 4. `compose config | awk '…{exit}'` 触发 SIGPIPE，脚本无声中止

`awk` 提前 `exit` 让上游 compose 收到 SIGPIPE，配合 `set -o pipefail`
整条管道非零，脚本一行错误都不打就退出。改为先落变量再取值。

同类问题还有一处：仓库里没有 `.env`（含密钥不入库）而 compose 写了 `env_file: .env`，
凡是在仓库目录跑 compose 都要用临时空 `.env` 顶一下。原先只在语法预检处理了，
取镜像名那处漏了。统一收进 `repo_compose_config()`。

### 5. DRY_IMAGE 注入无效（仅演练）

原来改的是部署目录里的文件，随后被 `sync_files` 用仓库版覆盖，等于没注入。
改为改仓库里那份并用 `trap` 保证退出时一定还原，同时限制只能在 `TARGET=local` 用。

## 还没验到的

演练栈与生产终究不是一回事，下面几项只有真部署才能验：

- **SSH 那条路完全没走。** `remote` / `remote_sudo` / `sync_files` 在 `TARGET=local`
  下是本地执行，`sshpass`、herestring 喂 sudo、tar 流过 SSH、
  「同一时刻只开一条连接」的等待逻辑，一行都没执行到。
- **`docker-compose pull`。** 演练用本机镜像，走的是 `docker image inspect` 分支。
  生产那条 `dc pull` 没跑过，ghcr 拉取、磁盘占用、拉取耗时都未知。
- **compose v1 与 v2 的差异。** 生产是 `/usr/local/bin/docker-compose`（v1），
  本机同名命令实际是 v5.0.1。`-p`、`-f` 叠加、`!override` 标签在 v1 上的行为需要确认，
  **`!override` 是 compose 规范较新的特性，v1 很可能不支持** ——
  但它只出现在演练用的 override 文件里，生产不加载那个文件，所以不影响生产部署。
- **240s 够不够。** 演练机是 Mac，NAS 只有 4G 内存且在用 swap，冷启跑迁移会慢得多。
  生产 `start_period` 是 180s，第一次真部署要盯着看实际用了多久。
- **权限。** 同步不需要 sudo 这一条是查实的（属主 `SAM-IPA518:users`，
  账号在 `administrators` 组），但没有真写过一次。
- **磁盘预检**只在 `TARGET=prod` 分支里，演练跳过了。

## 复现方式

```sh
cd /Volumes/D/code/learnhouse/deploy
TARGET=local ./deploy.sh                                  # 成功路径
TARGET=local ALLOW_DIRTY=1 DRY_IMAGE=nginx:alpine ./deploy.sh   # 故障注入验回滚
```

演练栈首次搭建见本文「演练栈怎么搭的」。栈不用了就
`docker-compose -p learnhouse-reh -f docker-compose.yml -f docker-compose.rehearsal.yml down -v`。
