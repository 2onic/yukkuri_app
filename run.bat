@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
set PYTHONPATH=%cd%;%PYTHONPATH%

REM 智能查找可用的 Python 解释器
set "PY_CMD="

REM 1. 优先使用当前激活的环境
if defined CONDA_PREFIX (
    if exist "%CONDA_PREFIX%\python.exe" (
        set "PY_CMD=%CONDA_PREFIX%\python.exe"
    )
)

REM 2. 检查本地虚拟环境
if not defined PY_CMD (
    if exist "%~dp0.venv\Scripts\python.exe" (
        set "PY_CMD=%~dp0.venv\Scripts\python.exe"
    ) else if exist "%~dp0venv\Scripts\python.exe" (
        set "PY_CMD=%~dp0venv\Scripts\python.exe"
    )
)

REM 3. 检查常见 Conda/Miniforge yukkuri 环境路径
if not defined PY_CMD (
    for %%P in (
        "D:\miniforge3\envs\yukkuri\python.exe"
        "C:\miniforge3\envs\yukkuri\python.exe"
        "%USERPROFILE%\miniforge3\envs\yukkuri\python.exe"
        "%USERPROFILE%\miniconda3\envs\yukkuri\python.exe"
        "%USERPROFILE%\anaconda3\envs\yukkuri\python.exe"
        "D:\miniconda3\envs\yukkuri\python.exe"
        "D:\anaconda3\envs\yukkuri\python.exe"
    ) do (
        if exist %%P (
            set "PY_CMD=%%~P"
            goto :found_py
        )
    )
)

REM 4. 尝试系统 PATH 中的 python (排除 WindowsApps 假别名)
if not defined PY_CMD (
    where python >nul 2>nul
    if %errorlevel% equ 0 (
        python -c "import sys" >nul 2>nul
        if !errorlevel! equ 0 (
            set "PY_CMD=python"
        )
    )
)

REM 5. 尝试 py 启动器
if not defined PY_CMD (
    where py >nul 2>nul
    if %errorlevel% equ 0 (
        py -3 -c "import sys" >nul 2>nul
        if !errorlevel! equ 0 (
            set "PY_CMD=py -3"
        )
    )
)

:found_py
if not defined PY_CMD (
    echo [错误] 未在系统中找到有效的 Python 3 解释器！
    echo 请安装 Python 3.10+ 并激活 yukkuri 环境。
    pause
    exit /b 1
)

REM 启动 Yukkuri (无参数时默认启动桌面图形界面，有参数时透传)
if "%~1"=="" (
    "%PY_CMD%" -m yukkuri.cli --gui
) else (
    "%PY_CMD%" -m yukkuri.cli %*
)
if %errorlevel% neq 0 (
    echo.
    echo 程序运行结束或发生异常退出。
    pause
)
