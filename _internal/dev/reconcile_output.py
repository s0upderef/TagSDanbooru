#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 _internal/output/<批次>/prompt.json 与磁盘上实际的图片文件对账并修正。

用途：
  * 手动挪走/删除过图片，或在回收站里还原过图片之后，让画廊重新显示正确的内容
  * 图片按 序号_seedXXX.png 命名，所以能精确匹配回它属于哪一项

用法：  python _internal\\dev\\reconcile_output.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "_internal" / "output"

changed_runs = 0
orphans_total = 0

for meta_path in sorted(list(OUT.glob("*/prompt.json")) + list(OUT.glob("*/*/prompt.json"))):
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        print("  [跳过] %s：%s" % (meta_path.parent.name, exc))
        continue

    d = meta_path.parent
    pngs = sorted(p.name for p in d.glob("*") if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".webp"))
    used = set()
    changed = False

    for it in meta.get("items") or []:
        idx = (it.get("index") or 0) + 1
        seed = it.get("seed")
        if seed is not None:
            pref = "%02d_seed%s" % (idx, seed)
        else:
            pref = "%02d_" % idx
        files = [f for f in pngs if f.startswith(pref) and f not in used]
        used.update(files)
        if files != (it.get("files") or []):
            print("  %s item%d: %s -> %s" % (d.name, it.get("index"), it.get("files") or [], files))
            it["files"] = files
            changed = True

    saved = sum(len(it.get("files") or []) for it in meta.get("items") or [])
    if meta.get("saved_count") != saved:
        meta["saved_count"] = saved
        changed = True

    orphans = [f for f in pngs if f not in used]
    if orphans:
        orphans_total += len(orphans)
        print("  %s 有 %d 个未被记录的文件：%s" % (d.name, len(orphans), ", ".join(orphans)))

    if changed:
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print("  已更新 %s（%d 张）" % (meta_path.relative_to(ROOT), saved))
        changed_runs += 1

print("对账完成：更新 %d 份 prompt.json，发现 %d 个孤立文件" % (changed_runs, orphans_total))
sys.exit(0)
