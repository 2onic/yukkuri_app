@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=%cd%;%PYTHONPATH%

REM 检查是否安装了 Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未在系统 PATH 中找到 Python 解释器！
    echo 请安装 Python 3.10+ 并勾选 "Add Python to PATH"。
    pause
    exit /b 1
)

REM 启动 Yukkuri 桌面图形界面
python -m yukkuri.cli --gui %*
if %errorlevel% neq 0 (
    echo.
    echo 程序运行结束或发生异常退出。
    pause
)
