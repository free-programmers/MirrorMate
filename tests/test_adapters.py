import json
import os
import tempfile
import unittest
from pathlib import Path

from mirrormate.adapters.apt import AptAdapter
from mirrormate.adapters.docker import DockerAdapter
from mirrormate.adapters.user_config import GoAdapter, NpmAdapter, PythonAdapter
from mirrormate.errors import UsageError
from mirrormate.models import DistroInfo, Mirror
from mirrormate.platform import UserContext
from mirrormate.runner import CommandRunner


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "home/tester"
        self.home.mkdir(parents=True)
        self.user = UserContext("tester", os.getuid(), os.getgid(), self.home)
        self.runner = CommandRunner()

    def test_user_adapters_preserve_unrelated_settings(self):
        npmrc = self.home / ".npmrc"
        npmrc.write_text("fund=false\nregistry=https://old.example\n", encoding="utf-8")
        npm = NpmAdapter(root=self.root, user=self.user, runner=self.runner)
        plan = npm.plan(Mirror("npm-new", "npm", "New", url="https://new.example"))
        text = plan.files[0].content.decode()
        self.assertIn("fund=false", text)
        self.assertIn("registry=https://new.example", text)

        go = GoAdapter(root=self.root, user=self.user, runner=self.runner)
        go_plan = go.plan(Mirror("go-new", "go", "New", url="https://go.example"))
        self.assertIn("GOPROXY=https://go.example", go_plan.files[0].content.decode())

        python = PythonAdapter(root=self.root, user=self.user, runner=self.runner)
        py_plan = python.plan(Mirror("py-new", "python", "New", url="https://py.example/simple"))
        self.assertIn("index-url = https://py.example/simple", py_plan.files[0].content.decode())

    def test_docker_merges_daemon_json(self):
        path = self.root / "etc/docker/daemon.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"log-driver": "journald", "registry-mirrors": ["https://old"]}))
        adapter = DockerAdapter(root=self.root, user=self.user, runner=self.runner)
        mirror = Mirror("docker-new", "docker", "New", url="https://docker.example")
        plan = adapter.plan(mirror)
        updated = json.loads(plan.files[0].content)
        self.assertEqual(updated["log-driver"], "journald")
        self.assertEqual(updated["registry-mirrors"], ["https://docker.example"])

    def test_docker_default_removes_only_registry_mirrors(self):
        path = self.root / "etc/docker/daemon.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"debug": True, "registry-mirrors": ["https://old"]}))
        adapter = DockerAdapter(root=self.root, user=self.user, runner=self.runner)
        plan = adapter.plan(Mirror("docker-default", "docker", "Default", url="https://registry-1.docker.io", default=True))
        updated = json.loads(plan.files[0].content)
        self.assertEqual(updated, {"debug": True})

    def test_insecure_docker_requires_explicit_opt_in(self):
        adapter = DockerAdapter(root=self.root, user=self.user, runner=self.runner)
        mirror = Mirror("docker-insecure", "docker", "Insecure", url="http://docker.example", insecure=True)
        with self.assertRaises(UsageError):
            adapter.plan(mirror)
        plan = adapter.plan(mirror, allow_insecure=True)
        updated = json.loads(plan.files[0].content)
        self.assertEqual(updated["insecure-registries"], ["docker.example"])

    def test_docker_removes_only_previously_managed_insecure_host(self):
        config = self.root / "etc/docker/daemon.json"
        config.parent.mkdir(parents=True)
        config.write_text(
            json.dumps({"insecure-registries": ["old.example", "unrelated.example"]})
        )
        state = self.root / "var/lib/mirrormate/state.json"
        state.parent.mkdir(parents=True)
        state.write_text(
            json.dumps({"schema_version": 1, "docker": {"managed_insecure_host": "old.example"}})
        )
        adapter = DockerAdapter(root=self.root, user=self.user, runner=self.runner)
        mirror = Mirror("secure", "docker", "Secure", url="https://secure.example")
        plan = adapter.plan(mirror)
        updated = json.loads(plan.files[0].content)
        self.assertEqual(updated["insecure-registries"], ["unrelated.example"])

    def test_apt_list_rewrite_preserves_third_party(self):
        path = self.root / "etc/apt/sources.list"
        path.parent.mkdir(parents=True)
        original = (
            "deb http://archive.ubuntu.com/ubuntu jammy main restricted universe multiverse\n"
            "deb http://security.ubuntu.com/ubuntu jammy-security main restricted\n"
            "deb https://packages.example.test/repo jammy main\n"
        )
        path.write_text(original, encoding="utf-8")
        distro = DistroInfo("ubuntu", "22.04", "jammy", "amd64")
        target = Mirror(
            "custom-ubuntu",
            "apt",
            "Custom",
            distro="ubuntu",
            archive_url="https://mirror.example/ubuntu",
            security_url="https://mirror.example/ubuntu-security",
        )
        adapter = AptAdapter(root=self.root, user=self.user, runner=self.runner, distro=distro, catalog=[target])
        plan = adapter.plan(target)
        updated = next(item for item in plan.files if item.path == path).content.decode()
        self.assertIn("https://mirror.example/ubuntu jammy", updated)
        self.assertIn("https://mirror.example/ubuntu-security jammy-security", updated)
        self.assertIn("https://packages.example.test/repo jammy main", updated)

    def test_apt_deb822_rewrite_preserves_fields(self):
        path = self.root / "etc/apt/sources.list.d/ubuntu.sources"
        path.parent.mkdir(parents=True)
        path.write_text(
            "Types: deb\n"
            "URIs: http://archive.ubuntu.com/ubuntu\n"
            "Suites: noble noble-updates\n"
            "Components: main restricted universe multiverse\n"
            "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n\n"
            "Types: deb\n"
            "URIs: http://security.ubuntu.com/ubuntu\n"
            "Suites: noble-security\n"
            "Components: main restricted\n"
            "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n",
            encoding="utf-8",
        )
        distro = DistroInfo("ubuntu", "24.04", "noble", "amd64")
        target = Mirror(
            "ubuntu-new", "apt", "New", distro="ubuntu",
            archive_url="https://new.example/ubuntu", security_url="https://new.example/security"
        )
        adapter = AptAdapter(root=self.root, user=self.user, runner=self.runner, distro=distro, catalog=[target])
        plan = adapter.plan(target)
        updated = next(item for item in plan.files if item.path == path).content.decode()
        self.assertIn("URIs: https://new.example/ubuntu", updated)
        self.assertIn("URIs: https://new.example/security", updated)
        self.assertEqual(updated.count("Signed-By:"), 2)
        self.assertIn("Components: main restricted universe multiverse", updated)

    def test_debian_archive_and_security_are_rewritten_separately(self):
        path = self.root / "etc/apt/sources.list.d/debian.sources"
        path.parent.mkdir(parents=True)
        path.write_text(
            "Types: deb\n"
            "URIs: https://deb.debian.org/debian\n"
            "Suites: bookworm bookworm-updates\n"
            "Components: main contrib non-free-firmware\n"
            "Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg\n\n"
            "Types: deb\n"
            "URIs: https://security.debian.org/debian-security\n"
            "Suites: bookworm-security\n"
            "Components: main contrib non-free-firmware\n"
            "Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg\n",
            encoding="utf-8",
        )
        distro = DistroInfo("debian", "12", "bookworm", "amd64")
        target = Mirror(
            "debian-new", "apt", "New", distro="debian",
            archive_url="https://mirror.example/debian",
            security_url="https://mirror.example/debian-security",
        )
        adapter = AptAdapter(root=self.root, user=self.user, runner=self.runner, distro=distro, catalog=[target])
        plan = adapter.plan(target)
        updated = next(item for item in plan.files if item.path == path).content.decode()
        self.assertIn("URIs: https://mirror.example/debian\n", updated)
        self.assertIn("URIs: https://mirror.example/debian-security\n", updated)
        self.assertEqual(updated.count("Signed-By:"), 2)


if __name__ == "__main__":
    unittest.main()
