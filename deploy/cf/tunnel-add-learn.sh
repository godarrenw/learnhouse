#!/bin/sh
# =============================================================================
# 给 NAS 上现有的 SZ_NAS 隧道加一条 ingress：
#     learn.sysu-sam.com -> http://172.25.5.162:8088
#
# 不新建隧道、不动 compose、不改 nginx。SZ_NAS 是远程托管配置（source=cloudflare），
# 所以改的是 CF 侧的 configuration，NAS 上那个 cloudflared 容器会自己拉到新配置，
# **不需要重启它**。
#
# 执行顺序：
#     1. 本脚本（加 ingress，此时还没有 DNS 指向，零流量影响）
#     2. dns-switch.sh（把 learn 的 A 记录换成隧道 CNAME，这一步才切流量）
# 回滚：
#     dns-rollback.sh（先回滚 DNS，流量立刻回到 DSM 直连）
#     tunnel-rollback.sh <备份文件>（可选。ingress 多一条无害，不急着回滚）
#
# 幂等：ingress 里已经有 learn.sysu-sam.com 就直接退出，不重复插入。
# 不带 CONFIRM=yes 时只做只读的 GET 和预演打印。
# =============================================================================
. "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/lib.sh"

HOSTNAME_TO_ADD="learn.sysu-sam.com"
ORIGIN_SERVICE="http://172.25.5.162:8088"

load_credentials
ensure_backup_dir

TS="$(timestamp)"
BEFORE="$BACKUP_DIR/tunnel-${CF_TUNNEL_ID}-${TS}.json"
NEWBODY="$BACKUP_DIR/.tunnel-newconfig-${TS}.json"

echo "隧道 : $CF_TUNNEL_ID (SZ_NAS)"
echo "要加 : $HOSTNAME_TO_ADD -> $ORIGIN_SERVICE"
echo

cf_api GET "/accounts/${CF_ACCOUNT_ID}/cfd_tunnel/${CF_TUNNEL_ID}/configurations" \
  | assert_ok "读取隧道配置" > "$BEFORE"
echo "当前配置已备份到 $BEFORE"
echo

# 生成新配置：在最后那条 catch-all（http_status:404）之前插入。
# 其余条目一字不动，顺序保持不变。
python3 - "$BEFORE" "$NEWBODY" "$HOSTNAME_TO_ADD" "$ORIGIN_SERVICE" <<'PY'
import json, sys

before_path, out_path, host, service = sys.argv[1:5]
doc = json.load(open(before_path))
cfg = doc["result"]["config"]
ingress = cfg["ingress"]

print("现有 ingress：")
for i, r in enumerate(ingress):
    print(f"  {i:2}  {r.get('hostname','(catch-all)'):32} -> {r.get('service')}")

if any(r.get("hostname") == host for r in ingress):
    print(f"\n{host} 已经在 ingress 里，无需改动。")
    sys.exit(3)

new_rule = {
    "hostname": host,
    "service": service,
    # 容器内 nginx 与 Next.js Server Actions 都按 Host 判定；
    # 不设这一项的话源站看到的 Host 是 172.25.5.162:8088，Server Actions 的 POST 会被拒。
    "originRequest": {"httpHostHeader": host},
}

# catch-all 是最后一条（没有 hostname，service 形如 http_status:404）。插在它之前。
insert_at = len(ingress) - 1
if ingress and "hostname" in ingress[-1]:
    # 万一末尾不是 catch-all，就追加到最后，并提醒。
    insert_at = len(ingress)
    print("\n注意：ingress 末尾不是 catch-all，新规则将追加到最后。请人工确认。")

new_ingress = ingress[:insert_at] + [new_rule] + ingress[insert_at:]
cfg["ingress"] = new_ingress

print("\n改后 ingress：")
for i, r in enumerate(new_ingress):
    mark = "  <== 新增" if r is new_rule else ""
    print(f"  {i:2}  {r.get('hostname','(catch-all)'):32} -> {r.get('service')}{mark}")

# PUT 只带 config，不带 version / source / tunnel_id（那些是服务端维护的）
json.dump({"config": cfg}, open(out_path, "w"), ensure_ascii=False, indent=2)
PY
rc=$?
if [ "$rc" -eq 3 ]; then rm -f "$NEWBODY"; exit 0; fi
[ "$rc" -eq 0 ] || die "生成新配置失败"

require_confirm

cf_api PUT "/accounts/${CF_ACCOUNT_ID}/cfd_tunnel/${CF_TUNNEL_ID}/configurations" "$NEWBODY" \
  | assert_ok "写入隧道配置" > /dev/null
rm -f "$NEWBODY"

echo "已写入。复核："
cf_api GET "/accounts/${CF_ACCOUNT_ID}/cfd_tunnel/${CF_TUNNEL_ID}/configurations" \
  | assert_ok "复核隧道配置" \
  | python3 -c "
import sys, json
r = json.load(sys.stdin)['result']
print('  version =', r['version'], '(应比改动前 +1)')
for i, x in enumerate(r['config']['ingress']):
    print(f\"  {i:2}  {x.get('hostname','(catch-all)'):32} -> {x.get('service')}\")
"
echo
echo "NAS 上的 cloudflared 会自己拉到新配置，不需要重启容器。"
echo "下一步：DNS 切换 —— CONFIRM=yes $SCRIPT_DIR/dns-switch.sh"
