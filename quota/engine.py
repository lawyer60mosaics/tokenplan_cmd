"""Independent refresh scheduling; UI remains responsive while sources run."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
import time

from .providers import Reading, SourceError, collect


@dataclass
class State:
    reading: Reading | None = None
    error: str = ""
    failures: int = 0
    next_due: float = 0
    blocked_until: float = 0
    checked_at: float | None = None
    future: Future | None = None
    auth_failed: bool = False


def source_key(panel: dict) -> tuple:
    fields = (
        "adapter",
        "provider",
        "credential_ref",
        "key_env",
        "codex_home",
        "codex_executable",
        "auth_file",
        "google_project",
        "gemini_oauth_module",
        "gemini_backend",
        "agy_executable",
        "gemini_executable",
        "ark_profile",
        "ark_scope",
        "ark_days",
        "ark_view",
        "ark_executable",
    )
    result = tuple(panel.get(field) for field in fields)
    if panel["adapter"] not in ("codex", "deepseek"):
        result += (panel.get("model", "account"),)
    if panel["adapter"] == "snapshot":
        result += (panel.get("snapshot"),)
    return result


class Engine:
    def __init__(self, panels: list[dict], base: Path, collector=collect):
        self.panels = panels
        self.base = base
        self.collector = collector
        self.states = {source_key(panel): State() for panel in panels}
        self.pool = ThreadPoolExecutor(max_workers=5, thread_name_prefix="quota")
        self.last_tick = time.monotonic()

    def state(self, panel: dict) -> State:
        return self.states[source_key(panel)]

    def reconfigure(self, panels: list[dict]) -> None:
        self.panels = panels
        for panel in panels:
            self.states.setdefault(source_key(panel), State())
        self.refresh([p for p in panels if p["enabled"] and not p["paused"]])

    def active(self, key: tuple) -> list[dict]:
        return [p for p in self.panels if source_key(p) == key and p["enabled"] and not p["paused"]]

    def tick(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        # A long suspension causes one refresh, never a burst of missed requests.
        if now - self.last_tick > 120:
            for state in self.states.values():
                state.next_due = min(state.next_due, now)
        self.last_tick = now
        for key, state in self.states.items():
            active = self.active(key)
            if state.future is not None and state.future.done():
                try:
                    state.reading = state.future.result()
                    state.error = ""
                    state.failures = 0
                    state.auth_failed = False
                    state.checked_at = time.time()
                    interval = min((p["interval"] for p in active), default=60)
                    minimum = 60 if key[0] in ("claude", "ark") else 10
                    state.blocked_until = now + minimum
                    state.next_due = now + max(minimum, interval)
                except SourceError as exc:
                    state.error = str(exc)
                    state.failures += 1
                    state.auth_failed = exc.auth
                    delay = max(exc.retry_after, min(900, 10 * 2 ** min(state.failures - 1, 7)))
                    state.blocked_until = now + delay
                    state.next_due = state.blocked_until
                except Exception:
                    state.error = "采集器异常；请检查配置"
                    state.failures += 1
                    state.next_due = state.blocked_until = now + 60
                state.future = None
            if (
                active
                and state.future is None
                and not state.auth_failed
                and now >= max(state.next_due, state.blocked_until)
            ):
                state.future = self.pool.submit(self.collector, dict(active[0]), self.base)

    def refresh(self, panels: list[dict]) -> None:
        for panel in panels:
            state = self.state(panel)
            # Explicit user retries may recover updated credentials, but respect backoff.
            state.auth_failed = False
            state.next_due = max(time.monotonic(), state.blocked_until)

    def close(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)
