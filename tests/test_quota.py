from concurrent.futures import Future
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import app
from quota import config
from quota.engine import Engine
from quota.providers import Reading, SourceError, parse_codex, parse_deepseek, snapshot, retry_seconds
from quota.terminal import fit, render, render_single, render_detail


class FakePool:
    def __init__(self):
        self.jobs = []

    def submit(self, *args):
        future = Future()
        self.jobs.append(future)
        return future

    def shutdown(self, **kwargs):
        pass


class QuotaTests(unittest.TestCase):
    def test_details_scroll_to_all_metrics_and_show_partial_state(self):
        panels = config.defaults()["panels"][:1]
        engine = self.engine(panels)
        engine.state(panels[0]).reading = Reading(
            tuple(f"Metric {i}" for i in range(40)), time.time(), "test", partial=True
        )
        top = render_detail(panels[0], engine, 80, 24, 0)
        bottom = render_detail(panels[0], engine, 80, 24, 999)
        self.assertIn("部分可用", top)
        self.assertIn("Metric 39", bottom)
        self.assertLessEqual(len(bottom.splitlines()), 23)

    def engine(self, panels):
        engine = Engine(panels, Path("."))
        engine.pool.shutdown()
        engine.pool = FakePool()
        self.addCleanup(engine.close)
        return engine

    def test_codex_multi_bucket_and_missing_window(self):
        reading = parse_codex(
            {
                "rateLimitsByLimitId": {
                    "codex": {"primary": None, "secondary": {"usedPercent": 25.5, "windowDurationMins": 10080}},
                    "fast": {"primary": {"usedPercent": 100, "windowDurationMins": 300}},
                }
            }
        )
        self.assertIn("剩余 74.5%", reading.metrics[0])
        self.assertIn("剩余 0.0%", reading.metrics[1])
        with self.assertRaises(SourceError):
            parse_codex({})

    def test_codex_protocol_with_real_child_process(self):
        import sys
        from quota.providers import codex

        with tempfile.TemporaryDirectory() as temporary:
            child = Path(temporary) / "server.py"
            child.write_text(
                """import sys,json
for line in sys.stdin:
 m=json.loads(line)
 if m.get('id') == 1:
  print(json.dumps({'id':1,'result':{}}),flush=True)
 if m.get('id') == 2:
  print(json.dumps({'id':2,'result':{'rateLimits':{'primary':{'usedPercent':42,'windowDurationMins':300}}}}),flush=True)
""",
                encoding="utf-8",
            )
            with patch("quota.providers.codex_command", return_value=[sys.executable, "-u", str(child)]):
                self.assertIn("剩余 58.0%", codex({}).metrics[0])

    def test_deepseek_balance_keeps_currency(self):
        reading = parse_deepseek(
            {
                "balance_infos": [
                    {"currency": "CNY", "total_balance": "12.30"},
                    {"currency": "USD", "total_balance": "1.20"},
                ]
            }
        )
        self.assertIn("12.30 CNY", reading.metrics[0])
        self.assertIn("1.20 USD", reading.metrics[1])

    def test_snapshot_identity_timestamp_and_unknown(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            panel = config.defaults()["panels"][1]
            panel["snapshot"] = "claude.json"
            data = {
                "provider": "claude",
                "observed_at": "2026-01-01T00:00:00Z",
                "metrics": [
                    {"label": "Tokens", "unit": "tokens", "used": 4, "limit": 10},
                    {"label": "Shared quota", "unit": "%"},
                ],
            }
            path = base / "claude.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            reading = snapshot(panel, base)
            self.assertIn("剩余 6 tokens", reading.metrics[1])
            self.assertIn("未知", reading.metrics[2])
            data["provider"] = "gemini"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(SourceError):
                snapshot(panel, base)

    def test_config_roundtrip_and_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.json"
            settings = config.load(path)
            settings["panels"][2]["enabled"] = False
            config.save(path, settings)
            self.assertFalse(config.load(path)["panels"][2]["enabled"])
            settings["panels"][0]["interval"] = float("nan")
            with self.assertRaises(ValueError):
                config.validate(settings)

    def test_nonoverlap_dedup_and_source_failure_isolation(self):
        panels = config.defaults()["panels"][:1]
        duplicate = dict(panels[0], id="codex-other-model", model="other")
        panels.append(duplicate)
        panels.append(config.defaults()["panels"][3])
        engine = self.engine(panels)
        engine.tick(100)
        self.assertEqual(len(engine.pool.jobs), 2)
        engine.tick(110)
        self.assertEqual(len(engine.pool.jobs), 2)
        engine.pool.jobs[0].set_exception(SourceError("offline", retry_after=90))
        engine.pool.jobs[1].set_result(Reading(("balance",), time.time(), "test"))
        engine.tick(111)
        self.assertEqual(engine.state(panels[0]).blocked_until, 201)
        self.assertIsNotNone(engine.state(panels[2]).reading)
        engine.tick(172)
        self.assertEqual(len(engine.pool.jobs), 3)
        self.assertEqual(engine.state(panels[0]).error, "offline")

    def test_retry_retains_last_good_data_and_manual_respects_limit(self):
        panels = config.defaults()["panels"][:1]
        engine = self.engine(panels)
        engine.tick(100)
        reading = Reading(("remaining",), time.time(), "test")
        engine.pool.jobs[0].set_result(reading)
        engine.tick(101)
        engine.tick(162)
        engine.pool.jobs[1].set_exception(SourceError("429", retry_after=60))
        engine.tick(163)
        self.assertEqual(engine.state(panels[0]).reading, reading)
        with patch("quota.engine.time.monotonic", return_value=170):
            engine.refresh(panels)
        engine.tick(180)
        self.assertEqual(len(engine.pool.jobs), 2)
        engine.tick(223)
        self.assertEqual(len(engine.pool.jobs), 3)

    def test_pause_disable_and_independent_intervals(self):
        panels = config.defaults()["panels"][2:4]
        panels[0]["interval"] = 10
        panels[1]["interval"] = 60
        engine = self.engine(panels)
        engine.tick(100)
        for future in engine.pool.jobs:
            future.set_result(Reading(("ok",), time.time(), "test"))
        engine.tick(101)
        self.assertEqual(engine.state(panels[0]).next_due, 111)
        self.assertEqual(engine.state(panels[1]).next_due, 161)
        panels[0]["paused"] = True
        panels[1]["enabled"] = False
        engine.tick(200)
        self.assertEqual(len(engine.pool.jobs), 2)
        panels[0]["paused"] = False
        engine.tick(201)
        self.assertEqual(len(engine.pool.jobs), 3)

    def test_auth_stops_automatic_retry(self):
        panels = config.defaults()["panels"][:1]
        engine = self.engine(panels)
        engine.tick(100)
        engine.pool.jobs[0].set_exception(SourceError("login", auth=True))
        engine.tick(101)
        engine.tick(1000)
        self.assertEqual(len(engine.pool.jobs), 1)

    def test_terminal_resizing_pagination_and_escape_filter(self):
        from quota.terminal import clean

        panels = config.defaults()["panels"]
        engine = self.engine(panels)
        for width, height in [(20, 8), (80, 25), (120, 40), (180, 50)]:
            frame = render(panels, engine, 4, width, height)
            self.assertLessEqual(len(frame.splitlines()), height - 1)
        self.assertEqual(fit("中文abc", 5), "中文a")
        self.assertNotIn("\x1b", clean("\x1b[2Jinjected"))
        self.assertIn("火山方舟", render(panels, engine, 4, 80, 25))
        compact = render(panels, engine, 0, 80, 24)
        for name in config.LABELS:
            self.assertIn(name, compact)
        self.assertIn("页 1/1", compact)
        many = [dict(panels[0], id=f"panel-{i}", label=f"Account {i}") for i in range(40)]
        selection = render(many, engine, 39, 80, 24, settings=True)
        self.assertIn("> [x] Account 39", selection)
        self.assertLessEqual(len(selection.splitlines()), 23)
        small = render_single(panels[0], engine, 38, 6)
        self.assertIn("额度: 未知", small)
        self.assertLessEqual(len(small.splitlines()), 5)

    def test_layout_quotes_paths_and_panel_ids(self):
        panels = config.defaults()["panels"]
        panels[0]["enabled"] = False
        text = app.layout_text(panels, Path("a b/config.json"), "C:\\Python Dir\\python.exe")
        self.assertNotIn('name="Codex"', text)
        self.assertEqual(text.count("command="), 4)
        self.assertIn('"--panel" "claude"', text)

    def test_retry_after_formats(self):
        self.assertEqual(retry_seconds("120"), 120)
        self.assertEqual(retry_seconds("bad"), 60)


if __name__ == "__main__":
    unittest.main()
