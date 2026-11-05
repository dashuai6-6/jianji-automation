#!/usr/bin/env bash
# 三道尺子出片质检 — Linux / macOS 一键安装
#
#   bash install_skill.sh              # 装依赖 + 复制技能 + 自检
#   bash install_skill.sh --check      # 只体检，不动任何东西
#
# Windows 用户请双击 install-skill.bat，别用这个。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_SRC="$SCRIPT_DIR/三道尺子出片质检"
SKILL_DST="${CODEBUDDY_SKILLS:-$HOME/.codebuddy/skills}/三道尺子出片质检"
MODE="${1:-install}"

say() { printf '\033[1m%s\033[0m\n' "$*"; }
ok()  { printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad() { printf '  \033[31m✗\033[0m %s\n' "$*"; }

for c in python3 ffmpeg; do
  command -v "$c" >/dev/null 2>&1 && ok "$c 在" || { bad "缺 $c，先装上再来"; exit 1; }
done

PY="python3"

# ---------- --check ----------
if [ "$MODE" = "--check" ]; then
  say "体检"
  $PY - <<'PY'
import importlib, sys
def probe(mod, label, extra=None):
    try:
        m = importlib.import_module(mod)
        v = getattr(m, "__version__", "?")
        print("  \033[32m✓\033[0m %s %s" % (label, v))
        return m
    except Exception:
        print("  \033[31m✗\033[0m 缺 %s" % label)
        return None
cv2 = probe("cv2", "opencv")
probe("numpy", "numpy")
if cv2 is not None:
    if hasattr(cv2, "quality"):
        print("  \033[32m✓\033[0m cv2.quality 在（BRISQUE 可用）")
    else:
        print("  \033[31m✗\033[0m cv2.quality 不在 —— 装的是 opencv-python，"
              "必须换成 opencv-contrib-python-headless，否则画质判据是假的")
PY
  [ -d "$SKILL_DST" ] && ok "技能已装在 $SKILL_DST" || bad "技能未安装"
  echo
  exit 0
fi

# ---------- 依赖 ----------
say "1/3 依赖"
PIP="$PY -m pip"
$PIP install --quiet --disable-pip-version-check \
    opencv-contrib-python-headless numpy 2>/dev/null || \
  $PIP install --quiet --disable-pip-version-check --break-system-packages \
    opencv-contrib-python-headless numpy
ok "opencv-contrib + numpy"

$PY - <<'PY'
import sys, cv2
if not hasattr(cv2, "quality"):
    print("  \033[31m✗\033[0m cv2.quality 仍然缺失：可能装了 opencv-python 抢了 contrib 的库")
    sys.exit(1)
print("  \033[32m✓\033[0m cv2 %s，quality 模块在" % cv2.__version__)
PY

# ---------- 复制 ----------
say "2/3 安装技能"
if [ ! -d "$SKILL_SRC" ]; then
  bad "找不到 $SKILL_SRC（是不是没在仓库根目录跑？）"
  exit 1
fi
mkdir -p "$(dirname "$SKILL_DST")"
rm -rf "$SKILL_DST"
cp -r "$SKILL_SRC" "$SKILL_DST"
find "$SKILL_DST" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
ok "$SKILL_DST"

# ---------- 自检 ----------
say "3/3 自检"
cd "$SKILL_DST"
$PY - <<'PY'
import sys, numpy as np
sys.path.insert(0, "scripts")
import aesthetic as A, qa_loop as Q

score = A.brisque((np.random.rand(480, 270) * 255).astype("uint8"))
if score is None:
    print("  \033[31m✗\033[0m BRISQUE 返回 None —— 画质判据失效，别拿这次的结论发片")
    print("     检查 scripts/models/ 下两个 yml 在不在")
    sys.exit(1)
print("  \033[32m✓\033[0m BRISQUE %.1f（噪声图，分数越高越差，这是对照值）" % score)

r = Q.loop([], verbose=False)
txt = Q.report(r["audit"], r)
assert "合格素材不足" in txt
print("  \033[32m✓\033[0m 空池报告正常")
PY

echo
say "装好了。"
cat <<'EOF'

直接说人话就能用：
  「这几条素材能不能用」   → 尺子 A，出可用/弃用清单
  「帮我剪一条 20 秒探店」  → 编排 → 五维评审 → 自动返修
  「这条成片能不能发」      → 尺子 B + C
  「按 128 BPM 卡点」       → 半拍网格 + 偏差毫秒

提醒：成片必须传 is_final=True，
否则花字会被 BRISQUE 当成结构异常，好片被判 0.22 折。
EOF
