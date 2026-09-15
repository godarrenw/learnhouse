#!/usr/bin/env bash
# 构建数字人页面并覆盖发布到实验室博客（同一 slug，已发出的链接自动用上新版）。
#
#   BLOG_API_KEY=<实验室博客 key> bash apps/avatar-page/publish.sh
#
# 需要走代理时再加 HTTPS_PROXY=http://127.0.0.1:6152。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SLUG="lh-avatar"
API="https://blog.sysu-sam.com/api/publish"
: "${BLOG_API_KEY:?先设置 BLOG_API_KEY（实验室博客的 API key）}"

python3 "$HERE/build_avatar.py"

PAYLOAD="$(mktemp)"
trap 'rm -f "$PAYLOAD"' EXIT
python3 - "$HERE/avatar.html" "$PAYLOAD" "$SLUG" <<'EOF'
import json, sys
html = open(sys.argv[1], encoding="utf-8").read()
json.dump({
    "title": "先进智造学堂 · 虚拟助教",
    "summary": "课程内容页里的网页虚拟助教，讲稿放在链接 hash 里",
    "slug": sys.argv[3],
    "date": "2026-09-10",
    "format": "html",
    "password": None,
    "content": html,
}, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False)
EOF

curl -sS -X POST -H "X-API-Key: $BLOG_API_KEY" -H "Content-Type: application/json" \
  -d @"$PAYLOAD" "$API"
echo
echo "已发布：https://blog.sysu-sam.com/@zhuyizhang/$SLUG"
