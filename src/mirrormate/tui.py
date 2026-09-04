from __future__ import annotations

import curses
import os
import shutil
import subprocess
import sys
import textwrap
from dataclasses import replace

from . import __version__
from .backup import list_snapshots
from .benchmark import benchmark_mirrors, fastest_result
from .catalog import (
    fetch_catalog,
    filter_mirrors,
    load_catalogs,
    mutate_custom_catalog,
    normalize_entry,
    parse_catalog,
    remove_custom_mirror,
)
from .errors import MirrorMateError
from .models import BenchmarkResult, MIRROR_TYPES, Mirror
from .service import MirrorService
from .settings import (
    ALLOWED_ATTEMPTS,
    ALLOWED_TIMEOUTS,
    TuiSettings,
    load_settings,
    save_settings,
)
from .themes import THEMES, THEME_ORDER, get_theme


MIN_HEIGHT = 16
MIN_WIDTH = 60
CATEGORY_DETAILS = {
    "apt": ("APT", "Ubuntu and Debian repositories"),
    "python": ("PYTHON", "Python Package Index"),
    "npm": ("NPM", "Node.js package registry"),
    "go": ("GO", "Go module proxy"),
    "docker": ("DOCKER", "Docker registry mirror"),
}


def latency_quality(result: BenchmarkResult | None, *, fastest: bool = False) -> str:
    if result is None:
        return "NOT TESTED"
    if not result.healthy or result.median_ms is None:
        return "OFFLINE"
    if fastest:
        return "FASTEST"
    if result.median_ms < 150:
        return "EXCELLENT"
    if result.median_ms < 350:
        return "GOOD"
    if result.median_ms < 700:
        return "FAIR"
    return "SLOW"


class Tui:
    def __init__(self, screen: curses.window, service: MirrorService) -> None:
        self.screen = screen
        self.service = service
        self.settings = load_settings(service.user)
        self.theme = get_theme(self.settings.theme)
        self.results: dict[str, BenchmarkResult] = {}
        self.testing: set[str] = set()
        self.last_test_summary = "No speed test has been run in this session"
        self.colors = False
        self.screen.keypad(True)
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        self._init_colors()

    def _init_colors(self) -> None:
        self.colors = False
        self.theme = get_theme(self.settings.theme)
        if self.theme.monochrome or not curses.has_colors():
            return
        try:
            curses.start_color()
            try:
                curses.use_default_colors()
                background = -1
            except curses.error:
                background = curses.COLOR_BLACK
            names = {
                "black": curses.COLOR_BLACK,
                "red": curses.COLOR_RED,
                "green": curses.COLOR_GREEN,
                "yellow": curses.COLOR_YELLOW,
                "blue": curses.COLOR_BLUE,
                "magenta": curses.COLOR_MAGENTA,
                "cyan": curses.COLOR_CYAN,
                "white": curses.COLOR_WHITE,
            }
            if getattr(curses, "COLORS", 0) >= 256:
                palette = self.theme.xterm
            else:
                palette = tuple(names[color] for color in self.theme.standard)
            accent, success, warning, danger, muted, select_fg, select_bg, header_fg, header_bg = palette
            curses.init_pair(1, accent, background)
            curses.init_pair(2, success, background)
            curses.init_pair(3, warning, background)
            curses.init_pair(4, danger, background)
            curses.init_pair(5, muted, background)
            curses.init_pair(6, select_fg, select_bg)
            curses.init_pair(7, header_fg, header_bg)
            self.colors = True
        except curses.error:
            self.colors = False

    def _attr(self, pair: int, extra: int = 0) -> int:
        return (curses.color_pair(pair) if self.colors else 0) | extra

    def _safe_add(self, y: int, x: int, text: str, attr: int = 0) -> None:
        height, width = self.screen.getmaxyx()
        if 0 <= y < height and 0 <= x < width:
            try:
                self.screen.addnstr(y, x, text, max(0, width - x - 1), attr)
            except curses.error:
                pass

    def _safe_hline(self, y: int, x: int, length: int, attr: int = 0) -> None:
        if length <= 0:
            return
        try:
            self.screen.hline(y, x, curses.ACS_HLINE, length, attr)
        except curses.error:
            self._safe_add(y, x, "-" * length, attr)

    def _frame(self, title: str, subtitle: str = "", footer: str = "q Back") -> tuple[int, int]:
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        if height < MIN_HEIGHT or width < MIN_WIDTH:
            self._safe_add(1, 2, "MirrorMate needs a little more room", curses.A_BOLD)
            self._safe_add(
                3,
                2,
                f"Resize the terminal to at least {MIN_WIDTH}x{MIN_HEIGHT} (current: {width}x{height}).",
                self._attr(3),
            )
            self._safe_add(height - 2, 2, "q Quit", curses.A_DIM)
            return height, width

        brand_attr = self._attr(7, curses.A_BOLD) if self.colors else curses.A_BOLD | curses.A_REVERSE
        self._safe_add(0, 0, " " * (width - 1), brand_attr)
        self._safe_add(0, 2, "MIRRORMATE", brand_attr)
        version = f"v{__version__}  {self.theme.name.upper()}"
        self._safe_add(0, max(2, width - len(version) - 3), version, brand_attr)
        self._safe_add(1, 2, title, self._attr(1, curses.A_BOLD))
        if subtitle:
            start = min(width - 2, len(title) + 5)
            self._safe_add(1, start, subtitle, curses.A_DIM)
        self._safe_hline(2, 2, width - 5, self._attr(1, curses.A_DIM))
        self._safe_hline(height - 2, 2, width - 5, curses.A_DIM)
        self._safe_add(height - 1, 2, footer, curses.A_DIM)
        return height, width

    def menu(self, title: str, items: list[tuple[str, str]], subtitle: str = "") -> str | None:
        selected = 0
        offset = 0
        while True:
            height, width = self._frame(
                title,
                subtitle,
                "↑/↓ or j/k Move   Enter Select   q/Esc Back",
            )
            if height < MIN_HEIGHT or width < MIN_WIDTH:
                self.screen.refresh()
                if self.screen.getch() in (ord("q"), 27):
                    return None
                continue
            visible = max(1, height - 7)
            selected = min(selected, max(0, len(items) - 1))
            if selected < offset:
                offset = selected
            if selected >= offset + visible:
                offset = selected - visible + 1

            for row, (_, label) in enumerate(items[offset : offset + visible], start=4):
                index = offset + row - 4
                is_selected = index == selected
                marker = "›" if is_selected else " "
                line = f" {marker}  {label}"
                attr = self._attr(6, curses.A_BOLD) if is_selected else 0
                self._safe_add(row, 2, line.ljust(width - 5), attr)
            if not items:
                self._safe_add(4, 4, "Nothing to show here.", curses.A_DIM)
            elif len(items) > visible:
                self._safe_add(height - 3, width - 18, f"{selected + 1}/{len(items)}", curses.A_DIM)
            self.screen.refresh()
            key = self.screen.getch()
            if key in (ord("q"), 27, curses.KEY_BACKSPACE):
                return None
            if key in (curses.KEY_UP, ord("k")) and items:
                selected = (selected - 1) % len(items)
            elif key in (curses.KEY_DOWN, ord("j")) and items:
                selected = (selected + 1) % len(items)
            elif key == curses.KEY_HOME and items:
                selected = 0
            elif key == curses.KEY_END and items:
                selected = len(items) - 1
            elif key == curses.KEY_PPAGE and items:
                selected = max(0, selected - visible)
            elif key == curses.KEY_NPAGE and items:
                selected = min(len(items) - 1, selected + visible)
            elif key in (10, 13, curses.KEY_ENTER) and items:
                return items[selected][0]

    def message(self, title: str, text: str) -> None:
        offset = 0
        while True:
            height, width = self._frame(title, footer="↑/↓ Scroll   Enter/q Close")
            if height < MIN_HEIGHT or width < MIN_WIDTH:
                self.screen.refresh()
                if self.screen.getch() in (ord("q"), 27, 10, 13):
                    return
                continue
            lines: list[str] = []
            for original in text.splitlines() or [""]:
                lines.extend(
                    textwrap.wrap(
                        original,
                        width=max(20, width - 8),
                        replace_whitespace=False,
                        drop_whitespace=False,
                    )
                    or [""]
                )
            visible = max(1, height - 7)
            offset = min(offset, max(0, len(lines) - visible))
            for row, line in enumerate(lines[offset : offset + visible], start=4):
                self._safe_add(row, 4, line)
            if len(lines) > visible:
                self._safe_add(
                    height - 3,
                    width - 18,
                    f"{offset + 1}-{min(len(lines), offset + visible)}/{len(lines)}",
                    curses.A_DIM,
                )
            self.screen.refresh()
            key = self.screen.getch()
            if key in (ord("q"), 27, 10, 13, curses.KEY_ENTER):
                return
            if key in (curses.KEY_UP, ord("k")):
                offset = max(0, offset - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                offset = min(max(0, len(lines) - visible), offset + 1)
            elif key == curses.KEY_PPAGE:
                offset = max(0, offset - visible)
            elif key == curses.KEY_NPAGE:
                offset = min(max(0, len(lines) - visible), offset + visible)

    def confirm(self, title: str, text: str) -> bool:
        choice = self.menu(
            title,
            [("yes", f"Yes — {text}"), ("no", "No — go back")],
            "Confirmation required",
        )
        return choice == "yes"

    def prompt(self, title: str, label: str) -> str | None:
        value: list[str] = []
        try:
            curses.curs_set(1)
        except curses.error:
            pass
        try:
            while True:
                height, width = self._frame(title, footer="Enter Confirm   Esc Cancel   Backspace Delete")
                if height < MIN_HEIGHT or width < MIN_WIDTH:
                    self.screen.refresh()
                    if self.screen.getch() == 27:
                        return None
                    continue
                self._safe_add(4, 4, label, curses.A_BOLD)
                input_width = max(1, width - 10)
                shown = "".join(value)[-input_width:]
                self._safe_add(6, 4, " " * (width - 8), self._attr(5, curses.A_UNDERLINE))
                self._safe_add(6, 4, shown, self._attr(1, curses.A_BOLD | curses.A_UNDERLINE))
                try:
                    self.screen.move(6, min(width - 5, 4 + len(shown)))
                except curses.error:
                    pass
                self.screen.refresh()
                key = self.screen.get_wch()
                if key in ("\n", "\r", curses.KEY_ENTER):
                    result = "".join(value).strip()
                    return result or None
                if key == "\x1b" or key == 27:
                    return None
                if key in ("\b", "\x7f", curses.KEY_BACKSPACE):
                    if value:
                        value.pop()
                    continue
                if isinstance(key, str) and key.isprintable() and len(value) < 512:
                    value.append(key)
        finally:
            try:
                curses.curs_set(0)
            except curses.error:
                pass

    def _eligible(self, category: str) -> list[Mirror]:
        if category != "apt":
            return filter_mirrors(self.service.catalog, category)
        distro = self.service.distro()
        return filter_mirrors(self.service.catalog, "apt", distro.id, distro.architecture)

    def _ordered_mirrors(self, mirrors: list[Mirror]) -> list[Mirror]:
        if not self.settings.sort_by_speed:
            return list(mirrors)

        def key(mirror: Mirror) -> tuple[int, float, str]:
            result = self.results.get(mirror.id)
            if result is None:
                return 1, float("inf"), mirror.name.lower()
            if not result.healthy or result.median_ms is None:
                return 2, float("inf"), mirror.name.lower()
            return 0, result.median_ms, mirror.name.lower()

        return sorted(mirrors, key=key)

    def _fastest_id(self, mirrors: list[Mirror]) -> str | None:
        result = fastest_result(self.results[item.id] for item in mirrors if item.id in self.results)
        return result.mirror_id if result else None

    @staticmethod
    def _mirror_url(mirror: Mirror) -> str:
        return mirror.archive_url or mirror.url or ""

    def _result_attr(self, mirror_id: str, fastest_id: str | None) -> int:
        if mirror_id in self.testing:
            return self._attr(1)
        result = self.results.get(mirror_id)
        if result is None:
            return curses.A_DIM
        if not result.healthy:
            return self._attr(4)
        if mirror_id == fastest_id:
            return self._attr(2, curses.A_BOLD)
        if result.median_ms is not None and result.median_ms >= 700:
            return self._attr(3)
        return self._attr(2)

    def _draw_mirror_table(
        self,
        category: str,
        mirrors: list[Mirror],
        selected_id: str,
        *,
        progress: tuple[int, int, str] | None = None,
    ) -> list[Mirror]:
        title, description = CATEGORY_DETAILS[category]
        footer = "↑/↓ Move  Enter Menu  r Test all  p Test one  f Fastest  s Settings  q Back"
        height, width = self._frame(f"{title} MIRRORS", description, footer)
        ordered = self._ordered_mirrors(mirrors)
        if height < MIN_HEIGHT or width < MIN_WIDTH:
            self.screen.refresh()
            return ordered

        fastest_id = self._fastest_id(mirrors)
        selected_index = next((i for i, item in enumerate(ordered) if item.id == selected_id), 0)
        visible = max(1, height - 10)
        offset = max(0, min(selected_index - visible + 1, len(ordered) - visible))
        if selected_index < visible:
            offset = 0

        content_width = width - 5
        name_width = max(12, content_width - 37)
        heading = f" {'#':>2}  {'MIRROR':<{name_width}} {'SOURCE':<9} {'HEALTH':<10} {'LATENCY':>10}"
        self._safe_add(3, 2, heading, self._attr(5, curses.A_BOLD))
        self._safe_hline(4, 2, width - 5, curses.A_DIM)

        healthy = [
            result
            for result in (self.results.get(item.id) for item in mirrors)
            if result is not None and result.healthy and result.median_ms is not None
        ]
        ranks = {
            result.mirror_id: index + 1
            for index, result in enumerate(sorted(healthy, key=lambda item: item.median_ms or 0))
        }
        for row, mirror in enumerate(ordered[offset : offset + visible], start=5):
            result = self.results.get(mirror.id)
            rank = f"#{ranks[mirror.id]}" if mirror.id in ranks else "-"
            source = {"builtin": "OFFICIAL", "system": "SYSTEM", "user": "USER"}.get(
                mirror.source, mirror.source.upper()
            )
            if mirror.id in self.testing:
                health, latency = "TESTING...", "..."
            else:
                health = latency_quality(result, fastest=mirror.id == fastest_id)
                latency = f"{result.median_ms:.2f} ms" if result and result.median_ms is not None else "-"
            line = (
                f" {rank:>2}  {mirror.name[:name_width]:<{name_width}} "
                f"{source[:9]:<9} {health:<10} {latency:>10}"
            )
            selected = mirror.id == selected_id
            if selected:
                self._safe_add(row, 2, line.ljust(content_width), self._attr(6, curses.A_BOLD))
            else:
                self._safe_add(row, 2, line.ljust(content_width))
                health_x = 2 + 5 + name_width + 1 + 9 + 1
                latency_x = health_x + 11
                result_attr = self._result_attr(mirror.id, fastest_id)
                self._safe_add(row, health_x, f"{health:<10}", result_attr)
                self._safe_add(row, latency_x, f"{latency:>10}", result_attr)
                if mirror.id == fastest_id:
                    self._safe_add(row, 3, f"{rank:>2}", self._attr(2, curses.A_BOLD))

        selected = next((item for item in mirrors if item.id == selected_id), None)
        if selected:
            detail = self._mirror_url(selected)
            result = self.results.get(selected.id)
            if result and not result.healthy and result.error:
                detail += f"  |  {result.error}"
            self._safe_add(height - 4, 3, detail, curses.A_DIM)

        if progress:
            done, total, current = progress
            bar_width = min(20, max(8, width // 4))
            filled = round(bar_width * done / max(1, total))
            bar = "█" * filled + "░" * (bar_width - filled)
            meta = f"Speed test  [{bar}]  {done}/{total}  {current}"
            self._safe_add(height - 3, 3, meta, self._attr(1, curses.A_BOLD))
        else:
            auto = "ON" if self.settings.auto_benchmark else "OFF"
            meta = (
                f"Auto-test: {auto}  •  {self.settings.benchmark_attempts} attempts  •  "
                f"{self.settings.benchmark_timeout:g}s timeout  •  {self.last_test_summary}"
            )
            self._safe_add(height - 3, 3, meta, curses.A_DIM)
        self.screen.refresh()
        return ordered

    def _benchmark(self, category: str, mirrors: list[Mirror], selected_id: str) -> None:
        if not mirrors:
            return
        self.testing = {item.id for item in mirrors}
        self._draw_mirror_table(category, mirrors, selected_id, progress=(0, len(mirrors), "Starting"))
        codename = self.service.distro().codename if category == "apt" else None

        def update(result: BenchmarkResult, done: int, total: int) -> None:
            self.results[result.mirror_id] = result
            self.testing.discard(result.mirror_id)
            self._draw_mirror_table(
                category, mirrors, selected_id, progress=(done, total, result.name)
            )

        try:
            results = benchmark_mirrors(
                mirrors,
                codename=codename,
                attempts=self.settings.benchmark_attempts,
                timeout=self.settings.benchmark_timeout,
                progress=update,
            )
        finally:
            self.testing.clear()
        healthy = sum(result.healthy for result in results)
        self.last_test_summary = f"{healthy}/{len(results)} reachable"

    def _elevated(self, arguments: list[str]) -> tuple[bool, str]:
        sudo = shutil.which("sudo")
        if not sudo:
            return False, "sudo is not installed; rerun MirrorMate as root"
        executable = shutil.which("mirrormate")
        command = [executable] if executable else [sys.executable, "-m", "mirrormate"]
        try:
            curses.def_prog_mode()
        except curses.error:
            pass
        curses.endwin()
        process = subprocess.run([sudo, *command, *arguments], check=False, text=True)
        try:
            curses.reset_prog_mode()
            self.screen.keypad(True)
            curses.curs_set(0)
            self.screen.clear()
            self.screen.refresh()
        except curses.error:
            pass
        return process.returncode == 0, f"Command exited with status {process.returncode}"

    def _apply(self, mirror: Mirror) -> None:
        result = self.results.get(mirror.id)
        speed = f" ({result.median_ms:.2f} ms)" if result and result.healthy else ""
        if not self.confirm("Apply mirror", f"Apply {mirror.name}{speed}?"):
            return
        backup = self.confirm("Backup", "Create a persistent backup first?")
        allow_insecure = False
        if mirror.insecure:
            allow_insecure = self.confirm(
                "Insecure mirror", "Trust this non-TLS or custom-CA Docker registry?"
            )
            if not allow_insecure:
                return
        adapter = self.service.adapter(mirror.type)
        if adapter.requires_root and os.geteuid() != 0:
            args = ["set", mirror.type, "--mirror", mirror.id]
            if mirror.type == "apt" and mirror.distro:
                args.extend(["--distro", mirror.distro])
            if backup:
                args.append("--backup")
            if allow_insecure:
                args.append("--allow-insecure")
            success, detail = self._elevated(args)
            self.message("Apply result", "Mirror applied successfully." if success else detail)
            return
        applied = self.service.apply(
            mirror.type, mirror, backup=backup, allow_insecure=allow_insecure
        )
        text = applied["summary"]
        if applied.get("backup_id"):
            text += f"\nBackup: {applied['backup_id']}"
        for warning in applied.get("warnings", []):
            text += f"\nWarning: {warning}"
        self.message("Apply result", text)

    def category(self, category: str) -> None:
        mirrors = self._eligible(category)
        if not mirrors:
            self.message("No mirrors", f"No compatible {category} mirrors were found.")
            return
        selected_id = mirrors[0].id
        if self.settings.auto_benchmark:
            self._benchmark(category, mirrors, selected_id)

        while True:
            ordered = self._draw_mirror_table(category, mirrors, selected_id)
            height, width = self.screen.getmaxyx()
            key = self.screen.getch()
            if key in (ord("q"), 27, curses.KEY_BACKSPACE):
                return
            if height < MIN_HEIGHT or width < MIN_WIDTH:
                continue
            selected_index = next((i for i, item in enumerate(ordered) if item.id == selected_id), 0)
            if key in (curses.KEY_UP, ord("k")):
                selected_id = ordered[(selected_index - 1) % len(ordered)].id
            elif key in (curses.KEY_DOWN, ord("j")):
                selected_id = ordered[(selected_index + 1) % len(ordered)].id
            elif key == curses.KEY_HOME:
                selected_id = ordered[0].id
            elif key == curses.KEY_END:
                selected_id = ordered[-1].id
            elif key in (ord("r"), ord("R")):
                self._benchmark(category, mirrors, selected_id)
            elif key in (ord("p"), ord("P")):
                mirror = next(item for item in mirrors if item.id == selected_id)
                self._benchmark(category, [mirror], selected_id)
            elif key in (ord("s"), ord("S")):
                previous = self.settings.auto_benchmark
                self.settings_menu()
                if self.settings.auto_benchmark and not previous:
                    self._benchmark(category, mirrors, selected_id)
            elif key in (ord("f"), ord("F")):
                fastest_id = self._fastest_id(mirrors)
                if fastest_id is None:
                    self._benchmark(category, mirrors, selected_id)
                    fastest_id = self._fastest_id(mirrors)
                if fastest_id is None:
                    self.message("Speed test", "No reachable mirror was found; nothing was changed.")
                else:
                    selected_id = fastest_id
                    try:
                        self._apply(next(item for item in mirrors if item.id == fastest_id))
                    except MirrorMateError as exc:
                        self.message("Apply error", str(exc))
            elif key in (10, 13, curses.KEY_ENTER):
                mirror = next(item for item in mirrors if item.id == selected_id)
                action = self.menu(
                    mirror.name,
                    [
                        ("apply", "Apply this mirror"),
                        ("benchmark", "Run HTTP speed test for this mirror"),
                    ],
                    self._mirror_url(mirror),
                )
                try:
                    if action == "apply":
                        self._apply(mirror)
                    elif action == "benchmark":
                        self._benchmark(category, [mirror], selected_id)
                except MirrorMateError as exc:
                    self.message("Error", str(exc))

    @staticmethod
    def _next_value(current: object, values: tuple[object, ...]) -> object:
        try:
            index = values.index(current)
        except ValueError:
            return values[0]
        return values[(index + 1) % len(values)]

    def _save_settings(self) -> None:
        save_settings(self.settings, self.service.user)

    def settings_menu(self) -> None:
        while True:
            auto = "ENABLED" if self.settings.auto_benchmark else "DISABLED"
            sorting = "FASTEST FIRST" if self.settings.sort_by_speed else "CATALOG ORDER"
            theme = get_theme(self.settings.theme)
            choice = self.menu(
                "TUI SETTINGS",
                [
                    ("theme", f"Color theme                               {theme.name.upper()}"),
                    ("auto", f"Ping/speed test when mirror list opens    {auto}"),
                    ("attempts", f"Requests per mirror                     {self.settings.benchmark_attempts}"),
                    ("timeout", f"Timeout for each request                 {self.settings.benchmark_timeout:g} seconds"),
                    ("sort", f"Mirror list order                         {sorting}"),
                    ("reset", "Reset all TUI settings to safe defaults"),
                ],
                "Enter changes a value • settings are saved automatically",
            )
            if choice is None:
                return
            if choice == "theme":
                selected_theme = self.menu(
                    "COLOR THEME",
                    [
                        (theme_id, f"{THEMES[theme_id].name:<12} {THEMES[theme_id].description}")
                        for theme_id in THEME_ORDER
                    ],
                    f"Current: {theme.name} • theme is applied immediately",
                )
                if selected_theme is None:
                    continue
                self.settings = replace(self.settings, theme=selected_theme)
                self._init_colors()
            elif choice == "auto":
                self.settings = replace(
                    self.settings, auto_benchmark=not self.settings.auto_benchmark
                )
            elif choice == "attempts":
                self.settings = replace(
                    self.settings,
                    benchmark_attempts=int(
                        self._next_value(self.settings.benchmark_attempts, ALLOWED_ATTEMPTS)
                    ),
                )
            elif choice == "timeout":
                self.settings = replace(
                    self.settings,
                    benchmark_timeout=float(
                        self._next_value(self.settings.benchmark_timeout, ALLOWED_TIMEOUTS)
                    ),
                )
            elif choice == "sort":
                self.settings = replace(
                    self.settings, sort_by_speed=not self.settings.sort_by_speed
                )
            elif choice == "reset":
                if not self.confirm("Reset settings", "Restore the default TUI settings?"):
                    continue
                self.settings = TuiSettings()
                self._init_colors()
            self._save_settings()

    def catalog(self) -> None:
        while True:
            choice = self.menu(
                "CUSTOM CATALOG",
                [
                    ("add", "Add a mirror manually"),
                    ("import", "Import a JSON file or HTTPS URL"),
                    ("remove", "Remove a custom mirror"),
                ],
                "User catalog • built-in mirrors remain read-only",
            )
            if choice is None:
                return
            try:
                if choice == "import":
                    source = self.prompt("Import catalog", "Local path or HTTPS URL:")
                    if source:
                        imported = parse_catalog(fetch_catalog(source))
                        path = mutate_custom_catalog(imported, user=self.service.user)
                        self.service.catalog = load_catalogs(self.service.user)
                        self.message("Catalog imported", f"Imported {len(imported)} mirrors into {path}")
                elif choice == "add":
                    category = self.menu("Mirror type", [(item, item.upper()) for item in MIRROR_TYPES])
                    if not category:
                        continue
                    mirror_id = self.prompt("Add mirror", "Stable id (lowercase letters, digits, ._-):")
                    name = self.prompt("Add mirror", "Display name:") if mirror_id else None
                    if not mirror_id or not name:
                        continue
                    entry: dict[str, object] = {"id": mirror_id, "type": category, "name": name}
                    if category == "apt":
                        distro = self.menu("Distribution", [("ubuntu", "Ubuntu"), ("debian", "Debian")])
                        archive = self.prompt("Add APT mirror", "Archive URL:") if distro else None
                        security = self.prompt("Add APT mirror", "Security URL (blank keeps current):") if archive else None
                        entry.update(distro=distro, archive_url=archive, security_url=security)
                    else:
                        entry["url"] = self.prompt("Add mirror", "Mirror URL:")
                        if category == "docker" and str(entry["url"] or "").startswith("http://"):
                            entry["insecure"] = self.confirm(
                                "Insecure mirror", "Mark this HTTP Docker registry as insecure?"
                            )
                    mirror = normalize_entry(entry)
                    path = mutate_custom_catalog([mirror], user=self.service.user)
                    self.service.catalog = load_catalogs(self.service.user)
                    self.message("Mirror added", f"Saved {mirror.id} to {path}")
                elif choice == "remove":
                    custom = [item for item in self.service.catalog if item.source == "user"]
                    if not custom:
                        self.message("Remove mirror", "No custom user mirrors were found.")
                        continue
                    selected = self.menu("Remove mirror", [(item.id, item.name) for item in custom])
                    if selected and self.confirm("Remove mirror", f"Remove {selected}?"):
                        remove_custom_mirror(selected, user=self.service.user)
                        self.service.catalog = load_catalogs(self.service.user)
            except MirrorMateError as exc:
                self.message("Catalog error", str(exc))

    def backups(self) -> None:
        while True:
            snapshots = list_snapshots(self.service.user)
            items = [
                (str(item["id"]), f"{item['created_at']}  {item['category'].upper()}  {item['id']}")
                for item in snapshots
            ]
            if not items:
                self.message("Backups", "No backups found.")
                return
            selected = self.menu("BACKUPS", items, "Persistent configuration snapshots")
            if selected is None:
                return
            snapshot = next(item for item in snapshots if item["id"] == selected)
            if not self.confirm("Restore backup", f"Restore {selected}?"):
                continue
            try:
                if snapshot["category"] in {"apt", "docker"} and os.geteuid() != 0:
                    success, detail = self._elevated(["backups", "restore", selected])
                    self.message("Restore", "Backup restored." if success else detail)
                else:
                    result = self.service.restore(selected)
                    self.message("Restore", f"Restored {result['restored_files']} file(s).")
            except MirrorMateError as exc:
                self.message("Restore error", str(exc))

    def status(self) -> None:
        lines = []
        for category in MIRROR_TYPES:
            try:
                status = self.service.status(category)
                if "url" in status:
                    value = status["url"] or "default"
                elif category == "docker":
                    value = ", ".join(status["registry_mirrors"]) or "Docker Hub default"
                else:
                    urls = sorted({entry["url"] for entry in status.get("entries", [])})
                    value = ", ".join(urls) or "not detected"
                lines.append(f"{category.upper():<8} {value}")
            except MirrorMateError as exc:
                lines.append(f"{category.upper():<8} {exc}")
        self.message("CURRENT STATUS", "\n\n".join(lines))

    def run(self) -> int:
        while True:
            items = [
                (category, f"{label:<10} {description}")
                for category, (label, description) in CATEGORY_DETAILS.items()
            ]
            items.extend(
                [
                    ("status", "STATUS     Inspect active mirror configuration"),
                    ("catalog", "CATALOG    Add, import, or remove custom mirrors"),
                    ("backups", "BACKUPS    Restore a configuration snapshot"),
                    ("settings", "SETTINGS   Speed-test and display preferences"),
                ]
            )
            selected = self.menu(
                "MIRROR DASHBOARD", items, "Browse • test real endpoints • apply safely"
            )
            if selected is None:
                return 0
            try:
                if selected in MIRROR_TYPES:
                    self.category(selected)
                elif selected == "catalog":
                    self.catalog()
                elif selected == "backups":
                    self.backups()
                elif selected == "status":
                    self.status()
                elif selected == "settings":
                    self.settings_menu()
            except MirrorMateError as exc:
                self.message("Error", str(exc))


def run_tui(service: MirrorService) -> int:
    try:
        return curses.wrapper(lambda screen: Tui(screen, service).run())
    except curses.error as exc:
        print(f"mirrormate: cannot initialize TUI: {exc}", file=sys.stderr)
        return 4
