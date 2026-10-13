#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TagSDanbooru 本地服务（单文件，仅依赖 aiohttp）

职责：
  1. 同源托管项目页面 —— 页面在 127.0.0.1:9000，ComfyUI 在 127.0.0.1:8188，
     所有 ComfyUI 请求经 /api/* 反向代理，浏览器端完全没有跨域问题。
  2. 自动检测 / 拉起 ComfyUI（若绘世启动器已开着，则直接复用）。
  3. 界面专用接口 /local/*（状态查询、出图归档、对比图拼接等）。

由项目根目录的 启动.bat 拉起；关闭那个命令行窗口即停止。
"""

import asyncio
import json
import os
import random
import re
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

try:
    from aiohttp import web, ClientSession, ClientTimeout
except Exception:
    print("[FATAL] 未找到 aiohttp。请用根目录的 启动.bat 启动（它会自动挑选带 aiohttp 的 python，通常是 ComfyUI 自带那个）；也可对当前 python 执行 pip install aiohttp。")
    raise SystemExit(1)

# ================================================================ 路径与配置

ROOT = Path(__file__).resolve().parent.parent          # 项目根目录
INTERNAL = ROOT / "_internal"
CFG_PATH = INTERNAL / "config.json"

FALLBACK_CFG = {
    "server": {"host": "127.0.0.1", "port": 9000, "open_browser": True, "page": "TagSDanbooru.html",
               "single_window": True, "close_window_on_exit": True, "browser_exe": ""},
    "comfy": {"python": r"C:\ComfyUI\python\python.exe",
              "dir": r"C:\ComfyUI\ComfyUI",
              "host": "127.0.0.1", "port": 8188, "auto_start": True,
              "startup_timeout_sec": 240, "extra_args": ["--disable-auto-launch"]},
    "paths": {"tag_csv": "_internal/data/tagsd_danbooru_zh.csv",
              "tag_json": "_internal/data/tagsd_danbooru_zh.json",
              "workflow": "_internal/workflows/illSdxl.json",
              "output_dir": "_internal/output",
              "sweeps_dir": "_internal/sweeps",
              "logs_dir": "_internal/logs"},
    "defaults": {"filename_prefix": "tagsd", "replace_preview_with_save": True},
}


def load_config():
    cfg = json.loads(json.dumps(FALLBACK_CFG))
    if CFG_PATH.exists():
        try:
            user = json.loads(CFG_PATH.read_text(encoding="utf-8-sig"))
            for section, values in user.items():
                if isinstance(values, dict):
                    cfg.setdefault(section, {}).update(values)
                else:
                    cfg[section] = values
        except Exception as exc:
            print("[WARN] config.json 解析失败，改用默认配置：%s" % exc)
    return cfg


CFG = load_config()
SRV = CFG["server"]
CMF = CFG["comfy"]
PTH = CFG["paths"]

COMFY_BASE = "http://%s:%d" % (CMF["host"], CMF["port"])
PAGE_URL = "http://%s:%d/%s" % (SRV["host"], SRV["port"], SRV["page"])

LOG_DIR = ROOT / PTH["logs_dir"]
LOG_DIR.mkdir(parents=True, exist_ok=True)


def abspath(rel):
    p = Path(rel)
    return p if p.is_absolute() else (ROOT / p)


# ---- 系列：同一个流程（同一个主题的反复迭代）的图收进同一个文件夹 ----

DEFAULT_SERIES = "未归类"


def sanitize_series(name):
    """系列名 -> 安全的文件夹名；空或含有非法字符时回退到当天日期。"""
    s = str(name or "").strip()
    for ch in '\\/:*?"<>|':
        s = s.replace(ch, "_")
    s = re.sub(r"\s+", " ", s).strip(" .")
    if not s:
        s = datetime.now().strftime("%Y%m%d")
    return s[:40]


def series_dir_of(name):
    return abspath(PTH["output_dir"]) / sanitize_series(name)


def series_rel(name):
    """系列文件夹相对项目根目录的路径（给前端「打开文件夹」用）。"""
    return (Path(PTH["output_dir"]) / sanitize_series(name)).as_posix()


LOG_FILE = LOG_DIR / ("server_%s.log" % datetime.now().strftime("%Y%m%d"))


def log(msg):
    """同时打到控制台和 _internal/logs/server_<日期>.log（关掉窗口后日志仍在）。"""
    line = "[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8", errors="replace") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


# ================================================================ 标签数据缓存

TAG_DATA = {"exists": False, "format": "csv", "url": None, "rows": None}


def _web_url(path):
    """把项目内的路径变成页面可直接访问的 URL（静态目录挂在项目根上）。"""
    try:
        rel = Path(path).resolve().relative_to(ROOT.resolve())
    except Exception:
        return None
    return "/" + rel.as_posix()


def _count_json_rows(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return len(json.load(fh))
    except Exception:
        return None


def ensure_tag_cache():
    """把 danbooru CSV 预转成 JSON，让页面首屏秒开。

    JSON.parse 由浏览器引擎原生实现（100+ MB/s），而 CSV 要逐字符状态机解析
    （约 1 MB/s）—— 15 万行差两个数量级。缓存不比 CSV 旧时直接复用。
    """
    csv_path = abspath(PTH.get("tag_csv") or "")
    csv_url = _web_url(csv_path) if csv_path.is_file() else None
    TAG_DATA.update({"exists": bool(csv_url), "format": "csv", "url": csv_url, "rows": None})

    json_cfg = PTH.get("tag_json")
    if not json_cfg or not csv_path.is_file():
        return TAG_DATA
    json_path = abspath(json_cfg)

    try:
        if json_path.is_file() and json_path.stat().st_mtime >= csv_path.stat().st_mtime:
            TAG_DATA.update({"exists": True, "format": "json",
                             "url": _web_url(json_path), "rows": _count_json_rows(json_path)})
            log("标签缓存已是最新：%s（%s 行）" % (json_path.name, TAG_DATA["rows"]))
            return TAG_DATA
    except Exception:
        pass

    t0 = time.time()
    try:
        import csv as _csv
        rows = []
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as fh:
            for row in _csv.reader(fh):
                if not row or not row[0].strip():
                    continue
                rows.append([(c or "") for c in row[:8]])

        def _pop(r):
            try:
                return int(r[2] or 0)
            except Exception:
                return 0

        rows.sort(key=_pop, reverse=True)          # 预排序：页面端可直接用
        json_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = json_path.with_name(json_path.name + ".tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, json_path)
        TAG_DATA.update({"exists": True, "format": "json",
                         "url": _web_url(json_path), "rows": len(rows)})
        log("已生成标签缓存 %s：%d 行，耗时 %.2f 秒（下次启动直接复用）"
            % (json_path.name, len(rows), time.time() - t0))
    except Exception as exc:
        log("生成标签缓存失败，页面会自动回退用 CSV：%s" % exc)
    return TAG_DATA


# ================================================================ ComfyUI 进程管理

class ComfyProcess:
    """检测 / 启动 / 停止 ComfyUI"""

    def __init__(self):
        self.proc = None
        self.started_by_us = False

    async def is_up(self, timeout=2.0):
        try:
            async with ClientSession(timeout=ClientTimeout(total=timeout)) as s:
                async with s.get(COMFY_BASE + "/system_stats") as r:
                    return r.status == 200
        except Exception:
            return False

    def _launch(self):
        py = CMF["python"]
        cdir = CMF["dir"]
        if not os.path.exists(py):
            raise FileNotFoundError("找不到 ComfyUI 的 python: %s" % py)
        if not os.path.isdir(cdir):
            raise FileNotFoundError("找不到 ComfyUI 目录: %s" % cdir)

        args = [py, "main.py", "--port", str(CMF["port"])] + list(CMF.get("extra_args") or [])
        logf_path = LOG_DIR / ("comfy_%s.log" % datetime.now().strftime("%Y%m%d_%H%M%S"))
        logf = open(logf_path, "a", encoding="utf-8", errors="replace")
        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        self.proc = subprocess.Popen(args, cwd=cdir, stdout=logf, stderr=subprocess.STDOUT,
                                     creationflags=flags)
        self.started_by_us = True
        log("已启动 ComfyUI (pid=%s)，日志 -> %s" % (self.proc.pid, logf_path))

    async def ensure_up(self):
        if await self.is_up():
            log("ComfyUI 已在运行（%s），直接复用" % COMFY_BASE)
            return True
        if not CMF.get("auto_start", True):
            log("ComfyUI 未运行，且 config 中 auto_start = false")
            return False
        try:
            self._launch()
        except Exception as exc:
            log("启动 ComfyUI 失败：%s" % exc)
            return False
        deadline = time.time() + float(CMF.get("startup_timeout_sec", 240))
        while time.time() < deadline:
            if await self.is_up(1.5):
                log("ComfyUI 就绪：%s" % COMFY_BASE)
                return True
            if self.proc and self.proc.poll() is not None:
                log("ComfyUI 进程已退出（退出码 %s），请查看 _internal/logs/ 下的日志" % self.proc.returncode)
                return False
            await asyncio.sleep(1.5)
        log("等待 ComfyUI 就绪超时（%ss）" % CMF.get("startup_timeout_sec"))
        return False

    def stop(self):
        if self.started_by_us and self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                log("已停止 ComfyUI（本服务启动的实例）")
            except Exception:
                pass


COMFY = ComfyProcess()

# ================================================================ HTTP 接口

# 反向代理时不转发的请求头
_HOP_HEADERS = {"host", "content-length", "connection", "keep-alive", "transfer-encoding",
                "upgrade", "proxy-authorization", "proxy-authenticate", "te", "trailer"}


def json_response(payload, status=200):
    return web.json_response(payload, status=status, dumps=lambda o: json.dumps(o, ensure_ascii=False))


async def handle_index(request):
    raise web.HTTPFound("/" + SRV["page"])


async def handle_ping(request):
    return json_response({"ok": True, "time": datetime.now().isoformat(timespec="seconds")})


async def handle_local_status(request):
    """页面用来显示连接状态：ComfyUI 是否在线、可用模型、当前工作流等。"""
    up = await COMFY.is_up()
    info = {
        "ok": True,
        "comfy_up": up,
        "comfy_base": COMFY_BASE,
        "page_url": PAGE_URL,
        "workflow": PTH["workflow"],
        "workflow_exists": abspath(PTH["workflow"]).exists(),
        "tag_csv_exists": abspath(PTH["tag_csv"]).exists(),
        "tag_data": TAG_DATA,
        "server_port": SRV["port"],
    }
    if up:
        try:
            info["system_stats"] = await proxy_json(request.app, "/system_stats")
        except Exception as exc:
            info["system_stats_error"] = str(exc)
        try:
            info["checkpoints"] = await proxy_json(request.app, "/models/checkpoints")
        except Exception as exc:
            info["checkpoints_error"] = str(exc)
    return json_response(info)


async def proxy_json(app, path):
    client = app["client"]
    async with client.get(COMFY_BASE + path) as resp:
        text = await resp.text()
        return json.loads(text)


async def handle_api_proxy(request):
    """把 /api/xxx 原样转发到 ComfyUI 的 /xxx（含查询串与二进制响应）。"""
    tail = request.match_info.get("tail", "")
    url = COMFY_BASE + "/" + tail
    if request.query_string:
        url += "?" + request.query_string

    if not await COMFY.is_up():
        return json_response({"ok": False, "error": "ComfyUI 未运行，请稍候或检查 _internal/logs/"}, 503)

    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_HEADERS}
    body = await request.read()

    client = request.app["client"]
    try:
        async with client.request(request.method, url, data=body or None, headers=headers) as resp:
            payload = await resp.read()
            out = web.Response(body=payload, status=resp.status)
            ctype = resp.headers.get("Content-Type")
            if ctype:
                out.headers["Content-Type"] = ctype
            cdisp = resp.headers.get("Content-Disposition")
            if cdisp:
                out.headers["Content-Disposition"] = cdisp
            return out
    except Exception as exc:
        return json_response({"ok": False, "error": "代理请求失败: %s" % exc}, 502)


async def handle_shutdown(request):
    log("收到关闭指令，正在退出…")
    raise web.GracefulExit()


# ================================================================ 工作流改写与出图

CLIENT_ID = uuid.uuid4().hex
RUNS = {}      # run_id -> run dict
TASKS = {}     # run_id -> asyncio.Task


def load_runs_from_disk():
    """从 _internal/output/ 重建历史出图。

    RUNS 只是内存字典，服务一重启页面就失忆。这里在启动时把磁盘上的
    归档读回来，页面才能一打开就看到全部历史，而不用手点文件夹。

    两种布局都认：
      output/<系列>/<run_id>/prompt.json   新布局 —— 同一流程收在同一个系列文件夹里
      output/<run_id>/prompt.json          老布局，归入「未归类」
    """
    outdir = abspath(PTH["output_dir"])
    if not outdir.is_dir():
        return 0
    added = 0
    metas = list(outdir.glob("*/prompt.json")) + list(outdir.glob("*/*/prompt.json"))
    for meta_path in sorted(metas, key=lambda p: str(p)):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        run_dir = meta_path.parent
        parent = run_dir.parent
        series = parent.name if parent != outdir else DEFAULT_SERIES
        run_id = meta.get("run_id") or run_dir.name
        if run_id in RUNS:
            continue
        items = []
        for it in meta.get("items") or []:
            items.append({"index": it.get("index", 0),
                          "seed": it.get("seed"),
                          "prompt_id": it.get("prompt_id"),
                          "status": "done",
                          "images": [],
                          "files": list(it.get("files") or []),
                          "notes": it.get("params")})
        if not items:
            continue
        created = meta.get("created")
        if not created:
            created = datetime.fromtimestamp(meta_path.stat().st_mtime).isoformat(timespec="seconds")
        RUNS[run_id] = {"run_id": run_id, "created": created,
                        "positive": meta.get("positive"), "negative": meta.get("negative"),
                        "series": meta.get("series") or series,
                        "count": meta.get("requested_count") or len(items),
                        "saved": meta.get("saved_count"),
                        "dir": str(run_dir), "items": items, "errors": [],
                        "status": "archived", "from_disk": True}
        added += 1
    if added:
        log("已从磁盘恢复 %d 次历史出图" % added)
    return added


def load_workflow():
    """每次出图都重新读盘，保证用的是最新的工作流文件。"""
    return json.loads(abspath(PTH["workflow"]).read_text(encoding="utf-8-sig"))


def _link_nodes(wf, start_ids):
    """沿连线广度优先收集链路里的 PrimitiveStringMultiline 节点 id。"""
    out, seen, queue = [], set(), list(start_ids)
    while queue:
        nid = queue.pop(0)
        if nid in seen or nid not in wf:
            continue
        seen.add(nid)
        node = wf[nid]
        if node.get("class_type") == "PrimitiveStringMultiline":
            out.append(nid)
            continue
        for value in (node.get("inputs") or {}).values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                queue.append(value[0])
    return out


def find_first(wf, *class_types):
    for nid, node in wf.items():
        if node.get("class_type") in class_types:
            return nid
    return None


def set_prompt(wf, link, text):
    """把文本写进链路末端（用户自定义内容）的那个字符串节点。"""
    if not text:
        return None
    if not link:
        return {"error": "未找到提示词链路"}
    entry_id = link[0]
    prims = _link_nodes(wf, [entry_id])
    if prims:
        target = prims[-1]
        wf[target]["inputs"]["value"] = text
        return {"node": target, "class_type": "PrimitiveStringMultiline", "chars": len(text)}
    node = wf.get(entry_id)
    if node and isinstance(node.get("inputs"), dict) and "text" in node["inputs"]:
        node["inputs"]["text"] = text
        return {"node": entry_id, "class_type": node.get("class_type"), "chars": len(text)}
    return {"error": "无法定位提示词节点"}


def ensure_save_node(wf, prefix):
    """确保工作流会把图片真正保存下来（PreviewImage 只在内存预览、落在 temp 目录）。"""
    for nid, node in wf.items():
        if node.get("class_type") == "SaveImage":
            node["inputs"]["filename_prefix"] = prefix
            return {"node": nid, "action": "set_prefix"}
    if CFG["defaults"].get("replace_preview_with_save", True):
        for nid, node in wf.items():
            if node.get("class_type") == "PreviewImage":
                wf[nid] = {"class_type": "SaveImage",
                           "inputs": {"images": node["inputs"].get("images"), "filename_prefix": prefix},
                           "_meta": {"title": "保存图像（TagSDanbooru 自动替换）"}}
                return {"node": nid, "action": "PreviewImage->SaveImage"}
    return {"action": "none", "note": "工作流里没有 PreviewImage/SaveImage，出图不会被保存"}


def patch_workflow(wf, opts):
    """把出图参数写进工作流副本，返回改写说明（便于界面/日志核对）。"""
    notes = {}

    ckpt_id = find_first(wf, "CheckpointLoaderSimple", "UNETLoader", "CheckpointLoader")
    if ckpt_id and opts.get("model"):
        ins = wf[ckpt_id]["inputs"]
        key = "ckpt_name" if "ckpt_name" in ins else ("unet_name" if "unet_name" in ins else None)
        if key:
            ins[key] = opts["model"]
            notes["model"] = {"node": ckpt_id, key: opts["model"]}

    sampler_id = find_first(wf, "KSampler", "KSamplerAdvanced")
    pos_link = neg_link = None
    if sampler_id:
        inputs = wf[sampler_id]["inputs"]
        if opts.get("seed") is not None:
            inputs["seed"] = int(opts["seed"])
        for key in ("steps", "cfg", "sampler_name", "scheduler", "denoise"):
            if opts.get(key) is not None:
                inputs[key] = opts[key]
        pos_link, neg_link = inputs.get("positive"), inputs.get("negative")
        notes["sampler"] = {"node": sampler_id, "steps": inputs.get("steps"), "cfg": inputs.get("cfg"),
                            "sampler_name": inputs.get("sampler_name"),
                            "scheduler": inputs.get("scheduler"), "seed": inputs.get("seed")}
    else:
        notes["sampler"] = {"error": "工作流中没有 KSampler"}

    latent_id = find_first(wf, "EmptyLatentImage", "EmptySD3LatentImage")
    if latent_id:
        if opts.get("width"):
            wf[latent_id]["inputs"]["width"] = int(opts["width"])
        if opts.get("height"):
            wf[latent_id]["inputs"]["height"] = int(opts["height"])
        notes["latent"] = {"node": latent_id, "width": wf[latent_id]["inputs"].get("width"),
                           "height": wf[latent_id]["inputs"].get("height")}

    notes["positive"] = set_prompt(wf, pos_link, opts.get("positive"))
    if opts.get("negative"):
        notes["negative"] = set_prompt(wf, neg_link, opts["negative"])
    notes["output"] = ensure_save_node(wf, opts.get("filename_prefix") or CFG["defaults"]["filename_prefix"])
    return notes


async def archive_run(app, run):
    """把出图从 ComfyUI 取回并存到项目 _internal/output/<系列>/<run_id>/。"""
    client = app["client"]
    outdir = Path(run["dir"])
    outdir.mkdir(parents=True, exist_ok=True)
    saved = 0
    for item in run["items"]:
        item["files"] = []
        for k, im in enumerate(item.get("images") or []):
            params = {"filename": im.get("filename"), "subfolder": im.get("subfolder") or "",
                      "type": im.get("type") or "output"}
            try:
                async with client.get(COMFY_BASE + "/view", params=params) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.read()
            except Exception:
                continue
            # 文件名带序号 + 种子，在文件夹里也能一眼认出哪张是哪个种子
            ext = os.path.splitext(im.get("filename") or "")[1] or ".png"
            seed = item.get("seed")
            tail = "" if k == 0 else "_%d" % (k + 1)
            name = "%02d%s%s%s" % (item["index"] + 1,
                                   ("_seed%s" % seed) if seed is not None else "",
                                   tail, ext)
            (outdir / name).write_bytes(data)
            item["files"].append(name)
            saved += 1
    run["saved"] = saved
    meta = {"run_id": run["run_id"], "created": run["created"], "series": run.get("series"),
            "positive": run["positive"],
            "negative": run.get("negative"), "requested_count": run["count"], "saved_count": saved,
            "items": [{"index": it["index"], "seed": it.get("seed"), "prompt_id": it.get("prompt_id"),
                       "files": it.get("files", []), "params": it.get("notes")} for it in run["items"]]}
    (outdir / "prompt.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    log("归档完成：%s（%d 张）-> %s" % (run["run_id"], saved, outdir))


async def track_run(app, run_id):
    """后台跟踪一个 run 的所有 prompt，全部完成后归档。"""
    run = RUNS[run_id]
    started = time.time()
    try:
        while True:
            for item in run["items"]:
                if item["status"] != "pending":
                    continue
                try:
                    hist = await proxy_json(app, "/history/" + str(item["prompt_id"]))
                except Exception:
                    continue
                entry = hist.get(str(item["prompt_id"]))
                if not entry:
                    continue
                images = []
                for out in (entry.get("outputs") or {}).values():
                    for im in (out.get("images") or []):
                        images.append(im)
                if images:
                    item["images"] = images
                item["exec_status"] = (entry.get("status") or {}).get("status_str")
                item["status"] = "done"
            # 处理被「清空队列 / 中断」掉的项（提交后给 6 秒宽限期，避免误判）
            if time.time() - started > 6:
                try:
                    q = await proxy_json(app, "/queue")
                    alive = {str(x[1]) for x in (q.get("queue_running") or [])}
                    alive |= {str(x[1]) for x in (q.get("queue_pending") or [])}
                    for item in run["items"]:
                        if item["status"] == "pending" and str(item["prompt_id"]) not in alive:
                            item["status"] = "cancelled"
                except Exception:
                    pass
            if all(it["status"] != "pending" for it in run["items"]):
                break
            await asyncio.sleep(1.0)
        await archive_run(app, run)
        run["status"] = "done"
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        run["status"] = "error"
        run["error"] = str(exc)
        log("run %s 出错：%s" % (run_id, exc))


def _run_dir_alive(run):
    """拿到 run 的实际目录；已完成、但目录已不在磁盘上的批次返回 None。

    用户会通过「在资源管理器中打开」按钮手动整理 output/，所以目录可能被移动或删除。
    这时先按 run_id 重新定位一次；确实找不到就不再展示，免得画廊里留下打不开的图块。
    """
    run_dir = Path(run["dir"])
    if not run_dir.is_dir():
        try:
            run_dir = _resolve_run_dir(abspath(PTH["output_dir"]).resolve(), run["run_id"], None)
        except Exception:
            run_dir = Path(run["dir"])
    if run.get("status") != "running" and not run_dir.is_dir():
        return None
    return run_dir


def _run_public(run):
    """给前端的 run 视图（目录已消失的已完成批次返回 None，由调用方跳过）"""
    run_dir = _run_dir_alive(run)
    if run_dir is None:
        return None
    # 文件路径直接从 run 目录反推，系列化之后不再是 output/<run_id> 这个固定形状
    try:
        rel = run_dir.resolve().relative_to(ROOT).as_posix()
    except Exception:
        rel = Path(PTH["output_dir"]).as_posix() + "/" + run["run_id"]
    base = "/" + rel
    items = []
    for it in run["items"]:
        live = []
        for im in it.get("images") or []:
            query = urlencode({"filename": im.get("filename") or "",
                               "subfolder": im.get("subfolder") or "",
                               "type": im.get("type") or "output"})
            live.append("/api/view?" + query)
        # 只认磁盘上真实存在的文件：用户在资源管理器里删掉图之后，这里立刻不再展示它
        files = [f for f in it.get("files", []) if (run_dir / f).is_file()]
        # 生成中的批次保留所有格子（含"等待中"）；已完成的批次跳过没图的格子，
        # 避免删掉某张后留下永远转圈的占位
        if run.get("status") != "running" and not files and not live:
            continue
        items.append({
            "index": it["index"],
            "status": it["status"],
            "seed": it.get("seed"),
            "files": [base + "/" + f for f in files],
            "live": live,
            "params": it.get("notes"),
        })
    return {
        "run_id": run["run_id"], "created": run["created"], "status": run["status"],
        "series": run.get("series") or DEFAULT_SERIES,
        "series_dir": series_rel(run.get("series")),
        "positive": run["positive"], "count": run["count"], "queued": len(run["items"]),
        "saved": run.get("saved"), "error": run.get("error"),
        "done_count": sum(1 for it in run["items"] if it["status"] == "done"),
        "items": items,
    }


async def handle_generate(request):
    try:
        opts = await request.json()
    except Exception:
        return json_response({"ok": False, "error": "请求体必须是 JSON"}, 400)

    positive = (opts.get("positive") or "").strip()
    if not positive:
        return json_response({"ok": False, "error": "正向提示词不能为空"}, 400)

    count = max(1, min(int(opts.get("count") or 1), 200))
    series = sanitize_series(opts.get("series"))
    base_seed = opts.get("seed")
    # 同批 seed 跨度：默认 1 = 连号（相邻 seed 噪声相关，构图容易雷同）；
    # 探索阶段给个 6 位以上的大奇数，同批就能拿到差异明显的样本（详见 README「seed 跨度」）
    seed_stride = max(1, int(opts.get("seed_stride") or 1))
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:4]
    prefix_root = "%s/%s" % (CFG["defaults"].get("filename_prefix", "tagsd"), run_id)

    client = request.app["client"]
    items, errors = [], []
    for i in range(count):
        wf = load_workflow()
        per = dict(opts)
        per["filename_prefix"] = "%s/%02d" % (prefix_root, i + 1)
        per["seed"] = (int(base_seed) + i * seed_stride) if base_seed is not None \
            else random.randint(0, 2 ** 31 - 1)
        notes = patch_workflow(wf, per)
        try:
            async with client.post(COMFY_BASE + "/prompt",
                                   json={"prompt": wf, "client_id": CLIENT_ID}) as resp:
                data = await resp.json()
        except Exception as exc:
            errors.append({"index": i + 1, "error": str(exc)})
            continue
        if data.get("node_errors"):
            errors.append({"index": i + 1, "error": "节点校验失败", "node_errors": data["node_errors"]})
            continue
        items.append({"index": i, "prompt_id": data.get("prompt_id"), "seed": per["seed"],
                      "number": data.get("number"), "status": "pending", "images": [], "notes": notes})

    run = {"run_id": run_id, "created": datetime.now().isoformat(timespec="seconds"),
           "positive": positive, "negative": opts.get("negative"), "count": count,
           "series": series, "dir": str(series_dir_of(series) / run_id),
           "items": items, "errors": errors,
           "status": "running" if items else "failed"}
    RUNS[run_id] = run
    if items:
        TASKS[run_id] = asyncio.ensure_future(track_run(request.app, run_id))
        log("提交 %s（系列 %s）：%d 张，队列位置 %s"
            % (run_id, series, len(items), items[0].get("number")))
    return json_response({"ok": bool(items), "run_id": run_id, "queued": len(items),
                          "errors": errors, "detected": items[0]["notes"] if items else None})


async def handle_run(request):
    run = RUNS.get(request.match_info["run_id"])
    if not run:
        return json_response({"ok": False, "error": "找不到该 run"}, 404)
    view = _run_public(run)
    if not view:
        return json_response({"ok": False, "error": "这一批的图片已不在磁盘上"}, 404)
    return json_response({"ok": True, "run": view})


async def handle_runs(request):
    views = (_run_public(r) for r in sorted(RUNS.values(), key=lambda r: r["created"], reverse=True))
    return json_response({"ok": True, "runs": [v for v in views if v][:50]})


async def handle_reveal(request):
    """在资源管理器里打开出图文件夹（图片则直接选中该文件）。

    只允许项目目录内的路径，避免被构造成 ..\\..\\ 去打开任意位置。
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    run_id = (body.get("run_id") or "").strip()
    if run_id:
        run = RUNS.get(run_id)
        target = Path(run["dir"]) if (run and run.get("dir")) else (abspath(PTH["output_dir"]) / run_id)
    elif body.get("rel"):
        target = abspath(str(body["rel"]))
    else:
        target = abspath(PTH["output_dir"])

    if os.name != "nt":
        return json_response({"ok": False, "error": "此功能仅支持 Windows"}, 400)

    try:
        resolved = target.resolve()
    except Exception as exc:
        return json_response({"ok": False, "error": "路径无效：%s" % exc}, 400)

    root = ROOT.resolve()
    if resolved != root and root not in resolved.parents:
        return json_response({"ok": False, "error": "拒绝访问项目目录之外的路径"}, 403)
    if not resolved.exists():
        return json_response({"ok": False, "error": "路径不存在：%s" % resolved}, 404)

    try:
        if resolved.is_dir():
            os.startfile(str(resolved))
        else:
            subprocess.Popen('explorer /select,"%s"' % resolved)
    except Exception as exc:
        return json_response({"ok": False, "error": "打开失败：%s" % exc}, 500)

    log("已在资源管理器中打开：%s" % resolved)
    return json_response({"ok": True, "path": str(resolved)})


# ================================================================ 删除（送回收站）

def _to_recycle_bin(path):
    """把文件或目录送进 Windows 回收站。成功返回 True。

    用 Windows 内置的 VB 文件 API（无需第三方库）。
    失败返回 False —— 调用方必须报错而不是退化成永久删除，
    杜绝「以为进了回收站、其实永久删了」这种情况。
    """
    if os.name != "nt":
        return False
    p = str(path)
    if '"' in p:
        return False
    if Path(p).is_dir():
        call = ('[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory('
                '"%s","OnlyErrorDialogs","SendToRecycleBin")' % p)
    else:
        call = ('[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile('
                '"%s","OnlyErrorDialogs","SendToRecycleBin")' % p)
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                            "Add-Type -AssemblyName Microsoft.VisualBasic; " + call],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            log("回收站 API 返回非零：%s" % (r.stderr or "").strip()[:200])
        return r.returncode == 0
    except Exception as exc:
        log("调用回收站 API 失败：%s" % exc)
        return False


def _rewrite_prompt_json(run_dir, run):
    """把内存里的 item 状态写回 prompt.json，保证删除后记录一致。"""
    meta = {"run_id": run["run_id"], "created": run["created"], "series": run.get("series"),
            "positive": run["positive"],
            "negative": run.get("negative"), "requested_count": run["count"],
            "saved_count": sum(len(it.get("files") or []) for it in run["items"]),
            "items": [{"index": it["index"], "seed": it.get("seed"), "prompt_id": it.get("prompt_id"),
                       "files": it.get("files") or [], "params": it.get("notes")}
                      for it in run["items"]]}
    try:
        (Path(run_dir) / "prompt.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        log("重写 prompt.json 失败：%s" % exc)


def _resolve_run_dir(out_root, run_id, run=None):
    """定位 run 目录。

    系列化之后 run 不再是 output 的直接子目录，所以优先用记录里的真实路径；
    没有记录时，按「新布局 output/<系列>/<run_id>」和「老布局 output/<run_id>」依次找。
    """
    if run and run.get("dir"):
        try:
            return Path(run["dir"]).resolve()
        except Exception:
            pass
    legacy = out_root / run_id
    if legacy.is_dir():
        return legacy.resolve()
    hits = [p for p in out_root.glob("*/" + run_id) if p.is_dir()]
    return (hits[0] if hits else legacy).resolve()


def _prune_empty_series(run_dir, out_root):
    """一批被删空之后，如果所属系列也空了，把系列文件夹一起送回收站。"""
    parent = run_dir.parent
    if parent == out_root:
        return
    try:
        if not parent.is_dir() or any(parent.iterdir()):
            return
    except OSError:
        return
    if _to_recycle_bin(parent):
        log("系列已空，一并送回收站：%s" % parent)


async def handle_delete(request):
    """删除单张出图或整批出图 —— 送进 Windows 回收站，可还原。

    范围硬限制在 _internal/output/ 之内（比 reveal 更严）；
    送回收站失败就报错不删。
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    run_id = (body.get("run_id") or "").strip()
    file_name = (body.get("file") or "").strip()
    if not run_id:
        return json_response({"ok": False, "error": "缺少 run_id"}, 400)
    for v in (run_id, file_name):
        if any(c in v for c in ("/", "\\", "..", ":")):
            return json_response({"ok": False, "error": "参数不合法"}, 400)

    run = RUNS.get(run_id)
    if run and run.get("status") == "running":
        return json_response({"ok": False, "error": "这一批还在生成中，请先中断再删"}, 409)

    out_root = abspath(PTH["output_dir"]).resolve()
    try:
        run_dir = _resolve_run_dir(out_root, run_id, run)
    except Exception as exc:
        return json_response({"ok": False, "error": "路径无效：%s" % exc}, 400)

    if run_dir == out_root or out_root not in run_dir.parents:
        return json_response({"ok": False, "error": "拒绝删除 output 目录之外的内容"}, 403)

    if not run_dir.is_dir():
        RUNS.pop(run_id, None)
        TASKS.pop(run_id, None)
        return json_response({"ok": True, "deleted": 0, "removed_run": True,
                              "note": "目录已不存在，只清理了记录"})

    # ---------------- 删单张 ----------------
    if file_name:
        fpath = run_dir / file_name
        if not fpath.is_file():
            return json_response({"ok": False, "error": "找不到这张图：%s" % file_name}, 404)
        if not _to_recycle_bin(fpath):
            return json_response({"ok": False, "error": "送回收站失败，为安全起见没有删除"}, 500)
        log("已删除（送回收站）：%s" % fpath)

        removed_run = True
        if run:
            for it in run["items"]:
                it["files"] = [f for f in (it.get("files") or []) if f != file_name]
            # 同步内存里的 saved，避免界面显示的张数对不上
            run["saved"] = sum(len(it.get("files") or []) for it in run["items"])
            removed_run = not any(it.get("files") for it in run["items"])

        if removed_run:
            RUNS.pop(run_id, None)
            TASKS.pop(run_id, None)
            if _to_recycle_bin(run_dir):
                log("这一批已无图片，整批送回收站：%s" % run_dir)
            else:
                log("警告：整批目录送回收站失败，已留在原处：%s" % run_dir)
            _prune_empty_series(run_dir, out_root)
        elif run:
            _rewrite_prompt_json(run_dir, run)
        return json_response({"ok": True, "deleted": 1, "removed_run": removed_run})

    # ---------------- 删整批 ----------------
    if not _to_recycle_bin(run_dir):
        return json_response({"ok": False, "error": "送回收站失败，为安全起见没有删除"}, 500)
    RUNS.pop(run_id, None)
    TASKS.pop(run_id, None)
    log("已删除整批（送回收站）：%s" % run_dir)
    _prune_empty_series(run_dir, out_root)
    return json_response({"ok": True, "deleted": -1, "removed_run": True})


async def handle_interrupt(request):
    client = request.app["client"]
    try:
        async with client.post(COMFY_BASE + "/interrupt") as resp:
            return json_response({"ok": True, "status": resp.status})
    except Exception as exc:
        return json_response({"ok": False, "error": str(exc)}, 502)


async def handle_free(request):
    client = request.app["client"]
    try:
        async with client.post(COMFY_BASE + "/free",
                               json={"unload_models": True, "free_memory": True}) as resp:
            return json_response({"ok": True, "status": resp.status})
    except Exception as exc:
        return json_response({"ok": False, "error": str(exc)}, 502)


def _current_text(wf, link):
    if not link:
        return None
    prims = _link_nodes(wf, [link[0]])
    if prims:
        return wf[prims[-1]]["inputs"].get("value")
    node = wf.get(link[0])
    return (node.get("inputs") or {}).get("text") if node else None


async def handle_workflow(request):
    """把当前工作流里的默认值交给界面（模型、采样参数、尺寸、负面词）。"""
    try:
        wf = load_workflow()
    except Exception as exc:
        return json_response({"ok": False, "error": "读取工作流失败: %s" % exc}, 500)

    info = {"ok": True, "path": PTH["workflow"]}
    nodes = {}
    ckpt_id = find_first(wf, "CheckpointLoaderSimple", "UNETLoader", "CheckpointLoader")
    if ckpt_id:
        ins = wf[ckpt_id]["inputs"]
        nodes["model"] = {"node": ckpt_id, "value": ins.get("ckpt_name") or ins.get("unet_name")}
    sampler_id = find_first(wf, "KSampler", "KSamplerAdvanced")
    if sampler_id:
        ins = wf[sampler_id]["inputs"]
        nodes["sampler"] = {"node": sampler_id,
                            **{k: ins.get(k) for k in ("steps", "cfg", "sampler_name", "scheduler", "denoise")}}
        neg_link = ins.get("negative")
        nodes["negative"] = {"node": (neg_link[0] if neg_link else None),
                             "text": _current_text(wf, neg_link)}
        pos_link = ins.get("positive")
        prims = _link_nodes(wf, [pos_link[0]]) if pos_link else []
        target_id = prims[-1] if prims else (pos_link[0] if pos_link else None)
        nodes["positive"] = {"chain": prims,
                             "base": wf[prims[0]]["inputs"].get("value") if prims else None,
                             "target": target_id,
                             "target_text": _current_text(wf, [target_id, 0]) if target_id else None}
    latent_id = find_first(wf, "EmptyLatentImage", "EmptySD3LatentImage")
    if latent_id:
        nodes["latent"] = {"node": latent_id, "width": wf[latent_id]["inputs"].get("width"),
                           "height": wf[latent_id]["inputs"].get("height")}
    info["nodes"] = nodes
    return json_response(info)


async def handle_workflow_prompts(request):
    """把界面上的「工作流预设词」（正向 base = 第一个前缀节点，负面 = 负面链路）写回工作流文件。

    与出图的临时替换不同：这里是**真的改** PTH["workflow"] 这个 json，所以先写临时文件再 os.replace。
    """
    try:
        opts = await request.json()
    except Exception:
        return json_response({"ok": False, "error": "请求体必须是 JSON"}, 400)
    if not isinstance(opts, dict):
        return json_response({"ok": False, "error": "请求体必须是 JSON"}, 400)
    try:
        wf = load_workflow()
    except Exception as exc:
        return json_response({"ok": False, "error": "读取工作流失败: %s" % exc}, 500)

    sampler_id = find_first(wf, "KSampler", "KSamplerAdvanced")
    if not sampler_id:
        return json_response({"ok": False, "error": "工作流里找不到 KSampler"}, 400)
    ins = wf[sampler_id]["inputs"]
    result = {}

    if "positive_base" in opts:
        text = opts.get("positive_base") or ""
        pos_link = ins.get("positive")
        prims = _link_nodes(wf, [pos_link[0]]) if pos_link else []
        if not prims:
            return json_response({"ok": False, "error": "找不到正向的固定前缀节点"}, 400)
        wf[prims[0]]["inputs"]["value"] = text
        result["positive_base"] = {"node": prims[0], "chars": len(text)}

    if "negative" in opts:
        text = opts.get("negative") or ""
        neg_link = ins.get("negative")
        if not neg_link:
            return json_response({"ok": False, "error": "找不到负面链路"}, 400)
        prims = _link_nodes(wf, [neg_link[0]])
        if prims:
            wf[prims[-1]]["inputs"]["value"] = text
            result["negative"] = {"node": prims[-1], "chars": len(text)}
        else:
            node = wf.get(neg_link[0])
            if node and isinstance(node.get("inputs"), dict) and "text" in node["inputs"]:
                node["inputs"]["text"] = text
                result["negative"] = {"node": neg_link[0], "chars": len(text)}
            else:
                return json_response({"ok": False, "error": "无法定位负面提示词节点"}, 400)

    path = abspath(PTH["workflow"])
    try:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(wf, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception as exc:
        return json_response({"ok": False, "error": "写入工作流失败: %s" % exc}, 500)

    log("工作流预设词已更新：%s" % result)
    return json_response({"ok": True, "nodes": result, "path": PTH["workflow"]})


# ================================================================ 页面窗口（单实例）

BROWSER_PROFILE = INTERNAL / ".browser" / "profile"

_BROWSER_CANDIDATES = (
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe",
)

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0)

# 反查「命令行里带本项目独立 profile」的进程。用 profile 路径判断比记 PID 可靠：
# PID 会被系统复用，profile 路径不会；而且只有我们自己启动的窗口才带这个路径，
# 绝不会碰到你日常浏览器里的任何窗口或标签页。
_PROFILE_QUERY = (
    "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
    "Where-Object { $_.CommandLine -and "
    "$_.CommandLine.ToLower().Contains(($env:TAGSD_PROFILE).ToLower()) } | "
    "ForEach-Object { $_.ProcessId }"
)


def find_browser_exe():
    """配置里指定了就用指定的，否则在常见路径里找。找不到返回 None。"""
    want = (SRV.get("browser_exe") or "").strip()
    if want:
        expanded = Path(os.path.expandvars(want))
        if expanded.exists():
            return str(expanded)
        log("配置的浏览器找不到：%s（改为自动查找）" % want)
    for cand in _BROWSER_CANDIDATES:
        p = Path(os.path.expandvars(cand))
        if p.exists():
            return str(p)
    return None


def _profile_browser_pids():
    """返回所有使用本项目独立 profile 的浏览器进程号。"""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PROFILE_QUERY],
            capture_output=True, text=True, timeout=25,
            creationflags=_NO_WINDOW,
            env=dict(os.environ, TAGSD_PROFILE=str(BROWSER_PROFILE)))
    except Exception as exc:
        log("查询页面窗口进程失败：%s" % exc)
        return []
    return [int(x) for x in (out.stdout or "").split() if x.strip().isdigit()]


def close_page_window():
    """关掉上一次由本程序打开的页面窗口。返回是否真的关掉了东西。"""
    pids = _profile_browser_pids()
    if not pids:
        return False
    killed = 0
    for pid in pids:
        try:
            r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               capture_output=True, text=True, timeout=15,
                               creationflags=_NO_WINDOW)
            if r.returncode == 0:
                killed += 1
        except Exception:
            pass
    if killed:
        log("已关闭上一次的页面窗口（%d 个进程）" % killed)
    return killed > 0


def open_page_window(url):
    """用独立 profile 开一个「应用窗口」：没有地址栏，像一个独立小工具。

    因为 profile 是项目专属的，它和系统默认浏览器完全隔离 —— 你日常浏览器的
    标签页不会被这个项目塞进任何东西；下次启动时也能凭 profile 路径精确关掉它。
    """
    exe = find_browser_exe()
    if not exe:
        return False
    try:
        BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log("创建浏览器 profile 失败：%s" % exc)
        return False
    args = [exe,
            "--app=" + url,
            "--user-data-dir=" + str(BROWSER_PROFILE),
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate,MediaRouter,ChromeWhatsNewUI",
            "--window-size=1380,940"]
    try:
        subprocess.Popen(args, creationflags=_NO_WINDOW | _DETACHED)
    except Exception as exc:
        log("启动应用窗口失败：%s" % exc)
        return False
    return True


# ================================================================ 终端（单实例）

SESSION_FILE = INTERNAL / ".session.json"


def _win_proc(target_pid):
    """查进程的 (名称, 父PID, 创建时间, 命令行)；查不到返回 None。"""
    script = ("$p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $env:TARGET) "
              "-ErrorAction SilentlyContinue; "
              "if ($p) { ($p.Name + '|' + $p.ParentProcessId + '|' + $p.CreationDate + '|' + $p.CommandLine) }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                             capture_output=True, text=True, timeout=25,
                             creationflags=_NO_WINDOW,
                             env=dict(os.environ, TARGET=str(int(target_pid))))
    except Exception:
        return None
    parts = (out.stdout or "").strip().split("|", 3)
    if len(parts) < 3 or not parts[0]:
        return None
    try:
        ppid = int(parts[1] or 0)
    except ValueError:
        ppid = 0
    return {"name": parts[0], "ppid": ppid, "created": parts[2],
            "cmd": parts[3] if len(parts) > 3 else ""}


def _kill_tree(pid):
    try:
        subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                       capture_output=True, text=True, timeout=15, creationflags=_NO_WINDOW)
        return True
    except Exception:
        return False


def record_session():
    """记下自己的 PID 和「启动我的那个终端窗口」，供下一次启动时接管。

    只在从 启动.bat 拉起时记录（它设了 TAGSD_TERMINAL）。如果有人在自己已经开着的
    命令行里手动跑 server.py，就什么都不记 —— 那种情况下「父进程」是用户自己的终端，
    绝不能被下一个人关掉。
    """
    if not os.environ.get("TAGSD_TERMINAL"):
        return
    me = _win_proc(os.getpid())
    if not me or not me["ppid"]:
        return
    term = _win_proc(me["ppid"])
    if not term or term["name"].lower() != "cmd.exe":
        return
    if "/c" not in (term["cmd"] or "").lower():
        return                       # 在交互式 cmd 里手敲的 bat：那是用户自己的窗口
    try:
        SESSION_FILE.write_text(json.dumps(
            {"server_pid": os.getpid(), "term_pid": me["ppid"], "term_created": term["created"]},
            ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _kill_launcher_terminal(term_pid):
    """如果这个 PID 是 启动.bat 开出来的 cmd 窗口，就关掉它。拿不准就不动。"""
    if not term_pid:
        return False
    info = _win_proc(term_pid)
    if not info or info["name"].lower() != "cmd.exe":
        return False
    if "/c" not in (info["cmd"] or "").lower():
        return False                     # 交互式 cmd：那是用户自己的窗口，别碰
    if _kill_tree(term_pid):
        log("已关闭上一次的终端窗口（PID=%d）" % term_pid)
        return True
    return False


def close_previous_terminal():
    """关掉上一次由 启动.bat 开出来的那个终端窗口（按记录里的 PID + 创建时间核对）。"""
    try:
        sess = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return False
    try:
        pid = int(sess.get("term_pid") or 0)
    except (TypeError, ValueError):
        return False
    if not pid:
        return False
    info = _win_proc(pid)
    if not info:
        return False
    # PID 会被系统复用；创建时间对不上，就说明这已经不是当初那个窗口了
    if sess.get("term_created") and info["created"] != sess["term_created"]:
        log("跳过关闭 PID=%d：创建时间不符（PID 已被复用）" % pid)
        return False
    return _kill_launcher_terminal(pid)


def _port_listening():
    try:
        with socket.create_connection((SRV["host"], int(SRV["port"])), timeout=0.5):
            return True
    except OSError:
        return False


def _wait_port_free(timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _port_listening():
            return True
        time.sleep(0.5)
    return not _port_listening()


def _listener_pids(port):
    """谁在监听这个端口。"""
    script = ("$c = Get-NetTCPConnection -LocalPort ([int]$env:PORT) -State Listen "
              "-ErrorAction SilentlyContinue; "
              "if ($c) { $c | Select-Object -ExpandProperty OwningProcess }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                             capture_output=True, text=True, timeout=25,
                             creationflags=_NO_WINDOW,
                             env=dict(os.environ, PORT=str(int(port))))
    except Exception:
        return []
    return sorted({int(x) for x in (out.stdout or "").split() if x.strip().isdigit()})


def _shutdown_instance(pid):
    """请某个实例优雅退出（它会自己停 ComfyUI、关掉页面窗口）；不听话就强制结束。"""
    log("正在关闭上一次的服务（PID=%d）…" % pid)
    try:
        req = urllib.request.Request(
            "http://%s:%d/local/shutdown" % (SRV["host"], int(SRV["port"])),
            data=b"", method="POST")
        urllib.request.urlopen(req, timeout=8).read()
    except Exception:
        pass
    if not _wait_port_free(30):
        log("它没有自己退出，强制结束")
        _kill_tree(pid)
        _wait_port_free(8)


def takeover_previous_instance():
    """启动前：让上一次的服务干净退出，并关掉它的终端窗口。

    这是「反复双击 启动.bat 不会堆一屏窗口」的关键 —— 页面窗口和终端窗口
    都只留最新那一个。
    """
    try:
        sess = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except Exception:
        sess = {}
    try:
        prev = int(sess.get("server_pid") or 0)
    except (TypeError, ValueError):
        prev = 0

    done = False
    if prev and prev != os.getpid():
        info = _win_proc(prev)
        if info and "server.py" in (info["cmd"] or ""):
            _shutdown_instance(prev)
            done = True

    # 兜底：没有记录（比如上一次跑的是没有本功能的旧版本）但端口还被占着。
    # 按「谁占着端口」反查，并且必须确认那个进程确实在跑本项目的 server.py 才动手 ——
    # 否则宁可启动失败，也不能去关别人的程序。
    if not done and _port_listening():
        for pid in _listener_pids(SRV["port"]):
            info = _win_proc(pid)
            if not info or "server.py" not in (info["cmd"] or ""):
                log("端口 %s 被 PID=%d 占着，但它不是本项目的服务，不自动接管"
                    % (SRV["port"], pid))
                continue
            _shutdown_instance(pid)
            _kill_launcher_terminal(info["ppid"])
            if not _port_listening():
                break

    close_previous_terminal()
    try:
        SESSION_FILE.unlink()
    except OSError:
        pass


# ================================================================ 应用装配


async def open_browser_when_ready(url):
    """等端口真正可连接后再打开页面。

    single_window=true（默认）：先关掉上一次打开的页面窗口，再用独立 profile 开一个
    应用窗口 —— 反复双击 启动.bat 也始终只有一个页面。
    single_window=false：退回传统的 webbrowser.open()，即往你现有浏览器里开新标签页。
    """
    host, port = SRV["host"], int(SRV["port"])
    for _ in range(60):                      # 最多等 15 秒
        try:
            with socket.create_connection((host, port), timeout=0.5):
                break
        except OSError:
            await asyncio.sleep(0.25)

    if SRV.get("single_window", True):
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, close_page_window)
            opened = await loop.run_in_executor(None, open_page_window, url)
        except Exception as exc:
            opened = False
            log("独立窗口方式出错：%s" % exc)
        if opened:
            log("已打开页面窗口（独立 profile；下次启动会自动接管，不会堆窗口）")
            return
        log("独立窗口方式不可用，改用普通方式打开")

    ok = False
    try:
        ok = bool(webbrowser.open(url))
    except Exception:
        ok = False
    if not ok:                               # 兜底 1：Windows 直接交给系统默认程序
        try:
            os.startfile(url)
            ok = True
        except Exception:
            ok = False
    if not ok:                               # 兜底 2：走 cmd start
        try:
            subprocess.Popen(["cmd", "/c", "start", "", url])
            ok = True
        except Exception:
            ok = False

    if ok:
        log("已打开浏览器：%s" % url)
    else:
        log("自动打开浏览器失败，请手动访问：%s" % url)


async def on_startup(app):
    app["client"] = ClientSession(timeout=ClientTimeout(total=1800))
    load_runs_from_disk()
    ensure_tag_cache()
    if SRV.get("open_browser", True) and not os.environ.get("TAGSD_NO_BROWSER"):
        asyncio.ensure_future(open_browser_when_ready(PAGE_URL))
    else:
        log("已跳过自动打开浏览器（open_browser=%s 或 TAGSD_NO_BROWSER 已设置）" % SRV.get("open_browser", True))
    app["comfy_task"] = asyncio.ensure_future(COMFY.ensure_up())


async def on_cleanup(app):
    task = app.get("comfy_task")
    if task and not task.done():
        task.cancel()
    client = app.get("client")
    if client:
        await client.close()
    COMFY.stop()
    # 关掉本程序自己开的那个页面窗口：服务都停了，留着它只会变成死页面
    if SRV.get("single_window", True) and SRV.get("close_window_on_exit", True):
        try:
            await asyncio.get_running_loop().run_in_executor(None, close_page_window)
        except Exception:
            pass


@web.middleware
async def no_cache_static(request, handler):
    """静态文件（页面 / 图片）只走 ETag 协商缓存，别让浏览器拿启发式缓存糊住旧画面。

    output/ 里的图随时会被删、被重出；aiohttp 的静态响应只有 ETag / Last-Modified、
    不带 Cache-Control，Chromium 会自己「猜」一个保鲜期 —— 于是明明已经删掉的图，
    页面上还会从磁盘缓存里显示出来。JSON 接口本来就没设缓存，这里不动它们。
    """
    resp = await handler(request)
    if isinstance(resp, web.FileResponse):
        resp.headers.setdefault("Cache-Control", "no-cache")
    return resp


def build_app():
    app = web.Application(client_max_size=512 * 1024 * 1024, middlewares=[no_cache_static])
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    # 注意顺序：具体路由必须注册在静态目录之前
    app.router.add_get("/", handle_index)
    app.router.add_get("/local/ping", handle_ping)
    app.router.add_get("/local/status", handle_local_status)
    app.router.add_post("/local/shutdown", handle_shutdown)
    app.router.add_post("/local/generate", handle_generate)
    app.router.add_post("/local/interrupt", handle_interrupt)
    app.router.add_post("/local/free", handle_free)
    app.router.add_get("/local/runs", handle_runs)
    app.router.add_get("/local/run/{run_id}", handle_run)
    app.router.add_get("/local/workflow", handle_workflow)
    app.router.add_post("/local/workflow/prompts", handle_workflow_prompts)
    app.router.add_post("/local/reveal", handle_reveal)
    app.router.add_post("/local/delete", handle_delete)
    app.router.add_route("*", "/api/{tail:.*}", handle_api_proxy)

    app.router.add_static("/", ROOT, show_index=False, follow_symlinks=True)
    return app


def main():
    log("=" * 62)
    log("TagSDanbooru 本地服务")
    log("  项目根目录 : %s" % ROOT)
    log("  页面地址   : %s" % PAGE_URL)
    log("  ComfyUI    : %s" % COMFY_BASE)
    log("=" * 62)
    takeover_previous_instance()
    record_session()
    rc = 0
    try:
        web.run_app(build_app(), host=SRV["host"], port=SRV["port"],
                    print=None, access_log=None)
    except OSError as exc:
        log("端口 %s 无法监听：%s" % (SRV["port"], exc))
        log("可能已有另一个实例在运行；请先关闭它，或修改 _internal/config.json 的 server.port")
        rc = 2
    finally:
        COMFY.stop()
        log("服务已退出")
    # 退出码 0 = 正常关闭：启动.bat 会直接收起终端窗口，不再要你按任意键
    return rc


if __name__ == "__main__":
    sys.exit(main())

