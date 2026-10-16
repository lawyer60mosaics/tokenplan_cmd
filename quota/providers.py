"""Read-only sources. Never manufacture unavailable quotas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import math
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
from urllib import error, request
from email.utils import parsedate_to_datetime


class SourceError(Exception):
    def __init__(self, message: str, retry_after: float = 0, auth: bool = False):
        super().__init__(message)
        self.retry_after = retry_after
        self.auth = auth


@dataclass(frozen=True)
class Reading:
    metrics: tuple[str, ...]
    observed_at: float
    source: str
    demo: bool = False
    partial: bool = False


def number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("指标必须是有限数值")
    return float(value)


def stamp(value: object) -> float:
    if isinstance(value, (int, float)):
        return number(value)
    if not isinstance(value, str):
        raise ValueError("需要时间戳")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("时间必须包含时区")
    return parsed.timestamp()


def clock(value: float) -> str:
    return datetime.fromtimestamp(value).strftime("%m-%d %H:%M:%S")


def parse_codex(data: dict) -> Reading:
    if not isinstance(data, dict):
        raise ValueError("需要 JSON 对象")
    buckets = data.get("rateLimitsByLimitId") or {}
    if not buckets and data.get("rateLimits"):
        buckets = {"codex": data["rateLimits"]}
    if not isinstance(buckets, dict):
        raise ValueError("额度桶必须为对象")
    lines = []
    for name, bucket in buckets.items():
        if not isinstance(bucket, dict):
            continue
        for field in ("primary", "secondary"):
            window = bucket.get(field)
            if not window:
                continue
            used = number(window["usedPercent"])
            if not 0 <= used <= 100:
                raise ValueError("额度百分比超出范围")
            minutes = window.get("windowDurationMins")
            duration = f"{number(minutes):g}min" if minutes is not None else field
            lines.append(f"{name} {duration}: 剩余 {100 - used:.1f}% / 已用 {used:.1f}%")
            reset = window.get("resetsAt")
            if reset is not None:
                lines.append(f"  重置: {clock(number(reset))}")
        credits = bucket.get("credits")
        if credits and credits.get("balance") is not None:
            lines.append(f"{name} credits: {credits['balance']}")
    if not lines:
        raise SourceError("Codex 未返回可用额度；请确认 CLI 已登录订阅账号")
    return Reading(tuple(lines), time.time(), "Codex app-server / account quota")


def codex_command(panel: dict) -> list[str]:
    explicit = panel.get("codex_executable") or os.environ.get("AI_QUOTA_CODEX_EXE")
    if explicit:
        return [explicit]
    found = shutil.which("codex.exe") or shutil.which("codex")
    if found and Path(found).suffix.lower() not in (".cmd", ".bat", ".ps1"):
        return [found]
    # npm shims require a shell on Windows. Use the packaged native binary instead.
    shim = found or shutil.which("codex.cmd")
    if shim:
        root = Path(shim).parent / "node_modules" / "@openai"
        native = next(root.glob("codex*/**/vendor/*/codex/codex.exe"), None)
        if native:
            return [str(native)]
    raise SourceError("未找到 Codex CLI；安装并登录，或配置 AI_QUOTA_CODEX_EXE")


def codex(panel: dict) -> Reading:
    env = os.environ.copy()
    if panel.get("codex_home"):
        env["CODEX_HOME"] = str(Path(panel["codex_home"]).expanduser())
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    with subprocess.Popen(
        codex_command(panel) + ["app-server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        env=env,
        **options,
    ) as process:
        responses: queue.Queue = queue.Queue()

        def read() -> None:
            try:
                for line in process.stdout:
                    try:
                        message = json.loads(line)
                        if isinstance(message, dict) and "id" in message:
                            responses.put(message)
                    except ValueError:
                        continue
            finally:
                responses.put(None)

        reader = threading.Thread(target=read, daemon=True)
        reader.start()

        def send(message: dict) -> None:
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()

        deadline = time.monotonic() + 20

        def receive(identity: int) -> dict:
            while True:
                if time.monotonic() >= deadline:
                    raise SourceError("Codex 额度读取超时")
                try:
                    message = responses.get(timeout=max(0.01, deadline - time.monotonic()))
                except queue.Empty as exc:
                    raise SourceError("Codex 额度读取超时") from exc
                if message is None:
                    raise SourceError("Codex 服务提前退出；请检查 CLI 登录状态")
                if message.get("id") == identity:
                    if "error" in message:
                        raise SourceError("Codex 拒绝额度读取；请确认 CLI 已登录且支持此协议")
                    return message.get("result", {})

        try:
            send({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "ai-quota", "version": "0.1.0"}}})
            receive(1)
            send({"method": "initialized", "params": {}})
            send({"id": 2, "method": "account/rateLimits/read", "params": {}})
            return parse_codex(receive(2))
        finally:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            reader.join(timeout=1)


def parse_deepseek(data: dict) -> Reading:
    if not isinstance(data, dict):
        raise ValueError("需要 JSON 对象")
    lines = []
    for balance in data.get("balance_infos", []):
        currency = balance["currency"]
        amount = Decimal(balance["total_balance"])
        if not amount.is_finite():
            raise ValueError("余额数值无效")
        lines.append(f"账户余额: {amount:f} {currency}")
    if not lines:
        raise SourceError("DeepSeek 未返回余额")
    lines.append("账户共享余额；此接口不提供模型 Token 用量")
    return Reading(tuple(lines), time.time(), "DeepSeek GET /user/balance")


def retry_seconds(value: str | None) -> float:
    try:
        return min(86400, max(0, float(value)))
    except (ValueError, TypeError):
        try:
            return min(86400, max(0, parsedate_to_datetime(value).timestamp() - time.time()))
        except (ValueError, TypeError, OverflowError):
            return 60


def deepseek(panel: dict) -> Reading:
    from . import credentials

    key_name = panel.get("key_env", "DEEPSEEK_API_KEY")
    key = credentials.read(panel["credential_ref"]) if panel.get("credential_ref") else os.environ.get(key_name)
    if not key:
        raise SourceError("未连接：按 C 在配置界面设置 API Key", auth=True)
    req = request.Request(
        "https://api.deepseek.com/user/balance",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=15) as response:
            return parse_deepseek(json.loads(response.read(1024 * 1024)))
    except error.HTTPError as exc:
        if exc.code in (401, 403):
            raise SourceError("DeepSeek 凭据无效，请在配置界面更新", auth=True) from exc
        raise SourceError(
            f"DeepSeek HTTP {exc.code}",
            retry_after=retry_seconds(exc.headers.get("Retry-After")) if exc.code == 429 else 0,
        ) from exc


def snapshot(panel: dict, base: Path) -> Reading:
    path = Path(panel["snapshot"]).expanduser()
    if not path.is_absolute():
        path = base / path
    if not path.exists():
        raise SourceError("待接入：配置 JSON 快照源；见 README")
    if path.stat().st_size > 1024 * 1024:
        raise SourceError("快照超过 1 MB")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or not isinstance(data.get("metrics"), list):
        raise ValueError("快照必须包含指标数组")
    if data.get("provider") != panel["provider"] or data.get("model", "account") != panel["model"]:
        raise SourceError("快照的平台／模型与面板配置不匹配")
    observed = stamp(data["observed_at"])
    if observed > time.time() + 60:
        raise SourceError("快照时间位于未来，请检查时区")
    lines = []
    for metric in data["metrics"]:
        if not isinstance(metric, dict):
            raise ValueError("指标必须是对象")
        label, unit = str(metric["label"]), str(metric["unit"])
        used, limit, remaining = metric.get("used"), metric.get("limit"), metric.get("remaining")
        if used is not None:
            used = number(used)
            lines.append(f"{label}: 已用 {used:g} {unit}")
        if limit is not None:
            limit = number(limit)
            if limit < 0:
                raise ValueError("额度上限不能为负")
            if remaining is None and used is not None:
                remaining = max(0, limit - used)
        if remaining is not None:
            lines.append(f"{label}: 剩余 {number(remaining):g} {unit}")
        if used is None and remaining is None:
            lines.append(f"{label}: 未知")
        if metric.get("resets_at") is not None:
            lines.append(f"  重置: {clock(stamp(metric['resets_at']))}")
    if not lines:
        raise SourceError("快照不包含指标")
    return Reading(tuple(lines), observed, "本地 JSON 快照 / " + str(data.get("source", "external")))


def collect(panel: dict, base: Path) -> Reading:
    adapter = panel["adapter"]
    try:
        if adapter == "codex":
            return codex(panel)
        if adapter == "deepseek":
            return deepseek(panel)
        if adapter == "gemini" and panel.get("gemini_backend", "agy") == "agy":
            from .antigravity import collect as agy_collect

            return agy_collect(panel)
        if adapter in ("claude", "gemini"):
            from .subscriptions import claude, gemini

            return (claude if adapter == "claude" else gemini)(panel)
        if adapter == "ark":
            from .ark import collect_ark

            return collect_ark(panel)
        if adapter == "snapshot":
            return snapshot(panel, base)
        if adapter == "demo":
            return Reading(("演示数据：不代表真实账户", "示例剩余额度: 72%"), time.time(), "DEMO", demo=True)
        raise SourceError("未知适配器")
    except SourceError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, OverflowError, InvalidOperation) as exc:
        raise SourceError("数据格式无效，请检查数据源与适配器版本") from exc
    except (OSError, error.URLError) as exc:
        raise SourceError("连接失败，请检查网络或数据源路径") from exc
