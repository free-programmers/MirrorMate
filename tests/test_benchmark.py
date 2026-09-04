import unittest

from mirrormate.benchmark import benchmark_mirrors, fastest_result, probe_url, probe_urls
from mirrormate.models import Mirror


class BenchmarkTests(unittest.TestCase):
    def test_category_probe_urls(self):
        self.assertEqual(
            probe_url(Mirror("npm", "npm", "NPM", url="https://npm.example")),
            "https://npm.example/-/ping",
        )
        apt = Mirror("apt", "apt", "APT", distro="debian", archive_url="https://deb.example/debian")
        self.assertEqual(probe_url(apt, "bookworm"), "https://deb.example/debian/dists/bookworm/InRelease")
        apt_with_security = Mirror(
            "apt-sec", "apt", "APT", distro="debian",
            archive_url="https://deb.example/debian",
            security_url="https://security.example/debian-security",
        )
        self.assertEqual(
            probe_urls(apt_with_security, "bookworm"),
            [
                "https://deb.example/debian/dists/bookworm/InRelease",
                "https://security.example/debian-security/dists/bookworm-security/InRelease",
            ],
        )

    def test_fastest_uses_median_and_ignores_unreachable(self):
        timings = {
            "https://one.example/pip/": iter([30.0, 20.0, 10.0]),
            "https://two.example/pip/": iter([8.0, 9.0, 10.0]),
        }

        def probe(url, timeout, mirror_type):
            if "down" in url:
                raise OSError("offline")
            return next(timings[url])

        mirrors = [
            Mirror("one", "python", "One", url="https://one.example"),
            Mirror("two", "python", "Two", url="https://two.example"),
            Mirror("down", "python", "Down", url="https://down.example"),
        ]
        results = benchmark_mirrors(mirrors, attempts=3, probe=probe)
        self.assertEqual(fastest_result(results).mirror_id, "two")
        self.assertFalse(next(item for item in results if item.mirror_id == "down").healthy)

    def test_progress_reports_each_completed_mirror(self):
        events = []

        def probe(url, timeout, mirror_type):
            return 12.0

        mirrors = [
            Mirror("one", "npm", "One", url="https://one.example"),
            Mirror("two", "npm", "Two", url="https://two.example"),
        ]
        benchmark_mirrors(
            mirrors,
            attempts=1,
            probe=probe,
            progress=lambda result, done, total: events.append((result.mirror_id, done, total)),
        )
        self.assertEqual({event[0] for event in events}, {"one", "two"})
        self.assertEqual([event[1] for event in events], [1, 2])
        self.assertTrue(all(event[2] == 2 for event in events))


if __name__ == "__main__":
    unittest.main()
