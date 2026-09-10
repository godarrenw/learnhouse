#!/usr/bin/env bash
# 部署 LearnHouse 到生产（群晖 NAS）或演练栈。流程说明见 DEPLOY.md。
#
#   TARGET=prod  ./deploy.sh     部署到生产 NAS（默认）
#   TARGET=local ./deploy.sh     部署到本机演练栈，用于验证脚本本身
#
# 两个模式**共用同一段流程代码**，差异全部收敛在下面 target 配置块里的几个变量和
# 三个执行原语（remote / remote_sudo / sync_files）。改流程只改一处。
#
# 本脚本由 learnhouse-local/deploy.sh 并入，并按**自建镜像**的部署模型改写：
#   - 同步清单里没有 patches/（补丁已是源码，编进镜像）
#   - 多了一步 pull 新镜像
#   - 健康检查后多一步「镜像内补丁是否真的编进去了」的校验
set -euo pipefail
cd "$(dirname "$0")"
REPO_DEPLOY_DIR="$PWD"

TARGET="${TARGET:-prod}"
DRY_IMAGE="${DRY_IMAGE:-}"          # 演练用：强行把 app 镜像改成这个 tag（验回滚）

die() { echo "[部署中止] $*" >&2; exit 1; }
log() { echo "[$(date +%F' '%H:%M:%S)] $*"; }

# ==== target 配置 ============================================================
case "$TARGET" in
prod)
  NAS_USER=SAM-IPA518
  NAS_HOST=172.25.5.162
  DEPLOY_DIR=/volume1/docker/learnhouse
  DC=/usr/local/bin/docker-compose        # 生产是 compose v1，没有 `docker compose`
  DOCKER=/usr/local/bin/docker
  DC_FILES="-f docker-compose.yml"
  COMPOSE_PROJECT=learnhouse-nas
  BASE=http://127.0.0.1:8088
  APP=learnhouse-app-nas
  HEALTHY_CONTAINERS="learnhouse-app-nas learnhouse-nginx-nas learnhouse-db-nas learnhouse-redis-nas"
  RUNNING_CONTAINERS="learnhouse-ssr-fwd-nas"   # 这个没配 healthcheck，只看 running

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
  remote()      { $SSH "$1" <<< "$LH_NAS_PASSWORD"; }
  # sudo 命令必须整条交给 `sh -c`：直接写 `sudo cd X && Y` 的话，
  # sudo 执行的是内建命令 cd（command not found），&& 短路，Y 根本不跑；
  # 就算跑了也是无 sudo 状态，会撞 docker.sock 权限不足。
  remote_sudo() { $SSH "sudo -S -p '' sh -c $(printf '%q' "$1")" <<< "$LH_NAS_PASSWORD"; }
  sync_files() {
    # 这一步**不需要 sudo**，也不需要先落 /tmp 中转（2026-09-10 已在 NAS 上查实）：
    #   uid=1026(SAM-IPA518) gid=100(users) groups=100(users),101(administrators),1023(http)
    #   部署目录及其下的 docker-compose.yml / extra / patches 属主都是 SAM-IPA518:users，
    #   且该账号在 administrators 组里。
    # 例外是 .env（600）和 backups/（文件 root 属主），读写都要 sudo ——
    # 但这两样本来就不在同步清单里；回滚时解 backups 里的归档仍然走 remote_sudo。
    #
    # 注意这里不能用 herestring 喂密码：herestring 会顶掉管道成为 stdin，
    # 远端 tar 收到的就是密码字节而不是归档。sshpass -e 已经从 SSHPASS 拿 SSH 密码了。
    tar -cf - extra docker-compose.yml | $SSH "tar -C ${DEPLOY_DIR} -xf -"
  }
  ;;
local)
  DEPLOY_DIR="${REHEARSAL_DIR:-/Volumes/D/code/learnhouse-rehearsal}"
  DC=docker-compose
  DOCKER=docker
  # 演练栈 = 生产 compose + 一层 override（改镜像/端口/网段/容器名），
  # 生产那份仍是唯一真相源，override 只写差异。
  DC_FILES="-f docker-compose.yml -f docker-compose.rehearsal.yml"
  COMPOSE_PROJECT=learnhouse-reh
  BASE=http://127.0.0.1:28088
  APP=learnhouse-app-reh
  HEALTHY_CONTAINERS="learnhouse-app-reh learnhouse-nginx-reh learnhouse-db-reh learnhouse-redis-reh"
  RUNNING_CONTAINERS="learnhouse-ssr-fwd-reh"

  remote()      { bash -c "$1"; }
  remote_sudo() { bash -c "$1"; }        # 本机不需要提权
  sync_files() {
    tar -cf - extra docker-compose.yml docker-compose.rehearsal.yml \
      | tar -C "${DEPLOY_DIR}" -xf -
  }
  ;;
*) die "TARGET 只能是 prod 或 local（当前：${TARGET}）" ;;
esac

# 在部署目录里跑 compose 的统一入口，两个模式共用
dc() { remote_sudo "cd ${DEPLOY_DIR} && ${DC} -p ${COMPOSE_PROJECT} ${DC_FILES} $*"; }

log "TARGET=${TARGET}  部署目录=${DEPLOY_DIR}  项目=${COMPOSE_PROJECT}"

# ==== 1. 预检 ================================================================
log "预检…"
[ -z "$(git status --porcelain)" ] || die "工作区不干净，先提交或 stash"
COMMIT=$(git rev-parse --short HEAD)
log "将要部署的 commit：${COMMIT}"

# compose 里写了 env_file: .env，而仓库里没有 .env（含密钥，不入库），
# 直接 config 会因为找不到 .env 报错。用一个临时空 .env 过语法检查。
_tmpenv=0; [ -f .env ] || { : > .env; _tmpenv=1; }
${DC} ${DC_FILES} config -q || { [ "$_tmpenv" = 1 ] && rm -f .env; die "本地 compose 语法错"; }
[ "$_tmpenv" = 1 ] && rm -f .env || true

# 仓库里已经没有 patches/ 了；如果它又出现，说明有人在走老的 bind-mount 模型
[ ! -d patches ] || die "deploy/ 下不该有 patches/，补丁应该在源码里（见 docs/sysu-sam/PATCHES.md）"

remote "true" >/dev/null 2>&1 || die "连不上部署目标"
remote "test -d ${DEPLOY_DIR}" || die "部署目录不存在：${DEPLOY_DIR}"

if [ "$TARGET" = prod ]; then
  FREE=$(remote "df -P /volume1 | tail -1 | awk '{print \$4}'")
  [ "${FREE:-0}" -gt 5000000 ] || die "磁盘不足：${FREE}KB"
fi

# 本来就不健康时不要部署，否则事后分不清是部署引入的还是原本就坏的
check_containers() {   # 打印不健康的容器名，全好则无输出
  local c st
  for c in $HEALTHY_CONTAINERS; do
    st=$(remote "${DOCKER} inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}nohealth{{end}}' ${c} 2>/dev/null" || echo missing)
    [ "$st" = healthy ] || echo "${c}=${st}"
  done
  for c in $RUNNING_CONTAINERS; do
    st=$(remote "${DOCKER} inspect -f '{{.State.Status}}' ${c} 2>/dev/null" || echo missing)
    [ "$st" = running ] || echo "${c}=${st}"
  done
}
if [ "${SKIP_PREFLIGHT_HEALTH:-0}" != 1 ]; then
  BAD=$(check_containers)
  [ -z "$BAD" ] || die "部署前就有容器不健康，先修好再部署：${BAD}"
  log "预检：五个容器都正常"
fi

# ==== 1b. 按 diff 推断受影响服务（保守版）====================================
# 保守策略：compose 或 extra 任何一处变了，就重建 nginx + app + ssr-fwd。
# ssr-fwd 是 network_mode: service:learnhouse-app，app 一重建它必须跟着重建。
# db / redis 永远不自动重建 —— 这两个动一次风险高得多，要动就显式设 SERVICES。
if [ -z "${SERVICES:-}" ]; then
  CHANGED=""
  remote "cat ${DEPLOY_DIR}/docker-compose.yml 2>/dev/null" > /tmp/.lh_remote_compose 2>/dev/null || true
  cmp -s /tmp/.lh_remote_compose docker-compose.yml || CHANGED="${CHANGED} compose"
  for f in extra/*; do
    remote "cat ${DEPLOY_DIR}/${f} 2>/dev/null" > /tmp/.lh_remote_f 2>/dev/null || true
    cmp -s /tmp/.lh_remote_f "$f" || CHANGED="${CHANGED} ${f}"
  done
  rm -f /tmp/.lh_remote_compose /tmp/.lh_remote_f
  if [ -n "$CHANGED" ]; then
    SERVICES="learnhouse-app ssr-fwd nginx"
    log "检测到改动：${CHANGED} → 重建 ${SERVICES}"
  else
    SERVICES="learnhouse-app ssr-fwd nginx"
    log "配置无改动，但仍按换镜像处理，重建 ${SERVICES}"
  fi
fi

# ==== 2. 备份 ================================================================
log "备份…"
if [ "$TARGET" = prod ]; then
  remote_sudo "sh ${DEPLOY_DIR}/backup.sh" || die "备份失败"
else
  # backup.sh 的目录与容器名都可用环境变量覆盖，生产不设就是原来的值
  remote_sudo "LH_DOCKER=${DOCKER} LH_DIR=${DEPLOY_DIR} \
     LH_DB_CONTAINER=learnhouse-db-reh LH_REDIS_CONTAINER=learnhouse-redis-reh \
     sh ${DEPLOY_DIR}/backup.sh" || die "备份失败"
fi
ROLLBACK=$(remote_sudo "ls -1t ${DEPLOY_DIR}/backups/config-*.tar.gz | head -1")
[ -n "$ROLLBACK" ] || die "找不到回滚点"
log "回滚点：${ROLLBACK}"

# ==== 3. 拉/确认镜像 =========================================================
# 演练模式用本机已构建的 learnhouse-sysu-sam:local（arm64），没有 pull 这一说。
# 生产模式从 ghcr.io/godarrenw/learnhouse 拉（公开包，不用登录）。
# 建议 compose 里钉 :sysu-sam-<sha7> 而不是浮动的 :sysu-sam，回滚只需换回上一个 tag。
if [ -n "$DRY_IMAGE" ]; then
  log "⚠️ DRY_IMAGE=${DRY_IMAGE}，强行改写 app 镜像（演练用）"
  remote "cd ${DEPLOY_DIR} && sed -i.bak 's#^\\( *image: \\).*learnhouse.*#\\1${DRY_IMAGE}#' docker-compose.rehearsal.yml"
fi
if [ "$TARGET" = prod ]; then
  # TODO: pull 之前先查这个 commit 的构建成功了没，别闷头拉一个还没推上去的 tag：
  #       gh run list -R godarrenw/learnhouse --limit 1
  log "拉取新镜像…"
  dc "pull learnhouse-app" || die "拉镜像失败"
else
  IMG=$(${DC} ${DC_FILES} config 2>/dev/null | awk '/learnhouse-app:/{f=1} f&&/image:/{print $2; exit}')
  log "演练镜像：${IMG}"
  remote "${DOCKER} image inspect ${IMG} >/dev/null 2>&1" \
    || die "本机没有镜像 ${IMG}（演练不重建镜像，请先 docker build 或换 tag）"
fi
OLD_IMG=$(remote "${DOCKER} inspect --format '{{.Image}}' ${APP} 2>/dev/null" || true)
log "当前 app 镜像层：${OLD_IMG:-未知}"

# ==== 4. 同步配置 ============================================================
log "同步 extra / docker-compose.yml…"
# .env 不同步：含密钥，只在目标机上手工维护
# patches 不同步：补丁已经在镜像里
sync_files || die "同步失败"

# ==== 5. 重建受影响容器 ======================================================
# 必须 --force-recreate：extra/nginx.prod.conf 是单文件 bind-mount，钉的是 inode，
# tar 解包换了新 inode，运行中的容器看到的还是旧文件；reload / restart 都没用。
log "重建：${SERVICES}"
dc "up -d --force-recreate ${SERVICES}" || die "重建失败"

# ==== 6. 健康检查 ============================================================
# 轮询必须在**一条** SSH 连接里做完。这台 NAS 对短时间内重复建连会直接拒，
# 48 次各开一条连接必然中途被拒，把「被拒」误判成「部署失败」。
# app 冷启要跑迁移，48×5s=240s（生产 start_period 是 180s）。
log "健康检查（HTTP）…"
ok=0
# --noproxy '*'：NAS 上没有代理无所谓，本机演练时系统代理会劫持 127.0.0.1，必须绕开
POLL="for i in \$(seq 1 48); do
   c=\$(curl -s --noproxy '*' ${BASE}/api/v1/orgs/slug/default || true);
   h=\$(curl -s --noproxy '*' -o /dev/null -w '%{http_code}' ${BASE}/ || true);
   case \"\$c\" in *'\"slug\":\"default\"'*) sc=1;; *) sc=0;; esac;
   if [ \"\$sc\" = 1 ] && [ \"\$h\" = 200 ]; then echo HEALTHY; exit 0; fi;
   sleep 5;
 done; exit 1"
if remote "$POLL" 2>/dev/null | grep -q HEALTHY; then ok=1; fi
[ "$ok" = 1 ] && log "HTTP 通过：/ 返回 200，orgs/slug/default 的 JSON 里 slug == default" \
             || log "HTTP 检查未通过"

# 容器状态：四个带 healthcheck 的要 healthy，ssr-fwd 只看 running
if [ "$ok" = 1 ]; then
  log "健康检查（容器状态）…"
  BAD=$(check_containers)
  if [ -n "$BAD" ]; then ok=0; log "容器状态异常：${BAD}"; else log "五个容器状态正常"; fi
fi

# ==== 6b. 镜像内补丁校验（换镜像的部署必做）==================================
# 老流程这里查的是「前端 chunk 挂载点文件名是否还在」。自建镜像模型下那个问题不存在了，
# 但要验「新镜像里补丁是不是真的编进去了」。完整说明见 docs/sysu-sam/PATCHES.md。
if [ "$ok" = 1 ]; then
  log "校验镜像内补丁…"
  PATCHCHK=$(remote "${DOCKER} exec ${APP} sh -c \"
      grep -c 'PATCH(nas)' /app/api/src/services/ai/courseplanning.py;
      grep -c 'images/generations' /app/api/src/services/ai/image/generator.py;
      grep -c '登录先进智造学堂' /app/api/src/services/auth/magic_login.py;
      grep -rl '先进智造学堂' /app/web/.next/static/chunks/ | head -1;
      grep -rl assignment-course-structure /app/web/.next/static/chunks/ | xargs grep -l getCourseMetadata
    \"" 2>/dev/null || true)
  echo "$PATCHCHK"
  # 五项都要有输出；任何一项空就说明这个镜像不是从 sysu-sam 分支建出来的
  if [ "$(printf '%s\n' "$PATCHCHK" | grep -c .)" -ge 5 ]; then
    log "补丁校验通过（5/5）"
  else
    ok=0; log "补丁校验未通过"
  fi
fi

# ==== 7. 回滚 ================================================================
if [ "$ok" != 1 ]; then
  log "检查未通过，回滚到 ${ROLLBACK}"
  # 只解 extra 与 compose，绝不覆盖 .env
  # ⚠️ 若回滚到「切换自建镜像之前」的 compose，它含 5 条 ./patches/... 挂载，
  #    部署目录下的 patches/ 必须还在，否则 Docker 会按目录建挂载点、补丁全失效。
  ROLL_ITEMS="extra docker-compose.yml"
  [ "$TARGET" = local ] && ROLL_ITEMS="${ROLL_ITEMS} docker-compose.rehearsal.yml"
  remote_sudo "tar -C ${DEPLOY_DIR} -xzf '${ROLLBACK}' ${ROLL_ITEMS}" || die "回滚解包失败"
  dc "up -d --force-recreate ${SERVICES}" || die "回滚重建失败"

  log "回滚后复跑健康检查…"
  rb=0
  if remote "$POLL" 2>/dev/null | grep -q HEALTHY; then
    BAD=$(check_containers); [ -z "$BAD" ] && rb=1 || log "回滚后容器仍异常：${BAD}"
  fi
  write_log() { :; }
  if [ "$rb" = 1 ]; then
    log "回滚成功，服务已恢复"
    remote "printf '%s\n' \"\$(date '+%F %T')  ROLLED_BACK  commit=${COMMIT}  services=${SERVICES}  backup=${ROLLBACK}  回滚后健康检查通过\" >> ${DEPLOY_DIR}/deploy.log"
    die "部署失败但已回滚，服务正常"
  else
    remote "printf '%s\n' \"\$(date '+%F %T')  ROLLBACK_FAILED  commit=${COMMIT}  services=${SERVICES}  backup=${ROLLBACK}  回滚后健康检查仍失败，需人工介入\" >> ${DEPLOY_DIR}/deploy.log"
    die "回滚后健康检查仍失败，停止一切自动动作，请人工介入"
  fi
fi

# ==== 8. 记录 ================================================================
NEW_IMG=$(remote "${DOCKER} inspect --format '{{.Image}}' ${APP} 2>/dev/null" || true)
remote "printf '%s\n' \"\$(date '+%F %T')  OK  target=${TARGET}  commit=${COMMIT}  services=${SERVICES}  image=${NEW_IMG}  backup=${ROLLBACK}  健康检查与补丁校验均通过\" >> ${DEPLOY_DIR}/deploy.log"
log "部署成功，已记入 ${DEPLOY_DIR}/deploy.log"
