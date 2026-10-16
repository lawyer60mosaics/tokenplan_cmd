"""Validated, non-secret panel configuration."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

PROVIDERS = ("codex", "claude", "gemini", "deepseek", "ark")
LABELS = ("Codex", "Claude", "Antigravity / Gemini", "DeepSeek", "火山方舟")


def defaults() -> dict:
    return {
        "version": 2,
        "panels": [
            {
                "id": provider,
                "provider": provider,
                "label": label,
                "model": "account",
                "enabled": True,
                "paused": False,
                "interval": 300 if provider in ("claude", "ark") else 60,
                "adapter": provider,
                "snapshot": f"snapshots/{provider}.json",
            }
            for provider, label in zip(PROVIDERS, LABELS)
        ],
    }


def validate(config: dict) -> dict:
    if not isinstance(config, dict) or config.get("version") not in (1, 2):
        raise ValueError("不支持的配置版本")
    panels = config.get("panels")
    if not isinstance(panels, list) or not 1 <= len(panels) <= 50:
        raise ValueError("需要配置 1 到 50 个面板")
    ids = set()
    for panel in panels:
        if not isinstance(panel, dict):
            raise ValueError("面板配置必须是对象")
        identity = panel.get("id")
        if not isinstance(identity, str) or not identity or identity in ids:
            raise ValueError("面板 id 必须非空且唯一")
        ids.add(identity)
        if panel.get("provider") not in PROVIDERS:
            raise ValueError(f"未知平台: {identity}")
        if panel.get("adapter") not in (*PROVIDERS, "snapshot", "demo"):
            raise ValueError(f"未知适配器: {identity}")
        if panel["adapter"] in PROVIDERS and panel["provider"] != panel["adapter"]:
            raise ValueError("平台与内置适配器不匹配")
        interval = panel.get("interval", 60)
        if (
            isinstance(interval, bool)
            or not isinstance(interval, (int, float))
            or not math.isfinite(interval)
            or not 10 <= interval <= 86400
        ):
            raise ValueError("刷新间隔必须在 10 秒至 24 小时之间")
        panel.setdefault("interval", 60)
        panel.setdefault("enabled", True)
        panel.setdefault("paused", False)
        for field in ("enabled", "paused"):
            if not isinstance(panel[field], bool):
                raise ValueError(f"{field} 必须为布尔值")
        for field in (
            "id",
            "label",
            "model",
            "snapshot",
            "key_env",
            "credential_ref",
            "codex_executable",
            "codex_home",
            "auth_file",
            "google_project",
            "gemini_oauth_module",
            "gemini_executable",
            "agy_executable",
            "gemini_backend",
            "claude_executable",
            "ark_executable",
            "ark_profile",
        ):
            if field in panel and not isinstance(panel[field], str):
                raise ValueError(f"{field} 必须为字符串")
        if panel["adapter"] == "snapshot" and not panel.get("snapshot"):
            raise ValueError("snapshot 面板需要指定快照路径")
        panel.setdefault("label", panel["provider"])
        panel.setdefault("model", "account")
        if panel.get("ark_scope", "mine") not in ("mine", "account"):
            raise ValueError("方舟查询范围必须是 mine 或 account")
        if panel.get("ark_view", "both") not in ("both", "usage", "free_quota"):
            raise ValueError("方舟查询类型无效")
        if panel.get("gemini_backend", "agy") not in ("agy", "gemini"):
            raise ValueError("Gemini 数据源必须是 agy 或 gemini")
        days = panel.get("ark_days", 1)
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 31:
            raise ValueError("方舟查询天数必须为 1 至 31")
    return config


def load(path: Path) -> dict:
    if not path.exists():
        save(path, defaults())
    result = validate(json.loads(path.read_text(encoding="utf-8-sig")))
    if result["version"] == 1:
        for panel in result["panels"]:
            expected = f"snapshots/{panel['provider']}.json"
            if (
                panel["adapter"] == "snapshot"
                and panel.get("snapshot") == expected
                and not (path.parent / expected).exists()
            ):
                panel["adapter"] = panel["provider"]
        result["version"] = 2
        save(path, result)
    return result


def save(path: Path, config: dict) -> None:
    validate(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
