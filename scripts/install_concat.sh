#!/usr/bin/env bash
# Concat 一键安装（Linux x86_64 / aarch64）
#
#   bash install_concat.sh              # 安装 + 冒烟测试
#   bash install_concat.sh --check      # 只体检，不动系统
#   bash install_concat.sh --download-only /tmp   # 只下载 + 校验，不安装
#
# 目标版本可用环境变量覆盖：CONCAT_VERSION=0.2.7 bash install_concat.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

VER="${CONCAT_VERSION:-0.2.8}"
REPO="jub0t/Concat"
MODE="${1:-install}"
DEST="${2:-/tmp/concat-dl}"

say() { printf '\033[1m%s\033[0m\n' "$*"; }
ok()  { printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad() { printf '  \033[31m✗\033[0m %s\n' "$*"; }

need_sudo() { if [ "$(id -u)" = "0" ]; then echo ""; else echo "sudo"; fi; }
SUDO="$(need_sudo)"

# ---------- 架构 ----------
case "$(uname -m)" in
  x86_64|amd64)  ARCH=x86_64 ;;
  aarch64|arm64) ARCH=aarch64 ;;
  *) echo "不支持的架构：$(uname -m)（只做了 x86_64 / aarch64）"; exit 1 ;;
esac
PKG="Concat-${VER}-linux-${ARCH}.deb"
BASE="${CONCAT_MIRROR:-}https://github.com/${REPO}/releases/download/v${VER}"

echo
say "Concat ${VER} / linux-${ARCH}"
echo

# ---------- --check ----------
if [ "$MODE" = "--check" ]; then
  say "体检"
  if command -v concat >/dev/null 2>&1; then
    ok "已安装：$(concat --version 2>&1 | head -1)"
  else
    bad "未安装 concat"
  fi
  command -v ffmpeg  >/dev/null 2>&1 && ok "ffmpeg $(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')" || bad "缺 ffmpeg"
  command -v curl    >/dev/null 2>&1 && ok "curl 在"   || bad "缺 curl"
  command -v python3 >/dev/null 2>&1 && ok "python3 $(python3 -V 2>&1 | awk '{print $2}')" || bad "缺 python3"
  for lib in libgtk-3-0 libfontconfig1 libfreetype6 libxkbcommon0 libgl1; do
    if dpkg -s "$lib" >/dev/null 2>&1 || dpkg -s "${lib}t64" >/dev/null 2>&1; then
      ok "依赖 $lib"
    else
      bad "缺依赖 $lib"
    fi
  done
  echo
  exit 0
fi

# ---------- 下载 ----------
say "1/4 下载"
mkdir -p "$DEST"
cd "$DEST"

if [ -f "$PKG" ] && [ -f SHA256SUMS ]; then
  ok "已有安装包，跳过下载"
else
  say "  拉 $PKG（约 148MB）"
  curl -fL --retry 3 --retry-delay 2 -C - --progress-bar -o "$PKG" "${BASE}/${PKG}"
  curl -fsSL --retry 3 -o SHA256SUMS "${BASE}/SHA256SUMS"
  ok "$(du -h "$PKG" | cut -f1)"
fi

# ---------- 校验 ----------
say "2/4 校验 SHA256"
EXPECT="$(grep -E "[[:space:]]${PKG}\$" SHA256SUMS | awk '{print $1}' | head -1)"
if [ -z "$EXPECT" ]; then
  bad "SHA256SUMS 里没找到 ${PKG}，拒绝安装"
  exit 1
fi
ACTUAL="$(sha256sum "$PKG" | awk '{print $1}')"
if [ "$EXPECT" != "$ACTUAL" ]; then
  bad "校验失败，包可能被篡改或下载残缺"
  echo "     期望 $EXPECT"
  echo "     实际 $ACTUAL"
  exit 1
fi
ok "SHA256 对得上"

if [ "$MODE" = "--download-only" ]; then
  echo
  say "包在 $DEST/$PKG（未安装）"
  exit 0
fi

# ---------- 依赖 + 安装 ----------
say "3/4 装依赖并安装"
$SUDO apt-get update -qq || true
$SUDO apt-get install -y -qq \
  libgtk-3-0 libfontconfig1 libfreetype6 libxkbcommon0 libxkbcommon-x11-0 \
  libgl1 libasound2 ffmpeg >/dev/null 2>&1 || \
  $SUDO apt-get install -y -qq \
    libgtk-3-0 libfontconfig1 libfreetype6 libxkbcommon0 libxkbcommon-x11-0 \
    libgl1 libasound2t64 ffmpeg >/dev/null 2>&1
$SUDO dpkg -i "$PKG" >/dev/null
ok "$(concat --version 2>&1 | head -1)"

# ---------- 冒烟测试 ----------
say "4/4 冒烟测试（起 headless，建项目，导出 1 秒）"
TMP="$(mktemp -d "${HOME}/.concat-smoke.XXXXXX")"   # 必须在家目录内，/tmp 会被拒
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

ffmpeg -v error -f lavfi -i "testsrc=size=1080x1920:rate=30:duration=1" \
  -pix_fmt yuv420p "$TMP/t.mp4" -y

python3 - "$TMP" "$SCRIPT_DIR" <<'PY'
import json, os, subprocess, sys
tmp, here = sys.argv[1], sys.argv[2]
sys.path.insert(0, here)
from concat_client import Concat

c = Concat()
try:
    c.call("project_create", {"location": tmp, "name": "smoke", "width": 1080, "height": 1920})
    P = os.path.join(tmp, "smoke")
    m = c.call("media_import", {"path": P, "file": os.path.join(tmp, "t.mp4")})["createdId"]
    T = c.call("timeline_read", {"path": P})["timeline"]["tracks"][0]["id"]
    c.call("clip_add", {"path": P, "mediaId": m, "trackId": T, "start": 0})
    c.call("project_save", {"path": P})
    out = os.path.join(tmp, "o.mp4")
    r = c.call("export_start", {"path": P, "output": out})
    c.call("export_wait", {"job": r["job"], "timeoutSeconds": 180})
    d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", out], capture_output=True, text=True).stdout.strip()
    print("  导出时长 %s 秒" % d)
    sys.exit(0 if abs(float(d) - 1.0) < 0.2 else 2)
finally:
    c.close()
PY

echo
say "装好了。"
cat <<'EOF'

如果下载卡在几十 KB/s（国内常见），可以换镜像重试：
  CONCAT_MIRROR=https://ghfast.top/ bash install_concat.sh

下一步：
  python3 scripts/probe_ops.py --src 素材1.mp4 --src2 素材2.mp4
  跑一遍 50 个命令的判定，跟 Concat命令实测表.md 对照。

Windows 用户：
  Concat 有官方 Windows 版（.exe / .msi），从同一 release 页下载即可，
  但 MCP headless 通道只在 Linux 这版验证过。
EOF
