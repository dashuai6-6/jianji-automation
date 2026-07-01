@echo off
chcp 65001 >nul
echo ========================================
echo   剪映自动化剪辑技能 — 一键安装
echo ========================================
echo.

:: Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python, 请先安装 Python 3.8+
    echo 下载: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [1/4] Python 已就绪

:: Install pyJianYingDraft
echo [2/4] 安装 pyJianYingDraft...
pip install pyJianYingDraft -q
if %errorlevel% neq 0 (
    echo [错误] pyJianYingDraft 安装失败
    pause
    exit /b 1
)
echo        pyJianYingDraft 安装完成

:: Check ffmpeg
where ffmpeg >nul 2>&1
if %errorlevel% neq 0 (
    echo [3/4] 下载 ffmpeg...
    curl -sL "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -o "%TEMP%\ffmpeg.zip"
    if %errorlevel% equ 0 (
        powershell -Command "Expand-Archive '%TEMP%\ffmpeg.zip' '%USERPROFILE%\.ffmpeg' -Force"
        set "PATH=%USERPROFILE%\.ffmpeg\ffmpeg-*-essentials_build\bin;%PATH%"
        echo        ffmpeg 安装完成
    ) else (
        echo        [警告] ffmpeg 下载失败, 黑场卡片功能不可用
        echo        手动安装: winget install ffmpeg
    )
) else (
    echo [3/4] ffmpeg 已就绪
)

:: Download jy-draftc
echo [4/4] 下载 jy-draftc (草稿加密工具)...
set "JY_DIR=%USERPROFILE%\.workbuddy\jy-draftc\jy-draftc-amd64-windows"
if not exist "%JY_DIR%\jy-draftc.exe" (
    mkdir "%JY_DIR%" 2>nul
    curl -sL "https://github.com/wenshui330/jy-draftc/releases/download/v0.1.1/jy-draftc-amd64-windows.zip" -o "%TEMP%\jy-draftc.zip"
    if %errorlevel% equ 0 (
        powershell -Command "Expand-Archive '%TEMP%\jy-draftc.zip' '%JY_DIR%' -Force"
        echo        jy-draftc 安装完成
    ) else (
        echo        [警告] jy-draftc 下载失败
        echo        手动下载: https://github.com/wenshui330/jy-draftc/releases
    )
) else (
    echo [4/4] jy-draftc 已就绪
)

echo.
echo ========================================
echo   安装完成！
echo ========================================
echo.
echo  技能位置: %~dp0
echo  使用方式: 在 WorkBuddy 中说"帮我剪辑视频"
echo.
echo  如果 jy-draftc 或 ffmpeg 有问题, 请重启终端后重试
echo.
pause
