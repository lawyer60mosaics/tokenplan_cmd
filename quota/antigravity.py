"""Read Antigravity's built-in /usage command without model inference."""

import math
import time

from .cli import resolve, run_json
from .providers import Reading, SourceError


def collect(panel: dict) -> Reading:
    data = run_json(
        resolve("agy", panel.get("agy_executable", ""))
        + ["--print", "/usage", "--output-format", "json", "--print-timeout", "30s"],
        timeout=40,
    )
    command = data.get("command", {})
    if data.get("status") != "SUCCESS" or command.get("name") != "usage" or data.get("num_turns") != 0:
        raise SourceError("agy 未返回内置额度查询结果，请升级 Antigravity CLI")
    groups = command.get("data", {}).get("groups", [])
    metrics = []
    selection = panel.get("model", "account").lower()
    for group in groups:
        name = group.get("name", "")
        if selection != "account" and selection not in name.lower():
            continue
        for bucket in group.get("buckets", []):
            remaining = bucket.get("remaining_fraction")
            if isinstance(remaining, bool) or not isinstance(remaining, (int, float)):
                raise SourceError("agy 额度数据缺少剩余比例")
            if not math.isfinite(remaining) or not 0 <= remaining <= 1:
                raise SourceError("agy 额度比例超出有效范围")
            window = {"weekly": "每周", "5h": "5小时"}.get(bucket.get("window"), bucket.get("name", "额度"))
            metrics.append(f"{name} / {window} 剩余 {remaining:.0%}")
            if bucket.get("reset_time"):
                metrics.append(f"  重置: {bucket['reset_time']} (UTC)")
    if not metrics:
        raise SourceError("未找到额度分组；模型/账户标识请填 account、Gemini 或 Claude")
    return Reading(tuple(metrics), time.time(), "Antigravity agy /usage（分组共享额度）")
