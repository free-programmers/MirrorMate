import json
import os
import tempfile
import unittest
from pathlib import Path

from mirrormate.errors import UsageError
from mirrormate.platform import UserContext
from mirrormate.settings import TuiSettings, load_settings, save_settings, settings_path


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name) / "home/tester"
        self.home.mkdir(parents=True)
        self.user = UserContext("tester", os.getuid(), os.getgid(), self.home)

    def test_missing_settings_use_safe_defaults(self):
        settings = load_settings(self.user)
        self.assertFalse(settings.auto_benchmark)
        self.assertTrue(settings.sort_by_speed)
        self.assertEqual(settings.benchmark_attempts, 3)
        self.assertEqual(settings.theme, "ocean")

    def test_settings_are_saved_atomically_with_private_mode(self):
        expected = TuiSettings(True, 5, 5.0, False, "violet")
        path = save_settings(expected, self.user)
        self.assertEqual(load_settings(self.user), expected)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_invalid_settings_are_rejected(self):
        path = settings_path(self.user)
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps({"schema_version": 1, "benchmark_attempts": 2}),
            encoding="utf-8",
        )
        with self.assertRaises(UsageError):
            load_settings(self.user)

    def test_unknown_theme_is_rejected(self):
        path = settings_path(self.user)
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps({"schema_version": 1, "theme": "not-a-theme"}),
            encoding="utf-8",
        )
        with self.assertRaises(UsageError):
            load_settings(self.user)


if __name__ == "__main__":
    unittest.main()
