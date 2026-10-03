@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "视界盾桌面防护\.venv\Scripts\pythonw.exe" (
    echo 请先按 docs\协作启动与同步.md 准备桌面模块环境。
    pause
    exit /b 1
)
start "" "视界盾桌面防护\.venv\Scripts\pythonw.exe" "VisionShield.py"
