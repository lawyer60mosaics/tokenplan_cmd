"""Explicit user-initiated login and connection checks for the settings UI."""

import os
from pathlib import Path
import subprocess

from .cli import resolve
from .providers import SourceError, codex_command, collect

HELP = {
    "codex": "安装 Codex CLI 后选择 L 登录；用 CLI 当前账号或独立 CODEX_HOME 读取额度。",
    "claude": "安装官方 Claude Code 后选择 L 登录订阅账号；读取 .claude/.credentials.json。API Key 不适用。",
    "gemini": "安装 Antigravity agy CLI，在其界面登录；使用内置 /usage 查询分组共享额度。旧 Gemini CLI 可在配置页 J 切换。",
    "deepseek": "选择 K 输入官方 DeepSeek API Key；选择 T 验证。仅查询余额，不调用模型。",
    "ark": "安装: npm install -g @volcengine/ark-cli；选择 L 完成 SSO。API Key 不能替代控制台查询权限；统计延迟 5–30 分钟。",
}


def login(panel: dict) -> int:
    provider = panel["provider"]
    env = os.environ.copy()
    if provider == "codex":
        command = codex_command(panel) + ["login"]
        if panel.get("codex_home"):
            env["CODEX_HOME"] = str(Path(panel["codex_home"]).expanduser())
    elif provider == "claude":
        command = resolve("claude", panel.get("claude_executable", "")) + ["auth", "login"]
        if panel.get("auth_file"):
            path = Path(panel["auth_file"]).expanduser()
            if path.name != ".credentials.json":
                raise SourceError("Claude 登录路径必须使用 CLI 标准文件名 .credentials.json")
            env["CLAUDE_CONFIG_DIR"] = str(path.parent)
    elif provider == "gemini" and panel.get("gemini_backend", "agy") == "agy":
        command = resolve("agy", panel.get("agy_executable", ""))
    elif provider == "gemini":
        if (
            panel.get("auth_file")
            and Path(panel["auth_file"]).expanduser().resolve()
            != (Path.home() / ".gemini" / "oauth_creds.json").resolve()
        ):
            raise SourceError("自定义 Gemini 账号请先在其官方 CLI 环境中登录，再选择对应凭据文件；不会覆盖默认登录")
        command = resolve("gemini", panel.get("gemini_executable", ""))
        if panel.get("google_project"):
            env["GOOGLE_CLOUD_PROJECT"] = panel["google_project"]
    elif provider == "ark":
        command = resolve("arkcli", panel.get("ark_executable", ""))
        if panel.get("ark_profile"):
            command += ["--profile", panel["ark_profile"]]
        command += ["auth", "login", "volc-sso"]
        env["ARKCLI_NO_UPDATE_NOTIFIER"] = "1"
    else:
        raise SourceError("此平台使用配置页中的 API Key，无需 CLI 登录")
    return subprocess.call(command, env=env)


def check(panel: dict, base: Path) -> list[str]:
    reading = collect(panel, base)
    return ["连接成功", "来源: " + reading.source, *reading.metrics]
