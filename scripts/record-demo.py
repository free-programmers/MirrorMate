#!/usr/bin/env python3
"""Record the real MirrorMate TUI into README-friendly media assets.

This development helper requires Pillow and pexpect. It runs MirrorMate with a
temporary user profile, so recording never changes the operator's settings.
"""

from __future__ import annotations

import codecs
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

try:
    import pexpect
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:  # pragma: no cover - development-only helper
    raise SystemExit("record-demo.py requires Pillow and pexpect") from exc


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
ROWS = 27
COLS = 100
FPS = 8
FONT_SIZE = 18
FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")
BOLD_FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf")


def xterm_color(index: int) -> tuple[int, int, int]:
    base = (
        (0, 0, 0),
        (205, 49, 49),
        (13, 188, 121),
        (229, 229, 16),
        (36, 114, 200),
        (188, 63, 188),
        (17, 168, 205),
        (229, 229, 229),
        (102, 102, 102),
        (241, 76, 76),
        (35, 209, 139),
        (245, 245, 67),
        (59, 142, 234),
        (214, 112, 214),
        (41, 184, 219),
        (255, 255, 255),
    )
    if index < 16:
        return base[index]
    if index < 232:
        value = index - 16
        levels = (0, 95, 135, 175, 215, 255)
        return levels[value // 36], levels[(value // 6) % 6], levels[value % 6]
    shade = 8 + (index - 232) * 10
    return shade, shade, shade


@dataclass(frozen=True, slots=True)
class Style:
    fg: int | None = None
    bg: int | None = None
    bold: bool = False
    dim: bool = False
    reverse: bool = False


@dataclass(slots=True)
class Cell:
    char: str = " "
    style: Style = Style()


class Terminal:
    GRAPHICS = {
        "j": "┘",
        "k": "┐",
        "l": "┌",
        "m": "└",
        "n": "┼",
        "q": "─",
        "t": "├",
        "u": "┤",
        "v": "┴",
        "w": "┬",
        "x": "│",
    }

    def __init__(self, rows: int, columns: int) -> None:
        self.rows = rows
        self.columns = columns
        self.cells = [[Cell() for _ in range(columns)] for _ in range(rows)]
        self.row = 0
        self.column = 0
        self.saved = (0, 0)
        self.style = Style()
        self.graphics = False
        self.scroll_top = 0
        self.scroll_bottom = rows - 1
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.pending = ""

    def clear(self) -> None:
        self.cells = [[Cell() for _ in range(self.columns)] for _ in range(self.rows)]

    def _blank(self) -> Cell:
        return Cell(" ", self.style)

    def _scroll(self) -> None:
        del self.cells[self.scroll_top]
        self.cells.insert(self.scroll_bottom, [Cell() for _ in range(self.columns)])
        self.row = self.scroll_bottom

    def _linefeed(self) -> None:
        if self.row == self.scroll_bottom:
            self._scroll()
        else:
            self.row = min(self.rows - 1, self.row + 1)

    @staticmethod
    def _width(character: str) -> int:
        if unicodedata.combining(character):
            return 0
        return 2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1

    def _put(self, character: str) -> None:
        if self.graphics:
            character = self.GRAPHICS.get(character, character)
        width = self._width(character)
        if width == 0:
            if self.column:
                self.cells[self.row][self.column - 1].char += character
            return
        if self.column >= self.columns:
            self.column = 0
            self._linefeed()
        self.cells[self.row][self.column] = Cell(character, self.style)
        if width == 2 and self.column + 1 < self.columns:
            self.cells[self.row][self.column + 1] = Cell("", self.style)
        self.column += width

    @staticmethod
    def _parameters(raw: str) -> list[int]:
        raw = raw.lstrip("?>!")
        if not raw:
            return [0]
        values = []
        for item in raw.split(";"):
            try:
                values.append(int(item or "0"))
            except ValueError:
                values.append(0)
        return values

    def _erase_display(self, mode: int) -> None:
        if mode in (2, 3):
            self.clear()
        elif mode == 0:
            self._erase_line(0)
            for row in range(self.row + 1, self.rows):
                self.cells[row] = [Cell() for _ in range(self.columns)]
        elif mode == 1:
            self._erase_line(1)
            for row in range(self.row):
                self.cells[row] = [Cell() for _ in range(self.columns)]

    def _erase_line(self, mode: int) -> None:
        if mode == 0:
            start, end = self.column, self.columns
        elif mode == 1:
            start, end = 0, self.column + 1
        else:
            start, end = 0, self.columns
        for column in range(start, end):
            self.cells[self.row][column] = self._blank()

    def _sgr(self, parameters: list[int]) -> None:
        if not parameters:
            parameters = [0]
        fg, bg = self.style.fg, self.style.bg
        bold, dim, reverse = self.style.bold, self.style.dim, self.style.reverse
        index = 0
        while index < len(parameters):
            value = parameters[index]
            if value == 0:
                fg = bg = None
                bold = dim = reverse = False
            elif value == 1:
                bold = True
            elif value == 2:
                dim = True
            elif value == 7:
                reverse = True
            elif value == 22:
                bold = dim = False
            elif value == 27:
                reverse = False
            elif 30 <= value <= 37:
                fg = value - 30
            elif value == 39:
                fg = None
            elif 40 <= value <= 47:
                bg = value - 40
            elif value == 49:
                bg = None
            elif 90 <= value <= 97:
                fg = value - 90 + 8
            elif 100 <= value <= 107:
                bg = value - 100 + 8
            elif value in (38, 48) and index + 2 < len(parameters) and parameters[index + 1] == 5:
                if value == 38:
                    fg = parameters[index + 2]
                else:
                    bg = parameters[index + 2]
                index += 2
            index += 1
        self.style = Style(fg, bg, bold, dim, reverse)

    def _csi(self, parameters: str, command: str) -> None:
        values = self._parameters(parameters)
        first = values[0] if values else 0
        if command in ("H", "f"):
            row = (values[0] if values and values[0] else 1) - 1
            column = (values[1] if len(values) > 1 and values[1] else 1) - 1
            self.row = max(0, min(self.rows - 1, row))
            self.column = max(0, min(self.columns - 1, column))
        elif command == "A":
            self.row = max(0, self.row - (first or 1))
        elif command == "B":
            self.row = min(self.rows - 1, self.row + (first or 1))
        elif command == "C":
            self.column = min(self.columns - 1, self.column + (first or 1))
        elif command == "D":
            self.column = max(0, self.column - (first or 1))
        elif command == "G":
            self.column = max(0, min(self.columns - 1, (first or 1) - 1))
        elif command == "d":
            self.row = max(0, min(self.rows - 1, (first or 1) - 1))
        elif command == "J":
            self._erase_display(first)
        elif command == "K":
            self._erase_line(first)
        elif command == "X":
            count = first or 1
            end = min(self.columns, self.column + count)
            for column in range(self.column, end):
                self.cells[self.row][column] = self._blank()
        elif command == "m":
            self._sgr(values)
        elif command == "r":
            top = (values[0] if values and values[0] else 1) - 1
            bottom = (values[1] if len(values) > 1 and values[1] else self.rows) - 1
            self.scroll_top = max(0, min(self.rows - 1, top))
            self.scroll_bottom = max(self.scroll_top, min(self.rows - 1, bottom))
        elif command == "s":
            self.saved = self.row, self.column
        elif command == "u":
            self.row, self.column = self.saved

    def feed(self, data: bytes) -> None:
        text = self.pending + self.decoder.decode(data)
        self.pending = ""
        index = 0
        while index < len(text):
            character = text[index]
            if character == "\x1b":
                if index + 1 >= len(text):
                    self.pending = text[index:]
                    break
                following = text[index + 1]
                if following == "[":
                    match = re.match(r"\x1b\[([0-9;:?>!]*)[ -/]*([@-~])", text[index:])
                    if match:
                        self._csi(match.group(1).replace(":", ";"), match.group(2))
                        index += len(match.group(0))
                        continue
                    self.pending = text[index:]
                    break
                elif following in "()" and index + 2 < len(text):
                    self.graphics = text[index + 2] == "0"
                    index += 3
                    continue
                elif following in "()":
                    self.pending = text[index:]
                    break
                elif following == "]":
                    end_bell = text.find("\x07", index + 2)
                    end_st = text.find("\x1b\\", index + 2)
                    ends = [item for item in (end_bell, end_st) if item >= 0]
                    if ends:
                        end = min(ends)
                        index = end + (2 if text[end : end + 2] == "\x1b\\" else 1)
                        continue
                    self.pending = text[index:]
                    break
                elif following == "7":
                    self.saved = self.row, self.column
                elif following == "8":
                    self.row, self.column = self.saved
                index += 2
                continue
            if character == "\r":
                self.column = 0
            elif character in ("\n", "\v", "\f"):
                self._linefeed()
            elif character == "\b":
                self.column = max(0, self.column - 1)
            elif character == "\t":
                self.column = min(self.columns - 1, ((self.column // 8) + 1) * 8)
            elif ord(character) >= 32 and character != "\x7f":
                self._put(character)
            index += 1

    def text(self) -> str:
        return "\n".join("".join(cell.char for cell in row) for row in self.cells)


class Renderer:
    def __init__(self, terminal: Terminal) -> None:
        self.terminal = terminal
        self.font = ImageFont.truetype(str(FONT_PATH), FONT_SIZE)
        self.bold_font = ImageFont.truetype(str(BOLD_FONT_PATH), FONT_SIZE)
        self.cell_width = round(self.font.getlength("M"))
        self.cell_height = FONT_SIZE + 5
        self.margin = 24
        self.chrome = 42
        self.default_fg = (216, 222, 233)
        self.default_bg = (9, 13, 24)
        self.frame_bg = (4, 7, 15)

    def render(self) -> Image.Image:
        terminal_width = self.terminal.columns * self.cell_width
        terminal_height = self.terminal.rows * self.cell_height
        size = (terminal_width + self.margin * 2, terminal_height + self.chrome + self.margin)
        image = Image.new("RGB", size, self.frame_bg)
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (8, 8, size[0] - 9, size[1] - 9),
            radius=14,
            fill=(13, 18, 30),
            outline=(45, 55, 75),
            width=1,
        )
        for position, color in zip((24, 44, 64), ((255, 95, 86), (255, 189, 46), (39, 201, 63))):
            draw.ellipse((position, 22, position + 11, 33), fill=color)
        title = "MirrorMate — interactive terminal"
        draw.text((size[0] // 2, 27), title, fill=(145, 156, 176), font=self.font, anchor="mm")
        origin_x, origin_y = self.margin, self.chrome
        draw.rectangle(
            (origin_x, origin_y, origin_x + terminal_width, origin_y + terminal_height),
            fill=self.default_bg,
        )

        for row, cells in enumerate(self.terminal.cells):
            for column, cell in enumerate(cells):
                if cell.char == "":
                    continue
                style = cell.style
                fg = self.default_fg if style.fg is None else xterm_color(style.fg)
                bg = self.default_bg if style.bg is None else xterm_color(style.bg)
                if style.reverse:
                    fg, bg = bg, fg
                if style.dim:
                    fg = tuple(round(value * 0.62) for value in fg)
                x = origin_x + column * self.cell_width
                y = origin_y + row * self.cell_height
                if bg != self.default_bg:
                    draw.rectangle((x, y, x + self.cell_width, y + self.cell_height), fill=bg)
                if cell.char != " ":
                    draw.text(
                        (x, y + 1),
                        cell.char,
                        fill=fg,
                        font=self.bold_font if style.bold else self.font,
                    )
        return image


class Recorder:
    def __init__(self, child: pexpect.spawn, terminal: Terminal, renderer: Renderer) -> None:
        self.child = child
        self.terminal = terminal
        self.renderer = renderer
        self.frames: list[Image.Image] = []
        self.durations: list[int] = []
        self.last_digest: bytes | None = None

    def _snapshot(self, milliseconds: int) -> Image.Image:
        image = self.renderer.render()
        digest = hashlib.blake2b(image.tobytes(), digest_size=16).digest()
        if digest == self.last_digest and self.frames:
            self.durations[-1] += milliseconds
        else:
            self.frames.append(image)
            self.durations.append(milliseconds)
            self.last_digest = digest
        return image

    def capture(self, seconds: float) -> Image.Image:
        interval = 1 / FPS
        deadline = time.monotonic() + seconds
        latest = self.renderer.render()
        while time.monotonic() < deadline:
            started = time.monotonic()
            try:
                data = self.child.read_nonblocking(65536, timeout=interval)
            except pexpect.TIMEOUT:
                data = ""
            except pexpect.EOF:
                data = ""
            if data:
                self.terminal.feed(data.encode("utf-8", "replace"))
            latest = self._snapshot(round(interval * 1000))
            remaining = interval - (time.monotonic() - started)
            if remaining > 0:
                time.sleep(remaining)
        return latest

    def send(self, keys: str, pause: float = 0.35) -> Image.Image:
        self.child.send(keys)
        return self.capture(pause)

    def capture_until(self, text: str, timeout: float) -> Image.Image:
        deadline = time.monotonic() + timeout
        latest = self.renderer.render()
        while text not in self.terminal.text():
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Timed out waiting for terminal text: {text!r}")
            latest = self.capture(0.25)
        return latest

    def reset_frames(self) -> None:
        self.frames.clear()
        self.durations.clear()
        self.last_digest = None

    def save_gif(self, path: Path) -> None:
        if not self.frames:
            raise RuntimeError("No terminal frames were captured")
        frames = [frame.quantize(colors=128, method=Image.Quantize.MEDIANCUT) for frame in self.frames]
        frames[0].save(
            path,
            save_all=True,
            append_images=frames[1:],
            duration=self.durations,
            loop=0,
            optimize=True,
            disposal=1,
        )


def prepare_demo_profile(home: Path) -> None:
    sys.path.insert(0, str(ROOT / "src"))
    from mirrormate.catalog import mutate_custom_catalog, parse_catalog
    from mirrormate.platform import UserContext
    from mirrormate.settings import TuiSettings, save_settings

    user = UserContext("demo", os.getuid(), os.getgid(), home)
    legacy = json.loads((ROOT / "mirros/mirrors.json").read_text(encoding="utf-8"))
    mirrors = [mirror for mirror in parse_catalog(legacy) if mirror.type == "python"][:5]
    mutate_custom_catalog(mirrors, user=user)
    save_settings(TuiSettings(False, 1, 2.0, True, "ocean"), user)


def child_command(home: Path) -> str:
    return (
        "import os; from pathlib import Path; "
        "from mirrormate.catalog import load_catalogs; "
        "from mirrormate.models import DistroInfo; "
        "from mirrormate.platform import UserContext; "
        "from mirrormate.service import MirrorService; "
        "from mirrormate.tui import run_tui; "
        f"u=UserContext('demo',os.getuid(),os.getgid(),Path({str(home)!r})); "
        "s=MirrorService(catalog=load_catalogs(u),user=u,"
        "distro=DistroInfo('ubuntu','24.04','noble','amd64')); "
        "raise SystemExit(run_tui(s))"
    )


def make_video(gif: Path, destination: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("ffmpeg was not found; skipping demo.mp4", file=sys.stderr)
        return
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(gif),
            "-vf",
            "fps=12,scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-movflags",
            "+faststart",
            "-pix_fmt",
            "yuv420p",
            str(destination),
        ],
        check=True,
    )


def capture_settings_views(recorder: Recorder) -> None:
    for _ in range(8):
        recorder.send("j", 0.08)
    recorder.send("\r", 0.8)
    recorder.capture(0.8).save(DOCS / "tui-settings.png", optimize=True)

    recorder.send("\r", 0.8)
    recorder.capture(1.0).save(DOCS / "tui-themes.png", optimize=True)

    recorder.send("j", 0.18)
    recorder.send("\r", 1.0)
    recorder.capture(0.8).save(DOCS / "tui-theme-forest.png", optimize=True)

    recorder.send("\r", 0.6)
    for _ in range(3):
        recorder.send("j", 0.18)
    recorder.send("\r", 1.2)
    recorder.capture(0.8).save(DOCS / "tui-theme-violet.png", optimize=True)


def main() -> int:
    if not FONT_PATH.exists() or not BOLD_FONT_PATH.exists():
        raise SystemExit("DejaVu Sans Mono is required to render the demo")
    DOCS.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mirrormate-demo-") as temporary:
        home = Path(temporary) / "home"
        home.mkdir()
        prepare_demo_profile(home)
        environment = os.environ.copy()
        environment.update(
            TERM="xterm-256color",
            LANG="C.UTF-8",
            LC_ALL="C.UTF-8",
            PYTHONPATH=str(ROOT / "src"),
        )
        child = pexpect.spawn(
            sys.executable,
            ["-c", child_command(home)],
            cwd=str(ROOT),
            env=environment,
            encoding="utf-8",
            codec_errors="replace",
            dimensions=(ROWS, COLS),
            timeout=1,
        )
        terminal = Terminal(ROWS, COLS)
        recorder = Recorder(child, terminal, Renderer(terminal))

        recorder.capture_until("MIRROR DASHBOARD", 5.0)
        recorder.capture(0.6)
        if "--themes-only" in sys.argv[1:]:
            recorder.reset_frames()
            capture_settings_views(recorder)
            recorder.send("q", 0.3)
            recorder.send("q", 0.3)
            child.close(force=True)
            print(f"Wrote {DOCS / 'tui-settings.png'}")
            print(f"Wrote {DOCS / 'tui-themes.png'}")
            print(f"Wrote {DOCS / 'tui-theme-forest.png'}")
            print(f"Wrote {DOCS / 'tui-theme-violet.png'}")
            return 0
        recorder.reset_frames()
        dashboard = recorder.capture(1.4)
        dashboard.save(DOCS / "tui-dashboard.png", optimize=True)

        recorder.send("j", 0.35)
        recorder.send("\r", 1.0)
        recorder.send("r", 0.4)
        recorder.capture_until("reachable", 35.0)
        speed_test = recorder.capture(1.2)
        speed_test.save(DOCS / "tui-speed-test.png", optimize=True)

        recorder.send("q", 0.5)
        capture_settings_views(recorder)

        recorder.send("q", 0.3)
        recorder.send("q", 0.3)
        try:
            child.expect(pexpect.EOF, timeout=2)
        except (pexpect.TIMEOUT, pexpect.EOF):
            child.close(force=True)

        gif = DOCS / "demo.gif"
        recorder.save_gif(gif)
        make_video(gif, DOCS / "demo.mp4")

    print(f"Wrote {DOCS / 'demo.gif'}")
    print(f"Wrote {DOCS / 'demo.mp4'}")
    print(f"Wrote {DOCS / 'tui-dashboard.png'}")
    print(f"Wrote {DOCS / 'tui-speed-test.png'}")
    print(f"Wrote {DOCS / 'tui-settings.png'}")
    print(f"Wrote {DOCS / 'tui-themes.png'}")
    print(f"Wrote {DOCS / 'tui-theme-forest.png'}")
    print(f"Wrote {DOCS / 'tui-theme-violet.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
