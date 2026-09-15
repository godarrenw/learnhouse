# 数字人页面（虚拟助教）

课程内容页里嵌的那个会说话的卡通助教，就是这个目录构建出来的**单文件静态页**。
它不跟随 LearnHouse 的 Docker 镜像部署，而是单独发布到实验室博客：

```
https://blog.sysu-sam.com/@zhuyizhang/lh-avatar
```

## 它怎么工作

```
老师在「内容工具 → 虚拟助教」写讲稿
  → 后端 apps/api/src/services/ext/content_tools/avatar.py 断句、压缩进链接的 # 后面
  → 链接作为 iframe 追加到内容页
  → 学生打开：本页面读 #，逐句请求云端 TTS 朗读，同时驱动口型和字幕
```

- **声音**：Edge TTS 代理（`POST {url}/v1/audio/speech`，`Authorization: Bearer <key>`），
  默认音色 `zh-CN-XiaoshuangNeural`（晓双·儿童）。地址、key、音色在模板里的 `TTS_DEFAULTS`。
  讲稿 payload 带 `tts` 字段时逐项覆盖。
- **兜底**：云端失败 → 浏览器自带 `speechSynthesis` → 无声字幕模式。
- **key 是公开的**：它在页面源码里，谁都看得到，只能放临时 key。

## 文件

| 文件 | 作用 |
| --- | --- |
| `avatar.template.html` | 页面源码，**改功能改这里**。图片位置是 `__IMG_CLOSED__` / `__IMG_OPEN__` 占位符 |
| `avatar_closed.png` / `avatar_open.png` | 闭嘴、张嘴两帧头像，必须是同一张底图只改嘴 |
| `build_avatar.py` | 把图片缩小、转 WebP、内联进模板，生成 `avatar.html`（不入库） |
| `check_page.py` | 无头浏览器本地走一遍播放、暂停、降级 |
| `publish.sh` | 构建并覆盖发布到博客 |

## 改完之后

```bash
python3 apps/avatar-page/build_avatar.py      # 生成 avatar.html
python3 apps/avatar-page/check_page.py        # 本地检查，需要 playwright
BLOG_API_KEY=... bash apps/avatar-page/publish.sh   # 覆盖发布
```

发布是覆盖同一个地址，**所有已经发出去的链接立刻用上新版**，讲稿不用重新生成。
只要不改 `#j=` / `#s=` 的讲稿格式，旧链接就一直能用；要改格式，记得同时改后端
`avatar.py` 的 `encode_payload` 并保留对旧格式的解析。

## 注意

- Safari 要求播放发生在点击里：`start()` 里同步播一段静音 wav 解锁 `<audio>`，别在它前面加 `await`。
- iPhone Safari 和微信没有自动化测试，改了播放逻辑要真机听一遍。
- 换了头像要重新对准眼皮位置（CSS 里的 `.lid` / `.lidL` / `.lidR`，都是百分比）。
