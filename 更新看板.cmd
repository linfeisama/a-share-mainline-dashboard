@echo off
chcp 65001 >nul
set "PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if not exist "%PYTHON%" (
  where python >nul 2>nul
  if errorlevel 1 (
    echo 没有找到 Python 运行环境，请先安装 Python 3.12 或让 Codex 修复运行环境。
    pause
    exit /b 1
  )
  set "PYTHON=python"
)

echo 正在更新申万分层主线看板，请稍候...
"%PYTHON%" "%~dp0运行一次.py"
if errorlevel 1 (
  echo.
  echo 更新失败，请保留本窗口中的错误信息。
) else (
  echo.
  echo 更新完成。程序不会自动打开浏览器。
  echo 本地看板：%~dp0结果\申万分层主线看板.html
)
pause
