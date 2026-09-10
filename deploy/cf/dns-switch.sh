#!/bin/sh
# =============================================================================
# 把 learn.sysu-sam.com 从「灰云 A -> 172.25.5.162」换成
# 「橙云 CNAME -> <SZ_NAS 隧道 id>.cfargotunnel.com」。
#
# **这一步才真正切流量。** 跑之前先确认 tunnel-add-learn.sh 已经执行过，
# 否则切过去会 502（隧道没有对应的 ingress，落到 catch-all 404）。
#
#     CONFIRM=yes ./dns-switch.sh
#
# 用「先删 A、再建 CNAME」两步，不用 PATCH 改 type：CF 对同名记录改类型的
# 行为在不同 API 版本里不一致，删加两步的结果是确定的。
# 两步之间有几百毫秒的空窗，此时 learn 无解析 —— 校内用户如果正好在这个瞬间
# 刷新会失败一次，重试即可。所以要在无课窗口做。
#
# 回滚：dns-rollback.sh（用本脚本留下的备份，把 A 记录原样建回来）
#
# 建议：切换前一天先把 A 记录的 TTL 从 300 降到 60，
# 这样万一要回滚，生效时间从 5 分钟缩到 1 分钟。降 TTL 本身不影响任何流量。
# =============================================================================
. "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/lib.sh"

RECORD_NAME="learn.sysu-sam.com"

load_credentials
ensure_backup_dir

TS="$(timestamp)"
BEFORE="$BACKUP_DIR/dns-learn-${TS}.json"
NEWBODY="$BACKUP_DIR/.dns-new-${TS}.json"

cf_api GET "/zones/${CF_ZONE_ID}/dns_records?name=${RECORD_NAME}" \
  | assert_ok "读取 ${RECORD_NAME} 记录" > "$BEFORE"
echo "现有记录已备份到 $BEFORE"
echo

RECORD_ID="$(python3 - "$BEFORE" "$CF_TUNNEL_ID" "$NEWBODY" <<'PY'
import json, sys
before_path, tunnel_id, out_path = sys.argv[1:4]
res = json.load(open(before_path))["result"]
if len(res) != 1:
    sys.stderr.write(f"预期正好 1 条 learn 记录，实际 {len(res)} 条，人工处理\n"); sys.exit(1)
r = res[0]
target = f"{tunnel_id}.cfargotunnel.com"

sys.stderr.write("当前：\n")
sys.stderr.write(f"  {r['type']:6} {r['name']} -> {r['content']}  proxied={r['proxied']} ttl={r['ttl']}\n")
sys.stderr.write(f"  id={r['id']}\n\n")
sys.stderr.write("将变成：\n")
sys.stderr.write(f"  CNAME  {r['name']} -> {target}  proxied=True ttl=1(auto)\n\n")
sys.stderr.write("动作：先 DELETE 上面那条 A，再 POST 新的 CNAME。\n")

if r["type"] != "A":
    sys.stderr.write(f"当前记录不是 A（是 {r['type']}），可能已经切过了。人工确认。\n"); sys.exit(1)

json.dump({
    "type": "CNAME", "name": r["name"], "content": target,
    "proxied": True, "ttl": 1,
    "comment": "LearnHouse via SZ_NAS Cloudflare Tunnel",
}, open(out_path, "w"), ensure_ascii=False)
print(r["id"])
PY
)" || die "预演失败"

require_confirm

echo "删除旧的 A 记录 ${RECORD_ID}…"
cf_api DELETE "/zones/${CF_ZONE_ID}/dns_records/${RECORD_ID}" \
  | assert_ok "删除 A 记录" > /dev/null

echo "创建新的 CNAME…"
cf_api POST "/zones/${CF_ZONE_ID}/dns_records" "$NEWBODY" \
  | assert_ok "创建 CNAME" \
  | python3 -c "
import sys, json
r = json.load(sys.stdin)['result']
print(f\"  {r['type']} {r['name']} -> {r['content']} proxied={r['proxied']} ttl={r['ttl']}\")
print('  id =', r['id'])
"
rm -f "$NEWBODY"

echo
echo "切换完成。解析生效约 1~5 分钟（旧 A 的 TTL 决定）。"
echo "验：dig +short learn.sysu-sam.com   应返回 CF 的公网 IP，不再是 172.25.5.162"
echo "回滚：CONFIRM=yes $SCRIPT_DIR/dns-rollback.sh $BEFORE"
