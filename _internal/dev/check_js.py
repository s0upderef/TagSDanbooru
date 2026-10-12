#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""粗略校验 TagSDanbooru.html 里内联 <script> 的括号/引号配平。

没有 node 时的兜底检查：能发现少了括号、引号没闭合、正则没闭合、
以及某个 <script> 块被插到别的块内部这类问题。
用法：  python _internal\\dev\\check_js.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# 「值」的结尾 —— 这之后出现的 / 是除号而不是正则
_VALUE_END = set(")]}")


def scan(src):
    """返回 None 表示配平，否则返回错误描述。

    用一个栈同时记录括号和模板串：
      * 栈顶是 'tpl'  -> 正在模板字符串里（只找 ` 或 ${）
      * 栈顶是括号    -> 正在普通代码里
    这样 ${ } 里的嵌套模板串能自然处理，模板里的 </div> 也不会被误认成正则。
    """
    i, n, line = 0, len(src), 1
    stack = []
    prev = ""

    def in_tpl():
        return bool(stack) and stack[-1] == "tpl"

    while i < n:
        c = src[i]

        if c == "\n":
            line += 1
            i += 1
            continue

        # ---------------- 模板字符串 ----------------
        if in_tpl():
            if c == "\\":                     # 转义
                if i + 1 < n and src[i + 1] == "\n":
                    line += 1
                i += 2
                continue
            if c == "`":
                stack.pop()
                prev = "x"
                i += 1
                continue
            if c == "$" and i + 1 < n and src[i + 1] == "{":
                stack.append("{")
                prev = ""
                i += 2
                continue
            i += 1
            continue

        # ---------------- 普通代码 ----------------
        if c in "'\"":
            q, start = c, line
            i += 1
            while i < n and src[i] != q:
                if src[i] == "\\":
                    i += 2
                    continue
                if src[i] == "\n":
                    return "第 %d 行：%s 字符串没有闭合" % (start, q)
                i += 1
            if i >= n:
                return "第 %d 行：%s 字符串没有闭合" % (start, q)
            i += 1
            prev = "x"
            continue

        if c == "`":
            stack.append("tpl")
            prev = ""
            i += 1
            continue

        if src.startswith("//", i):
            while i < n and src[i] != "\n":
                i += 1
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            if j < 0:
                return "第 %d 行：块注释没有闭合" % line
            line += src.count("\n", i, j)
            i = j + 2
            continue

        # 正则字面量：只在不可能当除号的位置才识别
        if c == "/" and (prev == "" or (prev not in _VALUE_END
                                        and not prev.isalnum() and prev not in "_$")):
            start = line
            i += 1
            closed = False
            while i < n and src[i] != "\n":
                if src[i] == "\\":
                    i += 2
                    continue
                if src[i] == "/":
                    closed = True
                    break
                i += 1
            if not closed:
                return "第 %d 行：正则字面量没有闭合" % start
            i += 1
            prev = "x"
            continue

        if c in "([{":
            stack.append(c)
        elif c in ")]}":
            if not stack:
                return "第 %d 行：多出一个 %s" % (line, c)
            o = stack.pop()
            if o == "tpl" or "([{".index(o) != ")]}".index(c):
                return "第 %d 行：%s 与第 %d 行的 %s 不匹配" % (line, c, line, o)

        if not c.isspace():
            prev = c
        i += 1

    if stack:
        return "有 %d 个括号没有闭合（例如模板串或 %s）" % (len(stack), stack[-1])
    return None


def selftest():
    """用已知正确/错误的片段验证 scan() 真的能报错（check_js.py --selftest）。"""
    cases = [
        ("配平的嵌套模板", "const a = `x ${b ? `y` : ''}`;", None),
        ("模板里带 HTML 闭合标签", "el.innerHTML = `<div><p>${t}</p></div>`;", None),
        ("正则字面量", "const r = /^\\/+/; s.replace(r, '');", None),
        ("字符串里带 // ", "const u = 'http://x';", None),
        ("缺一个右花括号", "function f() { if (1) { return; }", "没有闭合"),
        ("字符串没有闭合", "const s = 'abc;", "字符串"),
        ("多一个右括号", "const x = 1);", "多出"),
        ("模板串没有闭合", "const t = `abc;", "括号"),
    ]
    bad = 0
    for name, code, expect_kw in cases:
        err = scan(code)
        ok = (err is None) if expect_kw is None else (err is not None and expect_kw in err)
        if not ok:
            bad += 1
        print("  %-24s -> %-28s %s" % (name, err or "配平", "OK" if ok else "!! 判定错误"))
    print("自检结果：%s" % ("全部通过" if bad == 0 else "%d 项判定错误" % bad))
    return 1 if bad else 0


def main():
    if "--selftest" in sys.argv:
        return selftest()
    html = ROOT / "TagSDanbooru.html"
    if not html.exists():
        print("找不到 %s" % html)
        return 1
    text = html.read_text(encoding="utf-8")

    tags_o = len(re.findall(r"<script[\s>]", text))
    tags_c = len(re.findall(r"</script>", text))
    print("<script> %d 个 / </script> %d 个  ->  %s" % (tags_o, tags_c, "配平" if tags_o == tags_c else "不平衡!"))

    blocks = list(re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", text, re.S))
    print("内联 <script> 块：%d 个" % len(blocks))
    bad = 0
    for k, m in enumerate(blocks, 1):
        line0 = text.count("\n", 0, m.start()) + 1
        err = scan(m.group(1))
        if err:
            bad += 1
            print("  块 %d（起始第 %d 行）：%s" % (k, line0, err))
        else:
            print("  块 %d（起始第 %d 行）：OK" % (k, line0))

    # 关键函数是否都定义/调用了
    print("关键函数检查：")
    for name in ("renderGallery", "loadHistory", "renderRunbar", "openLightbox",
                 "stepLightbox", "closeLightbox", "reveal"):
        d = len(re.findall(r"function\s+%s\s*\(" % name, text))
        c = len(re.findall(r"\b%s\s*\(" % name, text)) - d
        print("  %-14s 定义 %d 次 / 调用 %d 处  %s" % (name, d, c, "OK" if d == 1 else "异常"))

    print("结果：%s" % ("全部通过" if bad == 0 else "有 %d 个块存在问题" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
