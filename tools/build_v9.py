#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_v9.py —— V9 镜头渲染器（观感专业美发沙龙 · 抖音竖屏探店）

针对 V8b「幻灯片感」的改造：
  1. 14 刀 / 每镜 1.24~1.85s，切点由 DP 求解落在音乐重音上
  2. 素材为 2133x1600 原图直裁紧凑特写，12 种不同主体，非同构图轮播
  3. 视频层与照片层双层同动，画面始终存在真实运动
  4. 切点加 0.05s 柔白闪转场，建立剪辑冲击力

关键技术要点（踩坑记录）
  - zoompan 的 zoom 变量在每次输入帧重置，必须用 on(输出帧计数) 做线性插值，
    否则运镜只在第一帧生效
  - zoompan 会把裁切区强制拉伸到 s 尺寸；要等比运镜必须先把图预放大成大画布
    (BIG_*)，再在其上取景
  - 静态图输入只有 1 帧，zoompan 的 d 必须等于目标帧数（不是 d=1）
  - overlay 输出尺寸跟随第一个输入，多层拼接要用「底层填满 + 上层叠压」而非 pad 拼接
  - 视频源帧数不足时用 tpad=stop_mode=clone 克隆末帧补齐

环境变量
  V9_SRC    工作目录（默认 /root/v9_src）
  V9_VIDEO  视频源路径
"""
import json, os, subprocess, sys

FF = "/usr/bin/ffmpeg"
SRC = os.environ.get("V9_SRC", "/root/v9_src")
OUT = f"{SRC}/shots"
os.makedirs(OUT, exist_ok=True)

BOUNDS = json.load(open(f"{SRC}/bounds.json"))["bounds"]
VIDEO_SRC = os.environ.get("V9_VIDEO", "/root/uploads/1794534566072704325-VID_20260131_225715.mp4")


# BIG_* 是 1.25 倍大画布，zoompan 在其上取景实现「真推进」而非拉伸
def asset(name, tag):
    return f"{SRC}/shots/BIG_{tag}_{name}.jpg"


# 视频窗口：(起始帧, 结束帧, 裁切x, 裁切宽)  源 720x406 / 87帧
WIN = {
    0: (0,  31, 0,  720),   # 静止段全景
    1: (8,  47, 40, 640),   # 绿植横摇
    2: (30, 78, 30, 660),   # 墙字+理发师
    3: (44, 87, 0,  700),   # 绿植+烫发机
    4: (12, 60, 20, 690),   # 全景运镜
}

# 14 镜最终编排
# (布局, 视频窗口, 照片素材, zoom起, zoom终, 描述)
# 布局: T=全屏照片  TB=视频条上+照片下  BB=照片上+视频条下  V=视频+照片同构
SHOTS = [
    ("V",  4, "v_cut",      1.00, 1.12, "开场·剪发+全景运镜"),
    ("T",  None, "v_hood",   1.00, 1.12, "烫发机+客人"),
    ("TB", 1, "v_dryer",    1.00, 1.10, "横摇/烫发机全景"),
    ("T",  None, "v_client", 1.00, 1.13, "客人发质特写"),
    ("BB", 2, "v_hand2",    1.00, 1.10, "理发师手部+烫字"),
    ("T",  None, "v_wall",   1.00, 1.11, "烫染书法墙"),
    ("TB", 3, "v_dryer3",   1.00, 1.12, "绿植摇镜/设备特写"),
    ("T",  None, "v_dryer3", 1.00, 1.12, "设备细节"),
    ("V",  0, "v_client",   1.00, 1.12, "客人实拍+门店"),
    ("TB", 1, "v_chair",    1.00, 1.10, "横摇/理发椅"),
    ("T",  None, "v_bottle", 1.00, 1.12, "洗护工具瓶"),
    ("BB", 2, "v_reflect",  1.00, 1.10, "墙字/地面倒影"),
    ("T",  None, "v_dryer2", 1.00, 1.12, "烫发机另一角度"),
    ("T",  None, "v_hood",   1.00, 1.06, "定版·烫发机+客人"),
]


def dur_of(i):
    return BOUNDS[i + 1] - BOUNDS[i]


def build(idx, layout, vwin, photo, z0, z1, desc):
    dur = dur_of(idx)
    out = f"{OUT}/shot_{idx:02d}.mp4"
    fc = []
    inp = []
    vi = pi = None

    if vwin is not None:
        vi = len([x for x in inp if x == "-i"])
        inp += ["-i", VIDEO_SRC]
    if photo is not None:
        pi = len([x for x in inp if x == "-i"])
        inp += ["-i", asset(photo, "A")]

    # zoompan 等比运镜：静态图输入 1 帧，d=目标帧数一次吐完，用 on 线性插值推进
    def zpan(sz, tag):
        n = max(int(round(dur * 30)), 1)
        z = f"min(max({z0}+({z1}-{z0})*on/{n-1},{z0}),{z1})"
        return (f"[{tag}:v]zoompan=z='{z}':x='iw/2-(iw/zoom/2)':"
                f"y='ih/2-(ih/zoom/2)':d={n}:s={sz}:fps=30,"
                f"trim=duration={dur:.3f},setpts=PTS-STARTPTS,"
                f"unsharp=5:5:0.45:5:5:0.0,setsar=1[{tag}z]")

    # 视频条统一：裁切 -> 1080x608 -> 帧数不足时用 tpad 克隆末帧补齐
    def vbar(tag):
        a, b, cx, cw = WIN[vwin]
        need = int(round(dur * 30))
        avail = b - a
        pad = max(0, need - avail)
        return (f"[{tag}:v]trim=start_frame={a}:end_frame={b},setpts=PTS-STARTPTS,"
                f"scale=1080:608:flags=lanczos,unsharp=5:5:0.7:5:5:0.0,fps=30,"
                f"tpad=stop_mode=clone:stop_duration={pad/30:.3f},"
                f"trim=duration={dur:.3f},setpts=PTS-STARTPTS[v]")

    if layout == "T":
        fc.append(zpan("1080x1920", str(pi)))
        fc.append(f"[{pi}z]format=yuv420p[o]")
    elif layout == "V":
        fc.append(vbar(str(vi)))
        fc.append(zpan("1080x1920", str(pi)))
        fc.append(f"[{pi}z]eq=brightness=-0.06:saturation=1.0[full]")
        fc.append("[full][v]overlay=0:0:shortest=1,format=yuv420p[o]")
    else:  # TB / BB
        # 照片层填满全屏做底，视频条叠在上/下 —— 避免 pad 出现黑边
        fc.append(vbar(str(vi)))
        fc.append(zpan("1080x1920", str(pi)))
        fc.append(f"[{pi}z]eq=brightness=-0.10:saturation=0.92[full]")
        if layout == "TB":
            fc.append("[full][v]overlay=0:0:shortest=1,format=yuv420p[o]")
        else:
            fc.append("[full][v]overlay=0:1312:shortest=1,format=yuv420p[o]")

    # ---- 转场闪白：每个镜头(除首镜)开头 0.05s 柔白闪（峰值 55%），不刺眼 ----
    final_label = "[o]"
    if idx > 0:
        inp += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "color=c=white:s=1080x1920:r=30"]
        wi = len([x for x in inp if x == "-i"]) - 1
        fc.append(
            f"[{wi}:v]format=rgba,colorchannelmixer=aa=0.55,"
            f"fade=t=in:st=0:d=0.010:alpha=1,fade=t=out:st=0.010:d=0.040:alpha=1[flash]")
        fc.append("[o][flash]overlay=0:0:shortest=1,format=yuv420p[vflash]")
        final_label = "[vflash]"

    cmd = [FF, "-y", "-v", "error"] + inp + [
        "-filter_complex", ";".join(fc),
        "-map", final_label, "-t", f"{dur:.3f}", "-r", "30",
        "-c:v", "libx264", "-crf", "17", "-preset", "medium",
        "-pix_fmt", "yuv420p", "-an", out,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[FAIL] {idx:02d} {desc}\n{r.stderr[:1200]}")
        return False
    print(f"[OK] {idx:02d} {dur:5.2f}s {layout:2s} {desc}")
    return True


if __name__ == "__main__":
    ok = True
    for i, s in enumerate(SHOTS):
        ok &= build(i, *s)
    print("\n=== 14 镜渲染完成 ===" if ok else "\n=== 有失败 ===")
    sys.exit(0 if ok else 1)
