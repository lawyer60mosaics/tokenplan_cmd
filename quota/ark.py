"""Volcengine API usage and remaining model resources through official arkcli."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import time

from .cli import resolve, run_json
from .providers import Reading, SourceError


def decimal_value(value, signed=False) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("指标不能为布尔值")
    result = Decimal(str(value))
    if not result.is_finite() or (result < 0 and not signed):
        raise ValueError("指标必须是非负有限数值")
    return result


def complete(data: dict) -> None:
    if data.get("is_truncated") or data.get("partial_failures"):
        raise SourceError("火山方舟返回了截断或部分失败，无法作为完整用量展示")


def parse_usage(data: dict, period: str, scope: str) -> list[str]:
    complete(data)
    totals = data.get("totals")
    if not isinstance(totals, dict) or "TotalTokens" not in totals:
        raise SourceError("方舟未返回 TotalTokens；不把未知用量当作零")
    lines = [f"{period} / {scope}:", f"Token 已用: {decimal_value(totals['TotalTokens']):f}"]
    if totals.get("ReqCnt") is not None:
        lines.append(f"请求数: {decimal_value(totals['ReqCnt']):f}")
    lines.append("聚合数据延迟约 5–30 分钟")
    return lines


def parse_resources(data: dict, model="account") -> list[str]:
    complete(data)
    items = data.get("items")
    if not isinstance(items, list):
        raise SourceError("方舟未返回模型资源包列表")
    lines = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("资源包数据无效")
        name = str(item.get("model", "unknown"))
        if model != "account" and name != model:
            continue
        free = item.get("free_usage")
        state = item.get("state")
        label = name + (f" [{state}]" if state and state != "Available" else "")
        if isinstance(free, dict) and free.get("remaining") is not None:
            lines.append(f"免费额度剩余 {decimal_value(free['remaining'], signed=True):f} | {label}")
        for pack in item.get("resource_packs") or []:
            if pack.get("remaining") is not None and (pack.get("type") != "FreeInference" or not free):
                lines.append(
                    f"{label} {pack.get('type', '资源包')}: 剩余 {decimal_value(pack['remaining'], signed=True):f}"
                )
    return lines or ["未返回匹配模型的剩余额度；不是现金余额，也不代表余额为零"]


def collect_ark(panel: dict) -> Reading:
    command = resolve("arkcli", panel.get("ark_executable", ""))
    prefix = command + (["--profile", panel["ark_profile"]] if panel.get("ark_profile") else [])
    # Freeze CLI version during polling; never auto-install or change profiles.
    env = os.environ.copy()
    env["ARKCLI_NO_UPDATE_NOTIFIER"] = "1"
    deadline = time.monotonic() + 90

    def query(args):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SourceError("方舟查询达到 90 秒预算，保留旧数据")
        return run_json(prefix + args, env, timeout=min(30, remaining))

    status = query(["auth", "status", "--format", "json"])
    if not status.get("logged_in"):
        raise SourceError("火山方舟未登录，请在配置页按 L 完成 SSO 登录", auth=True)
    model = panel.get("model", "account")
    view = panel.get("ark_view", "both")
    lines, failures = [], []
    if view in ("usage", "both"):
        try:
            today = datetime.now(timezone(timedelta(hours=8))).date()
            start = today - timedelta(days=panel.get("ark_days", 1) - 1)
            scope = panel.get("ark_scope", "mine")
            args = [
                "usage",
                "stats",
                "--start",
                str(start),
                "--end",
                str(today),
                "--by",
                "model",
                "--page-all",
                "--page-limit",
                "100",
                "--format",
                "json",
            ]
            if scope == "mine":
                args += ["--mine", "--mine-by", "apikey"]
            if model != "account":
                args += ["--model", model]
            data = query(args)
            lines += parse_usage(
                data, f"{start}~{today} (UTC+8)", "本人 Active Key" if scope == "mine" else "当前 Profile 账号范围"
            )
        except SourceError as exc:
            failures.append("用量: " + str(exc))
    if view in ("free_quota", "both"):
        try:
            items = []
            for page in range(1, 51):
                args = [
                    "usage",
                    "balance",
                    "--type",
                    "free-quota",
                    "--page-number",
                    str(page),
                    "--page-size",
                    "50",
                    "--format",
                    "json",
                ]
                if model != "account":
                    args += ["--model", model]
                data = query(args)
                complete(data)
                batch = data.get("items")
                if not isinstance(batch, list):
                    raise SourceError("资源包列表格式无效")
                items.extend(batch)
                total = data.get("total_count")
                # CLI omits models without balance fields; total_count counts upstream
                # models, not the filtered output items. Advance by the server page.
                page_size = int(data.get("page_size", 50))
                if data.get("page_number", page) != page or page_size <= 0:
                    raise SourceError("资源包服务端分页信息与请求不一致")
                if total is not None and page * page_size >= int(total):
                    break
                if total is None and len(batch) < 50:
                    break
                if page == 50:
                    raise SourceError("资源包分页未完整返回，无法展示完整额度")
            lines += parse_resources({"items": items}, model)
        except SourceError as exc:
            failures.append("资源额度: " + str(exc))
    if not lines:
        raise SourceError("; ".join(failures) or "未选择有效的方舟查询类型")
    lines += ["[部分数据不可用] " + failure for failure in failures]
    return Reading(tuple(lines), time.time(), "官方 arkcli / API 平台用量与模型资源额度", partial=bool(failures))
