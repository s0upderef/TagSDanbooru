# -*- coding: utf-8 -*-
"""练图前的提示词体检（零 GPU 成本）。

为什么需要它：实测「标签越多/越冷门，画面越杂乱、细节错误越多」——
模型没见过的词不会让画面更精细，只会让它自由发挥。
这个脚本把这类错误变成机器能拦住的检查。

用法：
  python _internal\\dev\\check_prompt.py 正向.txt [负向.txt]
  python _internal\\dev\\check_prompt.py --text "1girl, solo, (adult:1.1)"
  python _internal\\dev\\check_prompt.py 负向.txt --as-negative
  --budget N       标签总数预算，默认 18（横幅 / 全身题材可放宽到 22）
  --as-negative    把文件当负向提示词：只做逐词检查，不判「数量 / 加权超预算」

检查项：
  1) 不存在的标签（写了等于白写）
  2) 热度分级：>=10万 放心 / >=1万 可靠 / 1000-1万 慎用 / <1000 建议删
  3) 互为别名的重复（同一概念写两遍，例如 china_dress + cheongsam）
  4) 标签总数、加权词个数（权重只给 1-2 个"缺它不行"的锚点）
"""

import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent.parent
TAGS = ROOT / "_internal" / "data" / "tagsd_danbooru_zh.json"

BUCKETS = ((10 ** 5, "OK   >=10万"), (10 ** 4, "OK   >=1万"),
           (10 ** 3, "WARN 1千-1万"), (1, "BAD  <1千"), (0, "BAD  热度0（废弃/别名）"))


def load_tags():
    rows = json.loads(TAGS.read_text(encoding="utf-8"))
    out = {}
    for r in rows:
        name = r[0].lower()
        try:
            cnt = int(r[2] or 0)
        except ValueError:
            cnt = 0
        aliases = [a.strip().lower() for a in (r[3] or "").split(",") if a.strip()]
        cur = out.get(name)
        if cur is None:
            out[name] = {"count": cnt, "aliases": aliases}
        else:
            # 同名有多行：必须取热度最高的那行。
            # 否则会被 0 篇的废弃行覆盖，把 nipples(88万) 这种真标签误判成"废弃"。
            if cnt > cur["count"]:
                cur["count"] = cnt
            cur["aliases"] = sorted(set(cur["aliases"]) | set(aliases))
    return out


def split_tags(text):
    """把提示词切成单个标签（保留权重信息）。"""
    items = []
    for raw in re.split(r"[,\n]", text):
        raw = raw.strip()
        if not raw:
            continue
        m = re.match(r"^\((.+?):([0-9.]+)\)$", raw)
        name, weight = (m.group(1), float(m.group(2))) if m else (raw, 1.0)
        items.append((name.strip().lower().replace(" ", "_"), weight, raw))
    return items


def bucket(cnt):
    for limit, label in BUCKETS:
        if cnt >= limit:
            return label
    return "BAD  查不到"


def main(argv):
    budget = 18
    if "--budget" in argv:
        i = argv.index("--budget")
        budget = int(argv[i + 1])
        del argv[i:i + 2]

    as_negative = "--as-negative" in argv
    if as_negative:
        argv.remove("--as-negative")

    pos_text = neg_text = ""
    if "--text" in argv:
        pos_text = argv[argv.index("--text") + 1]
    else:
        for i, a in enumerate(argv):
            txt = Path(a).read_text(encoding="utf-8-sig")
            if i == 0 and not as_negative:
                pos_text = txt
            else:
                neg_text = txt
    if not (pos_text or neg_text):
        print(__doc__)
        return 1

    tags = load_tags()
    bad = []
    for label, text in (("正向", pos_text), ("负向", neg_text)):
        if not text.strip():
            continue
        items = split_tags(text)
        weighted = [it for it in items if it[1] != 1.0]
        print("=" * 60)
        print("%s：%d 个标签，其中 %d 个带权重" % (label, len(items), len(weighted)))
        if label == "正向" and len(items) > budget:
            print("  *** 超预算：%d > %d —— 标签越多画面越容易杂乱（详见 README）"
                  % (len(items), budget))
        if len(weighted) > 2:
            print("  *** 加权词过多（%d 个）：权重会互相拉扯，建议只留 1-2 个锚点"
                  % len(weighted))

        seen = {}
        for name, weight, raw in items:
            info = tags.get(name)
            if not info:
                bad.append((label, raw, "不存在"))
                print("  [不存在]      %s" % raw)
                continue
            if name in seen and seen[name] != raw:
                print("  [重复]        %s  <-> %s" % (raw, seen[name]))
            seen[name] = raw
            # 互为别名 = 同一概念写两遍
            for other, oraw in seen.items():
                if other != name and (other in info["aliases"] or name in tags[other]["aliases"]):
                    print("  [别名重复]    %s  <-> %s（同一概念，删掉一个）" % (raw, oraw))
            mark = bucket(info["count"])
            if info["count"] < 1000:
                print("  [%s]  %-28s 热度 %s" % (mark, raw, info["count"]))
            else:
                print("      %-28s 热度 %-9s %s" % (raw, info["count"], mark))
    print("=" * 60)
    print("体检结论：%s" % ("发现问题 %d 处，见上面的 [ ] 标记" % len(bad) if bad else "干净"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
