#!/usr/bin/env bash
# 部署到生产（群晖 NAS）。流程说明见 DEPLOY.md。
#
# ⚠️ 骨架，未在生产执行过，里面还有若干 TODO。
#    跑之前先把 NAS_HOST 指向本地栈（learnhouse-local）演练一遍。
#
# 本脚本由 learnhouse-local/deploy.sh 并入，并按**自建镜像**的部署模型改写：
#   - 同步清单里没有 patches/（补丁已是源码，编进镜像）
#   - 多了一步 pull 新镜像
#   - 健康检查后多一步「镜像内补丁是否真的编进去了」的校验
set -euo pipefail
cd "$(dirname "$0")"

NAS_USER=SAM-IPA518
NAS_HOST=172.25.5.162
NAS_DIR=/volume1/docker/learnhouse
DC=/usr/local/bin/docker-compose          # 生产是 compose v1，没有 `docker compose`
BASE=http://127.0.0.1:8088
APP=learnhouse-app-nas
SERVICES="${SERVICES:-}"                  # 要重建的服务，留空则由改动自动推断

die() { echo "[部署中止] $*" >&2; exit 1; }
log() { echo "[$(date +%F' '%H:%M:%S)] $*"; }

: "${LH_NAS_PASSWORD:?需要 LH_NAS_PASSWORD}"

# 同一时刻只允许一条到这台 NAS 的 SSH 连接，别的代理可能正在用，最多等 5 分钟。
waited=0
while pgrep -fl "ssh .*${NAS_HOST}" >/dev/null 2>&1; do
  [ "$waited" -ge 300 ] && die "等待 SSH 空闲超时"
  echo "已有到 NAS 的 SSH 连接，等 10 秒…"; sleep 10; waited=$((waited+10))
done
export SSHPASS="$LH_NAS_PASSWORD"
SSH="sshpass -e ssh -o NumberOfPasswordPrompts=1 -o StrictHostKeyChecking=no ${NAS_USER}@${NAS_HOST}"
# 密码一律用 herestring 喂 sudo，不要用管道（ssh 不读完 stdin，printf 会吃 SIGPIPE）
# sudo 命令必须整条交给 `sh -c`：直接写 `sudo cd X && Y` 的话，
# sudo 执行的是内建命令 cd（command not found），&& 短路，Y 根本不跑；
# 就算跑了也是无 sudo 状态，会撞 docker.sock 权限不足。
sudo_ssh() { $SSH "sudo -S -p '' sh -c $(printf '%q' "$1")" <<< "$LH_NAS_PASSWORD"; }

# --- 1. 预检 -----------------------------------------------------------------
log "预检…"
[ -z "$(git status --porcelain)" ] || die "工作区不干净，先提交或 stash"
COMMIT=$(git rev-parse --short HEAD)
log "将要部署的 commit：${COMMIT}"
# compose 里写了 env_file: .env，而仓库里没有 .env（含密钥，不入库），
# 直接 config 会因为找不到 .env 报错。用一个临时空 .env 过语法检查。
_tmpenv=0; [ -f .env ] || { : > .env; _tmpenv=1; }
docker-compose -f docker-compose.yml config -q || { [ "$_tmpenv" = 1 ] && rm -f .env; die "本地 compose 语法错"; }
[ "$_tmpenv" = 1 ] && rm -f .env || true
# 仓库里已经没有 patches/ 了；如果它又出现，说明有人在走老的 bind-mount 模型
[ ! -d patches ] || die "deploy/ 下不该有 patches/，补丁应该在源码里（见 docs/sysu-sam/PATCHES.md）"
$SSH true <<< "$LH_NAS_PASSWORD" || die "SSH 连不上"
FREE=$($SSH "df -P /volume1 | tail -1 | awk '{print \$4}'" <<< "$LH_NAS_PASSWORD")
[ "${FREE:-0}" -gt 5000000 ] || die "磁盘不足：${FREE}KB"
# TODO: sudo_ssh "$DC -f $NAS_DIR/docker-compose.yml ps" 解析出五个容器都 healthy，否则中止

# --- 2. 备份 -----------------------------------------------------------------
log "调用生产 backup.sh…"
sudo_ssh "sh ${NAS_DIR}/backup.sh" || die "备份失败"
ROLLBACK=$(sudo_ssh "ls -1t ${NAS_DIR}/backups/config-*.tar.gz | head -1")
log "回滚点：${ROLLBACK}"

# --- 3. 拉镜像 ---------------------------------------------------------------
# 镜像由 GitHub Actions 构建推到 ghcr.io/godarrenw/learnhouse（公开包，不用登录）。
# 建议 compose 里钉 :sysu-sam-<sha7> 而不是浮动的 :sysu-sam，回滚只需换回上一个 tag。
# TODO: pull 之前先查一下这个 commit 的构建成功了没，别闷头拉一个还没推上去的 tag：
#       gh run list -R godarrenw/learnhouse --limit 1
log "拉取新镜像…"
sudo_ssh "cd ${NAS_DIR} && $DC pull learnhouse-app" || die "拉镜像失败"
OLD_IMG=$(sudo_ssh "docker inspect --format '{{.Image}}' ${APP}" || true)
log "当前 app 镜像：${OLD_IMG:-未知}"

# --- 4. 同步配置 -------------------------------------------------------------
log "同步 extra / docker-compose.yml…"
# .env 不同步：含密钥，只在 NAS 上手工维护
# patches 不同步：补丁已经在镜像里
# 注意这里不能用 herestring 喂密码：herestring 会顶掉管道成为 stdin，
# 远端 tar 收到的就是密码字节而不是归档。sshpass -e 已经从 SSHPASS 拿 SSH 密码了。
# TODO: 未验证 SAM-IPA518 是否有权覆盖 NAS_DIR 下那些文件（属主/权限还没核实）。
#       不行就先 tar 到 /tmp，再 sudo_ssh 解包到 NAS_DIR。
tar -cf - extra docker-compose.yml \
  | $SSH "tar -C ${NAS_DIR} -xf -" || die "同步失败"

# --- 5. 重建受影响容器 -------------------------------------------------------
# 必须 --force-recreate：extra/nginx.prod.conf 是单文件 bind-mount，钉的是 inode，
# tar 解包换了新 inode，运行中的容器看到的还是旧文件；reload / restart 都没用。
[ -n "$SERVICES" ] || SERVICES="learnhouse-app ssr-fwd nginx"   # TODO: 按 diff 自动推断
log "重建：${SERVICES}"
sudo_ssh "cd ${NAS_DIR} && $DC up -d --force-recreate ${SERVICES}" || die "重建失败"
# （sudo_ssh 会把整条串交给 sh -c，所以 cd && 是安全的）

# --- 6. 健康检查 -------------------------------------------------------------
log "健康检查…"
# 轮询必须在**一条** SSH 连接里做完。这台 NAS 对短时间内重复建连会直接拒，
# 48 次各开一条连接必然中途被拒，把「被拒」误判成「部署失败」。
ok=0
if $SSH "for i in \$(seq 1 48); do
     c=\$(curl -s -o /dev/null -w '%{http_code}' ${BASE}/api/v1/orgs/slug/default);
     h=\$(curl -s -o /dev/null -w '%{http_code}' ${BASE}/);
     if [ \"\$c\" = 200 ] && [ \"\$h\" = 200 ]; then echo HEALTHY; exit 0; fi;
     sleep 5;
   done; exit 1" <<< "$LH_NAS_PASSWORD" | grep -q HEALTHY; then ok=1; fi
# TODO: 再加一条「slug == default」的 JSON 断言，光看 200 不够
# TODO: docker-compose ps 里五个容器都 healthy 也要校验

# --- 6b. 补丁校验（换镜像的部署必做）-----------------------------------------
# 老流程这里查的是「前端 chunk 挂载点文件名是否还在」。自建镜像模型下那个问题不存在了，
# 但要验「新镜像里补丁是不是真的编进去了」。完整说明见 docs/sysu-sam/PATCHES.md。
if [ "$ok" = 1 ]; then
  log "校验镜像内补丁…"
  PATCHCHK=$(sudo_ssh "docker exec ${APP} sh -c \"
      grep -c 'PATCH(nas)' /app/api/src/services/ai/courseplanning.py &&
      grep -c 'images/generations' /app/api/src/services/ai/image/generator.py &&
      grep -c '登录先进智造学堂' /app/api/src/services/auth/magic_login.py &&
      grep -rl '先进智造学堂' /app/web/.next/static/chunks/ | head -1 &&
      grep -rl assignment-course-structure /app/web/.next/static/chunks/ | xargs grep -l getCourseMetadata
    \"" || true)
  echo "$PATCHCHK"
  # 五项都要有输出；任何一项空就说明这个镜像不是从 sysu-sam 分支建出来的
  [ "$(printf '%s\n' "$PATCHCHK" | grep -c .)" -ge 5 ] || { ok=0; log "补丁校验未通过"; }
fi

# --- 7. 回滚 -----------------------------------------------------------------
if [ "$ok" != 1 ]; then
  log "检查未通过，回滚到 ${ROLLBACK}"
  # 只解两样，绝不覆盖 .env
  # ⚠️ 若回滚到「切换自建镜像之前」的 compose，它含 5 条 ./patches/... 挂载，
  #    NAS 上的 patches/ 目录必须还在，否则 Docker 会按目录建挂载点、补丁全失效。
  sudo_ssh "tar -C ${NAS_DIR} -xzf '${ROLLBACK}' extra docker-compose.yml" || die "回滚解包失败"
  sudo_ssh "cd ${NAS_DIR} && $DC up -d --force-recreate ${SERVICES}" || die "回滚重建失败"
  # TODO: 回滚后重跑一次健康检查；再失败就停下报警，不要继续自动动作
  die "已回滚"
fi

# --- 8. 记录 -----------------------------------------------------------------
log "部署成功"
# TODO: 追加一行到 NAS 的 deploy.log：时间 / commit / 镜像 tag / 文件 / 服务 / 健康结果 / 备份名
