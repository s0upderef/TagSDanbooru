#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""命令行走工作台的出图接口（UTF-8 安全，便于脚本化批量出图）。

为什么要这个脚本：Windows PowerShell 5.1 的 Invoke-RestMethod 发中文 JSON 会把
编码搞坏（系列名 "OL制服" 会变成 "OL__"），所以出图统一走这里。

用法：
  python _internal\\dev\\gen.py --series 旗袍晚礼服 --count 4 --seed 900001 \\
      --steps 28 --positive-file _internal\\dev\\_p1.txt --negative-file _internal\\dev\\_n1.txt --wait

  --positive / --negative 也可直接写（但中文请优先用 -file 形式，避免命令行编码问题）。

出图会进入 _internal/output/<系列>/<批次>/，与网页工作台完全一致。
"""

import argparse
import json
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:9000"


def read_text(path):
    from pathlib import Path
    return Path(path).read_text(encoding="utf-8-sig").strip()


def post(path, payload, timeout=180):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def get(path, timeout=60):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--series", default=None)
    ap.add_argument("--series-file", default=None,
                    help="从文件读系列名（中文更保险，避免命令行编码问题）")
    ap.add_argument("--positive", default=None)
    ap.add_argument("--positive-file", default=None)
    ap.add_argument("--negative", default=None)
    ap.add_argument("--negative-file", default=None)
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--seed-stride", type=int, default=None,
                    help="同批 seed 跨度：默认 1=连号（构图容易雷同），"
                         "探索时给个大奇数（如 137111）能拿到差异明显的样本")
    ap.add_argument("--steps", type=int, default=None)
    ap.add_argument("--cfg", type=float, default=None)
    ap.add_argument("--size", default=None, help="如 1024x1408")
    ap.add_argument("--sampler", default=None)
    ap.add_argument("--scheduler", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--wait", action="store_true", help="等出图完成并报告结果")
    a = ap.parse_args()

    pos = read_text(a.positive_file) if a.positive_file else (a.positive or "")
    neg = read_text(a.negative_file) if a.negative_file else (a.negative or "")
    series = read_text(a.series_file) if a.series_file else (a.series or "")
    if not series.strip():
        print("未指定系列名")
        return 2
    if not pos.strip():
        print("正向提示词为空")
        return 2

    body = {"positive": pos.strip(), "series": series.strip(), "count": a.count}
    if neg.strip():
        body["negative"] = neg.strip()
    for key, val in (("model", a.model), ("sampler_name", a.sampler),
                     ("scheduler", a.scheduler), ("steps", a.steps),
                     ("cfg", a.cfg), ("seed", a.seed), ("seed_stride", a.seed_stride)):
        if val is not None:
            body[key] = val
    if a.size:
        w, h = a.size.lower().split("x")
        body["width"], body["height"] = int(w), int(h)

    print("系列: %s   张数: %d   seed: %s%s   步数: %s   CFG: %s   尺寸: %s"
          % (series.strip(), a.count, a.seed,
             ("（跨度 %d）" % a.seed_stride) if a.seed_stride else "",
             a.steps, a.cfg, a.size or "(工作流默认)"))
    print("采样器: %s / %s" % (a.sampler or "-", a.scheduler or "-"))
    r = post("/local/generate", body)
    print("提交 -> ok=%s run=%s queued=%s" % (r.get("ok"), r.get("run_id"), r.get("queued")))
    if r.get("errors"):
        print("  错误: %s" % r["errors"])
    rid = r.get("run_id")
    if not (a.wait and r.get("ok")):
        return 0 if r.get("ok") else 1

    t0 = time.time()
    while True:
        time.sleep(3)
        try:
            run = get("/local/run/" + rid)["run"]
        except Exception as exc:
            # 图片被整体删掉后，服务端不再返回这一批
            if "404" in str(exc):
                print("  这一批已不在服务端（图片可能已被删除）")
                return 1
            print("  轮询出错: %s" % exc)
            continue
        if run["status"] in ("done", "error"):
            break
        print("  [%4ds] %s %s/%s" % (time.time() - t0, run["status"],
                                     run.get("done_count"), run.get("queued")))
    print("完成: %s  用时 %.0f 秒  存了 %s 张" % (run["status"], time.time() - t0, run.get("saved")))
    for it in run.get("items") or []:
        print("  seed %-12s %s" % (it.get("seed"), (it.get("files") or ["(无)"])[0]))
    return 0 if run["status"] == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
