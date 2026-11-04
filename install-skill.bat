@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
echo ========================================
echo   三道尺子出片质检 - 一键安装
echo ========================================
echo.

set "SRC=%~dp0三道尺子出片质检"
if not exist "%SRC%\SKILL.md" (
    echo [错误] 找不到技能目录: %SRC%
    echo        请确认是在仓库根目录运行本脚本
    pause
    exit /b 1
)

:: ---------- 1. Python ----------
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先装 Python 3.10+
    echo        下载: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [1/4] Python 已就绪

:: ---------- 2. 依赖 ----------
echo [2/4] 安装依赖 opencv-contrib-python-headless + numpy ...
python -m pip install -q opencv-contrib-python-headless numpy
if %errorlevel% neq 0 (
    echo [警告] 依赖安装失败，技能里的画质判据会失效
    echo        手动执行: python -m pip install opencv-contrib-python-headless numpy
)
echo       依赖安装完成

:: ---------- 3. ffmpeg ----------
where ffmpeg >nul 2>&1
if %errorlevel% neq 0 (
    echo [3/4] 未找到 ffmpeg，尝试用 winget 安装 ...
    winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements >nul 2>&1
    if %errorlevel% neq 0 (
        echo       [警告] ffmpeg 未装上，技能无法抽帧
        echo       手动安装: winget install Gyan.FFmpeg
        echo       装完记得重开终端让 PATH 生效
    ) else (
        echo       ffmpeg 安装完成，请重开终端后再用
    )
) else (
    echo [3/4] ffmpeg 已就绪
)

:: ---------- 4. 复制到技能目录 ----------
echo [4/4] 安装技能 ...
set "OK=0"

set "D1=%USERPROFILE%\.codebuddy\skills"
if not exist "%D1%" mkdir "%D1%" 2>nul
if exist "%D1%" (
    xcopy "%SRC%" "%D1%\三道尺子出片质检\" /E /I /Y /Q >nul
    if !errorlevel! equ 0 (
        echo       已装到 !D1!\三道尺子出片质检
        set "OK=1"
    )
)

:: WorkBuddy 桌面版也用同一个技能目录
set "D2=%USERPROFILE%\.workbuddy\skills"
if exist "%USERPROFILE%\.workbuddy" (
    if not exist "%D2%" mkdir "%D2%" 2>nul
    xcopy "%SRC%" "%D2%\三道尺子出片质检\" /E /I /Y /Q >nul
    if !errorlevel! equ 0 (
        echo       已装到 !D2!\三道尺子出片质检
        set "OK=1"
    )
)

if "!OK!"=="0" (
    echo [错误] 复制失败，请手动把下面这个文件夹
    echo        %SRC%
    echo        整个复制到  C:\Users\%USERNAME%\.codebuddy\skills\
    pause
    exit /b 1
)

:: ---------- 自检 ----------
echo.
echo ========================================
echo   自检（这步不过，画质判据就是假的）
echo ========================================
pushd "%D1%\三道尺子出片质检" 2>nul
python -c "import cv2,numpy as np,sys;sys.path.insert(0,'scripts');import aesthetic as A;q=hasattr(cv2,'quality');print('opencv',cv2.__version__,'| quality',q,'| BRISQUE',A.brisque((np.random.rand(480,270)*255).astype('uint8')) if q else 'N/A')"
if %errorlevel% neq 0 echo [警告] 自检没跑通，多半是依赖没装好，重跑一次本脚本
popd 2>nul
echo.
echo ========================================
echo   完成
echo ========================================
echo.
echo  以后怎么用：不用记命令，直接跟我说
echo     "这几条素材能不能用"      - 过尺子A
echo     "帮我剪一条 XX 秒的探店"  - 自动编排+返修
echo     "这条成片能不能发"        - 过尺子B+C
echo.
pause
