import unittest
from unittest.mock import patch

from quota.antigravity import collect
from quota.providers import SourceError


class AntigravityTests(unittest.TestCase):
    def response(self):
        return {
            "status": "SUCCESS",
            "num_turns": 0,
            "command": {
                "name": "usage",
                "data": {
                    "groups": [
                        {
                            "name": "Gemini Models",
                            "buckets": [
                                {"window": "weekly", "remaining_fraction": 0, "reset_time": "2026-10-23T00:00:00Z"},
                                {"window": "5h", "remaining_fraction": 1},
                            ],
                        }
                    ]
                },
            },
        }

    @patch("quota.antigravity.resolve", return_value=["agy.exe"])
    @patch("quota.antigravity.run_json")
    def test_builtin_usage_and_zero_remaining(self, run, resolve):
        run.return_value = self.response()
        reading = collect({"model": "Gemini"})
        self.assertIn("剩余 0%", reading.metrics[0])
        self.assertIn("剩余 100%", reading.metrics[-1])
        self.assertEqual(
            run.call_args.args[0], ["agy.exe", "--print", "/usage", "--output-format", "json", "--print-timeout", "30s"]
        )

    @patch("quota.antigravity.resolve", return_value=["agy.exe"])
    @patch("quota.antigravity.run_json")
    def test_reject_model_response_and_invalid_fraction(self, run, resolve):
        for field, value in (("num_turns", 1), ("status", "ERROR"), ("command", {})):
            data = self.response()
            data[field] = value
            run.return_value = data
            with self.assertRaises(SourceError):
                collect({})
        for value in (True, -1, 2, float("nan"), "100%"):
            data = self.response()
            data["command"]["data"]["groups"][0]["buckets"][0]["remaining_fraction"] = value
            run.return_value = data
            with self.assertRaises(SourceError):
                collect({})
