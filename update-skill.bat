@echo off
chcp 65001 >nul
echo ========================================
echo   更新技能（拉最新 + 重装）
echo ========================================
echo.

cd /d "%~dp0"
where git >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 git
    echo        下载: https://git-scm.com/download/win
    pause
    exit /b 1
)

echo [1/2] 拉取最新版本 ...
git pull
if %errorlevel% neq 0 (
    echo [警告] 拉取失败。如果提示冲突，删掉整个文件夹重新 clone 最省事
    pause
    exit /b 1
)

echo.
echo [2/2] 重新安装 ...
call "%~dp0install-skill.bat"
