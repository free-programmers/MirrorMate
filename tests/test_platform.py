import tempfile
import unittest
from pathlib import Path

from mirrormate.errors import UsageError
from mirrormate.platform import detect_distro, ensure_supported, normalize_architecture


class PlatformTests(unittest.TestCase):
    def _root(self, content: str) -> tuple[tempfile.TemporaryDirectory, Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        (root / "etc").mkdir()
        (root / "etc/os-release").write_text(content, encoding="utf-8")
        return temporary, root

    def test_detects_ubuntu_without_sourcing_shell(self):
        temporary, root = self._root('ID=ubuntu\nVERSION_ID="24.04"\nVERSION_CODENAME=noble\n')
        self.addCleanup(temporary.cleanup)
        distro = detect_distro(root, architecture="x86_64")
        self.assertEqual(distro.id, "ubuntu")
        self.assertEqual(distro.codename, "noble")
        self.assertEqual(distro.architecture, "amd64")
        ensure_supported(distro)

    def test_detects_debian(self):
        temporary, root = self._root('ID=debian\nVERSION_ID="12"\nVERSION_CODENAME=bookworm\n')
        self.addCleanup(temporary.cleanup)
        distro = detect_distro(root, architecture="aarch64")
        self.assertEqual(distro.architecture, "arm64")
        ensure_supported(distro)

    def test_rejects_unsupported_release(self):
        temporary, root = self._root('ID=ubuntu\nVERSION_ID="20.04"\nVERSION_CODENAME=focal\n')
        self.addCleanup(temporary.cleanup)
        with self.assertRaises(UsageError):
            ensure_supported(detect_distro(root))

    def test_architecture_aliases(self):
        self.assertEqual(normalize_architecture("ppc64le"), "ppc64el")

    def test_declared_release_matrix_is_supported(self):
        for distro_id, version, codename in (
            ("ubuntu", "22.04", "jammy"),
            ("ubuntu", "24.04", "noble"),
            ("ubuntu", "26.04", "resolute"),
            ("debian", "12", "bookworm"),
            ("debian", "13", "trixie"),
        ):
            temporary, root = self._root(
                f"ID={distro_id}\nVERSION_ID={version}\nVERSION_CODENAME={codename}\n"
            )
            try:
                ensure_supported(detect_distro(root))
            finally:
                temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
