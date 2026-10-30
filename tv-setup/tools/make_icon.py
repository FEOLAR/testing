"""Делает assets/icon.ico и assets/logo.png из картинки чёрной дыры лаунчера.

Запуск (из папки tv-setup):  python tools/make_icon.py
Результат закоммичен, в CI скрипт не нужен.
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT.parent / "tv-launcher/app/src/main/res/drawable-nodpi/hero_bg.jpg"
CENTER = (830, 478)  # центр чёрной дыры на hero_bg.jpg (1672x941)
HALF = 230           # половина стороны квадрата обрезки


def main() -> None:
    im = Image.open(SRC).convert("RGB")
    cx, cy = CENTER
    sq = im.crop((cx - HALF, cy - HALF, cx + HALF, cy + HALF)).resize((1024, 1024), Image.LANCZOS)
    big = 1024 * 4
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, big - 1, big - 1), fill=255)
    mask = mask.resize((1024, 1024), Image.LANCZOS)
    out = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    out.paste(sq, (0, 0), mask)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    (ROOT / "assets").mkdir(exist_ok=True)
    out.save(ROOT / "assets/icon.ico", sizes=sizes)
    out.resize((128, 128), Image.LANCZOS).save(ROOT / "assets/logo.png")
    print("ok")


if __name__ == "__main__":
    main()
