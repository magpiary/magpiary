"""The picture behind the icons in the Magpiary disk image: a clear first step (drag to Applications) and the steps for the one
thing every unsigned Mac app needs, macOS's "Open Anyway". Run by build-dmg.sh: dmg-backdrop.py <out.tiff> <brand icons folder>.

The window is 760 x 528 points (Finder's title bar and optional path bar cover about 60 of them, so the content stays in the top 440); the file holds a 1x and a 2x picture (Finder reads a plain 1520 px PNG as a window twice the size).
It is light, because Finder draws icon names in dark text over any backdrop."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, S = 760, 528, 2          # points, and the scale it is drawn at
OUT = Path(sys.argv[1])
ICONS = Path(sys.argv[2]) if len(sys.argv) > 2 else None
INK, MUTED, FAINT = (27, 27, 32), (104, 102, 110), (150, 148, 154)
PINK, GOLD = (255, 46, 147), (255, 196, 92)
FONT = "/System/Library/Fonts/Avenir Next.ttc"


def font(size: float, weight: str = "regular") -> ImageFont.FreeTypeFont:
    index = {"bold": 0, "demi": 2, "medium": 5, "regular": 7, "heavy": 8}[weight]
    try:
        return ImageFont.truetype(FONT, round(size * S), index=index)
    except OSError:
        return ImageFont.load_default()


img = Image.new("RGB", (W * S, H * S))
px = img.load()
for y in range(H * S):  # a soft warm fade, top to bottom
    t = y / (H * S)
    for x in range(W * S):
        px[x, y] = (round(248 - 10 * t), round(245 - 12 * t), round(238 - 16 * t))
d = ImageDraw.Draw(img)


def text(xy, s, f, fill, anchor="la"):
    d.text((xy[0] * S, xy[1] * S), s, font=f, fill=fill, anchor=anchor)


def card(box, radius=16, fill=(255, 255, 255)):
    """A white card with a soft shadow."""
    x0, y0, x1, y1 = [v * S for v in box]
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((x0, y0 + 4 * S, x1, y1 + 4 * S), radius * S, fill=(40, 30, 60, 46))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10 * S))
    img.paste(shadow, (0, 0), shadow)
    d.rounded_rectangle((x0, y0, x1, y1), radius * S, fill=fill)


# header: the logo as the app and the website show it (the two-bird mark and "magpiary" in Bricolage Grotesque), drawn at 4x in dmg-logo.png
LOGO = Path(__file__).with_name("dmg-logo.png")
if LOGO.exists():
    mark = Image.open(LOGO).convert("RGBA")
    mark = mark.resize((round(mark.width * S / 4), round(mark.height * S / 4)), Image.LANCZOS)
    img.paste(mark, (30 * S, 24 * S), mark)
text((W - 34, 41), "Step 1", font(12.5, "demi"), PINK, "rm")
text((W / 2, 94), "Drag Magpiary to Applications", font(30, "bold"), INK, "mm")

# the arrow between the two icon slots (icons sit at x = 215 and x = 545, y = 195)
shaft = Image.new("RGB", ((458 - 300) * S, 6 * S))
sp = shaft.load()
for x in range(shaft.width):
    t = x / shaft.width
    for y in range(shaft.height):
        sp[x, y] = (round(GOLD[0] + (PINK[0] - GOLD[0]) * t), round(GOLD[1] + (PINK[1] - GOLD[1]) * t), round(GOLD[2] + (PINK[2] - GOLD[2]) * t))
mask = Image.new("L", shaft.size, 0)
ImageDraw.Draw(mask).rounded_rectangle((0, 0, shaft.width, shaft.height), 3 * S, fill=255)
img.paste(shaft, (300 * S, 192 * S), mask)
d.polygon([(458 * S, 180 * S), (486 * S, 195 * S), (458 * S, 210 * S)], fill=PINK)

# the Open Anyway steps, on the plain backdrop with a clear gap under the icon names (which end near y = 275)
text((34, 310), "Step 2   The first time you open it", font(13, "demi"), PINK)
text((34, 332), "macOS says it can't check Magpiary, because the app isn't signed with a paid Apple account. It is safe to open:", font(12.5), MUTED)
steps = [("1", "Open Magpiary", "from Applications. macOS blocks it. That is expected."),
         ("2", "System Settings", "› Privacy & Security, then scroll to the bottom."),
         ("3", "Open Anyway", "next to Magpiary, then type your password.")]
colw = (W - 68 - 40) / 3
small = font(11.5)


def wrap(words: str, width: float) -> list[str]:
    lines, line = [], ""
    for word in words.split():
        trial = (line + " " + word).strip()
        if line and small.getlength(trial) / S > width:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + [line]


for n, (num, head, rest) in enumerate(steps):
    x = 34 + n * (colw + 20)
    d.ellipse((x * S, 358 * S, (x + 24) * S, 382 * S), fill=PINK)
    text((x + 12, 370), num, font(13, "bold"), (255, 255, 255), "mm")
    text((x + 34, 370), head, font(13.5, "bold"), INK, "lm")
    for row, line in enumerate(wrap(rest, colw - 6)):
        text((x, 392 + row * 15), line, small, MUTED)
text((34, 434), "You only do this once. After that Magpiary opens like any other app.", font(11.5, "medium"), FAINT, "lm")

out = str(OUT)
img.save(out.replace(".tiff", "@2x.png"), dpi=(144, 144))
img.resize((W, H), Image.LANCZOS).save(out.replace(".tiff", ".png"), dpi=(72, 72))
