from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Theme:
    id: str
    name: str
    description: str
    standard: tuple[str, str, str, str, str, str, str, str, str]
    xterm: tuple[int, int, int, int, int, int, int, int, int]
    monochrome: bool = False


THEMES = {
    "ocean": Theme(
        "ocean",
        "Ocean",
        "Cyan accents with a deep-blue header",
        ("cyan", "green", "yellow", "red", "white", "black", "cyan", "white", "blue"),
        (45, 84, 220, 203, 250, 16, 45, 231, 24),
    ),
    "forest": Theme(
        "forest",
        "Forest",
        "Fresh greens with a dark-forest header",
        ("green", "cyan", "yellow", "red", "white", "black", "green", "white", "green"),
        (78, 51, 220, 203, 250, 16, 78, 231, 22),
    ),
    "amber": Theme(
        "amber",
        "Amber",
        "Warm gold accents with an amber header",
        ("yellow", "green", "cyan", "red", "white", "black", "yellow", "black", "yellow"),
        (214, 84, 51, 203, 250, 16, 214, 16, 94),
    ),
    "violet": Theme(
        "violet",
        "Violet",
        "Purple accents with a deep-violet header",
        ("magenta", "green", "yellow", "red", "white", "black", "magenta", "white", "magenta"),
        (141, 84, 220, 203, 250, 16, 141, 231, 55),
    ),
    "monochrome": Theme(
        "monochrome",
        "Monochrome",
        "Uses the terminal's native foreground color",
        ("white", "white", "white", "white", "white", "black", "white", "white", "black"),
        (15, 15, 15, 15, 15, 0, 15, 15, 0),
        monochrome=True,
    ),
}
THEME_ORDER = tuple(THEMES)
DEFAULT_THEME = "ocean"


def get_theme(theme_id: str) -> Theme:
    return THEMES.get(theme_id, THEMES[DEFAULT_THEME])
