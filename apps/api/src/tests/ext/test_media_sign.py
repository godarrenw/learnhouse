"""重媒体限时签名的单元测试（SYSU-SAM）。

只测纯逻辑：白名单、签名往返、过期、篡改。走 HTTP 的部分（/ext/media/sign 与
两个媒体路由）由本地预发环境的端到端验证覆盖，见 docs/sysu-sam/QA/tunnel-media.md。
"""

import os
import time

import pytest

os.environ.setdefault("LEARNHOUSE_EXT_MEDIA_SIGN_SECRET", "t" * 48)

from src.services.ext.media_sign import (  # noqa: E402
    DEFAULT_TTL_SECONDS,
    MAX_TTL_SECONDS,
    MediaSignatureError,
    is_signable_media_path,
    resolve_signed_user_id,
    sign_media_path,
    verify_media_signature,
)

VIDEO = "/api/v1/stream/video/org_1/course_1/activity_1/a.mp4"
BLOCK = "/api/v1/stream/block/org_1/course_1/activity_1/block_1/a.mp4"
BLOCK_AUDIO = "/api/v1/stream/block/audio/org_1/course_1/activity_1/block_1/a.mp3"
CONTENT_VIDEO = "/content/orgs/o/courses/c/activities/a/video/x.mp4"
CONTENT_PDF = "/content/orgs/o/courses/c/activities/a/documentpdf/x.pdf"
CONTENT_VIDEO_BLOCK = "/content/orgs/o/courses/c/activities/a/dynamic/blocks/videoBlock/b/x.mp4"
CONTENT_PDF_BLOCK = "/content/orgs/o/courses/c/activities/a/dynamic/blocks/pdfBlock/b/x.pdf"
CONTENT_AUDIO_BLOCK = "/content/orgs/o/courses/c/activities/a/dynamic/blocks/audioBlock/b/x.mp3"


class TestSignablePaths:
    @pytest.mark.parametrize(
        "path",
        [VIDEO, BLOCK, BLOCK_AUDIO, CONTENT_VIDEO, CONTENT_PDF,
         CONTENT_VIDEO_BLOCK, CONTENT_PDF_BLOCK, CONTENT_AUDIO_BLOCK],
    )
    def test_heavy_media_is_signable(self, path):
        assert is_signable_media_path(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            # 图片块要留在 learn 域名，校外必须能看
            "/content/orgs/o/courses/c/activities/a/dynamic/blocks/imageBlock/b/x.png",
            # 课程封面、头像、机构 logo 同理
            "/content/orgs/o/courses/c/thumbnails/x.png",
            "/content/users/u/avatars/x.png",
            # 学生提交文件永远不进签名体系
            "/content/orgs/o/courses/c/activities/a/assignments/as/tasks/t/subs/f.pdf",
            # 字幕与 HLS 留在 learn，省一层 CORS
            "/api/v1/stream/captions/o/c/a/zh.vtt",
            "/api/v1/stream/hls/o/c/a/master.m3u8",
            "/api/v1/stream/block-hls/o/c/a/b/master.m3u8",
            # 播客本部署没在用
            "/api/v1/stream/audio/o/p/e/x.mp3",
            # 普通接口绝不能签
            "/api/v1/users/me",
            "/api/v1/auth/login",
            # 形态不合法
            "",
            "api/v1/stream/video/o/c/a/x.mp4",
            "/content/orgs/o/courses/c/activities/a/video/../../../etc/passwd",
        ],
    )
    def test_everything_else_is_not_signable(self, path):
        assert is_signable_media_path(path) is False


class TestRoundTrip:
    def test_sign_then_verify(self):
        signed = sign_media_path(VIDEO, 42)
        assert signed["uid"] == 42
        assert len(signed["sig"]) == 64
        assert verify_media_signature(VIDEO, signed["sig"], signed["exp"], signed["uid"]) == 42

    def test_default_ttl(self):
        now = 1_700_000_000
        signed = sign_media_path(VIDEO, 1, now=now)
        assert signed["exp"] == now + DEFAULT_TTL_SECONDS

    def test_refuses_unsignable_path(self):
        with pytest.raises(MediaSignatureError):
            sign_media_path("/api/v1/users/me", 1)

    @pytest.mark.parametrize("ttl", [0, -1, MAX_TTL_SECONDS + 1])
    def test_refuses_bad_ttl(self, ttl):
        with pytest.raises(MediaSignatureError):
            sign_media_path(VIDEO, 1, ttl_seconds=ttl)


class TestRejections:
    def test_expired(self):
        now = int(time.time())
        signed = sign_media_path(VIDEO, 1, ttl_seconds=60, now=now - 120)
        with pytest.raises(MediaSignatureError, match="expired"):
            verify_media_signature(VIDEO, signed["sig"], signed["exp"], signed["uid"])

    def test_tampered_path(self):
        signed = sign_media_path(VIDEO, 1)
        other = VIDEO.replace("a.mp4", "b.mp4")
        with pytest.raises(MediaSignatureError, match="mismatch"):
            verify_media_signature(other, signed["sig"], signed["exp"], signed["uid"])

    def test_tampered_uid(self):
        """把 uid 改成别人 —— 这是最要紧的一条：能改就等于可以冒充任意用户。"""
        signed = sign_media_path(VIDEO, 1)
        with pytest.raises(MediaSignatureError, match="mismatch"):
            verify_media_signature(VIDEO, signed["sig"], signed["exp"], 2)

    def test_extended_exp(self):
        signed = sign_media_path(VIDEO, 1)
        with pytest.raises(MediaSignatureError, match="mismatch"):
            verify_media_signature(VIDEO, signed["sig"], int(signed["exp"]) + 3600, signed["uid"])

    def test_tampered_sig(self):
        signed = sign_media_path(VIDEO, 1)
        flipped = ("0" if signed["sig"][0] != "0" else "1") + signed["sig"][1:]
        with pytest.raises(MediaSignatureError, match="mismatch"):
            verify_media_signature(VIDEO, flipped, signed["exp"], signed["uid"])

    @pytest.mark.parametrize("bad", ["", "  ", "notanint"])
    def test_malformed_exp(self, bad):
        signed = sign_media_path(VIDEO, 1)
        with pytest.raises(MediaSignatureError):
            verify_media_signature(VIDEO, signed["sig"], bad, signed["uid"])

    def test_signature_for_one_path_does_not_work_on_another(self):
        """拿一个视频的签名去读同课程的 PDF —— 必须拒绝。"""
        signed = sign_media_path(CONTENT_VIDEO, 1)
        with pytest.raises(MediaSignatureError, match="mismatch"):
            verify_media_signature(CONTENT_PDF, signed["sig"], signed["exp"], signed["uid"])


class TestResolveFromQuery:
    def test_no_params_means_not_a_signed_request(self):
        assert resolve_signed_user_id(VIDEO, {}) is None

    def test_valid_params(self):
        signed = sign_media_path(VIDEO, 9)
        q = {"sig": signed["sig"], "exp": str(signed["exp"]), "uid": str(signed["uid"])}
        assert resolve_signed_user_id(VIDEO, q) == 9

    def test_partial_params_raise_rather_than_fall_back(self):
        """只带一半参数不能静默当成匿名，否则过期签名会伪装成权限问题。"""
        with pytest.raises(MediaSignatureError):
            resolve_signed_user_id(VIDEO, {"sig": "abc"})


class TestSecretDerivation:
    def test_env_secret_changes_signature(self, monkeypatch):
        a = sign_media_path(VIDEO, 1, now=1_700_000_000)["sig"]
        monkeypatch.setenv("LEARNHOUSE_EXT_MEDIA_SIGN_SECRET", "d" * 48)
        b = sign_media_path(VIDEO, 1, now=1_700_000_000)["sig"]
        assert a != b, "换密钥后签名必须变，否则密钥没被真正使用"
