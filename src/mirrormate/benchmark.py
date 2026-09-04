from __future__ import annotations

import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable

from .models import BenchmarkResult, Mirror


def probe_url(mirror: Mirror, codename: str | None = None) -> str:
    if mirror.probe_url:
        return mirror.probe_url
    if mirror.type == "apt":
        if not mirror.archive_url or not codename:
            raise ValueError("APT benchmarks require archive_url and codename")
        return f"{mirror.archive_url.rstrip('/')}/dists/{codename}/InRelease"
    if not mirror.url:
        raise ValueError(f"Mirror {mirror.id} has no URL")
    base = mirror.url.rstrip("/")
    suffix = {
        "python": "/pip/",
        "npm": "/-/ping",
        "docker": "/v2/",
        "go": "/golang.org/x/text/@v/list",
    }.get(mirror.type, "")
    return base + suffix


def probe_urls(mirror: Mirror, codename: str | None = None) -> list[str]:
    primary = probe_url(mirror, codename)
    if mirror.type != "apt" or not mirror.security_url or not codename:
        return [primary]
    security = f"{mirror.security_url.rstrip('/')}/dists/{codename}-security/InRelease"
    return [primary, security]


def http_probe(url: str, timeout: float, mirror_type: str) -> float:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "MirrorMate/2",
            "Accept": "*/*",
        },
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status < 200 or status >= 400:
                raise OSError(f"HTTP {status}")
            response.read(16 * 1024)
    except urllib.error.HTTPError as exc:
        if not (mirror_type == "docker" and exc.code == 401):
            raise OSError(f"HTTP {exc.code}") from exc
        exc.close()
    return (time.perf_counter() - started) * 1000


ProbeFunction = Callable[[str, float, str], float]
ProgressCallback = Callable[[BenchmarkResult, int, int], None]


def benchmark_one(
    mirror: Mirror,
    *,
    codename: str | None,
    attempts: int,
    timeout: float,
    probe: ProbeFunction = http_probe,
) -> BenchmarkResult:
    urls = probe_urls(mirror, codename)
    url = urls[0]
    timings = []
    error = None
    for _ in range(attempts):
        try:
            timings.append(max(probe(item, timeout, mirror.type) for item in urls))
        except (OSError, ValueError) as exc:
            error = str(exc)
    median = round(statistics.median(timings), 2) if timings else None
    required_successes = (attempts + 1) // 2
    healthy = len(timings) >= required_successes
    if timings and not healthy:
        error = f"only {len(timings)}/{attempts} probes succeeded"
    return BenchmarkResult(
        mirror_id=mirror.id,
        name=mirror.name,
        url=url,
        healthy=healthy,
        median_ms=median,
        attempts=attempts,
        successful_attempts=len(timings),
        error=None if healthy else (error or "unreachable"),
    )


def benchmark_mirrors(
    mirrors: Iterable[Mirror],
    *,
    codename: str | None = None,
    attempts: int = 3,
    timeout: float = 3.0,
    max_workers: int = 8,
    probe: ProbeFunction = http_probe,
    progress: ProgressCallback | None = None,
) -> list[BenchmarkResult]:
    candidates = list(mirrors)
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    results = []
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(candidates) or 1))) as pool:
        futures = {
            pool.submit(
                benchmark_one,
                mirror,
                codename=codename,
                attempts=attempts,
                timeout=timeout,
                probe=probe,
            ): mirror
            for mirror in candidates
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            if progress is not None:
                progress(result, len(results), len(candidates))
    return sorted(
        results,
        key=lambda item: (not item.healthy, item.median_ms if item.median_ms is not None else float("inf")),
    )


def fastest_result(results: Iterable[BenchmarkResult]) -> BenchmarkResult | None:
    healthy = [result for result in results if result.healthy and result.median_ms is not None]
    return min(healthy, key=lambda item: item.median_ms or 0) if healthy else None
