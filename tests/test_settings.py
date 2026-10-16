import contextlib
import copy
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from quota import config, credentials
from quota.settings import screen, set_field


class SettingsTests(unittest.TestCase):
    def run_screen(self, answers, secret="synthetic-test-only"):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "config.json"
        settings = config.load(path)
        iterator = iter(answers)
        with contextlib.redirect_stdout(io.StringIO()):
            screen(settings, path, input_fn=lambda _: next(iterator), secret_fn=lambda _: secret)
        return settings, path

    def test_edit_and_add_without_json_editing(self):
        settings, path = self.run_screen(
            ["2", "1", "Claude Work", "3", "15", "s", "n", "2", "1", "Claude Personal", "s", "0"]
        )
        self.assertEqual(settings["panels"][1]["label"], "Claude Work")
        self.assertEqual(settings["panels"][1]["interval"], 15)
        self.assertEqual(len(settings["panels"]), 6)
        self.assertEqual(settings["panels"][-1]["label"], "Claude Personal")
        self.assertEqual(settings, config.load(path))

    def test_cancel_and_invalid_input_preserve_original(self):
        settings, _ = self.run_screen(["1", "3", "1", "1", "Changed", "0", "0"])
        self.assertEqual(settings, config.defaults())
        panel = copy.deepcopy(settings["panels"][0])
        before = copy.deepcopy(panel)
        with self.assertRaises(ValueError):
            set_field(panel, "interval", "nan")
        self.assertEqual(panel, before)
        set_field(panel, "codex_home", r"C:\Accounts\WorkABC")
        self.assertEqual(panel["codex_home"], r"C:\Accounts\WorkABC")

    def test_credential_saved_by_reference_only(self):
        with patch("quota.settings.credentials.write") as write, patch("quota.settings.credentials.delete"):
            settings, path = self.run_screen(["4", "k", "s", "0"])
            write.assert_called_once()
            self.assertTrue(settings["panels"][3]["credential_ref"].startswith("AIQuota/"))
            self.assertNotIn("synthetic-test-only", path.read_text(encoding="utf-8"))

    def test_cancel_removes_pending_credential(self):
        with patch("quota.settings.credentials.write") as write, patch("quota.settings.credentials.delete") as delete:
            settings, _ = self.run_screen(["4", "k", "0", "0"])
            self.assertEqual(settings, config.defaults())
            delete.assert_called_once_with(write.call_args.args[0])

    def test_deleting_last_panel_fails_without_losing_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.json"
            settings = {"version": 1, "panels": [config.defaults()["panels"][0]]}
            config.save(path, settings)
            answers = iter(["1", "x", "YES", "0"])
            with contextlib.redirect_stdout(io.StringIO()):
                screen(settings, path, lambda _: next(answers))
            self.assertEqual(len(config.load(path)["panels"]), 1)

    @unittest.skipUnless(os.name == "nt", "Windows Credential Manager")
    def test_windows_vault_roundtrip_and_cleanup(self):
        reference = "AIQuota/test/" + uuid.uuid4().hex
        try:
            credentials.write(reference, "SyntheticTest-Only-123")
            self.assertEqual(credentials.read(reference), "SyntheticTest-Only-123")
        finally:
            credentials.delete(reference)
        self.assertIsNone(credentials.read(reference))


if __name__ == "__main__":
    unittest.main()
