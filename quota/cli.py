"""Resolve native CLIs without invoking a shell with user-controlled text."""

import json
import os
from pathlib import Path
import shutil
import subprocess

from .providers import SourceError


def resolve(name: str, explicit: str = "") -> list[str]:
    if explicit:
        if Path(explicit).suffix.lower() in (".bat", ".cmd", ".ps1"):
            raise SourceError("程序路径请指定原生 exe 或 JS 入口，不要选择 Shell 包装脚本")
        if Path(explicit).suffix.lower() in (".js", ".mjs"):
            node = shutil.which("node")
            if not node:
                raise SourceError("运行此 CLI 需要 Node.js")
            return [node, explicit]
        return [explicit]
    found = shutil.which(name + ".exe") or shutil.which(name) or shutil.which(name + ".cmd")
    if found and Path(found).suffix.lower() not in (".cmd", ".bat", ".ps1"):
        return [found]
    roots = []
    if found:
        roots.append(Path(found).parent / "node_modules")
    if os.environ.get("APPDATA"):
        roots.append(Path(os.environ["APPDATA"]) / "npm" / "node_modules")
    for root in roots:
        if name == "arkcli":
            natives = list((root / "@volcengine" / "ark-cli" / "bin").glob("arkcli-windows-*.exe"))
            if natives:
                return [str(natives[0])]
        if name == "gemini":
            script = root / "@google" / "gemini-cli" / "dist" / "index.js"
            node = shutil.which("node")
            if script.is_file() and node:
                return [node, str(script)]
    raise SourceError(f"未找到 {name} CLI，请在配置页安装说明中查看安装方法")


def run_json(command: list[str], env=None, timeout=40) -> dict:
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
            **options,
        )
    except subprocess.TimeoutExpired as exc:
        raise SourceError("CLI 查询超时，请检查网络与登录状态") from exc
    if result.returncode:
        # Do not show raw stderr: CLIs may include credentials or account identifiers.
        message = (result.stderr + " " + result.stdout).lower()
        if "--mine" in message and "root" in message:
            raise SourceError("当前 Root 身份不支持 mine 范围；可在配置页明确选择 account，或登录子用户")
        if any(
            word in message
            for word in ("unauth", "expired", "login", "authfailure", "not logged", "未登录", "登录", "过期")
        ):
            raise SourceError("CLI 登录失效，请在配置页重新登录", auth=True)
        raise SourceError("CLI 查询失败，请核对权限、Profile 和查询范围")
    if len(result.stdout) > 8 * 1024 * 1024:
        raise SourceError("CLI 返回超过 8 MB，需缩小查询范围")
    try:
        data = json.loads(result.stdout)
    except ValueError as exc:
        raise SourceError("CLI 没有返回有效 JSON；请检查版本") from exc
    if not isinstance(data, dict):
        raise SourceError("CLI 返回格式不兼容")
    return data
