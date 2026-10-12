# -*- coding: utf-8 -*-
"""把“行号;;中文;;一级;;二级”形式的映射合并进 danbooru_all_2.csv（只填空格子）。

用法: python _internal/dev/fill_tags.py [映射文件]
映射文件默认取 %TEMP%/tagsd_zh_map.txt；首次运行会备份 CSV。
"""
import csv, io, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CSV = os.path.join(ROOT, '_internal', 'data', 'danbooru_all_2.csv')
MAP = sys.argv[1] if 2 <= len(sys.argv) else os.path.join(os.environ.get('TEMP', '.'), 'tagsd_zh_map.txt')
BACKUP = CSV + '.prefill.bak'

m = {}
with open(MAP, encoding='utf-8') as f:
    for line in f:
        p = (line.rstrip('\n').split(';;') + ['', '', '', ''])[:4]
        if not p[0].strip():
            continue
        try:
            ln = int(p[0])
        except ValueError:
            continue
        m[ln] = (p[1].strip(), p[2].strip(), p[3].strip())

raw = open(CSV, encoding='utf-8', newline='').read()
rows = list(csv.reader(io.StringIO(raw)))

if not os.path.exists(BACKUP):
    with open(BACKUP, 'w', encoding='utf-8', newline='') as b:
        b.write(raw)
    print('backup written:', os.path.basename(BACKUP))

zh_n = l1_n = l2_n = skip = 0
for ln, (zh, l1, l2) in m.items():
    try:
        r = rows[ln - 1]
    except IndexError:
        skip += 1
        continue
    if len(r) != 8:
        skip += 1
        continue
    if zh and not r[4].strip():
        r[4] = zh
        zh_n += 1
    if l1 and not r[5].strip():
        r[5] = l1
        l1_n += 1
    if l2 and not r[6].strip():
        r[6] = l2
        l2_n += 1

buf = io.StringIO()
csv.writer(buf, lineterminator='\n').writerows(rows)
out = buf.getvalue()
if out.endswith('\n'):
    out = out[:-1]
with open(CSV, 'w', encoding='utf-8', newline='') as f:
    f.write(out)

print('map entries   :', len(m))
print('filled 中文   :', zh_n)
print('filled 一级   :', l1_n)
print('filled 二级   :', l2_n)
print('skipped       :', skip)