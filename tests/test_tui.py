import unittest

from mirrormate.models import BenchmarkResult
from mirrormate.tui import latency_quality


def result(latency=None, healthy=True):
    return BenchmarkResult("mirror", "Mirror", "https://example.test", healthy, latency, 3, 3)


class TuiPresentationTests(unittest.TestCase):
    def test_latency_quality_bands(self):
        self.assertEqual(latency_quality(None), "NOT TESTED")
        self.assertEqual(latency_quality(result(80)), "EXCELLENT")
        self.assertEqual(latency_quality(result(250)), "GOOD")
        self.assertEqual(latency_quality(result(500)), "FAIR")
        self.assertEqual(latency_quality(result(900)), "SLOW")
        self.assertEqual(latency_quality(result(None, healthy=False)), "OFFLINE")

    def test_fastest_label_only_applies_to_healthy_results(self):
        self.assertEqual(latency_quality(result(200), fastest=True), "FASTEST")
        self.assertEqual(latency_quality(result(None, healthy=False), fastest=True), "OFFLINE")


if __name__ == "__main__":
    unittest.main()
