"""Small ANSI terminal UI, with Windows console setup and guaranteed restoration."""

from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager
import math
import os
import sys
import time
import unicodedata

from .engine import Engine
from .providers import clock

ESC = "\x1b["


def clean(value: object) -> str:
    # External labels/data must never become terminal control sequences.
    return "".join(c for c in str(value) if not unicodedata.category(c).startswith("C"))


def fit(value: object, width: int) -> str:
    result, used = [], 0
    for char in clean(value):
        size = 0 if unicodedata.combining(char) else (2 if unicodedata.east_asian_width(char) in ("W", "F") else 1)
        if used + size > width:
            break
        result.append(char)
        used += size
    return "".join(result) + " " * max(0, width - used)


class Terminal(AbstractContextManager):
    @contextmanager
    def prompt_mode(self):
        """Temporarily restore line editing for configuration forms."""
        if os.name != "nt":
            import termios

            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.original)
        sys.stdout.write(ESC + "?25h" + ESC + "2J" + ESC + "H")
        sys.stdout.flush()
        try:
            yield
        finally:
            if os.name != "nt":
                import tty

                tty.setcbreak(sys.stdin.fileno())
            sys.stdout.write(ESC + "?25l" + ESC + "2J" + ESC + "H")
            sys.stdout.flush()

    def __enter__(self):
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise RuntimeError("交互模式需要终端；使用 --once 输出一次快照")
        self.original = None
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            self.kernel.GetStdHandle.argtypes = [wintypes.DWORD]
            self.kernel.GetStdHandle.restype = wintypes.HANDLE
            self.kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            self.kernel.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            self.handle = self.kernel.GetStdHandle(-11 & 0xFFFFFFFF)
            mode = wintypes.DWORD()
            if not self.kernel.GetConsoleMode(self.handle, ctypes.byref(mode)):
                raise RuntimeError("无法读取 CMD 控制台模式")
            self.original = mode.value
            if not self.kernel.SetConsoleMode(self.handle, mode.value | 4):
                raise RuntimeError("控制台不支持 ANSI；请使用 Windows 10/11 CMD")
        else:
            import termios
            import tty

            self.original = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        sys.stdout.write(ESC + "?1049h" + ESC + "?25l" + ESC + "2J")
        sys.stdout.flush()
        return self

    def __exit__(self, *args):
        sys.stdout.write(ESC + "0m" + ESC + "?25h" + ESC + "?1049l")
        sys.stdout.flush()
        if os.name == "nt":
            if self.original is not None:
                self.kernel.SetConsoleMode(self.handle, self.original)
        else:
            import termios

            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.original)

    def key(self) -> str:
        if os.name == "nt":
            import msvcrt

            if msvcrt.kbhit():
                char = msvcrt.getwch()
                if char in ("\x00", "\xe0"):
                    return {"K": "left", "M": "right", "H": "up", "P": "down", "Q": "pagedown", "I": "pageup"}.get(
                        msvcrt.getwch(), ""
                    )
                return char.lower()
        else:
            import select

            if select.select([sys.stdin], [], [], 0)[0]:
                return sys.stdin.read(1).lower()
        return ""


def panel_lines(panel: dict, engine: Engine) -> list[str]:
    state = engine.state(panel)
    now = time.monotonic()
    if panel["paused"]:
        status = "已暂停"
    elif state.future is not None:
        status = "刷新中..."
    elif state.auth_failed:
        status = "需要连接"
    elif state.error:
        status = "读取失败 / 等待重试"
    else:
        status = ("部分可用" if state.reading.partial else "已连接") if state.reading else "等待首次刷新"
    minimum = 60 if panel["adapter"] in ("claude", "ark") else 10
    effective = max(minimum, panel["interval"])
    lines = [f"状态: {status} | 间隔 {effective:g}s"]
    reading = state.reading
    if reading:
        age = max(0, time.time() - reading.observed_at)
        stale = bool(state.error) or age > max(120, panel["interval"] * 2)
        lines.append(
            ("[DEMO] " if reading.demo else "")
            + ("[过期] " if stale else "")
            + "数据时间: "
            + clock(reading.observed_at)
        )
        lines.extend(reading.metrics)
        lines.append("来源: " + reading.source)
        lines.append("最近读取: " + (clock(state.checked_at) if state.checked_at else "--"))
    else:
        lines.append("使用量 / 剩余额度: 未知")
    if state.error:
        lines.append(state.error)
    if not panel["paused"] and not state.auth_failed:
        lines.append(f"下次刷新: {max(0, math.ceil(max(state.next_due, state.blocked_until) - now))}s")
    return lines


def render_single(panel: dict, engine: Engine, width: int, height: int) -> str:
    """Zellij already supplies pane frames: leave room for data in small panes."""
    width, height = max(1, width - 1), max(1, height - 1)
    state = engine.state(panel)
    heading = f"{panel['label']} / {panel['model']}"
    if height >= 10:
        lines = [heading] + panel_lines(panel, engine)
    elif state.reading:
        reading = state.reading
        stale = bool(state.error) or time.time() - reading.observed_at > max(120, panel["interval"] * 2)
        heading = (
            ("[DEMO] " if reading.demo else "")
            + ("[过期] " if stale else "")
            + ("[部分] " if reading.partial else "")
            + heading
        )
        status = (
            "暂停"
            if panel["paused"]
            else ("刷新中" if state.future else f"{max(0, math.ceil(state.next_due - time.monotonic()))}s")
        )
        lines = [heading, f"{status} 数据 {clock(reading.observed_at)[6:]}"]
        lines.extend(line for line in reading.metrics if not line.startswith("  重置:"))
        if state.error:
            lines = lines[: max(1, height - 2)] + [state.error]
    else:
        lines = [heading, "额度: 未知", state.error or "正在读取..."]
    footer = "Enter 详情 R 刷新 P 暂停 Q 退出"
    if height >= 4:
        lines = lines[: height - 1] + [footer]
    return "\n".join(fit(line, width) for line in lines[:height])


def render_detail(panel: dict, engine: Engine, width: int, height: int, offset: int) -> str:
    width, height = max(1, width - 1), max(3, height - 1)
    content = panel_lines(panel, engine)
    rows = max(1, height - 2)
    offset = max(0, min(offset, max(0, len(content) - rows)))
    lines = [f"{panel['label']} / {panel['model']} 详情 ({offset + 1}/{len(content)})"]
    lines += content[offset : offset + rows]
    lines += ["↑↓/J K/PgUp PgDn 滚动  Enter/Esc 返回  R 刷新"]
    return "\n".join(fit(line, width) for line in lines)


def render(
    panels: list[dict], engine: Engine, selected: int, width: int, height: int, notice: str = "", settings: bool = False
) -> str:
    width, height = max(1, width - 1), max(1, height - 1)
    if width < 38 or height < 12:
        return "\n".join(fit(line, width) for line in ["AI QUOTA", "请放大终端至至少 40 列 x 13 行", "Q 退出"][:height])
    lines = [fit("AI QUOTA  |  CMD TERMINAL DASHBOARD", width)]
    if settings:
        lines.append(fit("面板选择：↑↓/J K 移动，空格开关，V 返回；设置自动保存", width))
        capacity = max(1, height - 4)
        start = (selected // capacity) * capacity
        for i, panel in enumerate(panels[start : start + capacity], start=start):
            lines.append(
                fit(
                    f"{'>' if i == selected else ' '} [{'x' if panel['enabled'] else ' '}] {panel['label']} / {panel['model']}  ({panel['interval']:g}s)",
                    width,
                )
            )
        lines.append(fit(f"选择列表 {start + 1}-{min(len(panels), start + capacity)} / {len(panels)}", width))
        lines.append(fit(notice, width))
        return "\n".join(lines[:height])
    visible = [p for p in panels if p["enabled"]]
    lines.append(
        fit(
            f"显示 {len(visible)}/{len(panels)} 个面板  |  {time.strftime('%Y-%m-%d %H:%M:%S')}  |  V 选择显示面板",
            width,
        )
    )
    if not visible:
        lines.extend([fit("", width), fit("没有启用的面板，按 V 选择。", width)])
    else:
        columns = min(len(visible), max(1, width // 38))
        needed_rows = math.ceil(len(visible) / columns)
        card_height = min(10, max(6, (height - 5) // needed_rows))
        rows = max(1, (height - 5) // card_height)
        content_rows = card_height - 3
        capacity = columns * rows
        selected = selected % len(visible)
        page = selected // capacity
        group = visible[page * capacity : (page + 1) * capacity]
        cell_width = width // columns
        for row_start in range(0, len(group), columns):
            cells = []
            for j, panel in enumerate(group[row_start : row_start + columns]):
                index = page * capacity + row_start + j
                heading = f"{'>' if index == selected else ' '} {panel['label']} / {panel['model']}"
                content = panel_lines(panel, engine)
                if content_rows < 7:
                    state = engine.state(panel)
                    reading = state.reading
                    if reading:
                        stale = bool(state.error) or time.time() - reading.observed_at > max(120, panel["interval"] * 2)
                        tag = (
                            ("[DEMO] " if reading.demo else "")
                            + ("[过期] " if stale else "")
                            + ("[部分] " if reading.partial else "")
                        )
                        status = (
                            "暂停"
                            if panel["paused"]
                            else (
                                "刷新中" if state.future else f"{max(0, math.ceil(state.next_due - time.monotonic()))}s"
                            )
                        )
                        content = [tag + f"{status} 数据 {clock(reading.observed_at)[6:]}"]
                        content.extend(line for line in reading.metrics if not line.startswith("  重置:"))
                        if state.error:
                            content = content[: content_rows - 1] + [state.error]
                if len(content) > content_rows:
                    content = content[:content_rows]
                cells.append(
                    ["+" + "-" * (cell_width - 2) + "+", "|" + fit(heading, cell_width - 2) + "|"]
                    + ["|" + fit(line, cell_width - 2) + "|" for line in content + [""] * (content_rows - len(content))]
                    + ["+" + "-" * (cell_width - 2) + "+"]
                )
            for row in zip(*cells):
                lines.append("".join(row))
        lines.append(fit(f"页 {page + 1}/{math.ceil(len(visible) / capacity)}  (Tab/J/K 切换，自动翻页)", width))
    lines = lines[: height - 2]
    lines.extend(
        [fit("Enter 详情 C 配置 V 显示 Tab 切换 R 刷新 A 全刷 P 暂停 +/- 间隔 Q 退出", width), fit(notice, width)]
    )
    return "\n".join(lines)
