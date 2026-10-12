#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把出图拼成便于快速检视的对比图。

用途：一轮出图后，用两三张图同时看清「整体构图」和「五官 / 衣摆 / 足部细节」，
不必逐张打开原图（原图太大时检视工具往往加载不出来）。

用法：
  python _internal\\dev\\contact_sheet.py --series 旗袍晚礼服
  python _internal\\dev\\contact_sheet.py --run 20261012_211052_2f37
  python _internal\\dev\\contact_sheet.py <图1> <图2> ...

  --limit N   只拼最新的 N 张（默认 16，避免整个系列拼出一张巨型图）；0 = 不限制
  --name X    自定义输出文件名
  --no-detail 只出总览，不做头部 / 下半身特写

输出到 _internal/dev/_preview/：
  sheet_<名称>.jpg   网格总览：每格标注 时间 / seed / 步数 / CFG / 尺寸
  face_<名称>.jpg    头部区域放大拼图（盯眼睛与五官）
  lower_<名称>.jpg   下半身放大拼图（盯衣摆、开衩、鞋、脚）

FACE_BOX / LOWER_BOX 是启发式裁剪比例，换了构图（全身/过膝/半身）可能需要调整。
"""

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "_internal" / "output"
DST = ROOT / "_internal" / "dev" / "_preview"
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")

COLS = 4
THUMB_W = 400
FACE_BOX = (0.14, 0.00, 0.86, 0.32)      # 左, 上, 右, 下 —— 比例
LOWER_BOX = (0.10, 0.58, 0.90, 1.00)
FONTS = (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc",
         r"C:\Windows\Fonts\simhei.ttf")


def font(size):
    for p in FONTS:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size)      # Pillow >= 10.1
    except Exception:
        return ImageFont.load_default()


def find_run_dir(run_id):
    """run 目录可能在 output/<run_id>/ 或 output/<系列>/<run_id>/。"""
    direct = OUT / run_id
    if direct.is_dir():
        return direct
    for p in OUT.glob("*/" + run_id):
        if p.is_dir():
            return p
    return None


def collect(a):
    """收集要拼的图片，按「批次时间 + 序号」排序（= 时间顺序，能看出改进过程）。"""
    if a.series:
        base = OUT / a.series
        if not base.is_dir():
            print("找不到系列目录：%s" % base)
            return []
        files = [p for p in base.rglob("*") if p.suffix.lower() in IMG_EXT]
    elif a.run:
        base = find_run_dir(a.run)
        if not base:
            print("找不到批次：%s" % a.run)
            return []
        files = [p for p in base.glob("*") if p.suffix.lower() in IMG_EXT]
    else:
        files = [Path(x) for x in a.paths if Path(x).is_file()]
        return files                     # 显式给路径时保持给定顺序（便于做 A/B 对照）
    return sorted(files, key=lambda p: (p.parent.name, p.name))


def params_for(path, cache):
    """从所在批次的 prompt.json 里查出这张图的参数。"""
    run_dir = path.parent
    if run_dir not in cache:
        meta = {}
        pj = run_dir / "prompt.json"
        if pj.is_file():
            try:
                meta = json.loads(pj.read_text(encoding="utf-8-sig"))
            except Exception:
                meta = {}
        cache[run_dir] = meta
    for it in cache[run_dir].get("items") or []:
        if path.name in (it.get("files") or []):
            p = it.get("params") or {}
            s, l = p.get("sampler") or {}, p.get("latent") or {}
            size = ("%sx%s" % (l.get("width"), l.get("height"))) if l.get("width") else ""
            return {"seed": it.get("seed"), "steps": s.get("steps"), "cfg": s.get("cfg"),
                    "sampler": s.get("sampler_name"), "scheduler": s.get("scheduler"),
                    "size": size}
    return {}


def label_of(path, prm):
    d = path.parent.name                       # 20261012_215010_ba09
    when = d[9:11] + ":" + d[11:13] if len(d) >= 13 else d[:13]
    bits = [when, "seed %s" % prm.get("seed")]
    if prm.get("steps") is not None:
        bits.append("%s步" % prm["steps"])
    if prm.get("cfg") is not None:
        bits.append("cfg%s" % prm["cfg"])
    if prm.get("size"):
        bits.append(prm["size"])
    return "  ".join(str(b) for b in bits if b)

def crop(im, box):
    w, h = im.size
    return im.crop((int(w * box[0]), int(h * box[1]), int(w * box[2]), int(h * box[3])))


def tile(cells, title, cols, cell_w, cell_h, dst, note=""):
    """cells: [(图, 说明)] -> 拼成网格存盘。"""
    rows = (len(cells) + cols - 1) // cols
    pad, head = 8, 34
    W = cols * cell_w + pad * (cols + 1)
    H = head + rows * (cell_h + pad) + pad + (26 if note else 0)
    canvas = Image.new("RGB", (W, H), (24, 26, 32))
    dr = ImageDraw.Draw(canvas)
    f_head, f_cell = font(20), font(16)
    dr.text((pad, 8), title, font=f_head, fill=(235, 238, 245))
    for k, (im, cap) in enumerate(cells):
        r, c = divmod(k, cols)
        x = pad + c * (cell_w + pad)
        y = head + r * (cell_h + pad)
        canvas.paste(im, (x, y))
        if cap:
            dr.rectangle([x, y + cell_h - 24, x + cell_w - 1, y + cell_h - 1], fill=(0, 0, 0))
            dr.text((x + 4, y + cell_h - 21), cap, font=f_cell, fill=(255, 255, 255))
    if note:
        dr.text((pad, H - 23), note, font=f_cell, fill=(150, 158, 172))
    DST.mkdir(parents=True, exist_ok=True)
    canvas.save(dst, format="JPEG", quality=86)
    print("  %s  %dx%d" % (dst.name, W, H))
    return dst


def layout(n):
    """按张数决定列数与缩略图宽度。

    拼图太大时读图工具会直接拒绝加载（实测 1640×2274 就打不开了），
    所以张数一多就自动改用「更多列 + 更小格」，把总高压在可读范围内。
    """
    if n <= 8:
        return COLS, THUMB_W
    return 6, 260


def build(files, name, cache, with_detail=True):
    made = []
    cols, thumb_w = layout(len(files))

    cells = []
    for f in files:
        im = Image.open(f).convert("RGB")
        w, h = im.size
        th = max(1, int(h * thumb_w / w))
        cells.append((im.resize((thumb_w, th), Image.LANCZOS),
                      label_of(f, params_for(f, cache))))
    if not cells:
        return made
    ch = cells[0][0].size[1]
    made.append(tile(cells, "总览 · %s（%d 张，按时间顺序）" % (name, len(cells)),
                     cols, thumb_w, ch, DST / ("sheet_%s.jpg" % name)))

    if not with_detail:
        return made

    # 特写图：格宽按总宽预算定，再按裁剪区的宽高比反推格高
    dcols = 4
    dcw = min(400, 1560 // dcols)
    for tag, box, title in (
            ("face", FACE_BOX, "头部特写 · %s（盯眼睛与五官）" % name),
            ("lower", LOWER_BOX, "下半身特写 · %s（盯衣摆 / 开衩 / 鞋 / 脚）" % name)):
        cells = []
        for f in files:
            c = crop(Image.open(f).convert("RGB"), box)
            dch = max(1, int(dcw * c.size[1] / c.size[0]))
            cells.append((c.resize((dcw, dch), Image.LANCZOS),
                          label_of(f, params_for(f, cache))))
        dch = cells[0][0].size[1]
        made.append(tile(cells, title, dcols, dcw, dch, DST / ("%s_%s.jpg" % (tag, name)),
                         note="裁剪比例 FACE=%s LOWER=%s" % (FACE_BOX, LOWER_BOX)))
    return made


def main(argv):
    class A:
        series = run = name = None
        paths = []
        no_detail = False
        limit = 16          # 默认只拼最新的 16 张，见下面的说明

    a, i = A(), 0
    while i < len(argv):
        t = argv[i]
        if t == "--series":
            i += 1
            a.series = argv[i]
        elif t == "--run":
            i += 1
            a.run = argv[i]
        elif t == "--name":
            i += 1
            a.name = argv[i]
        elif t == "--limit":
            i += 1
            a.limit = int(argv[i])
        elif t == "--no-detail":
            a.no_detail = True
        else:
            a.paths.append(t)
        i += 1

    if not (a.series or a.run or a.paths):
        print(__doc__)
        return 1
    files = collect(a)
    if not files:
        print("没有找到图片")
        return 1
    if a.limit and len(files) > a.limit:
        print("共 %d 张，超过上限 %d，只拼最新的 %d 张（--limit 0 可关闭上限）"
              % (len(files), a.limit, a.limit))
        files = files[-a.limit:]
    else:
        print("共 %d 张 ->" % len(files))
    name = a.name or a.series or a.run or "custom"
    build(files, name, {}, with_detail=not a.no_detail)
    print("输出目录：%s" % DST)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
