# -*- coding: utf-8 -*-
"""页面冒烟测试：真加载一次页面，检查「有没有 JS 报错、数据有没有加载进来、筛选行有没有渲染」。

为什么需要它：check_js.py / check_js_syntax.py 只查函数有没有定义、括号配不配平，
查不出「注释少了个 //」这类语法错误 —— 那种错会让整段脚本解析失败，页面看起来就是
「加载不了 CSV」。这个脚本用系统里的 Chrome 无头模式跑一遍真实页面，几十秒就能发现。

用法:
    python _internal/dev/page_smoke.py
退出码 0 = 通过；1 = 有问题。
"""
import glob
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHROME_CANDIDATES = (
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
)


def find_browser():
    for pat in CHROME_CANDIDATES:
        for p in glob.glob(os.path.expandvars(pat)):
            if os.path.isfile(p):
                return p
    return None


def free_port(start=8899):
    import socket
    for port in range(start, start + 30):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    raise RuntimeError("找不到空闲端口")


def main():
    py = sys.executable
    browser = find_browser()
    if not browser:
        print("找不到 Chrome / Edge，跳过页面冒烟测试")
        return 0

    port = free_port()
    srv = subprocess.Popen([py, "-m", "http.server", str(port)], cwd=ROOT,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    problems = []
    try:
        url = "http://127.0.0.1:%d/TagSDanbooru.html" % port
        for _ in range(20):                       # 等静态服务起来
            try:
                urllib.request.urlopen(url, timeout=2).read(200)
                break
            except (urllib.error.URLError, OSError):
                time.sleep(0.3)

        r = subprocess.run(
            [browser, "--headless=new", "--disable-gpu", "--virtual-time-budget=20000",
             "--user-data-dir=" + os.path.join(os.environ.get("TEMP", "."), "chrome-tagsmoke"),
             "--enable-logging=stderr", "--log-level=0", "--dump-dom", url],
            capture_output=True, timeout=180)
        dom = r.stdout.decode("utf-8", "replace")
        err = r.stderr.decode("utf-8", "replace")

        js_errors = [l.strip() for l in err.splitlines()
                     if re.search(r"Uncaught|SyntaxError|ReferenceError|TypeError", l)]
        status = re.search(r'id="status-message"[^>]*>(.*?)</div>', dom, re.S)
        status = status.group(1).strip() if status else ""
        cards = len(re.findall(r'class="tag-item', dom))
        l1 = re.findall(r'<span>([^<]+)</span>', re.search(
            r'id="l1-filters"(.*?)<div id="l2-filters"', dom, re.S).group(1)) if 'id="l1-filters"' in dom else []
        l2 = re.findall(r'<span>([^<]+)</span>', re.search(
            r'id="l2-filters"(.*?)<div id="l1-note"', dom, re.S).group(1)) if 'id="l2-filters"' in dom else []

        print("控制台 JS 报错 :", len(js_errors), "条")
        for e in js_errors[:5]:
            print("   ", e[:200])
        print("加载状态       :", (status[:80] or "(没读到)"))
        print("标签卡片数     :", cards)
        print("一级按钮(%d)   : %s" % (len(l1), " / ".join(l1)))
        print("二级按钮(%d)   : %s" % (len(l2), " / ".join(l2[:14])))
        print("旧分类行已移除 :", 'id="category-filters"' not in dom)

        if js_errors:
            problems.append("页面有 JS 异常（脚本会整体失效，表现就是加载不了数据）")
        if "加载完成" not in status:
            problems.append("数据没有加载完成，状态为：%s" % (status[:60] or "空"))
        if cards == 0:
            problems.append("标签列表是空的")
        if not l1 or not l2:
            problems.append("一级 / 二级分类按钮没渲染出来")
    finally:
        srv.terminate()

    print("")
    if problems:
        for p in problems:
            print("FAIL", p)
        return 1
    print("页面冒烟测试：全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
