"""CMD entry point. Python 3.10+, standard library only."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from quota import config
from quota.engine import Engine
from quota.providers import collect, SourceError
from quota.terminal import ESC, Terminal, clean, render, render_single, render_detail, panel_lines
from quota.settings import screen as settings_screen

RESOURCES = Path(__file__).resolve().parent
ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else RESOURCES
VERSION = "1.1.0"
DATA_ROOT = Path(os.environ.get("APPDATA", Path.home() / ".config")) / "XCLI"


def layout_text(panels: list[dict], config_path: Path, python: str = sys.executable) -> str:
    def quote(value):
        return json.dumps(str(value), ensure_ascii=False)

    enabled = [p for p in panels if p["enabled"]]
    if not enabled:
        raise ValueError("至少启用一个面板才能生成 Zellij 布局")
    lines = ["layout {", '    pane split_direction="horizontal" {']
    for start in range(0, len(enabled), 2):
        lines.append('        pane split_direction="vertical" {')
        for panel in enabled[start : start + 2]:
            lines.append(f"            pane name={quote(panel['label'])} command={quote(python)} {{")
            args = ([] if getattr(sys, "frozen", False) else [ROOT / "app.py"]) + [
                "--config",
                config_path.resolve(),
                "--panel",
                panel["id"],
            ]
            lines.append("                args " + " ".join(quote(arg) for arg in args))
            lines.append("            }")
        lines.append("        }")
    lines.extend(["    }", "}"])
    return "\n".join(lines) + "\n"


def once(panels: list[dict], base: Path, json_output: bool) -> int:
    # Parallel bounded reads; do not mutate config or store credentials/results.
    from concurrent.futures import ThreadPoolExecutor
    from quota.engine import source_key

    enabled = [p for p in panels if p["enabled"]]
    with ThreadPoolExecutor(max_workers=5) as pool:
        jobs = {}
        for panel in enabled:
            key = source_key(panel)
            if key not in jobs:
                jobs[key] = pool.submit(collect, panel, base)
        output = []
        for panel in enabled:
            row = {"id": panel["id"], "label": panel["label"], "model": panel["model"]}
            try:
                row.update(asdict(jobs[source_key(panel)].result()))
            except SourceError as exc:
                row["error"] = str(exc)
            output.append(row)
    if json_output:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        for row in output:
            print(clean(f"[{row['label']} / {row['model']}]"))
            if "error" in row:
                print("  未知 | " + clean(row["error"]))
            else:
                print("\n".join("  " + clean(line) for line in row["metrics"]))
                print("  来源: " + clean(row["source"]))
    return 0


def interactive(settings: dict, path: Path, single: bool = False, persist: bool = True) -> None:
    engine = Engine(settings["panels"], path.parent)
    selected, selecting, notice = 0, False, "设置自动保存；未知不等于零额度"
    detailed, offset = False, 0
    try:
        with Terminal() as terminal:
            previous_frame = None
            while True:
                engine.tick()
                size = shutil.get_terminal_size((120, 40))
                visible = [p for p in settings["panels"] if p["enabled"]]
                frame = (
                    render_detail(visible[selected % len(visible)], engine, size.columns, size.lines, offset)
                    if detailed and visible
                    else render_single(settings["panels"][0], engine, size.columns, size.lines)
                    if single
                    else render(settings["panels"], engine, selected, size.columns, size.lines, notice, selecting)
                )
                if frame != previous_frame:
                    sys.stdout.write(ESC + "H" + ESC + "J" + frame.replace("\n", "\r\n"))
                    sys.stdout.flush()
                    previous_frame = frame
                key = terminal.key()
                if key in ("q", "\x03"):
                    break
                panels = settings["panels"] if selecting else [p for p in settings["panels"] if p["enabled"]]
                if panels:
                    selected %= len(panels)
                if key in ("\r", "\n", "\x1b") and not selecting and panels:
                    detailed, offset = not detailed, 0
                elif detailed and key in ("j", "down", "pagedown", "k", "up", "pageup"):
                    step = max(1, size.lines - 4) if key in ("pagedown", "pageup") else 1
                    limit = len(panel_lines(panels[selected], engine))
                    offset = (
                        min(limit - 1, offset + step) if key in ("j", "down", "pagedown") else max(0, offset - step)
                    )
                elif key in ("\t", "j", "right", "down"):
                    selected = (selected + 1) % max(1, len(panels))
                elif key in ("k", "left", "up"):
                    selected = (selected - 1) % max(1, len(panels))
                elif key == "v" and not single:
                    selecting, selected = not selecting, 0
                    detailed = False
                elif key == "c":
                    if not persist:
                        notice = "请通过 start-config.cmd 配置；演示和单窗格不保存全局设置"
                    else:
                        with terminal.prompt_mode():
                            settings_screen(settings, path)
                        engine.reconfigure(settings["panels"])
                        selected, selecting, previous_frame = 0, False, None
                        detailed = False
                        notice = "配置已生效"
                elif key == "a":
                    engine.refresh([p for p in settings["panels"] if p["enabled"] and not p["paused"]])
                elif panels:
                    panel = panels[selected]
                    changed = False
                    if selecting and key == " ":
                        panel["enabled"] = not panel["enabled"]
                        changed = True
                    elif key == "p":
                        panel["paused"] = not panel["paused"]
                        changed = True
                    elif key in ("+", "=", "-"):
                        panel["interval"] = (
                            min(86400, panel["interval"] + 10) if key != "-" else max(10, panel["interval"] - 10)
                        )
                        engine.state(panel).next_due = max(
                            engine.state(panel).blocked_until, time.monotonic() + panel["interval"]
                        )
                        changed = True
                    elif key == "r" and not panel["paused"]:
                        engine.refresh([panel])
                    if changed:
                        if not persist:
                            notice = "临时设置；持久设置请在主界面修改配置"
                        else:
                            config.save(path, settings)
                            notice = "已保存设置"
                time.sleep(0.1)
    finally:
        engine.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="AI Quota: CMD 多 AI 额度仪表盘")
    parser.add_argument("--version", action="version", version="TokenPlan CMD " + VERSION)
    parser.add_argument("--config", type=Path, default=DATA_ROOT / "config.json")
    parser.add_argument("--once", action="store_true", help="读取一次并退出")
    parser.add_argument("--json", action="store_true", help="配合 --once 输出 JSON")
    parser.add_argument("--demo", action="store_true", help="明确标记的演示数据，不访问真实账户")
    parser.add_argument("--panel", help="只显示指定面板 id，供 Zellij 布局使用")
    parser.add_argument("--layout", type=Path, help="导出 Zellij KDL 布局")
    parser.add_argument("--zellij", action="store_true", help="通过 PATH 中的 Zellij 启动分屏")
    parser.add_argument("--configure", action="store_true", help="打开 CMD 配置中心")
    args = parser.parse_args(argv)
    try:
        path = args.config.resolve()
        settings = config.load(path)
        if args.configure:
            if args.demo or args.panel or args.once:
                raise ValueError("--configure 不可与演示、单面板或一次读取模式组合")
            with Terminal() as terminal:
                with terminal.prompt_mode():
                    settings_screen(settings, path)
        if args.demo:
            for panel in settings["panels"]:
                panel["adapter"] = "demo"
        if args.panel:
            settings["panels"] = [p for p in settings["panels"] if p["id"] == args.panel]
            if not settings["panels"]:
                raise ValueError("未找到面板 id")
            settings["panels"][0]["enabled"] = True
        if args.layout or args.zellij:
            if args.demo:
                raise ValueError("布局使用真实配置；演示请直接运行 --demo")
            target = args.layout or path.parent / "quota-layout.kdl"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(layout_text(settings["panels"], path), encoding="utf-8")
            if args.zellij:
                executable = shutil.which("zellij")
                if not executable:
                    filename = "zellij.exe" if os.name == "nt" else "zellij"
                    for local in (
                        ROOT / filename,
                        ROOT / "vendor" / "zellij" / "target" / "debug" / filename,
                        ROOT.parent / "zellij" / "target" / "debug" / filename,
                    ):
                        if local.is_file():
                            executable = str(local)
                            break
                if not executable:
                    raise ValueError("未找到 zellij；可先直接运行 CMD 模式，或将编译后的 zellij 加入 PATH")
                return subprocess.call(
                    [executable, "--config", str(RESOURCES / "zellij.kdl"), "--layout", str(target.resolve())]
                )
            print(f"已生成布局: {target.resolve()}")
            return 0
        if args.once:
            return once(settings["panels"], path.parent, args.json)
        if args.json:
            raise ValueError("--json 需要配合 --once")
        interactive(settings, path, single=bool(args.panel), persist=not (args.panel or args.demo))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
