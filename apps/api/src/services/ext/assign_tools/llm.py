"""AI 出题用的 OpenAI 兼容接口客户端。

配置走环境变量（改 organization_config 模型太重，见 PHASE3_BRIEF 的取舍）：

- `LEARNHOUSE_EXT_LLM_BASE_URL`  端点，形如 `https://example.com/v1`
- `LEARNHOUSE_EXT_LLM_API_KEY`   API key，**只从环境变量读，代码里不写死**
- `LEARNHOUSE_EXT_LLM_MODEL`     默认模型 id，请求里可以用 `model` 覆盖

整个模块对外只有 `chat_completion` 和 `list_models` 两个联网入口，
测试里只需要 monkeypatch 这两个点。
"""

import json
import os
import re

import httpx

from .spec import SpecError

TIMEOUT_SECONDS = 180.0


class LLMNotConfiguredError(SpecError):
    """没配 LLM 端点。是配置问题不是代码问题，单独一个类型方便路由回 503。"""


def llm_config() -> dict:
    """读环境变量里的 LLM 配置。"""
    base = (os.environ.get("LEARNHOUSE_EXT_LLM_BASE_URL") or "").strip().rstrip("/")
    return {
        "base": base,
        "key": (os.environ.get("LEARNHOUSE_EXT_LLM_API_KEY") or "").strip(),
        "model": (os.environ.get("LEARNHOUSE_EXT_LLM_MODEL") or "").strip(),
    }


def _require_config() -> dict:
    c = llm_config()
    if not c["base"]:
        raise LLMNotConfiguredError(
            "没有配置 AI 出题的大模型端点。请在部署环境里设置 "
            "LEARNHOUSE_EXT_LLM_BASE_URL（以及 LEARNHOUSE_EXT_LLM_API_KEY、"
            "LEARNHOUSE_EXT_LLM_MODEL）后重启后端。"
        )
    return c


def _headers(key: str) -> dict:
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if key:
        h["Authorization"] = "Bearer " + key
    return h


def _client() -> httpx.AsyncClient:
    # trust_env=False：端点可能在内网，或者本机装了会劫持出网请求的代理。
    # 对应原实现里的 urllib ProxyHandler({})。
    return httpx.AsyncClient(timeout=TIMEOUT_SECONDS, trust_env=False)


async def list_models() -> dict:
    """列出端点上可用的模型 id。"""
    c = _require_config()
    async with _client() as client:
        try:
            resp = await client.get(c["base"] + "/models", headers=_headers(c["key"]))
        except httpx.HTTPError as e:
            raise SpecError(
                "连不上大模型接口 %s（%s）。检查端点是否可达。" % (c["base"], type(e).__name__)
            )
    if resp.status_code >= 400:
        raise SpecError("大模型接口返回 HTTP %s：%s" % (resp.status_code, resp.text[:300]))
    data = resp.json()
    ids = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
    return {"base": c["base"], "models": ids, "configured_model": c["model"] or None}


async def chat_completion(model: str, messages: list[dict], temperature: float = 0.3) -> str:
    """调一次 chat/completions，返回助手消息的文本内容。"""
    c = _require_config()
    payload = {"model": model, "messages": messages, "temperature": temperature}
    async with _client() as client:
        try:
            resp = await client.post(
                c["base"] + "/chat/completions",
                headers=_headers(c["key"]),
                content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            )
        except httpx.HTTPError as e:
            raise SpecError(
                "连不上大模型接口 %s（%s）。检查端点是否可达。" % (c["base"], type(e).__name__)
            )
    if resp.status_code >= 400:
        raise SpecError("调用大模型接口失败（HTTP %s）：%s" % (resp.status_code, resp.text[:300]))
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise SpecError("模型没有返回内容：%s" % json.dumps(data, ensure_ascii=False)[:300])
    return (choices[0].get("message") or {}).get("content") or ""


def extract_json(text: str) -> dict:
    """从模型输出里抠出那个 JSON 对象：去代码围栏，取第一个 { 到最后一个 }。"""
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t).strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        raise ValueError("输出里找不到 JSON 对象")
    return json.loads(t[i:j + 1])
