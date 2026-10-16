"""Bounded HTTPS JSON requests; never forward authentication on redirects."""

import json
from urllib import error, request

from .providers import SourceError, retry_seconds


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def https_json(url: str, headers=None, body: bytes | None = None, method=None) -> dict:
    req = request.Request(url, data=body, headers=headers or {}, method=method)
    opener = request.build_opener(NoRedirect())
    try:
        with opener.open(req, timeout=20) as response:
            payload = response.read(1024 * 1024 + 1)
        if len(payload) > 1024 * 1024:
            raise SourceError("平台响应超过 1 MB，停止解析")
        result = json.loads(payload)
        if not isinstance(result, dict):
            raise SourceError("平台返回了非对象 JSON")
        return result
    except error.HTTPError as exc:
        if exc.code == 400 and url == "https://oauth2.googleapis.com/token":
            raise SourceError("Google 登录刷新失败，请重新登录 Gemini CLI", auth=True) from exc
        if exc.code in (401, 403):
            raise SourceError(f"认证或权限失败 (HTTP {exc.code})，请在配置页登录或更新凭据", auth=True) from exc
        if exc.code == 429:
            raise SourceError(
                "平台限流 (HTTP 429)，等待后重试", retry_after=retry_seconds(exc.headers.get("Retry-After"))
            ) from exc
        raise SourceError(f"平台 HTTP {exc.code}，未取得最新数据") from exc


def post_json(url: str, token: str, data: dict) -> dict:
    return https_json(
        url, {"Authorization": "Bearer " + token, "Content-Type": "application/json"}, json.dumps(data).encode(), "POST"
    )
