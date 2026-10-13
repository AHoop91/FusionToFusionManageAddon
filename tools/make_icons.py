"""Writes the ribbon icons as SVG (Fusion draws a vector icon sharp at any size and screen scaling, which a PNG is not).

Each icon folder under ``resources`` gets ``16x16.svg`` (toolbars and menus) and ``32x32.svg`` (the ribbon). The 16 pixel one is
simpler: heavier lines, and no small print that would only blur. Run:  python tools/make_icons.py
"""

import math
import os

RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources")

PAGE, PAGE_LINE, TEXT_LINE = "#EEF0F3", "#A9AFBA", "#9AA1AD"
DESIGN, DESIGN_LIGHT = "#2F8FE0", "#9ACDF6"
BADGE = "#0B73D1"
SEARCH, ARROW = "search", "arrow"


def svg(size, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 64 64">\n{body}</svg>\n')


def stroke(d, colour, width):
    return f'  <path d="{d}" fill="none" stroke="{colour}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"/>\n'


def page(small, folded=False):
    """The page: rounded, or with a turned corner (an exported file)."""
    line = 3.4 if small else 2.4
    if folded:
        outline = "M12 3 H38 L52 17 V54 Q52 59 47 59 H12 Q7 59 7 54 V8 Q7 3 12 3 Z"
        return (f'  <path d="{outline}" fill="{PAGE}" stroke="{PAGE_LINE}" stroke-width="{line}" stroke-linejoin="round"/>\n'
                + stroke("M38 3 V12 Q38 17 43 17 H52", PAGE_LINE, line))
    return f'  <rect x="7" y="3" width="42" height="54" rx="5" fill="{PAGE}" stroke="{PAGE_LINE}" stroke-width="{line}"/>\n'


def badge(kind, small):
    """A blue disc with a white ring (so it stands off the page and off a dark ribbon), holding a white search or arrow up."""
    width = 4.6 if small else 3.8
    out = f'  <circle cx="46" cy="44" r="17" fill="#fff"/>\n  <circle cx="46" cy="44" r="14.5" fill="{BADGE}"/>\n'
    if kind == SEARCH:
        out += f'  <circle cx="44.5" cy="42.5" r="5.6" fill="none" stroke="#fff" stroke-width="{width}"/>\n'
        out += stroke("M49 47 L53.5 51.5", "#fff", width)
    else:
        out += stroke("M46 53 V37.5 M39 44.5 L46 37.5 L53 44.5", "#fff", width)
    return out


def design_on_page(small):
    out = f'  <rect x="14" y="10" width="28" height="22" rx="3" fill="{DESIGN}"/>\n'
    out += f'  <rect x="19" y="15" width="12" height="12" rx="2" fill="{DESIGN_LIGHT}"/>\n'
    if not small:
        out += stroke("M14 39 H38 M14 46 H30", TEXT_LINE, 3.4)
    return out


def item_icon(kind):
    return lambda size: svg(size, page(size == 16) + design_on_page(size == 16) + badge(kind, size == 16))


# ---- Letters, as strokes on a 5 x 6 box, so they do not depend on a font being there ----

LETTERS = {
    "S": "M5 1 Q4.5 0 2.5 0 Q0 0 0 1.5 Q0 2.9 2.5 3 Q5 3.1 5 4.5 Q5 6 2.5 6 Q0.5 6 0 5",
    "T": "M0 0 H5 M2.5 0 V6",
    "E": "M5 0 H0 V6 H5 M0 3 H4",
    "P": "M0 6 V0 H3 Q5 0 5 1.75 Q5 3.5 3 3.5 H0",
    "D": "M0 0 H2.5 Q5 0 5 3 Q5 6 2.5 6 H0 Z",
    "F": "M5 0 H0 V6 M0 3 H4",
}


def label(word, colour, small):
    """A coloured label across the page, with ``word`` on it (a plain bar at the small size)."""
    out = f'  <rect x="10" y="14" width="34" height="14" rx="2.5" fill="{colour}"/>\n'
    if small:
        return out
    step = 8
    x = 27 - (len(word) * step - 3) / 2
    for letter in word:
        out += f'  <g transform="translate({x:.1f} 18)">\n  {stroke(LETTERS[letter], "#fff", 1.7)}  </g>\n'
        x += step
    return out


def export_icon(word, colour):
    def make(size):
        small = size == 16
        body = page(small, folded=True) + label(word, colour, small)
        if not small:
            body += stroke("M14 36 H34 M14 43 H26", TEXT_LINE, 3.4)
        return svg(size, body + badge(ARROW, small))
    return make


# ---- The gear, and the clock of the job queue ----

def gear(size):
    teeth, outer, root, hole = 8, 28.0, 21.5, 9.0
    points = []
    for tooth in range(teeth):
        centre = 2 * math.pi * tooth / teeth
        for offset, radius in ((-0.30, root), (-0.17, outer), (0.17, outer), (0.30, root)):
            angle = centre + offset
            points.append((32 + radius * math.sin(angle), 32 - radius * math.cos(angle)))
    d = "M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in points) + f" Z M{32 + hole} 32 A{hole} {hole} 0 1 0 {32 - hole} 32 A{hole} {hole} 0 1 0 {32 + hole} 32 Z"
    return svg(size, f'  <path d="{d}" fill="#E6E8EB" fill-rule="evenodd" stroke="#8A919C" stroke-width="1.5" stroke-linejoin="round"/>\n')


def clock(dot=None):
    def make(size):
        width = 7 if size == 16 else 5.5
        body = f'  <circle cx="30" cy="30" r="24" fill="none" stroke="#1F78D1" stroke-width="{width}"/>\n'
        body += stroke("M30 16 V31 L40 37", "#1F78D1", width - 1)
        if dot:
            body += f'  <circle cx="49" cy="49" r="13" fill="#fff"/>\n  <circle cx="49" cy="49" r="10" fill="{dot}"/>\n'
        return svg(size, body)
    return make


ICONS = {
    "item": item_icon(SEARCH),
    "publish": item_icon(ARROW),
    "upload_step": export_icon("STEP", "#D6204D"),
    "upload_drawing": export_icon("PDF", "#E5383B"),
    "settings": gear,
    "jobs": clock(),
    "jobs_running": clock("#2EB85C"),
    "jobs_error": clock("#E5383B"),
}

for folder, make in ICONS.items():
    target = os.path.join(RESOURCES, folder)
    os.makedirs(target, exist_ok=True)
    for size in (16, 32):
        with open(os.path.join(target, f"{size}x{size}.svg"), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(make(size))
print("Icons written under", RESOURCES)
