import { describe, expect, test } from "bun:test";

import { matchPastedVideo } from "../../components/Objects/Editor/Extensions/SysuBilibiliPaste/SysuBilibiliPaste.ts";

// 粘贴规则的触发条件刻意做得很窄：老师在编辑器里粘贴一条 bilibili 链接才变播放器，
// 别的粘贴一律交回 TipTap 默认行为。这个判断错了有两种后果，都很难被发现：
// 放宽了会把正常的文字粘贴吃掉，收紧了功能等于没做。所以单独测它。
describe("matchPastedVideo", () => {
  test("单独一条 bilibili 链接命中", () => {
    for (const url of [
      "https://www.bilibili.com/video/BV1GJ411x7h7",
      "https://www.bilibili.com/video/BV1GJ411x7h7?p=2&spm_id_from=333.788",
      "https://m.bilibili.com/video/BV1GJ411x7h7",
      "https://www.bilibili.com/video/av170001",
      "https://b23.tv/abcd1234",
      "https://player.bilibili.com/player.html?bvid=BV1GJ411x7h7",
    ]) {
      expect(matchPastedVideo(url)).toBe(url);
    }
  });

  test("首尾空白会被去掉后再判断", () => {
    expect(matchPastedVideo("  https://b23.tv/abcd1234\n")).toBe(
      "https://b23.tv/abcd1234"
    );
  });

  test("官方 iframe 嵌入代码整段命中", () => {
    const code =
      '<iframe src="//player.bilibili.com/player.html?bvid=BV1GJ411x7h7&p=1" ' +
      'scrolling="no" border="0" allowfullscreen="true"></iframe>';
    expect(matchPastedVideo(code)).toBe(code);
  });

  test("抖音、腾讯、YouTube 也命中（后端负责标未确认）", () => {
    for (const url of [
      "https://www.douyin.com/video/7123456789",
      "https://v.qq.com/x/page/abcdefg.html",
      "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
      "https://youtu.be/dQw4w9WgXcQ",
    ]) {
      expect(matchPastedVideo(url)).toBe(url);
    }
  });

  test("不是视频站的链接不命中", () => {
    expect(matchPastedVideo("https://example.com/page")).toBeNull();
    expect(matchPastedVideo("https://github.com/learnhouse/learnhouse")).toBeNull();
  });

  test("bilibili 的分享文案带说明文字，不命中", () => {
    // 从 App 里复制出来长这样，直接吃掉的话老师的文案就没了
    expect(
      matchPastedVideo(
        "【某某公开课】 https://www.bilibili.com/video/BV1GJ411x7h7 分享自B站"
      )
    ).toBeNull();
  });

  test("多行内容不命中", () => {
    expect(
      matchPastedVideo(
        "第一行\nhttps://www.bilibili.com/video/BV1GJ411x7h7\n第三行"
      )
    ).toBeNull();
  });

  test("整段正文里恰好提到 bilibili 也不命中", () => {
    expect(
      matchPastedVideo("这节课的视频在 bilibili.com 上，自己去搜")
    ).toBeNull();
  });

  test("不带协议头的裸域名不命中", () => {
    expect(matchPastedVideo("www.bilibili.com/video/BV1GJ411x7h7")).toBeNull();
  });

  test("非 http 协议不命中", () => {
    expect(
      matchPastedVideo("javascript:alert('bilibili.com')")
    ).toBeNull();
  });

  test("空内容不命中", () => {
    expect(matchPastedVideo("")).toBeNull();
    expect(matchPastedVideo("   \n  ")).toBeNull();
    expect(matchPastedVideo(undefined)).toBeNull();
  });

  test("不含视频站的 iframe 不命中", () => {
    expect(
      matchPastedVideo('<iframe src="https://example.com/x"></iframe>')
    ).toBeNull();
  });
});
