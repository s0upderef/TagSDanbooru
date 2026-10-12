@echo off
chcp 65001 >nul
title TagSDanbooru  (close this window to stop)
cd /d "%~dp0"

set "SERVER=_internal\server.py"

rem Tell server.py that it was launched by this .bat. Only then will the NEXT
rem launch take over and close this terminal window. If you run server.py by
rem hand from your own shell, nothing is recorded and your shell is never touched.
set "TAGSD_TERMINAL=1"

rem ---- 找一个可用的 python：需要能 import aiohttp（ComfyUI 自带的那个通常已内置）----
set "PY="

rem 1) 环境变量 TAGSD_PY 显式指定，优先级最高
if defined TAGSD_PY call :try "%TAGSD_PY%"
if defined TAGSD_PY if not defined PY echo [WARN] TAGSD_PY 指向的 python 不可用（不存在或缺 aiohttp）：%TAGSD_PY%

rem 2) 读 _internal\config.json 里的 comfy.python（用 PATH 上的 python 解析；没有该文件就跳过）
python -c "import json;print(json.load(open('_internal/config.json',encoding='utf-8-sig')).get('comfy',{}).get('python',''))" >"%TEMP%\tagsd_py_path.txt" 2>nul
set "PYCFG="
set /p PYCFG=<"%TEMP%\tagsd_py_path.txt" 2>nul
del "%TEMP%\tagsd_py_path.txt" >nul 2>nul
if not defined PY if defined PYCFG call :try "%PYCFG%"

rem 3) 常见安装位置兜底，最后退到 PATH 上的 python / py
if not defined PY call :try "C:\ComfyUI\python\python.exe"
if not defined PY call :try "C:\ComfyUI-aki-v3.2\python\python.exe"
if not defined PY call :try "C:\ComfyUI_windows_portable\python_embeded\python.exe"
if not defined PY call :try "C:\ComfyUI\python_embeded\python.exe"
if not defined PY call :try "python"
if not defined PY call :try "py"

if not defined PY (
  echo [ERROR] 没有找到可用的 Python（需要能 import aiohttp）。
  echo         出图工作台服务依赖 aiohttp，ComfyUI 自带的 python 通常已内置。请任选其一：
  echo           * 装好 ComfyUI 后重跑本文件（启动.bat 会自动找到它的 python）
  echo           * 复制 _internal\config.example.json 为 _internal\config.json，
  echo             并把 comfy.python 指向你的 python.exe
  echo           * 设环境变量 TAGSD_PY 指向你的 python.exe
  echo           * 或者对某个 python 执行： pip install aiohttp
  pause
  exit /b 1
)

if not exist "%SERVER%" (
  echo [ERROR] %SERVER% not found.
  pause
  exit /b 1
)

echo ============================================================
echo   TagSDanbooru local server
echo   - page : http://127.0.0.1:9000/TagSDanbooru.html
echo   - relaunching this file closes the previous window first
echo   - keep this window open; close it to stop everything
echo ============================================================
echo.

"%PY%" "%SERVER%"
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
  echo.
  echo [ERROR] server exited with code %RC%
  echo         see _internal\logs\ for details
  echo.
  pause
  exit /b %RC%
)

echo.
echo Server stopped cleanly. Closing this window...
timeout /t 2 >nul
exit /b 0

rem ================================================================
rem  子程序：测试候选 python 是否带 aiohttp，是则写入 PY
rem  参数：完整路径，或 PATH 上的命令名（python / py）
rem ================================================================
:try
set "CAND=%~1"
if not defined CAND goto :eof
if exist "%CAND%" (
  "%CAND%" -c "import aiohttp" >nul 2>&1 || goto :eof
  set "PY=%CAND%"
  goto :eof
)
for /f "delims=" %%W in ('where "%CAND%" 2^>nul') do (
  "%%W" -c "import aiohttp" >nul 2>&1 || goto :eof
  set "PY=%%W"
  goto :eof
)
goto :eof
