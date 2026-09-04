import re
import unittest
from pathlib import Path

from mirrormate import __version__


class PackagingTests(unittest.TestCase):
    def test_version_is_consistent(self):
        pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), __version__)

    def test_debian_control_declares_supported_python(self):
        control = Path("packaging/debian/control").read_text(encoding="utf-8")
        self.assertIn("Depends: python3 (>= 3.10)", control)
        self.assertIn("Version: @VERSION@", control)


if __name__ == "__main__":
    unittest.main()
