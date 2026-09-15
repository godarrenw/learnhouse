# -*- coding: utf-8 -*-
"""把头像图片内联进模板，生成单文件 `avatar.html`。

    python3 apps/avatar-page/build_avatar.py

输入：`avatar.template.html` + `avatar_closed.png` / `avatar_open.png`
输出：`avatar.html`（自包含，可以直接托管到任意静态空间）

图片会被缩到 384px 并转成 WebP 再 base64 内联（需要 macOS 的 `sips` 和 `cwebp`；
`cwebp` 缺失就退回 PNG，只是文件大一些）。两张图必须是**同一张底图**改出来的，
只有嘴不一样——页面靠叠加两帧的不透明度做连续口型，底图不一致会看到脸在抖。

换头像：把两张新图放到这里覆盖同名文件，重跑本脚本，再重新发布 avatar.html。
"""
import base64
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "avatar.template.html")
OUT = os.path.join(HERE, "avatar.html")
SIZE = 384
QUALITY = 82
MAX_BYTES = 400 * 1024


def encode(png_path):
    """缩放 + 转 WebP + base64，返回 (data URI, 字节数, 格式)。"""
    if not os.path.exists(png_path):
        raise FileNotFoundError(png_path)
    tmp = tempfile.mkdtemp()
    try:
        small = os.path.join(tmp, "s.png")
        if shutil.which("sips"):
            subprocess.run(["sips", "-Z", str(SIZE), png_path, "--out", small],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            shutil.copy(png_path, small)
        webp = os.path.join(tmp, "s.webp")
        if shutil.which("cwebp"):
            subprocess.run(["cwebp", "-q", str(QUALITY), "-quiet", small, "-o", webp],
                           check=True)
            raw, mime, fmt = open(webp, "rb").read(), "image/webp", "webp"
        else:
            raw, mime, fmt = open(small, "rb").read(), "image/png", "png"
        return ("data:%s;base64,%s" % (mime, base64.b64encode(raw).decode("ascii")),
                len(raw), fmt)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    html = open(TEMPLATE, encoding="utf-8").read()
    total = 0
    for key, name in (("__IMG_CLOSED__", "avatar_closed.png"),
                      ("__IMG_OPEN__", "avatar_open.png")):
        uri, n, fmt = encode(os.path.join(HERE, name))
        total += n
        html = html.replace(key, uri)
        print(f"  {name} -> {fmt} {n} 字节")
    if "__IMG_" in html:
        raise RuntimeError("模板里还有没替换掉的图片占位符")
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    size = os.path.getsize(OUT)
    print(f"  写出 {OUT}  {size} 字节（图片原始 {total} 字节）")
    if size > MAX_BYTES:
        print(f"  [警告] 超过 {MAX_BYTES} 字节的预算，考虑调小 SIZE 或 QUALITY")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
