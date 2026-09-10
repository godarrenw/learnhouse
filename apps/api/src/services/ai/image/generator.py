# ============================================================================
# 修改声明（GNU AGPL-3.0 第 5(a) 条）
#
# 本文件是 LearnHouse v1.3.6 的修改版本。
#   上游项目： https://github.com/learnhouse/learnhouse  （tag v1.3.6）
#   修改方：   中山大学先进制造学院 · 先进智造实验室
#   修改日期： 2026-09-08
#   修改摘要： 生图接口由硬编码的 Google GenAI SDK 改为 OpenAI 兼容的 /images/generations，以便使用硅基流动等第三方服务商。
#
# 上游原始文件见本仓库 git 历史：git show 1.3.6:apps/api/src/services/ai/image/generator.py
# 本平台整体仍以 AGPL-3.0 授权；完整的修改源码获取方式见平台页脚。
# ============================================================================
"""AI image generation — PATCH(nas): OpenAI 兼容的图片接口（硅基流动）。

上游原版是 **Google-only** 的：直接调 google-genai SDK 的 nano banana 模型，
不走 ``src/services/ai/llm`` 那层 provider 抽象，所以即使把 LEARNHOUSE_AI_PROVIDER
设成别家，生图仍然强制要 Gemini key。本部署没有 Gemini key，改成走
OpenAI 兼容的 ``POST {base_url}/images/generations``（硅基流动实现了这套接口）。

复用文本层已有的凭据，不需要额外配置：
  - api_key  <- ai_config.api_key      (LEARNHOUSE_AI_API_KEY)
  - base_url <- ai_config.base_url     (LEARNHOUSE_AI_BASE_URL)

两种模式与上游一致：
  - 文生图     (只有 ``prompt``)                    -> IMAGE_MODEL
  - 图像编辑   (``prompt`` + ``input_images``)      -> IMAGE_EDIT_MODEL
    这条路径支撑编辑器里"再暗一点 / 加个示意图"的迭代优化循环。

对外契约与上游保持一致：``generate_image()`` 返回图片字节，
未配置时抛 ``AINotConfiguredError``，模型没给图时抛 ``RuntimeError``。
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from typing import Optional

import httpx

from config.config import get_learnhouse_config
from src.services.ai.llm import AINotConfiguredError

logger = logging.getLogger(__name__)

# 文生图 / 图像编辑的默认模型（硅基流动模型名）。
# 可用 LEARNHOUSE_AI_IMAGE_MODEL / LEARNHOUSE_AI_IMAGE_EDIT_MODEL 覆盖。
DEFAULT_IMAGE_MODEL = "Qwen/Qwen-Image"
DEFAULT_IMAGE_EDIT_MODEL = "Qwen/Qwen-Image-Edit-2509"
DEFAULT_IMAGE_SIZE = "1024x1024"

OUTPUT_MIME = "image/png"
OUTPUT_EXT = "png"

# 调用前先截断超长 prompt，避免白白花掉一次额度。
MAX_PROMPT_CHARS = 4000

# 针对限流 / 容量问题的有限重试。
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 1.5
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# 生图比文本慢得多，超时给足。
_REQUEST_TIMEOUT = 300.0


def _sniff_mime(data: bytes) -> str:
    """尽力识别真实 MIME —— 把 JPEG/WebP 标成 PNG 会被上游拒绝。"""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return OUTPUT_MIME


def _is_retryable_status(status: Optional[int]) -> bool:
    return isinstance(status, int) and status in _RETRYABLE_STATUS


def _resolve_image_config() -> tuple[str, str]:
    """返回 ``(api_key, base_url)``，未配置则抛异常。"""
    cfg = get_learnhouse_config().ai_config

    api_key = getattr(cfg, "api_key", None) or getattr(cfg, "gemini_api_key", None)
    base_url = (getattr(cfg, "base_url", None) or "").strip().rstrip("/")

    if not api_key or not base_url:
        raise AINotConfiguredError(
            "AI 生图需要配置 OpenAI 兼容的图片接口："
            "请设置 LEARNHOUSE_AI_API_KEY 与 LEARNHOUSE_AI_BASE_URL。"
        )
    return api_key, base_url


def _pick_image_url(payload: dict) -> Optional[str]:
    """从返回体里取第一张图的 URL。

    硅基流动返回 ``{"images": [{"url": ...}], ...}``；
    OpenAI 官方那套是 ``{"data": [{"url"|"b64_json": ...}]}``。两种都认。
    """
    for key in ("images", "data"):
        items = payload.get(key)
        if isinstance(items, list) and items:
            first = items[0]
            if isinstance(first, dict) and first.get("url"):
                return first["url"]
    return None


def _pick_image_b64(payload: dict) -> Optional[str]:
    for key in ("images", "data"):
        items = payload.get(key)
        if isinstance(items, list) and items:
            first = items[0]
            if isinstance(first, dict) and first.get("b64_json"):
                return first["b64_json"]
    return None


async def generate_image(
    prompt: str,
    *,
    input_images: Optional[list[bytes]] = None,
) -> bytes:
    """生成（或编辑）一张图片，返回图片字节。

    未配置凭据时抛 ``AINotConfiguredError``；模型没返回图片（例如被安全策略
    拦截）时抛 ``RuntimeError``。
    """
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("A non-empty prompt is required for image generation.")
    if len(prompt) > MAX_PROMPT_CHARS:
        prompt = prompt[:MAX_PROMPT_CHARS]

    api_key, base_url = _resolve_image_config()

    imgs = [img for img in (input_images or []) if img]
    if imgs:
        model = (os.environ.get("LEARNHOUSE_AI_IMAGE_EDIT_MODEL") or "").strip() or DEFAULT_IMAGE_EDIT_MODEL
        # 编辑模式：把参考图作为 data URI 传上去。上游只用得到第一张，
        # 与原实现"以提供的图片为起点进行编辑"的语义保持一致。
        head = imgs[0]
        data_uri = f"data:{_sniff_mime(head)};base64,{base64.b64encode(head).decode('ascii')}"
        payload = {
            "model": model,
            "prompt": prompt,
            "image": data_uri,
        }
    else:
        cfg = get_learnhouse_config().ai_config
        model = (getattr(cfg, "image_model", None) or "").strip() or DEFAULT_IMAGE_MODEL
        payload = {
            "model": model,
            "prompt": prompt,
            "image_size": (os.environ.get("LEARNHOUSE_AI_IMAGE_SIZE") or "").strip() or DEFAULT_IMAGE_SIZE,
            "batch_size": 1,
        }

    url = f"{base_url}/images/generations"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    body: Optional[dict] = None
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                resp = await client.post(url, json=payload, headers=headers)
                if _is_retryable_status(resp.status_code) and attempt < _MAX_ATTEMPTS:
                    logger.warning(
                        "Image generation transient status %s, retry %d/%d",
                        resp.status_code, attempt, _MAX_ATTEMPTS,
                    )
                    await asyncio.sleep(_RETRY_BACKOFF_SECONDS * attempt)
                    continue
                if resp.status_code >= 400:
                    # 只记状态码：上游报错正文可能回显请求内容，避免泄露 key。
                    logger.error("Image generation failed with status %s", resp.status_code)
                    raise RuntimeError("Image generation failed")
                body = resp.json()
                break
            except httpx.HTTPError as e:
                # 同样只记异常类型，不记消息（可能含 URL / 凭据）。
                if attempt < _MAX_ATTEMPTS:
                    logger.warning(
                        "Image generation transport error (%s), retry %d/%d",
                        type(e).__name__, attempt, _MAX_ATTEMPTS,
                    )
                    await asyncio.sleep(_RETRY_BACKOFF_SECONDS * attempt)
                    continue
                logger.error("Image generation call failed: %s", type(e).__name__)
                raise RuntimeError("Image generation failed") from e

        if not isinstance(body, dict):
            logger.warning("Image generation returned no usable payload")
            raise RuntimeError(
                "The model did not return an image. Try rephrasing your prompt."
            )

        b64 = _pick_image_b64(body)
        if b64:
            try:
                return base64.b64decode(b64)
            except Exception as e:  # noqa: BLE001
                logger.error("Image generation base64 decode failed: %s", type(e).__name__)
                raise RuntimeError("Image generation failed") from e

        image_url = _pick_image_url(body)
        if not image_url:
            logger.warning("Image generation returned no image")
            raise RuntimeError(
                "The model did not return an image. Try rephrasing your prompt."
            )

        # 返回的是有时效的签名 URL，必须当场取回字节存进内容库。
        try:
            img_resp = await client.get(image_url)
            img_resp.raise_for_status()
            return img_resp.content
        except httpx.HTTPError as e:
            logger.error("Image download failed: %s", type(e).__name__)
            raise RuntimeError("Image generation failed") from e
