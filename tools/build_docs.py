"""Build the self-contained report.html and slides.html from docs/src/ (images embedded, no AI).

    python tools/build_docs.py [--shots DIR]

Placeholders in the sources:
  {{img:NAME|caption|max_height_px}}  screenshot NAME.png, cropped to max height, embedded as JPEG
  {{svg:agent}}                       the agent diagram from docs/agent_design.html
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import re
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
IMG = re.compile(r"\{\{img:([\w-]+)\|([^|}]*)\|?(\d*)\}\}")


def embed(shots: Path, name: str, caption: str, max_h: str, width: int) -> str:
    im = Image.open(shots / f"{name}.png").convert("RGB")
    if max_h:
        im = im.crop((0, 0, im.width, min(im.height, int(max_h))))
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80, optimize=True)
    src = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    cap = html.escape(caption)
    return f'<figure><img src="{src}" alt="{cap}"><figcaption>{cap}</figcaption></figure>'


def build(src: Path, dst: Path, shots: Path, svg: str, width: int) -> int:
    text = src.read_text(encoding="utf-8").replace("{{svg:agent}}", svg)
    text = IMG.sub(lambda m: embed(shots, m.group(1), m.group(2), m.group(3), width), text)
    dst.write_text(text, encoding="utf-8")
    return dst.stat().st_size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default=str(ROOT.parent / "docs" / "evidence" / "screenshots"))
    a = ap.parse_args()
    shots = Path(a.shots)
    svg = re.search(r"<svg.*?</svg>", (ROOT / "docs" / "agent_design.html").read_text(encoding="utf-8"), re.S).group(0)
    for name, width in (("report", 1100), ("slides", 1000)):
        size = build(ROOT / "docs" / "src" / f"{name}_src.html", ROOT / f"{name}.html", shots, svg, width)
        print(f"{name}.html: {size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
