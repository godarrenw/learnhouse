#!/bin/sh
# =============================================================================
# 把 learn.sysu-sam.com 从隧道 CNAME 换回原来的灰云 A 记录。
#
#     CONFIRM=yes ./dns-rollback.sh backups/dns-learn-<时间>.json
#
# 备份文件由 dns-switch.sh 在改动前自动生成。不给参数时自动挑 backups/ 里
# 最新的一份 dns-learn-*.json，并把它打印出来让你确认。
#
# **这是出问题时的第一手段，也通常是唯一需要做的一步。**
# DNS 一切回来，流量立刻回到 DSM 反代直连 8088，与改造前完全一致。
# 隧道里那条 learn 的 ingress 留着不用管，没有 DNS 指向它就是闲置的。
#
# 生效时间取决于切换前那条 A 记录的 TTL（备份里能看到）。
# =============================================================================
. "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/lib.sh"

RECORD_NAME="learn.sysu-sam.com"

load_credentials
ensure_backup_dir

BACKUP_FILE="${1:-}"
if [ -z "$BACKUP_FILE" ]; then
  BACKUP_FILE="$(ls -1t "$BACKUP_DIR"/dns-learn-*.json 2>/dev/null | head -1 || true)"
  [ -n "$BACKUP_FILE" ] || die "backups/ 下没有 dns-learn-*.json，请显式给出备份文件路径"
  echo "未指定备份文件，自动选用最新的一份：$BACKUP_FILE"
  echo
fi
[ -f "$BACKUP_FILE" ] || die "找不到备份文件 $BACKUP_FILE"

TS="$(timestamp)"
CURRENT="$BACKUP_DIR/dns-learn-before-rollback-${TS}.json"
NEWBODY="$BACKUP_DIR/.dns-rollback-${TS}.json"

cf_api GET "/zones/${CF_ZONE_ID}/dns_records?name=${RECORD_NAME}" \
  | assert_ok "读取当前 ${RECORD_NAME} 记录" > "$CURRENT"

CURRENT_ID="$(python3 - "$CURRENT" "$BACKUP_FILE" "$NEWBODY" <<'PY'
import json, sys
cur_path, bak_path, out_path = sys.argv[1:4]
cur = json.load(open(cur_path))["result"]
bak = json.load(open(bak_path))["result"]

if len(bak) != 1:
    sys.stderr.write(f"备份里预期正好 1 条记录，实际 {len(bak)} 条\n"); sys.exit(1)
b = bak[0]

sys.stderr.write("当前：\n")
if not cur:
    sys.stderr.write("  （learn 目前没有任何记录）\n")
for r in cur:
    sys.stderr.write(f"  {r['type']:6} {r['name']} -> {r['content']}  proxied={r['proxied']} ttl={r['ttl']}  id={r['id']}\n")
sys.stderr.write("\n将恢复成：\n")
sys.stderr.write(f"  {b['type']:6} {b['name']} -> {b['content']}  proxied={b['proxied']} ttl={b['ttl']}\n")
sys.stderr.write(f"\n生效时间约等于 ttl={b['ttl']} 秒。\n")

json.dump({
    "type": b["type"], "name": b["name"], "content": b["content"],
    "proxied": b["proxied"], "ttl": b["ttl"],
}, open(out_path, "w"), ensure_ascii=False)
print(cur[0]["id"] if cur else "")
PY
)" || die "预演失败"

require_confirm "$BACKUP_FILE"

if [ -n "$CURRENT_ID" ]; then
  echo "删除当前记录 ${CURRENT_ID}…"
  cf_api DELETE "/zones/${CF_ZONE_ID}/dns_records/${CURRENT_ID}" \
    | assert_ok "删除当前记录" > /dev/null
fi

echo "恢复原记录…"
cf_api POST "/zones/${CF_ZONE_ID}/dns_records" "$NEWBODY" \
  | assert_ok "恢复记录" \
  | python3 -c "
import sys, json
r = json.load(sys.stdin)['result']
print(f\"  {r['type']} {r['name']} -> {r['content']} proxied={r['proxied']} ttl={r['ttl']}\")
"
rm -f "$NEWBODY"

echo
echo "已回滚。验：dig +short learn.sysu-sam.com  应返回 172.25.5.162"
echo "隧道里那条 learn 的 ingress 留着无害；确实要清掉再跑 tunnel-rollback.sh。"
