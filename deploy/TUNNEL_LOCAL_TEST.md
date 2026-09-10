# nginx 媒体分流的本地验证记录

日期：2026-09-10 ｜ 环境：本地预发 `/Volumes/D/code/learnhouse-local`（五个 `learnhouse-*-local` 容器）
被验对象：本仓库 `deploy/extra/nginx.prod.conf`（feat/tunnel 分支）
**没有触碰生产 NAS、Cloudflare、DNS，也没有改动本地预发那五个容器。**

## 怎么做的

本地预发那五个容器一个都没动。另起两个**临时** nginx 容器，加入同一个 Docker 网络
`learnhouse-local_learnhouse-network-local`，proxy_pass 指向同一个 `learnhouse-app`：

| 容器 | 宿主机端口 | 挂的配置 |
|---|---|---|
| `lh-tunnel-test-on` | 18089 | `nginx.prod.conf` 的副本，只把总闸那一行改成 `on` |
| `lh-tunnel-test-off` | 18090 | 仓库里的 `nginx.prod.conf` **逐字未改**（总闸默认 `off`） |

配置文件本身不需要「本地版」：`server_name` 与上游主机名 `learnhouse-app` 在本地网络里
同样成立，唯一的差别就是总闸取值。所以这里验的就是将来推上生产的那份文件。

```sh
docker run -d --name lh-tunnel-test-on  --network learnhouse-local_learnhouse-network-local \
  -p 18089:80 -v <改成 on 的副本>:/etc/nginx/conf.d/default.conf:ro nginx:alpine
docker run -d --name lh-tunnel-test-off --network learnhouse-local_learnhouse-network-local \
  -p 18090:80 -v <仓库原件>:/etc/nginx/conf.d/default.conf:ro nginx:alpine
```

语法先过了一遍：

```
$ docker run --rm --network learnhouse-local_learnhouse-network-local \
    -v .../nginx.prod.conf:/etc/nginx/conf.d/default.conf:ro nginx:alpine nginx -t
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

### 媒体样本

本地库是从生产备份恢复的，有真实课程与 activity 记录，只是 `data/content` 为空。
所以按数据库里的真实 uuid 和文件名，往 `learnhouse-local/data/content/` 下投了几个假文件
（bind mount，即时可见，不用重建容器）：

```
课程 course_faa2f9fc…（制造系统自动化技术）public=t published=t
活动 activity_4a7112bc…  TYPE_VIDEO  filename 6e7581ca…_video.mp4
```

| 用途 | 相对 `content/` 的路径 | 内容 |
|---|---|---|
| 视频活动 | `orgs/…/courses/…/activities/…/video/6e7581ca…_video.mp4` | 3 MB 随机数据 |
| PDF 活动 | `…/activities/…/documentpdf/tunneltest.pdf` | 几十字节 |
| 视频块 | `…/dynamic/blocks/videoBlock/block_test0001/tunneltest_video.mp4` | 3 MB |
| PDF 块 | `…/dynamic/blocks/pdfBlock/block_test0003/tunneltest.pdf` | 几十字节 |
| **图片块（对照组）** | `…/dynamic/blocks/imageBlock/block_test0002/tunneltest.png` | 几字节 |

用真实 uuid 的好处是 `/content/` 的鉴权（`local_content.py`）和 `/api/v1/stream/` 的 RBAC
都会真的跑一遍，拿到的是 Starlette `FileResponse` 与 `stream.py` 手写 Range 的真实响应，
而不是一个假上游。**验完这些文件全部删掉了**，`data/content` 已回到空目录。

下面所有请求都带 `--noproxy '*'`，避免走本机 Surge 代理。

## 结果

一共 15 条，全部符合预期。

### learn 块（总闸 on，端口 18089）

| # | 请求 | 结果 | 判定 |
|---|---|---|---|
| 1 | `Host: learn…` `GET /` | 200 | ✅ 页面正常 |
| 2 | `Host: learn…` imageBlock 图片 | 200，无 Location | ✅ **图片不分流**，校外不会裂图 |
| 3 | `Host: learn…` 视频活动 + `?token=abc&x=1` | 302 → `https://media.sysu-sam.com/content/…/video/…mp4?token=abc&x=1` | ✅ 目标域名对，**query 完整保留** |
| 4 | `Host: learn…` `/api/v1/stream/video/…` | 302 → `https://media.sysu-sam.com/api/v1/stream/video/…` | ✅ |
| 5 | `Host: learn…` videoBlock、documentpdf | 均 302 → media 同路径 | ✅ |

### media 块（端口 18089）

| # | 请求 | 结果 | 判定 |
|---|---|---|---|
| 6 | `Host: media…` 视频活动，带 Origin | 200，`Content-Type: video/mp4`，`Content-Length: 3145728`，`accept-ranges: bytes`，六个 CORS 头齐全 | ✅ |
| 7 | `Host: media…` 视频活动 `Range: bytes=0-1023` | **206**，`content-range: bytes 0-1023/3145728`，`Content-Length: 1024` | ✅ `/content/` 的 Range 透传成立 |
| 8 | `Host: media…` `/api/v1/stream/…` `Range: bytes=100-599` | **206**，`content-range: bytes 100-599/3145728` + CORS 头 | ✅ stream.py 手写 Range 也透传，且**匿名可取**（公开课程无需 cookie，印证设计文档 §3） |
| 9 | `Host: media…` `/`、`/dash`、imageBlock 图片、`/api/v1/orgs/slug/default` | 全部 **404** | ✅ 只放行重媒体，页面与普通 API 不暴露；**图片块在 media 域名上取不到**，与规则一致 |
| 10 | `Host: media…` `GET /api/v1/health` | 200，body `true` | ✅ 探测端点放行 |
| 11 | `Host: media…` `OPTIONS /api/v1/stream/…` | 204 + 全套 CORS 头 | ✅ 预检在边缘回掉，不打后端 |
| 12 | 同 8，数 `Access-Control-Allow-Origin` 出现次数 | **1** | ✅ `proxy_hide_header` 生效，没有和后端 CORSMiddleware 叠成两份（两份会让浏览器直接判 CORS 失败） |

`HEAD /api/v1/health` 返回 **405**（后端只注册了 GET）。前端探测用的是 `mode:'no-cors'`，
405 一样算「连得上」，但为了少一个疑点，`useCampusNetwork` 里用的是 GET。

### 环路与开关

| # | 请求 | 结果 | 判定 |
|---|---|---|---|
| 13 | `Host: 127.0.0.1` `GET /`（模拟容器健康检查） | 200 | ✅ 落到 learn 块，`default_server` 生效 |
| 13b | `Host: 127.0.0.1` 视频活动路径 | 200，无 Location | ✅ 正向白名单：非 learn 域名不分流，健康检查与 `lh` CLI 直连 IP 都不受影响 |
| 14 | `Host: media…` videoBlock 路径 | 200，无 Location | ✅ **不会 302 到自己**，环路守住 |
| 15 | 端口 18090（总闸 off）：视频活动 / stream / 首页 | 200 / 200 / 200，无任何 Location | ✅ 关掉开关后行为与今天完全一致，阶段一可以先只上隧道 |

第 14 条特意用正向白名单而不是「$host 不是 media 就重定向」：设计文档 §10 第 7 项
「DSM 反向代理是否保留原始 Host」还没核实，万一 DSM 把 Host 改写成 localhost 或 IP，
负向写法会让 media 域名的请求在 learn 块里被无限 302 到自己。正向白名单下最坏情况
只是「分流静默不生效」，用第 15 条那种 curl 一测就知道。

## 没验到的

这几条本地做不了，留给上线时验（清单在 `TUNNEL_RUNBOOK.md`）：

1. **浏览器真的跟随 302 并重发 Range**。本地没有 `media.sysu-sam.com` 的 TLS 端点，
   `curl -L` 跟不过去（Location 是 https）。302 的目标串已逐字比对正确，media 块也已单独验过，
   但「`<video>` seek 时跟随 302 后继续 206」要在校内用 DevTools 看一次。
2. **iframe 里的 PDF 跟随 302**。同上，且跨域 iframe 没有可靠的错误事件。
3. **非公开课程在 media 域名上返回 401**。本地库里带视频的课程只有那一门，且是 public，
   构造不出对照。设计文档 §3 的代码依据是 `local_content.py:101-102`。
4. **cloudflared 真的连得上**、CF 的 100 MB 上传上限、CF 边缘缓存绕过。都要 CF 凭据。
5. **DSM 是否保留原始 Host**（§10 第 7 项）。要 NAS 权限。

## 收尾

```sh
docker rm -f lh-tunnel-test-on lh-tunnel-test-off
rm -rf /Volumes/D/code/learnhouse-local/data/content/orgs
```

两个临时容器已删除，`data/content` 已清空，本地预发那五个容器全程 healthy 未受影响。
