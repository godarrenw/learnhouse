#!/bin/sh
# =============================================================================
# Cloudflare API 公共函数。被同目录的四个脚本 source。
#
# 凭据来自 ~/.learnhouse/cf.env（权限 600，**绝不入库**），三个键：
#   CF_API_EMAIL / CF_API_KEY / CF_ACCOUNT_ID
# 目前是 Global API Key。它权限过大，建议尽快换成 scoped Token：
#   Zone:DNS:Edit + Zone:Cache Rules:Edit + Account:Cloudflare Tunnel:Edit
# 换成 Token 后把 cf_api 里的两个 X-Auth-* 头换成 Authorization: Bearer 即可。
#
# 写法约定：凭据只在函数内展开成 curl 的参数，
# **不要**把凭据拼进 shell 变量再 eval，也**不要** set -x —— 那样密钥会进日志。
# =============================================================================

set -eu

CF_ENV_FILE="${CF_ENV_FILE:-$HOME/.learnhouse/cf.env}"
CF_PROXY="${CF_PROXY:-http://127.0.0.1:6152}"   # 本机访问外网要走 Surge；置空则直连
CF_ZONE_ID="${CF_ZONE_ID:-1438baf87cbb3d400feed72af00520f5}"   # sysu-sam.com
CF_TUNNEL_ID="${CF_TUNNEL_ID:-f8b7e1c1-6077-4fc4-9a55-c4bc1678d325}"  # SZ_NAS

CF_API_BASE="https://api.cloudflare.com/client/v4"

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$SCRIPT_DIR/backups}"

die() { echo "错误：$*" >&2; exit 1; }

load_credentials() {
  [ -f "$CF_ENV_FILE" ] || die "找不到凭据文件 $CF_ENV_FILE"
  # shellcheck disable=SC1090
  set -a; . "$CF_ENV_FILE"; set +a
  [ -n "${CF_API_EMAIL:-}" ] || die "$CF_ENV_FILE 里缺 CF_API_EMAIL"
  [ -n "${CF_API_KEY:-}" ]   || die "$CF_ENV_FILE 里缺 CF_API_KEY"
  [ -n "${CF_ACCOUNT_ID:-}" ] || die "$CF_ENV_FILE 里缺 CF_ACCOUNT_ID"
}

# cf_api METHOD /path [body-file]
# 成功时把响应 JSON 打到 stdout；HTTP 层失败直接退出。
cf_api() {
  _method="$1"; _path="$2"; _body="${3:-}"
  # 用 if 而不是 `[ … ] && …`：后者作为一整条 && 列表返回非零时，
  # set -e 会让整个函数直接退出（踩过一次，表现是 curl 根本没跑、响应为空）。
  set -- -s -X "$_method" \
    -H "X-Auth-Email: ${CF_API_EMAIL}" \
    -H "X-Auth-Key: ${CF_API_KEY}" \
    -H "Content-Type: application/json"
  if [ -n "$CF_PROXY" ]; then set -- "$@" --proxy "$CF_PROXY"; fi
  if [ -n "$_body" ]; then set -- "$@" --data-binary "@$_body"; fi
  curl "$@" "${CF_API_BASE}${_path}"
}

# 从 stdin 读 CF 响应，success 不为 true 就打印 errors 并退出。
# 必须用 python3 -c，不能用 `python3 - <<'EOF'`：
# 后者让程序本身占用 stdin，管道进来的响应就读不到了（也踩过一次）。
assert_ok() {
  python3 -c '
import json, sys
label = sys.argv[1]
raw = sys.stdin.read()
try:
    d = json.loads(raw)
except Exception:
    sys.stderr.write(label + "：响应不是 JSON：" + raw[:300] + "\n"); sys.exit(1)
if not d.get("success"):
    sys.stderr.write(label + " 失败：" + json.dumps(d.get("errors"), ensure_ascii=False) + "\n"); sys.exit(1)
sys.stdout.write(raw)
' "$1"
}

# 没有 CONFIRM=yes 就停在这里。所有写操作前必须调用。
require_confirm() {
  if [ "${CONFIRM:-}" != "yes" ]; then
    echo
    echo "———— 以上是**预演**，没有做任何改动 ————"
    echo "确认无误后重跑并带上：CONFIRM=yes $0 $*"
    exit 1
  fi
  echo
  echo "CONFIRM=yes，开始执行改动…"
}

timestamp() { date +%Y%m%d-%H%M%S; }

ensure_backup_dir() { mkdir -p "$BACKUP_DIR"; }
