# -*- coding: utf-8 -*-
"""端到端接口自检"""
import json
import sys
import urllib.request

# Windows 控制台默认是 GBK，工作流里可能含 \u2011 之类的字符，直接 print 会 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = "http://127.0.0.1:9000"


def get(path, timeout=60):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def post(path, payload=None, timeout=180):
    data = json.dumps(payload).encode("utf-8") if payload is not None else b""
    req = urllib.request.Request(BASE + path, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8")
        try:
            return r.status, json.loads(body)
        except Exception:
            return r.status, body


print("=== 1) /local/status ===")
s, j = get("/local/status")
print("  HTTP", s, " comfy_up =", j.get("comfy_up"))
dev = ((j.get("system_stats") or {}).get("devices") or [{}])[0]
print("  GPU :", dev.get("name"))
print("  VRAM:", round((dev.get("vram_total") or 0) / 1073741824, 1), "GB")
print("  模型:", j.get("checkpoints"))
print("  工作流存在:", j.get("workflow_exists"), " CSV存在:", j.get("tag_csv_exists"))

print()
print("=== 2) /local/workflow（界面默认值来源）===")
s, j = get("/local/workflow")
print("  HTTP", s)
print(json.dumps(j, ensure_ascii=False, indent=2))

print()
print("=== 3) /api/object_info/KSampler（反向代理）===")
s, j = get("/api/object_info/KSampler")
req = j["KSampler"]["input"]["required"]
print("  HTTP", s, " 采样器", len(req["sampler_name"][0]), "个 / 调度器", len(req["scheduler"][0]), "个")

print()
print("=== 4) 页面加载与工作台存在性 ===")
with urllib.request.urlopen(BASE + "/TagSDanbooru.html", timeout=30) as r:
    html = r.read().decode("utf-8")
for needle in ("出图工作台", 'id="wb-gallery"', 'id="wb-generate"', "startPolling",
               'id="wb-model"', 'id="wb-positive"'):
    print("  %-26s %s" % (needle, "OK" if needle in html else "*** 缺失 ***"))
print("  页面大小:", len(html), "字符")

print()
print("=== 5) 排 2 张图，观察队列与进度 ===")
s, g = post("/local/generate", {
    "positive": "1girl, solo, adult, mature female, black hair, blue eyes, smile, casual clothes, park, upper body",
    "count": 2,
    "steps": 20,
    "cfg": 6.5,
})
print("  HTTP", s, " ok =", g.get("ok"), " run_id =", g.get("run_id"), " queued =", g.get("queued"))
det = g.get("detected") or {}
print("  自动定位 -> 采样器节点", (det.get("sampler") or {}).get("node"),
      "| 尺寸节点", (det.get("latent") or {}).get("node"),
      "| 正向节点", (det.get("positive") or {}).get("node"),
      "| 输出", (det.get("output") or {}).get("action"))
print("  两枪种子:", [it["index"] for it in [{}]] if False else "见下方轮询")
rid = g.get("run_id")

import time
deadline = time.time() + 300
while time.time() < deadline:
    time.sleep(4)
    try:
        s, d = get("/local/run/" + rid, timeout=30)
    except Exception as e:
        print("  轮询异常:", e)
        continue
    run = d["run"]
    print("  [%s] status=%-8s done=%s/%s saved=%s" % (
        time.strftime("%H:%M:%S"), run["status"], run.get("done_count"),
        run.get("queued"), run.get("saved")))
    if run["status"] in ("done", "error"):
        for it in run.get("items", []):
            print("     #%d seed=%s status=%s files=%s" % (
                it["index"], it["seed"], it["status"], it.get("files")))
        break
