import io
import unittest
from contextlib import redirect_stderr
from unittest import mock

from mirrormate.cli import build_parser, main


class CliTests(unittest.TestCase):
    def test_backup_alias(self):
        args = build_parser().parse_args(["set", "python", "--url", "https://example.test", "--make-backup"])
        self.assertTrue(args.backup)

    def test_no_arguments_in_non_interactive_mode_prints_help(self):
        error = io.StringIO()
        with mock.patch("sys.stdin.isatty", return_value=False), mock.patch("sys.stdout.isatty", return_value=False):
            with redirect_stderr(error):
                result = main([])
        self.assertEqual(result, 2)
        self.assertIn("Safely benchmark", error.getvalue())

    def test_no_arguments_in_tty_opens_tui(self):
        with mock.patch("sys.stdin.isatty", return_value=True), mock.patch("sys.stdout.isatty", return_value=True):
            with mock.patch("mirrormate.cli.invoking_user"), mock.patch(
                "mirrormate.cli.load_catalogs", return_value=[]
            ), mock.patch("mirrormate.tui.run_tui", return_value=0) as tui:
                result = main([])
        self.assertEqual(result, 0)
        tui.assert_called_once()

    def test_subcommand_shape(self):
        args = build_parser().parse_args(["set", "apt", "--distro", "debian", "--fastest", "--backup"])
        self.assertEqual(args.mirror_type, "apt")
        self.assertEqual(args.distro, "debian")
        self.assertTrue(args.fastest)


if __name__ == "__main__":
    unittest.main()
