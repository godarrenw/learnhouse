#!/bin/sh
# =============================================================================
# 把 SZ_NAS 隧道的配置恢复成某个备份文件里的样子。
#
#     CONFIRM=yes ./tunnel-rollback.sh backups/tunnel-f8b7e1c1-…-20260910-2200.json
#
# 备份文件由 tunnel-add-learn.sh 在改动前自动生成。
#
# **一般不需要跑这个。** 出问题时先跑 dns-rollback.sh —— DNS 一回滚流量就回到
# DSM 直连，隧道里多一条用不上的 ingress 完全无害。只有在确实要把隧道恢复原状
# （比如彻底放弃这个方案）时才用本脚本。
#
# 注意：备份是某一时刻的快照。如果这期间别人给 SZ_NAS 加了别的 hostname，
# 恢复会把那些也一起抹掉。执行前会打印当前与目标的对照，看清楚再确认。
# =============================================================================
. "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/lib.sh"

BACKUP_FILE="${1:-}"
[ -n "$BACKUP_FILE" ] || die "用法：CONFIRM=yes $0 <备份文件路径>"
[ -f "$BACKUP_FILE" ] || die "找不到备份文件 $BACKUP_FILE"

load_credentials
ensure_backup_dir

TS="$(timestamp)"
CURRENT="$BACKUP_DIR/tunnel-${CF_TUNNEL_ID}-before-rollback-${TS}.json"
NEWBODY="$BACKUP_DIR/.tunnel-rollback-body-${TS}.json"

cf_api GET "/accounts/${CF_ACCOUNT_ID}/cfd_tunnel/${CF_TUNNEL_ID}/configurations" \
  | assert_ok "读取当前隧道配置" > "$CURRENT"
echo "当前配置已另存到 ${CURRENT}（回滚的回滚用）"
echo

python3 - "$CURRENT" "$BACKUP_FILE" "$NEWBODY" <<'PY'
import json, sys
cur_path, bak_path, out_path = sys.argv[1:4]
cur = json.load(open(cur_path))["result"]
bak = json.load(open(bak_path))["result"]

def show(title, cfg):
    print(title)
    for i, r in enumerate(cfg["ingress"]):
        print(f"  {i:2}  {r.get('hostname','(catch-all)'):32} -> {r.get('service')}")

show(f"当前（version {cur['version']}）：", cur["config"])
print()
show("将恢复成：", bak["config"])

cur_hosts = {r.get("hostname") for r in cur["config"]["ingress"] if r.get("hostname")}
bak_hosts = {r.get("hostname") for r in bak["config"]["ingress"] if r.get("hostname")}
lost = cur_hosts - bak_hosts
if lost:
    print("\n将被移除的 hostname：" + ", ".join(sorted(lost)))
gained = bak_hosts - cur_hosts
if gained:
    print("将被加回的 hostname：" + ", ".join(sorted(gained)))

json.dump({"config": bak["config"]}, open(out_path, "w"), ensure_ascii=False, indent=2)
PY

require_confirm "$BACKUP_FILE"

cf_api PUT "/accounts/${CF_ACCOUNT_ID}/cfd_tunnel/${CF_TUNNEL_ID}/configurations" "$NEWBODY" \
  | assert_ok "恢复隧道配置" > /dev/null
rm -f "$NEWBODY"

echo "已恢复。复核："
cf_api GET "/accounts/${CF_ACCOUNT_ID}/cfd_tunnel/${CF_TUNNEL_ID}/configurations" \
  | assert_ok "复核" \
  | python3 -c "
import sys, json
r = json.load(sys.stdin)['result']
print('  version =', r['version'])
for i, x in enumerate(r['config']['ingress']):
    print(f\"  {i:2}  {x.get('hostname','(catch-all)'):32} -> {x.get('service')}\")
"
