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

echo 正在启动看板网站...
echo 启动后请在浏览器访问：http://127.0.0.1:8765
echo 本程序不会自动打开浏览器。
"%PYTHON%" "%~dp0网站服务.py"
if errorlevel 1 (
  echo.
  echo 网站服务启动失败，请保留本窗口中的错误信息。
  pause
)
