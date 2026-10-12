# -*- coding: utf-8 -*-
"""JS 词法级括号配平检查（正确处理字符串 / 模板串（含嵌套 ${}）/ 正则 / 注释）。

浏览器里没法看 console，所以用这个替代：语法层面的括号错配、字符串/模板串/正则
未闭合都能抓出来。它自己也有自检用例（见文件末尾），保证不会给出假的「通过」。
"""
import io
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def check(js):
    """返回第一个问题的描述，没问题返回 None。"""
    n = len(js)
    i = 0
    line = 1
    stack = []            # (字符, 行号, 是否来自模板串的 ${)
    prev = ""             # 上一个有意义的字符，用来区分正则 / 除号
    mode = "code"         # code | template

    while i < n:
        c = js[i]
        if c == "\n":
            line += 1

        if mode == "template":
            if c == "\\":
                i += 2
                continue
            if c == "`":
                stack.pop()
                mode = "code"
                prev = "`"
                i += 1
                continue
            if c == "$" and js[i + 1:i + 2] == "{":
                stack.append(("{", line, True))
                mode = "code"
                i += 2
                continue
            i += 1
            continue

        two = js[i:i + 2]
        if two == "//":
            j = js.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if two == "/*":
            j = js.find("*/", i + 2)
            if j < 0:
                return "第 %d 行：块注释未闭合" % line
            line += js.count("\n", i, j)
            i = j + 2
            continue
        if c == "`":
            stack.append(("`", line, False))
            mode = "template"
            i += 1
            continue
        if c in "\"'":
            i += 1
            while i < n:
                ch = js[i]
                if ch == "\\":
                    i += 2
                    continue
                if ch == "\n":
                    return "第 %d 行：字符串未闭合" % line
                if ch == c:
                    break
                i += 1
            i += 1
            prev = c
            continue
        if c == "/":
            if prev == "" or prev in "(,=:[!&|?{};+-*%~^<>":
                i += 1
                inclass = False
                while i < n:
                    ch = js[i]
                    if ch == "\\":
                        i += 2
                        continue
                    if ch == "\n":
                        return "第 %d 行：正则未闭合" % line
                    if ch == "[":
                        inclass = True
                    elif ch == "]":
                        inclass = False
                    elif ch == "/" and not inclass:
                        break
                    i += 1
                i += 1
                prev = "/"
                continue
            prev = c
            i += 1
            continue
        if c in "{([":
            stack.append((c, line, False))
            prev = c
            i += 1
            continue
        if c in "})]":
            want = {"}": "{", ")": "(", "]": "["}[c]
            if not stack or stack[-1][0] != want:
                return "第 %d 行：多余的 %s" % (line, c)
            _, _, from_tpl = stack.pop()
            if from_tpl:
                mode = "template"
            prev = c
            i += 1
            continue
        if not c.isspace():
            prev = c
        i += 1

    if stack:
        return "第 %d 行的 %s 未闭合" % (stack[-1][1], stack[-1][0])
    if mode == "template":
        return "模板字符串未闭合"
    return None


# ---------------- 自检：先证明这个检查器真的能抓到错误 ----------------
SELFTEST = [
    ("平衡的正常代码", "const a = f(1, [2, 3], {b: 'x'});", True),
    ("缺一个右括号", "function f() { return (1 + 2; }", False),
    ("多一个右括号", "const x = 1); ", False),
    ("嵌套模板串（本次误判的那种）", "el.innerHTML = `a ${c ? 'x' : `y ${d}`} b`;", True),
    ("字符串里的括号", "const s = '}({'; const t = \"]([\";", True),
    ("注释里的括号", "// }}}\n/* ((( */\nconst a = 1;", True),
    ("正则里的括号和斜杠", "const r = /[^a-z(){}]/g; s.replace(r, '_');", True),
    ("除号不能被当成正则", "const h = (w) / 2; const k = a / b / c;", True),
    ("模板串未闭合", "const s = `abc;", False),
]

print("=== 检查器自检 ===")
self_ok = True
for name, code, expect_pass in SELFTEST:
    problem = check(code)
    got_pass = (problem is None)
    mark = "OK " if got_pass == expect_pass else "!! "
    if got_pass != expect_pass:
        self_ok = False
    print("  %s%-32s -> %s" % (mark, name, "通过" if got_pass else ("报错：" + problem)))
print("  自检结论:", "检查器可信" if self_ok else "检查器本身有问题，结论不可信")

# ---------------- 正式检查 ----------------
HTML = str(Path(__file__).resolve().parent.parent.parent / "TagSDanbooru.html")
src = io.open(HTML, encoding="utf-8").read()
found = list(re.finditer(r"<script[^>]*>(.*?)</script>", src, re.S))
print()
print("=== 检查 %s ===" % HTML)
bad = 0
for k, m in enumerate(found):
    body = m.group(1)
    base = src.count("\n", 0, m.start(1)) + 1
    if not body.strip():
        continue                     # <script src=...></script>
    problem = check(body)
    if problem:
        bad += 1
        print("  块 %d（HTML 第 %d 行起，%d 字符）: %s" % (k + 1, base, len(body), problem))
    else:
        print("  块 %d（HTML 第 %d 行起，%d 字符）: 括号配平 OK" % (k + 1, base, len(body)))
print()
print("结果:", "全部通过" if (bad == 0 and self_ok) else ("%d 个块有问题" % bad))
