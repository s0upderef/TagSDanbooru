#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把出图缩成便于快速检视的小图（默认长边 900），输出到 _internal/dev/_preview/。

原图不动。用于放大分辨率后仍能快速看整体构图与细节。

用法：
  python _internal\\dev\\preview.py <图片路径> [更多路径...]
  python _internal\\dev\\preview.py --run 20261012_210802_fff4
"""

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "_internal" / "output"
DST = ROOT / "_internal" / "dev" / "_preview"
LONG_EDGE = 900


def shrink(src):
    src = Path(src)
    im = Image.open(src)
    w, h = im.size
    scale = min(1.0, LONG_EDGE / float(max(w, h)))
    if scale < 1.0:
        im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    DST.mkdir(parents=True, exist_ok=True)
    dst = DST / (src.stem + ".jpg")
    im.convert("RGB").save(dst, format="JPEG", quality=88)
    print("  %s  %dx%d -> %dx%d  %s" % (src.name, w, h, im.size[0], im.size[1], dst))
    return dst


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    if argv[0] == "--run":
        d = OUT / argv[1]
        files = sorted(p for p in d.glob("*") if p.suffix.lower() in (".png", ".jpg", ".webp"))
    else:
        files = [Path(a) for a in argv]
    if not files:
        print("没有找到图片")
        return 1
    for f in files:
        shrink(f)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
