import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from quota import config
from quota.ark import collect_ark, parse_usage, parse_resources
from quota.providers import SourceError, collect
from quota.subscriptions import claude, gemini, google_token, parse_claude, parse_gemini, _google_tokens


class SourceTests(unittest.TestCase):
    def test_claude_model_panels_share_fetch_and_original_timestamp(self):
        path = self.auth_file({"claudeAiOauth": {"accessToken": "synthetic", "expiresAt": (time.time() + 3600) * 1000}})
        data = {"five_hour": {"utilization": 10}, "seven_day_sonnet": {"utilization": 20}}
        with patch("quota.subscriptions.https_json", return_value=data) as http:
            first = claude({"auth_file": str(path), "model": "account"})
            second = claude({"auth_file": str(path), "model": "sonnet"})
        http.assert_called_once()
        self.assertEqual(first.observed_at, second.observed_at)

    def temporary(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Path(directory.name)

    def auth_file(self, data):
        path = self.temporary() / "auth.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_claude_live_adapter_uses_only_oauth_usage(self):
        path = self.auth_file(
            {"claudeAiOauth": {"accessToken": "synthetic-oauth", "expiresAt": (time.time() + 3600) * 1000}}
        )
        response = {
            "five_hour": {"utilization": 0},
            "seven_day": {"utilization": 100},
            "seven_day_sonnet": {"utilization": 12.5},
            "seven_day_opus": None,
        }
        with patch("quota.subscriptions.https_json", return_value=response) as http:
            reading = claude({"auth_file": str(path)})
        self.assertIn("剩余 100.0%", reading.metrics[0])
        self.assertIn("剩余 0.0%", reading.metrics[1])
        self.assertIn("剩余 87.5%", reading.metrics[2])
        self.assertEqual(http.call_args.args[0], "https://api.anthropic.com/api/oauth/usage")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer synthetic-oauth")
        self.assertNotIn("synthetic-oauth", repr(reading))

    def test_claude_expired_or_missing_login_does_not_call_network(self):
        path = self.auth_file({"claudeAiOauth": {"accessToken": "fake", "expiresAt": 1}})
        with patch("quota.subscriptions.https_json") as http:
            with self.assertRaises(SourceError) as error:
                claude({"auth_file": str(path)})
            self.assertTrue(error.exception.auth)
            http.assert_not_called()
        self.assertEqual(
            len(
                parse_claude(
                    {
                        "five_hour": {"utilization": 1},
                        "seven_day_sonnet": {"utilization": 2},
                        "seven_day_opus": {"utilization": 3},
                    },
                    "sonnet",
                ).metrics
            ),
            3,
        )

    def test_gemini_full_zero_and_model_filter(self):
        data = {
            "buckets": [
                {"modelId": "pro", "remainingFraction": 1, "tokenType": "REQUESTS"},
                {"modelId": "flash", "remainingFraction": 0, "remainingAmount": "0"},
            ]
        }
        self.assertIn("100.0%", parse_gemini(data).metrics[0])
        filtered = parse_gemini(data, "flash")
        self.assertIn("0.0%", filtered.metrics[0])
        self.assertIn("剩余数量: 0", filtered.metrics[1])
        with self.assertRaises(SourceError):
            parse_gemini(data, "unknown")

    def test_gemini_adapter_discovers_project_without_onboarding_or_inference(self):
        path = self.auth_file({"access_token": "synthetic-google", "expiry_date": (time.time() + 3600) * 1000})
        with patch(
            "quota.subscriptions.post_json",
            side_effect=[
                {"cloudaicompanionProject": "test-project"},
                {"buckets": [{"modelId": "pro", "remainingFraction": 0.75}]},
            ],
        ) as http:
            reading = gemini({"auth_file": str(path)})
        self.assertIn("75.0%", reading.metrics[0])
        self.assertEqual(
            [call.args[0].rsplit(":", 1)[-1] for call in http.call_args_list], ["loadCodeAssist", "retrieveUserQuota"]
        )
        self.assertNotIn("synthetic-google", repr(reading))

    def test_gemini_refresh_cache_does_not_overwrite_cli_credentials(self):
        path = self.auth_file({"access_token": "expired", "expiry_date": 1, "refresh_token": "synthetic-refresh"})
        module = path.parent / "oauth2.js"
        module.write_text(
            "const OAUTH_CLIENT_ID = 'test-app'; const OAUTH_CLIENT_SECRET = 'test-public-metadata';", encoding="utf-8"
        )
        panel = {"auth_file": str(path), "gemini_oauth_module": str(module)}
        _google_tokens.clear()
        with patch(
            "quota.subscriptions.https_json", return_value={"access_token": "new-test-token", "expires_in": 3600}
        ) as http:
            self.assertEqual(google_token(panel), "new-test-token")
            self.assertEqual(google_token(panel), "new-test-token")
            http.assert_called_once()
        self.assertEqual(json.loads(path.read_text())["access_token"], "expired")
        _google_tokens.clear()

    def test_ark_stats_and_free_quota_are_separate_units(self):
        usage = parse_usage({"totals": {"TotalTokens": "12345678901234567890", "ReqCnt": "42"}}, "today", "mine")
        self.assertIn("12345678901234567890", usage[1])
        resources = parse_resources(
            {
                "items": [
                    {
                        "model": "doubao",
                        "free_usage": {"remaining": "1000"},
                        "resource_packs": [{"type": "paid-pack", "remaining": 22}],
                    }
                ]
            }
        )
        self.assertIn("免费额度剩余 1000", resources[0])
        self.assertIn("paid-pack: 剩余 22", resources[1])
        with self.assertRaises(SourceError):
            parse_usage({"totals": {"TotalTokens": 0}, "is_truncated": True}, "", "")

    def test_ark_adapter_preserves_profile_scope_and_model(self):
        panel = dict(config.defaults()["panels"][4], ark_profile="my-profile", model="doubao", ark_scope="mine")
        responses = [
            {"logged_in": True},
            {"totals": {"TotalTokens": "100", "ReqCnt": "2"}},
            {"items": [{"model": "doubao", "free_usage": {"remaining": 50}}], "total_count": 1},
        ]
        with (
            patch("quota.ark.resolve", return_value=["arkcli.exe"]),
            patch("quota.ark.run_json", side_effect=responses) as run,
        ):
            reading = collect_ark(panel)
        args = run.call_args_list[1].args[0]
        self.assertIn("--mine", args)
        self.assertEqual(args[args.index("--mine-by") + 1], "apikey")
        self.assertEqual(args[args.index("--model") + 1], "doubao")
        self.assertEqual(args[1:3], ["--profile", "my-profile"])
        self.assertIn("Token 已用: 100", reading.metrics)
        self.assertEqual(len(run.call_args_list), 3)

    def test_ark_resources_paginate_and_partial_usage_is_visible(self):
        panel = config.defaults()["panels"][4]
        responses = [
            {"logged_in": True},
            SourceError("scope failure"),
            {"items": [{"model": "a", "free_usage": {"remaining": 1}}], "page_size": 1, "total_count": 2},
            {"items": [{"model": "b", "free_usage": {"remaining": 2}}], "page_size": 1, "total_count": 2},
        ]
        with (
            patch("quota.ark.resolve", return_value=["arkcli.exe"]),
            patch("quota.ark.run_json", side_effect=responses),
        ):
            reading = collect_ark(panel)
        self.assertTrue(any("部分数据不可用" in item for item in reading.metrics))
        self.assertTrue(any("免费额度剩余 2 | b" in item for item in reading.metrics))
        self.assertTrue(reading.partial)

    def test_ark_filtered_page_and_negative_resource_balance(self):
        panel = dict(config.defaults()["panels"][4], ark_view="free_quota")
        response = {
            "items": [
                {
                    "model": "model-a",
                    "state": "Unavailable",
                    "resource_packs": [{"type": "FreeInference", "remaining": -3}],
                }
            ],
            "page_number": 1,
            "page_size": 50,
            "total_count": 34,
        }
        with (
            patch("quota.ark.resolve", return_value=["arkcli.exe"]),
            patch("quota.ark.run_json", side_effect=[{"logged_in": True}, response]) as run,
        ):
            reading = collect_ark(panel)
        self.assertEqual(len(run.call_args_list), 2)
        self.assertIn("Unavailable", reading.metrics[0])
        self.assertIn("剩余 -3", reading.metrics[0])

    def test_v1_default_snapshot_migrates_but_custom_source_remains(self):
        path = self.temporary() / "config.json"
        settings = config.defaults()
        settings["version"] = 1
        settings["panels"][1]["adapter"] = "snapshot"
        settings["panels"][2].update(adapter="snapshot", snapshot="custom.json")
        config.save(path, settings)
        updated = config.load(path)
        self.assertEqual(updated["version"], 2)
        self.assertEqual(updated["panels"][1]["adapter"], "claude")
        self.assertEqual(updated["panels"][2]["adapter"], "snapshot")

    def test_malformed_data_is_reported_without_secret_or_traceback(self):
        panel = config.defaults()["panels"][1]
        with patch("quota.subscriptions.claude", side_effect=KeyError("synthetic-private-value")):
            with self.assertRaises(SourceError) as error:
                collect(panel, Path("."))
        self.assertNotIn("synthetic-private-value", str(error.exception))


if __name__ == "__main__":
    unittest.main()
