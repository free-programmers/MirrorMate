import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mirrormate.backup import create_snapshot, restore_snapshot
from mirrormate.errors import MirrorMateError, PermissionDeniedError
from mirrormate.models import DistroInfo, Mirror
from mirrormate.platform import UserContext
from mirrormate.service import MirrorService


class FailingRunner:
    def which(self, command):
        return f"/usr/bin/{command}"

    def run(self, args, **kwargs):
        raise MirrorMateError("simulated apt failure")


class BackupAndServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "home/tester"
        self.home.mkdir(parents=True)
        self.user = UserContext("tester", os.getuid(), os.getgid(), self.home)

    def test_restore_existing_user_file(self):
        path = self.home / ".npmrc"
        path.write_text("registry=https://old.example\n", encoding="utf-8")
        identifier = create_snapshot("npm", [path], user=self.user, root=self.root)
        path.write_text("registry=https://new.example\n", encoding="utf-8")
        result = restore_snapshot(identifier, user=self.user, root=self.root)
        self.assertEqual(result["restored_files"], 1)
        self.assertEqual(path.read_text(), "registry=https://old.example\n")

    def test_restore_removes_file_that_was_originally_absent(self):
        path = self.home / ".config/go/env"
        identifier = create_snapshot("go", [path], user=self.user, root=self.root)
        path.parent.mkdir(parents=True)
        path.write_text("GOPROXY=https://new.example\n", encoding="utf-8")
        restore_snapshot(identifier, user=self.user, root=self.root)
        self.assertFalse(path.exists())

    def test_service_rolls_back_apt_files_when_refresh_fails(self):
        os_release = self.root / "etc/os-release"
        os_release.parent.mkdir(parents=True)
        os_release.write_text("ID=ubuntu\nVERSION_ID=22.04\nVERSION_CODENAME=jammy\n")
        sources = self.root / "etc/apt/sources.list"
        sources.parent.mkdir(parents=True)
        original = "deb http://archive.ubuntu.com/ubuntu jammy main restricted\n"
        sources.write_text(original)
        mirror = Mirror(
            "new-ubuntu",
            "apt",
            "New",
            distro="ubuntu",
            archive_url="https://new.example/ubuntu",
        )
        service = MirrorService(
            catalog=[mirror],
            user=self.user,
            root=self.root,
            runner=FailingRunner(),
            distro=DistroInfo("ubuntu", "22.04", "jammy", "amd64"),
        )
        with mock.patch("mirrormate.platform.os.geteuid", return_value=0):
            with self.assertRaises(MirrorMateError):
                service.apply("apt", mirror)
        self.assertEqual(sources.read_text(), original)
        self.assertFalse((self.root / "var/lib/mirrormate/state.json").exists())

    def test_dry_run_never_writes_or_requires_root(self):
        path = self.home / ".npmrc"
        path.write_text("registry=https://old.example\n")
        mirror = Mirror("npm-new", "npm", "New", url="https://new.example")
        service = MirrorService(catalog=[mirror], user=self.user, root=self.root)
        result = service.apply("npm", mirror, dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertIn("https://new.example", result["diff"])
        self.assertIn("https://old.example", path.read_text())

    def test_system_apply_fails_with_permission_code_before_writing(self):
        mirror = Mirror("docker-new", "docker", "New", url="https://docker.example")
        service = MirrorService(catalog=[mirror], user=self.user, root=self.root)
        with mock.patch("mirrormate.platform.os.geteuid", return_value=1000):
            with self.assertRaises(PermissionDeniedError) as raised:
                service.apply("docker", mirror)
        self.assertEqual(raised.exception.exit_code, 77)
        self.assertFalse((self.root / "etc/docker/daemon.json").exists())

    def test_restore_rolls_back_if_post_restore_validation_fails(self):
        sources = self.root / "etc/apt/sources.list"
        sources.parent.mkdir(parents=True)
        sources.write_text("deb https://backup.example jammy main\n")
        identifier = create_snapshot("apt", [sources], user=self.user, root=self.root)
        current = "deb https://current.example jammy main\n"
        sources.write_text(current)
        service = MirrorService(
            catalog=[],
            user=self.user,
            root=self.root,
            runner=FailingRunner(),
            distro=DistroInfo("ubuntu", "22.04", "jammy", "amd64"),
        )
        with mock.patch("mirrormate.platform.os.geteuid", return_value=0):
            with self.assertRaises(MirrorMateError):
                service.restore(identifier)
        self.assertEqual(sources.read_text(), current)


if __name__ == "__main__":
    unittest.main()
