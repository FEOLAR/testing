import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from whitehole_setup import theme  # noqa: E402

PKG = Path(__file__).resolve().parents[1] / "whitehole_setup"


def test_text_contrast_aa():
    for bg in (theme.BG, theme.PANEL, theme.RAISED, theme.LOG_BG):
        assert theme.contrast(theme.TEXT, bg) >= 7
        assert theme.contrast(theme.MUTED, bg) >= 4.5
        for status in (theme.SUCCESS, theme.WARN, theme.DANGER, theme.ACCENT):
            assert theme.contrast(status, bg) >= 4.5
    for fill in (theme.ACCENT, theme.ACCENT_HOVER, theme.ACCENT_PRESSED):
        assert theme.contrast(theme.ACCENT_TEXT, fill) >= 4.5


def test_palette_matches_spec():
    assert (theme.BG, theme.PANEL, theme.RAISED, theme.BORDER) == ("#111418", "#1a1f26", "#222832", "#2a313b")
    assert (theme.TEXT, theme.MUTED, theme.ACCENT) == ("#e8edf3", "#9aa5b4", "#38bdf8")
    assert (theme.ACCENT_HOVER, theme.ACCENT_PRESSED, theme.ACCENT_TEXT) == ("#7dd3fc", "#0ea5e9", "#0b1220")
    assert (theme.DISABLED_BG, theme.DISABLED_TEXT, theme.LOG_BG) == ("#3a424d", "#6b7684", "#0d1014")


def test_no_hex_colors_outside_theme():
    for f in PKG.glob("*.py"):
        if f.name == "theme.py":
            continue
        assert not re.search(r"#[0-9a-fA-F]{6}\b", f.read_text(encoding="utf-8")), f.name
