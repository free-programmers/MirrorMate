import unittest

from mirrormate.themes import DEFAULT_THEME, THEMES, THEME_ORDER, get_theme


class ThemeTests(unittest.TestCase):
    def test_default_themes_have_complete_color_palettes(self):
        self.assertEqual(
            THEME_ORDER,
            ("ocean", "forest", "amber", "violet", "monochrome"),
        )
        for theme in THEMES.values():
            self.assertEqual(len(theme.standard), 9)
            self.assertEqual(len(theme.xterm), 9)

    def test_unknown_theme_falls_back_to_default(self):
        self.assertEqual(get_theme("unknown"), THEMES[DEFAULT_THEME])


if __name__ == "__main__":
    unittest.main()
