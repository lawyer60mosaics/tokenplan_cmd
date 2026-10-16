"""Read subscription quota with credentials managed by the corresponding CLI.

No browser storage extraction. Claude's usage endpoint and Google's Code Assist
quota protocol are internal interfaces and can change independently of this app.
"""

import json
from dataclasses import replace
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlencode

from .providers import Reading, SourceError, clock, number, stamp
from .network import https_json, post_json
from .cache import cached, cached_with_time

_google_tokens = {}
_google_lock = threading.Lock()


def read_auth(path: Path) -> dict:
    if not path.is_file():
        raise SourceError("未找到 CLI 登录凭据；请在配置页按 L 登录，或指定正确的凭据路径", auth=True)
    if path.stat().st_size > 1024 * 1024:
        raise SourceError("登录凭据文件过大")
    result = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(result, dict):
        raise SourceError("CLI 凭据格式无效，请重新登录", auth=True)
    return result


def claude_path(panel: dict) -> Path:
    return Path(
        panel.get("auth_file")
        or Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))) / ".credentials.json"
    ).expanduser()


def parse_claude(data: dict, model="account") -> Reading:
    lines = []
    names = {"five_hour": "5小时", "seven_day": "7天"}
    for key, window in data.items():
        if key not in names and not key.startswith("seven_day_"):
            continue
        if window is None:
            continue
        if not isinstance(window, dict) or window.get("utilization") is None:
            continue
        scope = key.removeprefix("seven_day_")
        if model != "account" and key not in names and model.casefold() not in scope.casefold():
            continue
        used = number(window["utilization"])
        if not 0 <= used <= 100:
            raise ValueError("订阅百分比超出范围")
        label = names.get(key, "7天 " + scope)
        lines.append(f"{label}: 剩余 {100 - used:.1f}% / 已用 {used:.1f}%")
        if window.get("resets_at"):
            lines.append("  重置: " + clock(stamp(window["resets_at"])))
    if not lines:
        raise SourceError("Claude 未返回可用的订阅额度，不能据此推断剩余为零")
    if model != "account":
        lines.append("含账户共享额度；模型筛选不代表独立额度")
    return Reading(tuple(lines), time.time(), "Claude Code subscription / OAuth usage")


def claude(panel: dict) -> Reading:
    path = claude_path(panel)
    auth = read_auth(path).get("claudeAiOauth")
    if not isinstance(auth, dict) or not auth.get("accessToken"):
        raise SourceError("需要 Claude Code 订阅登录，API Key 无法读取此订阅额度", auth=True)
    if auth.get("expiresAt") and number(auth["expiresAt"]) / 1000 <= time.time():
        raise SourceError("Claude 登录已过期；请在配置页按 L 重新登录", auth=True)
    response, observed = cached_with_time(
        ("claude", str(path.resolve()), path.stat().st_mtime_ns),
        60,
        lambda: https_json(
            "https://api.anthropic.com/api/oauth/usage",
            {
                "Authorization": "Bearer " + auth["accessToken"],
                "anthropic-beta": "oauth-2025-04-20",
                "Accept": "application/json",
            },
        ),
    )
    return replace(parse_claude(response, panel.get("model", "account")), observed_at=observed)


def gemini_path(panel: dict) -> Path:
    return Path(panel.get("auth_file") or Path.home() / ".gemini" / "oauth_creds.json").expanduser()


def google_client_metadata(panel: dict) -> tuple[str, str]:
    """Read the installed public CLI's OAuth app metadata, never embed it in Git."""
    candidates = []
    if panel.get("gemini_oauth_module"):
        candidates.append(Path(panel["gemini_oauth_module"]).expanduser())
    import shutil

    executable = shutil.which("gemini") or shutil.which("gemini.cmd")
    roots = [Path(executable).parent / "node_modules"] if executable else []
    if os.environ.get("APPDATA"):
        roots.append(Path(os.environ["APPDATA"]) / "npm" / "node_modules")
    for root in roots:
        for package in (
            root / "@google" / "gemini-cli-core",
            root / "@google" / "gemini-cli" / "node_modules" / "@google" / "gemini-cli-core",
        ):
            candidates.append(package / "dist" / "src" / "code_assist" / "oauth2.js")
    for path in candidates:
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        values = []
        for field in ("OAUTH_CLIENT_ID", "OAUTH_CLIENT_SECRET"):
            match = re.search(r"\b" + field + r"""\s*=\s*['"]([^'"\r\n]+)['"]""", source)
            values.append(match.group(1) if match else "")
        if all(values):
            return values[0], values[1]
    raise SourceError("Google 登录需要刷新；请安装 Gemini CLI，或配置其 oauth2.js 模块路径", auth=True)


def google_token(panel: dict) -> str:
    path = gemini_path(panel)
    auth = read_auth(path)
    key = (str(path.resolve()), path.stat().st_mtime_ns)
    with _google_lock:
        cached = _google_tokens.get(key)
        if cached and cached[1] > time.time() + 90:
            return cached[0]
        token = auth.get("access_token")
        expiry = auth.get("expiry_date", 0)
        if token and expiry and number(expiry) / 1000 > time.time() + 90:
            return token
        if not auth.get("refresh_token"):
            raise SourceError("Gemini 登录已过期，请在配置页重新登录", auth=True)
        client_id, client_secret = google_client_metadata(panel)
        response = https_json(
            "https://oauth2.googleapis.com/token",
            {"Content-Type": "application/x-www-form-urlencoded"},
            urlencode(
                {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": auth["refresh_token"],
                    "grant_type": "refresh_token",
                }
            ).encode(),
            "POST",
        )
        if not response.get("access_token"):
            raise SourceError("Google 未返回有效登录令牌", auth=True)
        _google_tokens[key] = (response["access_token"], time.time() + number(response.get("expires_in", 3600)))
        # The CLI owns its credential file; do not overwrite concurrent CLI updates.
        if len(_google_tokens) > 50:
            for old in list(_google_tokens)[:-25]:
                del _google_tokens[old]
        return response["access_token"]


def parse_gemini(data: dict, model="account") -> Reading:
    buckets = data.get("buckets")
    if not isinstance(buckets, list):
        raise SourceError("Gemini 未返回额度桶")
    lines = []
    for bucket in buckets:
        if not isinstance(bucket, dict):
            continue
        name = str(bucket.get("modelId") or "account")
        if model != "account" and model.casefold() != name.casefold():
            continue
        unit = bucket.get("tokenType") or "quota"
        fraction = bucket.get("remainingFraction")
        if fraction is not None:
            fraction = number(fraction)
            if not 0 <= fraction <= 1:
                raise ValueError("Gemini 剩余比例超出范围")
            lines.append(f"剩余 {fraction * 100:.1f}% {unit} | {name}")
        if bucket.get("remainingAmount") is not None:
            from decimal import Decimal

            amount = Decimal(str(bucket["remainingAmount"]))
            if not amount.is_finite() or amount < 0:
                raise ValueError("Gemini 剩余数量无效")
            lines.append(f"  剩余数量: {amount:f} {unit}")
        if bucket.get("resetTime"):
            lines.append("  重置: " + clock(stamp(bucket["resetTime"])))
    if not lines:
        raise SourceError("没有匹配的 Gemini 模型额度，请检查模型 ID 或选择 account")
    return Reading(tuple(lines), time.time(), "Gemini CLI / Code Assist quota (非 Gemini 网页聊天额度)")


def gemini(panel: dict) -> Reading:
    token = google_token(panel)
    endpoint = "https://cloudcode-pa.googleapis.com/v1internal:"
    project = (
        panel.get("google_project")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("GOOGLE_CLOUD_PROJECT_ID")
    )
    path = gemini_path(panel)
    key = ("gemini", str(path.resolve()), path.stat().st_mtime_ns, project)
    if not project:
        response = cached(
            key + ("project",),
            300,
            lambda: post_json(
                endpoint + "loadCodeAssist",
                token,
                {
                    "metadata": {
                        "ideType": "IDE_UNSPECIFIED",
                        "platform": "PLATFORM_UNSPECIFIED",
                        "pluginType": "GEMINI",
                    }
                },
            ),
        )
        project = response.get("cloudaicompanionProject")
    if not isinstance(project, str) or not project:
        raise SourceError(
            "Google 未提供项目 ID；请在配置页填写已授权的 Google Cloud Project，或先完成 Gemini CLI 登录", auth=True
        )
    response, observed = cached_with_time(
        key + ("quota", project), 10, lambda: post_json(endpoint + "retrieveUserQuota", token, {"project": project})
    )
    return replace(parse_gemini(response, panel.get("model", "account")), observed_at=observed)
