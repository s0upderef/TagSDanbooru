# -*- coding: utf-8 -*-
"""标签库体检：分段看中文 / 分类覆盖率，顺便当回归断言用。

用法:
    python _internal/dev/audit_tags.py            # 只看报告
    python _internal/dev/audit_tags.py --assert   # 结构或覆盖率回退时退出码 1
"""
import collections
import csv
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CSV = os.path.join(ROOT, "_internal", "data", "tagsd_danbooru_zh.csv")
HTML = os.path.join(ROOT, "TagSDanbooru.html")
BANDS = [(0, 5000, "前5000"), (5000, 10000, "5k-10k"), (10000, 20000, "10k-20k"),
         (20000, 50000, "20k-50k"), (50000, 10 ** 9, "50k+")]
# 画师 / 作品 / 角色（danbooru category 1/3/4）：按约定不铺分类，不算缺口
NOT_USEFUL = ("1", "3", "4")
# 这些一级本来就不设二级（只按一级筛），"缺二级"不算问题
NO_L2 = ("角色", "画师", "作品")
# 现状基线（只允许变好，不允许变差）：前 20k 里还没认出的实用词条
BASELINE = {"top5000_missing_l1": 0, "top20k_missing_l1": 1653}


def main():
    check = "--assert" in sys.argv
    rows = list(csv.reader(open(CSV, encoding="utf-8-sig", newline="")))
    print("总行数:", len(rows))

    heat = lambda r: int(r[2] or 0)
    order = sorted(range(len(rows)), key=lambda i: -heat(rows[i]))
    rank = {i: k + 1 for k, i in enumerate(order)}

    zh = lambda r: bool((r[4] or "").strip())
    t1 = lambda r: bool((r[5] or "").strip())
    t2 = lambda r: bool((r[6] or "").strip())

    print("")
    print("热度段      总行数   缺中文          缺一级(实用词条)   缺二级(有一级但没二级)")
    for lo, hi, label in BANDS:
        idx = [i for i in range(len(rows)) if lo < rank[i] <= hi]
        n = len(idx)
        z = sum(1 for i in idx if not zh(rows[i]))
        m1 = sum(1 for i in idx if rows[i][1] not in NOT_USEFUL and not t1(rows[i]))
        m2 = sum(1 for i in idx if t1(rows[i]) and not t2(rows[i])
                 and (rows[i][5] or "").strip() not in NO_L2)
        print("%-10s %6d  %5d (%4.1f%%)  %6d          %6d" % (label, n, z, 100.0 * z / max(n, 1), m1, m2))

    print("")
    dist = collections.Counter((rows[i][5] or "").strip() for i in range(len(rows)) if t1(rows[i]))
    print("一级分类分布：")
    for name, n in dist.most_common():
        print("   %-12s %6d" % (name or "(空)", n))

    problems = []
    bad_fields = [i for i, r in enumerate(rows) if len(r) != 8]
    if bad_fields:
        problems.append("有 %d 行字段数不是 8" % len(bad_fields))
    dupes = len(rows) - len({r[0] for r in rows})
    if dupes:
        print("注意：有 %d 个重复标签（历史遗留：同一标签两行，其中一行 heat 为空；不是本次改出来的）"
              % dupes)
    orphan = [i for i, r in enumerate(rows) if not t1(r) and t2(r) and (r[6] or "").strip() != ""
              and not (r[6] or "").strip().startswith("魔法")]
    if orphan:
        problems.append("有 %d 行只有二级没一级（历史遗留）" % len(orphan))
    top5 = [i for i in order[:5000] if rows[i][1] not in NOT_USEFUL and not t1(rows[i])]
    top20 = [i for i in order[:20000] if rows[i][1] not in NOT_USEFUL and not t1(rows[i])]
    print("")
    print("前 5000 里实用词条缺一级:", len(top5), "（基线 %d）" % BASELINE["top5000_missing_l1"])
    print("前 20000 里实用词条缺一级:", len(top20), "（基线 %d）" % BASELINE["top20k_missing_l1"])
    if len(top5) > BASELINE["top5000_missing_l1"]:
        problems.append("前 5000 缺一级从基线 %d 涨到 %d" % (BASELINE["top5000_missing_l1"], len(top5)))
    if len(top20) > BASELINE["top20k_missing_l1"]:
        problems.append("前 20000 缺一级从基线 %d 涨到 %d" % (BASELINE["top20k_missing_l1"], len(top20)))

    # 页面的一级/二级按钮必须覆盖数据里出现过的一级/二级，否则筛选项会悄悄变少
    try:
        html = open(HTML, encoding="utf-8").read()
        pref_src = re.search(r"L2_PREF = \{(.*?)\n\s*\};", html, re.S).group(1)
        l2_pref = eval("{" + pref_src + "}")
        order_src = re.search(r"L1_ORDER = \[(.*?)\]", html, re.S).group(1)
        l1_order = [s.strip().strip("'") for s in order_src.split(",") if s.strip()]
        have = collections.defaultdict(set)
        for r in rows:
            if t1(r):
                have[(r[5] or "").strip()].add((r[6] or "").strip())
        miss_l1 = sorted(set(have) - set(l1_order))
        if miss_l1:
            problems.append("页面一级按钮漏了: %s" % ", ".join(miss_l1))
        for l1, l2s in sorted(have.items()):
            pref = set(l2_pref.get(l1) or [])
            if not pref:
                continue
            miss = sorted(x for x in l2s if x and x not in pref)
            if miss:
                problems.append("页面二级按钮[%s]漏了: %s" % (l1, ", ".join(miss)))
    except Exception as e:                                  # noqa: BLE001
        problems.append("页面分类按钮检查失败: %r" % (e,))

    print("")
    if problems:
        for p in problems:
            print("FAIL", p)
    else:
        print("结构检查 + 覆盖率基线：全部通过")
    if not check:
        return 0
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
