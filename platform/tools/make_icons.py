"""Generate the IME's tray/engine icons in platform/server_ime/icons/.

The glyphs are converted to outlines (no <text>), so the icons look the same on
systems without a CJK font. Re-run after changing the design:

    python3 platform/tools/make_icons.py
"""
from pathlib import Path
import re

import cairo
import gi
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo

OUT = Path(__file__).resolve().parents[1] / "server_ime" / "icons"
SIZE = 64
FONT = "Noto Sans CJK SC Bold"

# name: (glyph, background, foreground)
ICONS = {
    "server-ime": ("拼", "#1a73e8", "#ffffff"),     # the engine itself
    "server-ime-zh": ("中", "#1a73e8", "#ffffff"),  # Chinese mode
    "server-ime-en": ("英", "#5f6368", "#ffffff"),  # English / direct input
}


def glyph_path(glyph):
    """Return the glyph's outline as SVG path data, centred in a SIZE box."""
    surface = cairo.RecordingSurface(cairo.CONTENT_COLOR_ALPHA, None)
    cr = cairo.Context(surface)
    layout = PangoCairo.create_layout(cr)
    desc = Pango.FontDescription.from_string(FONT)
    desc.set_absolute_size(SIZE * 0.80 * Pango.SCALE)
    layout.set_font_description(desc)
    layout.set_text(glyph, -1)
    ink, _ = layout.get_pixel_extents()
    cr.move_to((SIZE - ink.width) / 2 - ink.x, (SIZE - ink.height) / 2 - ink.y)
    PangoCairo.layout_path(cr, layout)
    parts = []
    for kind, pts in cr.copy_path():
        if kind == cairo.PATH_MOVE_TO:
            parts.append("M%.2f %.2f" % pts)
        elif kind == cairo.PATH_LINE_TO:
            parts.append("L%.2f %.2f" % pts)
        elif kind == cairo.PATH_CURVE_TO:
            parts.append("C%.2f %.2f %.2f %.2f %.2f %.2f" % pts)
        elif kind == cairo.PATH_CLOSE_PATH:
            parts.append("Z")
    return "".join(parts)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (glyph, bg, fg) in ICONS.items():
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 {s} {s}">'
            '<rect x="2" y="2" width="60" height="60" rx="13" fill="{bg}"/>'
            '<path fill="{fg}" d="{d}"/></svg>\n'
        ).format(s=SIZE, bg=bg, fg=fg, d=glyph_path(glyph))
        assert "<text" not in svg and re.search(r"[MLC]", svg)
        (OUT / (name + ".svg")).write_text(svg)
        print(OUT / (name + ".svg"))


if __name__ == "__main__":
    main()
