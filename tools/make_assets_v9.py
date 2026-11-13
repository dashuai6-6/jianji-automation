#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_assets_v9.py —— V9 素材生成器

从 2133x1600 原图直裁两种目标比例，主体框用原图坐标，窗口自动包住主体并保持目标比例。
  A_9x16  : 2160x3840  供全屏镜头 (1080x1920)
  B_1312  : 2160x2624  供上下分屏面板 (1080x1312)

核心要点：横构图原图硬裁 9:16 会丢主体，必须先用主体框定位再裁。
放大倍数控制在 2.4~4x 内（源 2133px，等效 1080p 级锐度）。

环境变量
  V9_SRC    原图目录（默认 /root/new_src）
  V9_SHOTS  输出目录（默认 /root/v9_src/shots）
"""
from PIL import Image
import os

SRC = os.environ.get("V9_SRC", "/root/new_src")
OUT = os.environ.get("V9_SHOTS", "/root/v9_src/shots")
os.makedirs(OUT, exist_ok=True)

# (源文件, 主体框 x1,y1,x2,y2, 名称)
JOBS = [
    ("p1.jpg", 470,  270,  830,  760, "v_hood"),
    ("p2.jpg", 1300, 520, 1560,  870, "v_cut"),
    ("p4.jpg", 1180, 500, 1440,  850, "v_stylist"),
    ("p3.jpg", 560,  560,  820,  810, "v_client"),
    ("p1.jpg", 480,  280,  780,  700, "v_dryer"),
    ("p4.jpg", 1560, 1180, 2080, 1590, "v_reflect"),
    ("p1.jpg", 600,  760,  960, 1120, "v_bottle"),
    ("p4.jpg", 1560, 390, 2060,  880, "v_wall"),
    ("p4.jpg", 640,  560, 1000,  910, "v_chair"),
    ("p4.jpg", 1180, 900, 1620, 1330, "v_legs"),
    ("p3.jpg", 380,  340,  740,  690, "v_dryer2"),
    ("p1.jpg", 760,  840, 1120, 1200, "v_bottle2"),
]


def make(src, x1, y1, x2, y2, name, out_w, out_h, tag, pad=1.20):
    im = Image.open(f"{SRC}/{src}").convert("RGB")
    W, H = im.size
    bw, bh = x2 - x1, y2 - y1
    # 包住主体 + pad
    wx = int(bw * pad)
    wy = int(bh * pad)
    # 对齐目标比例
    tr = out_w / out_h
    if wx / wy < tr:
        wx = int(wy * tr)
    else:
        wy = int(wx / tr)
    if wx > W:
        wx = W
        wy = int(W / tr)
    if wy > H:
        wy = H
        wx = int(H * tr)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    X = int(min(max(0, cx - wx / 2), max(0, W - wx)))
    Y = int(min(max(0, cy - wy / 2), max(0, H - wy)))
    s = max(out_w / wx, out_h / wy)
    crop = im.crop((X, Y, X + wx, Y + wy)).resize(
        (int(wx * s), int(wy * s)), Image.LANCZOS)
    nw, nh = crop.size
    if nw < out_w or nh < out_h:
        s2 = max(out_w / nw, out_h / nh)
        crop = crop.resize((int(nw * s2), int(nh * s2)), Image.LANCZOS)
        nw, nh = crop.size
    crop = crop.crop((int((nw - out_w) / 2), int((nh - out_h) / 2),
                      int((nw - out_w) / 2) + out_w, int((nh - out_h) / 2) + out_h))
    crop.save(f"{OUT}/{tag}_{name}.jpg", quality=95, subsampling=0)
    return s


if __name__ == "__main__":
    for src, x1, y1, x2, y2, name in JOBS:
        s1 = make(src, x1, y1, x2, y2, name, 2160, 3840, "A")
        s2 = make(src, x1, y1, x2, y2, name, 2160, 2624, "B")
        print(f"{name:11s} {src}  A放大={s1:.2f}x  B放大={s2:.2f}x")
