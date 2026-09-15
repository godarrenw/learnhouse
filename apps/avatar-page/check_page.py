# -*- coding: utf-8 -*-
"""数字人页面本地检查：无头浏览器打开构建好的 avatar.html，走一遍真实播放。

    python3 apps/avatar-page/build_avatar.py
    python3 apps/avatar-page/check_page.py

需要 `pip install playwright && playwright install chromium`，并且本机能连上 TTS 代理。
讲稿编码直接复用后端的 `avatar.py`，保证和线上生成的链接是同一套规则。
"""
import importlib.util
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
AVATAR_PY = os.path.join(HERE, "..", "api", "src", "services", "ext", "content_tools", "avatar.py")
PAGE = os.path.join(HERE, "avatar.html")

spec = importlib.util.spec_from_file_location("avatar", AVATAR_PY)
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)

MD = "同学们好，今天我们来认识分数。\n\n把一个蛋糕平均分成四份，每一份就是四分之一。\n\n下课前我们做一个小练习。"
fails = []


def url(tts=None):
    data = {"title": "分数测试", "lines": A.split_script(MD)}
    if tts:
        data["tts"] = tts
    return "file://" + PAGE + "#" + A.encode_payload(data)


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  {detail}" if detail else ""))
    if not cond:
        fails.append(name)


def main():
    if not os.path.exists(PAGE):
        print("还没构建，先跑 python3 apps/avatar-page/build_avatar.py")
        return 2
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(url())
        page.wait_for_selector("#main:not([hidden])")
        check("云端模式下音色下拉隐藏", page.evaluate("document.getElementById('voiceCtl').hidden"))
        page.click("#play")
        page.wait_for_function("window.__avatar.state === 'speaking'", timeout=5000)
        check("默认走云端语音", page.evaluate("window.__avatar.engine") == "remote",
              page.evaluate("window.__avatar.engine"))
        page.wait_for_function("window.__avatar.audioPlaying", timeout=15000)
        mouth = []
        for _ in range(14):
            mouth.append(page.evaluate("window.__avatar.mouth"))
            time.sleep(0.06)
        check("出声时嘴在动", max(mouth) > 0.15, f"max={max(mouth):.2f}")
        page.wait_for_function("window.__avatar.index >= 1", timeout=20000)
        check("念完一句自动推进", True)
        page.wait_for_function("window.__avatar.audioPlaying", timeout=15000)
        page.click("#play")
        page.wait_for_function("window.__avatar.state === 'paused'")
        time.sleep(1.5)
        check("暂停后不会有迟到的音频突然开口", not page.evaluate("window.__avatar.audioPlaying"))
        page.click("#play")
        page.wait_for_function("window.__avatar.state === 'done'", timeout=30000)
        check("整篇念完", True)
        check("没有 JS 报错", not errors, "; ".join(errors[:3]))

        # key 错了要能降级，而不是卡住
        page.goto("about:blank")
        page.goto(url({"key": "wrong-key"}))
        page.wait_for_selector("#main:not([hidden])")
        page.click("#play")
        page.wait_for_function("window.__avatar.engine !== 'remote'", timeout=15000)
        check("坏 key 时降级到本机语音 / 无声字幕",
              page.evaluate("window.__avatar.engine") in ("tts", "silent"),
              page.inner_text("#status"))
        page.wait_for_function("window.__avatar.index >= 1", timeout=20000)
        check("降级后照样推进", True)
        browser.close()

    print("\n全部通过" if not fails else "\n失败：%s" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
