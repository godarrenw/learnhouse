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
# 健康检查总超时（秒）。默认 240s 是按生产 start_period 180s 留的余量。
# 冷启要跑 SQLModel.metadata.create_all 建新表时会更慢，这台 NAS 只有 4G 内存
# 且在用 swap，必要时调大（只改调用时的环境变量，别改这里的默认值）：
#   HEALTH_TIMEOUT=480 TARGET=prod ./deploy.sh
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-240}"
# 预检等待容器稳定的超时，比健康检查短：这时只是等上一次操作的余波散去。
PREFLIGHT_TIMEOUT="${PREFLIGHT_TIMEOUT:-120}"

die() { echo "[部署中止] $*" >&2; exit 1; }
log() { echo "[$(date +%F' '%H:%M:%S)] $*"; }

# ==== target 配置 ============================================================
case "$TARGET" in
prod)
  NAS_USER=SAM-IPA518
  NAS_HOST=172.25.5.162
  DEPLOY_DIR=/volume1/docker/learnhouse
  DC=/usr/local/bin/docker-compose        # ContainerManager 的软链，实测 v2.20.1（不是 v1）
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
  # 连接复用（ControlMaster）：整轮部署有 20 多处 remote/remote_sudo 调用，
  # 各开一条 TCP 连接的话，这台 NAS 对短时间内重复建连会直接拒 —— 那会把「被拒」
  # 误判成「部署失败」，而且可能发生在同步之后、健康检查之前的危险窗口里。
  # 开了之后第一次调用建主连接，后续全部复用它，整轮部署**物理上只有一条 SSH**。
  # 副作用：后续调用不再走认证，sshpass 形同虚设（无害）。
  # 2026-09-12 已在真实 NAS 上验证：6 次连续只读调用全部成功，且 6 次落在同一秒内
  #   （每次新建连接光密码认证就要 1s 上下，这个速度只有复用才可能），
  #   `ssh -O check` 确认主连接存在，`-O exit` 干净关闭，无残留。
  # 若哪天复用出问题，去掉这三个 -o Control* 选项即可退回每次新建连接的老行为。
  # 注意：remote() 里是 `$SSH "$1"`，依赖 bash 的按空格分词。本脚本 shebang 是 bash，
  #   没问题；但**不要**在 zsh 里手工 source 这些片段 —— zsh 默认不对未加引号的
  #   变量做分词，整个字符串会被当成一个命令名，报 "no such file or directory"。
  SSH_CTL="/tmp/lh-ssh-ctl-$$"
  SSH="sshpass -e ssh -o NumberOfPasswordPrompts=1 -o StrictHostKeyChecking=no \
       -o ControlMaster=auto -o ControlPath=${SSH_CTL} -o ControlPersist=300 \
       ${NAS_USER}@${NAS_HOST}"
  # 退出时收掉主连接，别把它留到 ControlPersist 超时
  cleanup_ssh() {
    [ -S "$SSH_CTL" ] || return 0
    ssh -o ControlPath="$SSH_CTL" -O exit "${NAS_USER}@${NAS_HOST}" 2>/dev/null || true
  }
  trap cleanup_ssh EXIT

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

# 跑 docker 的统一入口。**必须走 remote_sudo**：生产 NAS 上 SAM-IPA518 没有
# docker.sock 的权限，不加 sudo 的 `docker inspect` 会直接失败，而调用处大多写了
# `|| echo missing` / `|| true`，失败会被悄悄吞掉 —— 表现为「五个容器全部 missing」，
# 而它们其实好好跑着。2026-09-12 第一次真部署就是栽在这里（预检直接中止，
# 好在中止发生在任何写操作之前，生产没被碰到）。
# 本机演练模式下 remote_sudo 就是 bash -c，不需要提权，行为不变。
dk() { remote_sudo "${DOCKER} $*"; }

# 在**仓库 deploy/ 目录**里跑 compose config。
# compose 里写了 env_file: .env，而仓库里没有 .env（含密钥，不入库），
# 直接跑会因为找不到 .env 报错，所以用一个临时空 .env 顶一下再删掉。
repo_compose_config() {
  local rc=0 tmp=0
  [ -f .env ] || { : > .env; tmp=1; }
  ${DC} ${DC_FILES} config "$@" || rc=$?
  [ "$tmp" = 1 ] && rm -f .env || true
  return $rc
}

log "TARGET=${TARGET}  部署目录=${DEPLOY_DIR}  项目=${COMPOSE_PROJECT}"

# ==== 1. 预检 ================================================================
log "预检…"
# 生产必须从干净的工作区部署，否则 deploy.log 里记的 commit 对不上实际部署的内容。
# 演练时允许带脏工作区（边改边试），但仅限 TARGET=local，且要显式设 ALLOW_DIRTY=1。
if [ -n "$(git status --porcelain)" ]; then
  if [ "$TARGET" = local ] && [ "${ALLOW_DIRTY:-0}" = 1 ]; then
    log "⚠️ 工作区不干净，ALLOW_DIRTY=1 且 TARGET=local，继续（commit 号仅供参考）"
  else
    die "工作区不干净，先提交或 stash"
  fi
fi
COMMIT=$(git rev-parse --short HEAD)
log "将要部署的 commit：${COMMIT}"

repo_compose_config -q || die "本地 compose 语法错"

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
    st=$(dk "inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}nohealth{{end}}' ${c} 2>/dev/null" || echo missing)
    [ "$st" = healthy ] || echo "${c}=${st}"
  done
  for c in $RUNNING_CONTAINERS; do
    st=$(dk "inspect -f '{{.State.Status}}' ${c} 2>/dev/null" || echo missing)
    [ "$st" = running ] || echo "${c}=${st}"
  done
}
# 重建之后不能只采样一次容器状态：nginx 的 healthcheck 是 interval 30s 且没有
# start_period，刚 recreate 完必然处于 starting，即使它其实已经在正常服务。
# 所以这里要轮询等待，starting 视为「还没到时候」，直到全好或超时。
wait_containers() {   # $1=超时秒数，默认 240
  local deadline=$(( $(date +%s) + ${1:-240} )) bad
  while :; do
    bad=$(check_containers)
    [ -z "$bad" ] && return 0
    [ "$(date +%s)" -ge "$deadline" ] && { echo "$bad"; return 1; }
    sleep 5
  done
}

if [ "${SKIP_PREFLIGHT_HEALTH:-0}" != 1 ]; then
  # 给 120s 缓冲：上一次操作刚重建过容器时会短暂处于 starting，那不算「坏」。
  # 到点还没稳定成 healthy 才拒绝部署 —— 本来就不健康时不要部署，
  # 否则事后分不清是部署引入的还是原本就坏的。
  if BAD=$(wait_containers "$PREFLIGHT_TIMEOUT"); then log "预检：五个容器都正常"
  else die "部署前就有容器不健康，先修好再部署：${BAD}"; fi
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
  # 故障注入（只在演练用）：把 app 镜像换成别的，验证健康检查失败后能自动回滚。
  # 必须改**仓库里**这份，因为第 4 步 sync_files 会用仓库的文件覆盖部署目录；
  # 只改部署目录的话会被同步覆盖掉，等于没注入。改完用 trap 保证一定还原。
  [ "$TARGET" = local ] || die "DRY_IMAGE 只允许在 TARGET=local 下使用"
  log "⚠️ DRY_IMAGE=${DRY_IMAGE}，把 app 镜像改写成它（故障注入）"
  cp docker-compose.rehearsal.yml "/tmp/.lh_reh_orig.$$"
  trap 'cp "/tmp/.lh_reh_orig.$$" "'"$REPO_DEPLOY_DIR"'/docker-compose.rehearsal.yml"; rm -f "/tmp/.lh_reh_orig.$$"; echo "[已还原仓库里的 docker-compose.rehearsal.yml]"' EXIT
  python3 - "$DRY_IMAGE" <<'PYEOF'
import re, sys, pathlib
img = sys.argv[1]
p = pathlib.Path('docker-compose.rehearsal.yml')
p.write_text(re.sub(r'^(\s*image:\s*).*learnhouse.*$', r'\g<1>' + img, p.read_text(), count=1, flags=re.M))
PYEOF
fi
if [ "$TARGET" = prod ]; then
  # TODO: pull 之前先查这个 commit 的构建成功了没，别闷头拉一个还没推上去的 tag：
  #       gh run list -R godarrenw/learnhouse --limit 1
  log "拉取新镜像…"
  dc "pull learnhouse-app" || die "拉镜像失败"
else
  # 注意不能写成 `config | awk '…{exit}'`：awk 提前 exit 会让上游 compose 收到
  # SIGPIPE，配合 set -o pipefail 整条管道非零，脚本会在这里无声中止。
  # 先把 config 落到变量里，再在变量上取值。
  CFG=$(repo_compose_config 2>/dev/null) || die "compose config 失败"
  IMG=$(printf '%s\n' "$CFG" | awk '/learnhouse-app:/{f=1} f&&/image:/{print $2; exit}')
  [ -n "$IMG" ] || die "从 compose config 里取不到 app 镜像名"
  log "演练镜像：${IMG}"
  dk "image inspect ${IMG} >/dev/null 2>&1" \
    || die "本机没有镜像 ${IMG}（演练不重建镜像，请先 docker build 或换 tag）"
fi
OLD_IMG=$(dk "inspect --format '{{.Image}}' ${APP} 2>/dev/null" || true)
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
# 重建失败**不能直接 die**：那样会把服务留在半新半旧的状态没人收拾。
# 记下失败，照样走后面的健康检查与回滚流程。
recreate_ok=1
dc "up -d --force-recreate ${SERVICES}" || { recreate_ok=0; log "重建命令返回失败，继续走健康检查与回滚"; }

# ==== 6. 健康检查 ============================================================
# 轮询必须在**一条** SSH 连接里做完。这台 NAS 对短时间内重复建连会直接拒，
# 48 次各开一条连接必然中途被拒，把「被拒」误判成「部署失败」。
# app 冷启要跑 create_all 建新表（生产 start_period 是 180s，默认总超时 240s）。
# 轮询次数 = 总超时 / 5s，至少 1 次。必须在下面 log 之前算出来。
POLL_TRIES=$(( HEALTH_TIMEOUT / 5 )); [ "$POLL_TRIES" -ge 1 ] || POLL_TRIES=1
log "健康检查（HTTP，总超时 ${HEALTH_TIMEOUT}s，共 ${POLL_TRIES} 轮）…"
ok=0
# --noproxy '*'：NAS 上没有代理无所谓，本机演练时系统代理会劫持 127.0.0.1，必须绕开
POLL="for i in \$(seq 1 ${POLL_TRIES}); do
   c=\$(curl -s --noproxy '*' ${BASE}/api/v1/orgs/slug/default || true);
   h=\$(curl -s --noproxy '*' -o /dev/null -w '%{http_code}' ${BASE}/ || true);
   case \"\$c\" in *'\"slug\":\"default\"'*) sc=1;; *) sc=0;; esac;
   if [ \"\$sc\" = 1 ] && [ \"\$h\" = 200 ]; then echo HEALTHY; exit 0; fi;
   sleep 5;
 done; exit 1"
if [ "$recreate_ok" = 1 ] && remote "$POLL" 2>/dev/null | grep -q HEALTHY; then ok=1; fi
[ "$ok" = 1 ] && log "HTTP 通过：/ 返回 200，orgs/slug/default 的 JSON 里 slug == default" \
             || log "HTTP 检查未通过"

# 容器状态：四个带 healthcheck 的要 healthy，ssr-fwd 只看 running
if [ "$ok" = 1 ]; then
  log "健康检查（容器状态，最多等 ${HEALTH_TIMEOUT}s）…"
  if BAD=$(wait_containers "$HEALTH_TIMEOUT"); then log "五个容器状态正常"; else ok=0; log "容器状态异常：${BAD}"; fi
fi

# ==== 6b. 镜像内补丁校验（换镜像的部署必做）==================================
# 老流程这里查的是「前端 chunk 挂载点文件名是否还在」。自建镜像模型下那个问题不存在了，
# 但要验「新镜像里补丁是不是真的编进去了」。完整说明见 docs/sysu-sam/PATCHES.md。
if [ "$ok" = 1 ]; then
  log "校验镜像内补丁…"
  PATCHCHK=$(dk "exec ${APP} sh -c \"
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
    if BAD=$(wait_containers "$HEALTH_TIMEOUT"); then rb=1; else log "回滚后容器仍异常：${BAD}"; fi
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
NEW_IMG=$(dk "inspect --format '{{.Image}}' ${APP} 2>/dev/null" || true)
remote "printf '%s\n' \"\$(date '+%F %T')  OK  target=${TARGET}  commit=${COMMIT}  services=${SERVICES}  image=${NEW_IMG}  backup=${ROLLBACK}  健康检查与补丁校验均通过\" >> ${DEPLOY_DIR}/deploy.log"
log "部署成功，已记入 ${DEPLOY_DIR}/deploy.log"
