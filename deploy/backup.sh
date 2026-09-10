#!/bin/sh
# 先进智造学堂（LearnHouse@NAS）每日备份
#   产出：backups/db-<时间>.dump      数据库（pg_dump 自定义格式，可 pg_restore）
#         backups/redis-<时间>.tar.gz   Redis（邀请码、AI 会话——这些不在数据库里）
#         backups/config-<时间>.tar.gz  .env / docker-compose.yml / patches / extra
#   保留 14 天。课程图片视频在 data/content，不在此脚本内——那部分靠
#   DSM 对 docker 共享文件夹的快照 / Hyper Backup 覆盖。
#
# 还原： docker exec -i learnhouse-db-nas pg_restore -U learnhouse -d learnhouse --clean < db-xxx.dump
set -e
DOCKER=/usr/local/bin/docker
D=/volume1/docker/learnhouse
B="$D/backups"
TS=$(date +%F-%H%M)

mkdir -p "$B"; chmod 700 "$B"

"$DOCKER" exec learnhouse-db-nas pg_dump -U learnhouse -Fc learnhouse > "$B/db-$TS.dump"

# 自检：pg_dump 自定义格式必须以 PGDMP 开头。容器没起来时会产出 0 字节文件，
# 那种"看着有备份其实没有"的情况比没备份更危险，所以失败就删掉并报错退出。
if ! head -c 5 "$B/db-$TS.dump" | grep -q PGDMP; then
    rm -f "$B/db-$TS.dump"
    echo "[备份失败] 数据库 dump 无效，已删除。检查 learnhouse-db-nas 是否运行。" >&2
    exit 1
fi

# Redis 不是纯缓存：注册邀请码（TTL 365 天）、AI 会话都只存在这里，Postgres 里没有。
# 丢了 Redis = 已发出去的邀请码全部失效，所以必须一起备份。
# SAVE 是同步阻塞的，但这个库只有几 MB，瞬间完成。
"$DOCKER" exec learnhouse-redis-nas redis-cli SAVE > /dev/null
"$DOCKER" exec learnhouse-redis-nas tar -czf - -C / data > "$B/redis-$TS.tar.gz"
if ! tar -tzf "$B/redis-$TS.tar.gz" > /dev/null 2>&1; then
    rm -f "$B/redis-$TS.tar.gz"
    echo "[备份失败] Redis 归档无效，已删除。" >&2
    exit 1
fi

tar -czf "$B/config-$TS.tar.gz" -C "$D" .env docker-compose.yml patches extra 2>/dev/null

find "$B" -name 'db-*.dump'        -mtime +14 -delete
find "$B" -name 'config-*.tar.gz'  -mtime +14 -delete
find "$B" -name 'redis-*.tar.gz'   -mtime +14 -delete

chmod 600 "$B"/*.dump "$B"/*.tar.gz 2>/dev/null

echo "[备份完成] $TS  db=$(wc -c < "$B/db-$TS.dump") 字节"
