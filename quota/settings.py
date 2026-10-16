"""CMD configuration screens. Users never need to edit JSON."""

from __future__ import annotations

import copy
import getpass
import hashlib
from pathlib import Path
import sys
import uuid

from . import config, credentials
from .terminal import ESC, clean
from . import accounts
from .providers import SourceError


def page(title: str, lines: list[str]) -> None:
    sys.stdout.write(ESC + "2J" + ESC + "H")
    print("AI QUOTA / " + title + "\n")
    for line in lines:
        print(clean(line))
    print()


def choose_provider(input_fn=input) -> str | None:
    page("选择平台", [f"{i + 1}. {label}" for i, label in enumerate(config.LABELS)] + ["0. 返回"])
    value = input_fn("输入平台编号 > ").strip()
    return config.PROVIDERS[int(value) - 1] if value in ("1", "2", "3", "4", "5") else None


def new_panel(provider: str) -> dict:
    panel = copy.deepcopy(config.defaults()["panels"][config.PROVIDERS.index(provider)])
    panel["id"] = provider + "-" + uuid.uuid4().hex[:10]
    return panel


def set_field(panel: dict, field: str, value: str) -> None:
    """Validate changes before touching the live configuration."""
    candidate = copy.deepcopy(panel)
    if field == "interval":
        candidate[field] = float(value)
    elif field in ("label", "model"):
        if not value.strip():
            raise ValueError("此字段不能为空")
        candidate[field] = value.strip()
    elif field == "ark_days":
        candidate[field] = int(value)
    else:
        candidate[field] = value.strip()
    config.validate({"version": 1, "panels": [candidate]})
    panel.clear()
    panel.update(candidate)


def edit_panel(panel: dict, config_path: Path, input_fn=input, secret_fn=getpass.getpass) -> bool:
    notice = ""
    initial_ref = panel.get("credential_ref")
    while True:
        source = {
            "codex": "CLI 订阅账号",
            "deepseek": "API 余额",
            "claude": "Claude Code 订阅",
            "gemini": "Gemini CLI / Code Assist",
            "ark": "方舟 API 用量与资源额度",
            "snapshot": "外部快照",
            "demo": "演示数据",
        }[panel["adapter"]]
        lines = [
            f"平台: {panel['provider']} | 数据源: {source}",
            f"1. 面板名称       {panel['label']}",
            f"2. 模型/账户标识  {panel['model']}",
            f"3. 刷新间隔(秒)   {panel['interval']:g}",
            f"4. 显示面板       {'是' if panel['enabled'] else '否'}",
            f"5. 自动刷新       {'暂停' if panel['paused'] else '启用'}",
        ]
        allowed = {"1", "2", "3", "4", "5"}
        if panel["adapter"] == "codex":
            lines += [
                f"6. Codex 状态目录 {panel.get('codex_home') or '默认登录账号'}",
                f"7. Codex 程序路径 {panel.get('codex_executable') or '自动查找'}",
            ]
            allowed.update(("6", "7"))
        if panel["adapter"] == "snapshot":
            lines.append(f"8. 快照文件路径   {panel.get('snapshot', '')}")
            allowed.add("8")
        if panel["adapter"] in ("claude", "gemini"):
            lines += [f"A. 登录凭据文件   {panel.get('auth_file') or '官方 CLI 默认路径'}"]
            allowed.add("a")
        if panel["adapter"] == "gemini":
            lines += [
                f"G. Google 项目 ID {panel.get('google_project') or '自动发现'}",
                f"O. OAuth 模块路径 {panel.get('gemini_oauth_module') or '自动查找官方 CLI'}",
            ]
            allowed.update(("g", "o"))
        if panel["adapter"] == "ark":
            lines += [
                f"P. 方舟 Profile   {panel.get('ark_profile') or 'CLI 当前 Profile'}",
                f"F. 用量范围       {panel.get('ark_scope', 'mine')}（mine=本人Key，account=账号范围）",
                f"W. 查询类型       {panel.get('ark_view', 'both')}（usage/free_quota/both）",
                f"D. 查询最近天数   {panel.get('ark_days', 1)}（最多31）",
            ]
            allowed.update(("p", "f", "w", "d"))
        if panel["provider"] in ("claude", "gemini", "ark"):
            field = panel["provider"] + "_executable"
            lines.append(f"E. CLI 程序路径   {panel.get(field) or '自动查找'}")
            allowed.add("e")
        if panel["adapter"] == "deepseek":
            lines += [
                f"9. 密钥环境变量   {panel.get('key_env', 'DEEPSEEK_API_KEY')}",
                f"K. 设置 API Key   {'已安全保存（不显示内容）' if panel.get('credential_ref') else '未保存'}",
            ]
            allowed.update(("9", "k"))
        lines += [
            "B. 切换内置采集/外部快照  L. 登录  T. 检查连接  H. 接入帮助",
            "S. 保存并返回    X. 删除此面板    0. 取消修改",
            notice,
        ]
        page("面板配置", lines)
        choice = input_fn("输入选项 > ").strip().lower()
        try:
            if choice == "0":
                return False
            if choice == "s":
                return True
            if choice == "x":
                if input_fn("确认删除此面板？输入 YES > ").strip() == "YES":
                    panel["_delete"] = True
                    return True
            elif choice in ("4", "5"):
                field = "enabled" if choice == "4" else "paused"
                panel[field] = not panel[field]
            elif choice in ("1", "2", "3", "6", "7", "8", "9"):
                if choice not in allowed:
                    notice = "此选项不适用于当前平台和数据源。"
                    continue
                field = {
                    "1": "label",
                    "2": "model",
                    "3": "interval",
                    "6": "codex_home",
                    "7": "codex_executable",
                    "8": "snapshot",
                    "9": "key_env",
                }[choice]
                value = input_fn("输入新值（留空保留，输入 - 清空可选路径） > ")
                if value:
                    set_field(panel, field, "" if value == "-" else value)
            elif choice == "b":
                panel["adapter"] = "snapshot" if panel["adapter"] != "snapshot" else panel["provider"]
            elif choice in ("a", "g", "o", "p", "f", "w", "d", "e"):
                if choice not in allowed:
                    notice = "此选项不适用于当前数据源。"
                    continue
                field = {
                    "a": "auth_file",
                    "g": "google_project",
                    "o": "gemini_oauth_module",
                    "p": "ark_profile",
                    "f": "ark_scope",
                    "w": "ark_view",
                    "d": "ark_days",
                    "e": panel["provider"] + "_executable",
                }[choice]
                value = input_fn("输入新值（留空保留，- 清空可选值） > ")
                if value:
                    set_field(panel, field, "" if value == "-" else value)
            elif choice == "h":
                page("接入帮助", [accounts.HELP[panel["provider"]]])
                input_fn("按 Enter 返回 > ")
            elif choice == "l":
                page(
                    "账号登录",
                    [
                        accounts.HELP[panel["provider"]],
                        "接下来由官方 CLI 完成登录；登录更改立即生效，不随取消面板修改而撤销。",
                    ],
                )
                if input_fn("输入 LOGIN 启动登录，其他输入取消 > ").strip() == "LOGIN":
                    code = accounts.login(panel)
                    notice = "登录程序已退出，可按 T 检查连接。" if code == 0 else "登录未成功，请查看官方 CLI 提示。"
                    input_fn("按 Enter 返回配置 > ")
            elif choice == "t":
                page("连接检查", ["正在执行只读查询，不发起模型推理..."])
                try:
                    messages = accounts.check(panel, config_path.parent)
                except SourceError as exc:
                    messages = ["连接未成功: " + str(exc)]
                page("连接检查", messages[:12])
                input_fn("按 Enter 返回配置 > ")
            elif choice == "k":
                if panel["provider"] != "deepseek":
                    notice = "当前只有 DeepSeek 内置采集器使用 API Key；其余平台直接采集尚未完成。"
                    continue
                secret = secret_fn("API Key（隐藏输入；留空取消） > ")
                if secret:
                    # New references keep cancel/failed saves from overwriting existing credentials.
                    digest = hashlib.sha256(str(config_path.resolve()).encode()).hexdigest()[:12]
                    reference = f"AIQuota/{digest}/{panel['id']}/{uuid.uuid4().hex}"
                    credentials.write(reference, secret)
                    if panel.get("credential_ref") and panel["credential_ref"] != initial_ref:
                        credentials.delete(panel["credential_ref"])
                    panel["credential_ref"] = reference
                    notice = "密钥已暂存；按 S 保存，取消时删除本次暂存凭据。"
            else:
                notice = "请选择界面中列出的操作。"
        except (ValueError, OSError, SourceError) as exc:
            notice = str(exc)


def screen(settings: dict, path: Path, input_fn=input, secret_fn=getpass.getpass) -> bool:
    """Each panel edit is a transaction; credential writes are cleaned up on cancel."""
    notice, changed = "", False
    while True:
        panels = settings["panels"]
        page(
            "配置中心",
            [
                f"{i + 1}. [{'显示' if p['enabled'] else '隐藏'}] {p['label']} / {p['model']}  {p['interval']:g}s"
                for i, p in enumerate(panels)
            ]
            + ["N. 添加面板（可重复添加同一平台的不同账号/模型）", "0. 保存并返回仪表盘", notice],
        )
        try:
            choice = input_fn("输入面板编号或选项 > ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            return changed
        if choice in ("0", "q"):
            return changed
        draft = None
        original_ref = None
        current = None
        committed = False
        try:
            if choice == "n":
                if len(panels) >= 50:
                    notice = "最多配置 50 个面板。"
                    continue
                provider = choose_provider(input_fn)
                if provider is None:
                    continue
                draft = new_panel(provider)
            elif choice.isdigit() and 1 <= int(choice) <= len(panels):
                current = int(choice) - 1
                draft = copy.deepcopy(panels[current])
                original_ref = draft.get("credential_ref")
            else:
                notice = "请输入有效面板编号，或 N 添加面板。"
                continue
            accepted = edit_panel(draft, path, input_fn, secret_fn)
            deleting = draft.pop("_delete", False)
            if accepted:
                updated = copy.deepcopy(settings)
                if current is None:
                    if not deleting:
                        updated["panels"].append(draft)
                elif deleting:
                    del updated["panels"][current]
                else:
                    updated["panels"][current] = draft
                config.save(path, updated)
                settings.clear()
                settings.update(updated)
                committed = True
                changed = True
                notice = "配置已保存。"
            else:
                notice = "已取消本次面板修改。"
            if draft.get("credential_ref") != original_ref:
                if not accepted or deleting:
                    if draft.get("credential_ref"):
                        credentials.delete(draft["credential_ref"])
                elif original_ref:
                    if not any(p.get("credential_ref") == original_ref for p in settings["panels"]):
                        credentials.delete(original_ref)
            elif accepted and deleting and original_ref:
                if not any(p.get("credential_ref") == original_ref for p in settings["panels"]):
                    credentials.delete(original_ref)
        except (KeyboardInterrupt, EOFError):
            if not committed and draft and draft.get("credential_ref") and draft.get("credential_ref") != original_ref:
                credentials.delete(draft["credential_ref"])
            notice = "已取消本次修改。"
        except (OSError, ValueError) as exc:
            if not committed and draft and draft.get("credential_ref") and draft.get("credential_ref") != original_ref:
                credentials.delete(draft["credential_ref"])
            notice = str(exc)
