#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""
五维审美引擎 aesthetic.py
=========================
思路：不是"让 AI 有品味"，而是把剪辑师的判断拆成**可计算的代理指标**，
      再转成**可执行的编排动作**。每条打分都能说出依据，每个结论都能落到帧号。

D1 镜头审美 shot      —— 这一条值不值得留，值多少
D2 节奏审美 rhythm    —— 什么时候快切，什么时候慢放
D3 构图色彩 look      —— 有没有质感，统不统一，真不真实
D4 叙事审美 story     —— 怎么讲这个故事（不是按拍摄顺序拼）
D5 商业审美 business  —— 观众为什么愿意看完

用法：
  python3.11 aesthetic.py 片子.mp4
  python3.11 aesthetic.py --pool 素材目录/       # 整池排序，输出留/弃建议
  python3.11 aesthetic.py --pool 素材目录/ --plan 120   # 顺带出节奏方案
"""
import os
import sys
import json
import math
import subprocess
import argparse

import numpy as np
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# ============================================================ 基础工具

def sh(cmd, timeout=300):
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def probe(path):
    r = sh(["ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", path])
    try:
        j = json.loads(r.stdout.decode("utf-8", "ignore") or "{}")
    except Exception:
        j = {}
    v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in j.get("streams", []) if s.get("codec_type") == "audio"), None)

    def _rate(s):
        try:
            n, d = s.split("/")
            return float(n) / float(d) if float(d) else 0.0
        except Exception:
            return 0.0

    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            try:
                rot = int(float(sd["rotation"]))
            except Exception:
                pass
    if not rot:
        try:
            rot = int(float(v.get("tags", {}).get("rotate", 0)))
        except Exception:
            pass
    if abs(rot) % 180 == 90:
        w, h = h, w

    return {
        "path": path,
        "w": w, "h": h,
        "fps": round(_rate(v.get("r_frame_rate", "0/1")), 3) or 30.0,
        "dur": float(j.get("format", {}).get("duration") or 0),
        "vcodec": v.get("codec_name"),
        "has_audio": a is not None,
        "size_mb": round(float(j.get("format", {}).get("size") or 0) / 1048576, 2),
    }


def grab(path, n=36, w=640, start=0.0, end=None, no_upscale=True):
    """均匀抽 n 帧，返回 BGR ndarray 列表（等比缩放）。

    no_upscale=True：素材比 w 窄时保持原尺寸，**绝不放大**。
    原因：插值放大会人为低通，锐度暴跌（实测 406 宽素材拉到 640，拉普拉斯方差
    从 52 掉到 11.7，被判成"糊"——但原片发丝根根分明）。测质量必须在原尺寸上测。
    """
    info = probe(path)
    if no_upscale and info["w"] < w:
        w = info["w"] if info["w"] % 2 == 0 else info["w"] - 1
    dur = info["dur"] or 1.0
    s = start
    e = end if end is not None else dur
    span = max(0.05, e - s)
    fps = max(0.2, n / span)
    h = int(round(w * info["h"] / max(1, info["w"]) / 2)) * 2
    r = sh(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{s:.3f}", "-t", f"{span:.3f}",
            "-i", path, "-vf", f"fps={fps:.4f},scale={w}:{h}",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], timeout=180)
    fsz = w * h * 3
    cnt = len(r.stdout) // fsz
    return [np.frombuffer(r.stdout[i * fsz:(i + 1) * fsz], np.uint8).reshape(h, w, 3)
            for i in range(cnt)], (w, h)


def grab_gray_src(path, n=4, max_w=1280):
    """抽几帧**原始尺寸**灰度图，专供跨尺度伪影校验。

    不能用 grab() 的帧：它统一缩到 640，而缩放本身就是低通滤波——
    8×8 的块边界一缩就没了，等于把要检测的东西提前擦掉。
    实测同一条 120kbps 压缩片：原始尺寸跨尺度比 2.3，缩到 640 再测变 3.0，
    伪影判据直接钝掉。所以这一路必须原图。
    """
    info = probe(path)
    w, h = int(info["w"]), int(info["h"])
    if w > max_w:                                  # 4K 素材先减半，否则内存和耗时都吃不消
        h = int(h * max_w / w / 2) * 2
        w = max_w
    dur = info["dur"] or 1
    fps = max(0.1, n / max(0.2, dur))
    vf = f"fps={fps:.4f}" + (f",scale={w}:{h}" if (w != int(info["w"])) else "")
    r = sh(["ffmpeg", "-v", "error", "-nostdin", "-i", path, "-vf", vf,
            "-f", "rawvideo", "-pix_fmt", "gray", "-"], timeout=180)
    fsz = w * h
    cnt = len(r.stdout) // fsz
    return [np.frombuffer(r.stdout[i * fsz:(i + 1) * fsz], np.uint8).reshape(h, w)
            for i in range(min(cnt, n))]


def grab_seq(path, fps=15, win=2.2, w=320):
    """抓一段**连续帧**（用于运动/抖动分析）"""
    info = probe(path)
    dur = info["dur"] or 1
    if dur <= win * 1.6:
        ss = max(0.0, min(0.10, dur * 0.05))       # 短素材从头取，别漏掉急速位移
    else:
        ss = max(0.0, min(dur - win, dur * 0.4))
    h = int(round(w * info["h"] / max(1, info["w"]) / 2)) * 2
    r = sh(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{ss:.3f}", "-t", f"{win:.3f}",
            "-i", path, "-vf", f"fps={fps},scale={w}:{h},gblur=sigma=1.0",
            "-f", "rawvideo", "-pix_fmt", "gray", "-"], timeout=120)
    fsz = w * h
    cnt = len(r.stdout) // fsz
    return [np.frombuffer(r.stdout[i * fsz:(i + 1) * fsz], np.uint8).reshape(h, w)
            for i in range(cnt)], (w, h)


_CASC = None


def casc():
    global _CASC
    if _CASC is None:
        p = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        c = cv2.CascadeClassifier(p)
        _CASC = c if not c.empty() else False
    return _CASC or None


# ============================================================ D3 基础：色彩描述

def lab_stats(frame):
    """LAB 均值 + 直方图（L/a/b 各 16 bin），用于跨镜头一致性"""
    small = cv2.resize(frame, (160, 284), interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB)
    L, A, B = lab[..., 0], lab[..., 1], lab[..., 2]
    hist = []
    for ch in (L, A, B):
        h = cv2.calcHist([ch], [0], None, [16], [0, 256]).ravel()
        h = h / max(1e-6, h.sum())
        hist.append(h)
    return {
        "L": float(L.mean()), "a": float(A.mean()), "b": float(B.mean()),
        "Lsd": float(L.std()),
        "sat": float((cv2.cvtColor(small, cv2.COLOR_BGR2HSV)[..., 1]).mean()),
        "hist": np.concatenate(hist),
    }


def delta_e(l1, l2):
    """CIE76 色差（LAB 欧氏距离），<3 肉眼几乎无差，>8 明显不同"""
    return float(math.sqrt((l1["L"] - l2["L"]) ** 2 +
                           (l1["a"] - l2["a"]) ** 2 +
                           (l1["b"] - l2["b"]) ** 2))


def hist_dist(h1, h2):
    """直方图交集距离 0..1，越大越不一致"""
    return float(1.0 - np.minimum(h1, h2).sum() / max(1e-6, np.minimum(h1.sum(), h2.sum())))


# ============================================================ 主体区域

def subject_masks(frame):
    """返回 人脸框 / 头发区 / 手部皮肤区 / 主体占比"""
    h, w = frame.shape[:2]
    out = {"faces": [], "hair_box": None, "face_area": 0.0, "hair_area": 0.0,
           "skin_pct": 0.0, "n_face": 0, "subj_src": None, "subj_box": None, "subj_conf": 0.0}
    c = casc()
    if c is not None:
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        rects = c.detectMultiScale(g, 1.08, 4, minSize=(int(h * 0.05), int(h * 0.05)))
        if len(rects):
            rs = sorted(rects, key=lambda r: -r[2] * r[3])[:2]
            out["n_face"] = len(rs)
            for (x, y, fw, fh) in rs:
                out["faces"].append((int(x), int(y), int(fw), int(fh)))
            x, y, fw, fh = rs[0]
            out["face_area"] = (fw * fh) / (w * h)
            # 头发区：人脸上方 + 两侧扩展（发型占画面比人脸大得多）
            hx0 = max(0, int(x - fw * 0.35))
            hx1 = min(w, int(x + fw * 1.35))
            hy0 = max(0, int(y - fh * 1.05))
            hy1 = min(h, int(y + fh * 0.45))
            out["hair_box"] = (hx0, hy0, hx1, hy1)
            out["hair_area"] = ((hx1 - hx0) * (hy1 - hy0)) / (w * h)
            out["subj_src"] = "face"
            out["subj_box"] = (int(x), int(y), int(x + fw), int(y + fh))
            out["subj_conf"] = 1.0
    if out["subj_box"] is None:
        # 背影/侧后/产品特写：人脸检测必然失效，改用深色高频块定位主体
        box, ar, conf = texture_subject(frame)
        if box is not None:
            out["hair_box"] = box
            out["hair_area"] = ar
            out["subj_box"] = box
            out["subj_conf"] = round(conf, 3)
            out["subj_src"] = "texture"
            # 是头发还是产品？头发处处有纹理，瓶身/包装是"大片平坦色块+少量硬边"。
            # 只靠面积也能分（头发占满画面 40%，产品 12%），两个一起用更稳。
            fl = flat_ratio(frame, box)
            out["flat_ratio"] = round(fl, 3)
            out["subj_kind"] = "object" if (fl > 0.60 or ar < 0.18) else "hair"

    ycc = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)
    skin = cv2.inRange(ycc, (0, 133, 77), (255, 173, 127))
    out["skin_pct"] = float(skin.mean()) / 255.0
    return out


def region_detail(gray, box):
    """区域纹理细节量：发丝、工具刃口这类高频信息"""
    if box is None:
        return 0.0
    x0, y0, x1, y1 = box
    if x1 - x0 < 12 or y1 - y0 < 12:
        return 0.0
    roi = gray[y0:y1, x0:x1]
    lap = cv2.Laplacian(roi, cv2.CV_64F)
    return float(lap.var())


def lap_norm(gray, ref_w=640):
    """尺度归一的拉普拉斯方差。

    实测标定（同一画面、不同宽度）：
        1680 原生 996  ↔  缩到 640 实测 2599     比值 2.61 = 1680/640
        406  原生 217  ↔  归一到 640 应为 137.7
    即 lap ∝ 1/w，指数正好 1.0。所以 等效值 = lap × (w / 640)。
    这样 1080 宽的原片、406 宽的压缩片能在同一把尺子上比。
    """
    h, w = gray.shape[:2]
    return float(cv2.Laplacian(gray, cv2.CV_64F).var()) * (w / ref_w)


# ---------------------------------------------------------------- 画质：BRISQUE
# 为什么必须上模型：手搓指标全试过，没有一个能同时摆平 模糊/噪声/压缩。
#   拉普拉斯方差  —— 120kbps 与 8Mbps 只差 6 分（60.6 vs 54.6），肉眼却是色块 vs 根根分明
#   Sobel p99     —— 抗噪好，但尺度不归一（同图 406 与 1620 差 2.1 倍）
#   跨尺度能量比  —— 分得开纹理/伪影，却与分辨率强耦合（1080 素材 1.1-2.7，406 素材 3.0-4.0）
#   帧差估噪      —— 压缩噪声在时间上稳定（编码器复用静止块残差），测出来 σ=0
#   8px 块效应    —— 被画面内容干扰，自家成片 1.567 高于压缩片 1.174
# BRISQUE 一次全对，见下方实测。它输出 0-100，越低越干净。
_BRQ = None
_BRQ_TRIED = False


def brisque(gray):
    """BRISQUE 无参考画质分（0-100，越低越好）。缺模型文件时返回 None，不影响主流程。

    实测（同一素材的不同劣化版本）：
        清晰 35.5 → 糊0.8 48.0 → 糊1.5 62.2 → 糊2.5 71.6
        干净 32.5 → 800k 43.8 → 300k 52.8 → 120k 60.0
        无噪 35.5 → 噪5 30.1 → 噪10 47.1 → 噪20 62.0
    三条线全部单调，这是手工指标做不到的。

    **只用于拍摄素材，不能用于成片**：它按自然照片统计建模，
    画面上的花字/贴纸/边框会被当成"结构异常"，自家成片实测被判 79.8。
    """
    global _BRQ, _BRQ_TRIED
    if not _BRQ_TRIED:
        _BRQ_TRIED = True
        try:
            mp = os.path.join(HERE, "models", "brisque_model.yml")
            rp = os.path.join(HERE, "models", "brisque_range.yml")
            if os.path.exists(mp) and os.path.exists(rp) and hasattr(cv2, "quality"):
                _BRQ = cv2.quality.QualityBRISQUE_create(mp, rp)
        except Exception:
            _BRQ = None
    if _BRQ is None:
        return None
    try:
        return float(_BRQ.compute(gray)[0])
    except Exception:
        return None


def noise_sigma_lap(gray, q=25.0):
    """用拉普拉斯响应幅值的低分位估噪声水平 σ（灰度级 0-255）。

    原理：噪声在**每个像素**都存在，真纹理只占边缘的少数像素，
    所以幅值分布的低分位由噪声主导，高分位由边缘主导。
    |N(0,σo)| 的 25 分位 = 0.3186·σo，而拉普拉斯核的能量增益是 sqrt(20)。

    实测（同一素材）：
        406 原片 0.00（这条压缩片确实干净，不会被误扣）
        加噪 σ3 → 3.51    σ8 → 8.42    σ14 → 14.04
    对比之前用"平坦块 std 20 分位"的估法：在 406 片上估出 1.5~2，
    20σ² 直接把 42 的锐度扣成 0 —— 把干净片当噪片。

    为什么可以扣：拉普拉斯方差对白噪声的贡献是精确的 20σ²
    （核 [[0,1,0],[1,-4,1],[0,1,0]] 的系数平方和 = 20）。
    实测加噪 σ14：裸测 4268，理论噪声项 20×13.6²=3699，残差 569 ≈ 原图 470。对得上。
    """
    if min(gray.shape[:2]) < 32:
        return 0.0
    l = np.abs(cv2.Laplacian(gray, cv2.CV_64F))
    return float(np.percentile(l, q)) / 0.3186 / math.sqrt(20.0)


# 画质分档：BRISQUE → 清晰度维度的折扣系数
BRISQUE_LEVELS = [
    (45.0, 1.00, None),              # 干净/可用，不打折
    (55.0, 0.86, "画质偏软"),
    (60.0, 0.62, "压缩损伤可见"),
    (70.0, 0.40, "压缩损伤明显"),
    (999.0, 0.22, "画质严重劣化"),
]


def quality_factor(bq):
    """BRISQUE 分 → (系数, 说明)。None 表示没测（缺模型），返回 1.0 不干扰。"""
    if bq is None:
        return 1.0, None
    for lim, k, lab in BRISQUE_LEVELS:
        if bq < lim:
            return k, lab
    return 0.20, "画质严重劣化"


# 跨尺度能量保持率的分档：区分"真纹理"和"压缩伪影/噪点"
# 只负责一件事：识别"高频是噪点，不是细节"。
# 阈值卡在 1.05 而不是"理论值 4.0"：实测跨尺度比与分辨率强耦合
# （干净 1080 素材 1.1~2.7，干净 406 素材 3.0~4.0），拿它判压缩必误伤。
# 压缩损伤交给 BRISQUE，两者各管一摊、不重叠。
ART_LEVELS = [
    (1.05, 1.00, None),              # 正常（含轻微压缩，压缩另有 BRISQUE 判）
    (0.75, 0.60, "噪点偏多"),
    (0.45, 0.35, "噪点明显"),
    (0.00, 0.20, "噪点盖过细节"),
]


def art_ratio(gray):
    """半尺度 / 原尺度 的高频能量比。

    为什么必须加这一项：拉普拉斯方差**分不清真纹理和伪影**。
    实测同一段素材的 8Mbps 与 120kbps 两版——肉眼看一个发丝根根分明、
    一个糊成色块，但 lap 只有 60.6 和 54.6，几乎一样。
    因为压缩伪影（块效应 + 振铃）本身就是高频能量，把丢掉的细节"补"了回来，
    所以单看高频总量判不出优劣 —— 这就是"劣质片被判清晰"的根因。

    跨尺度才是分水岭：真发丝缩一半还在（lap ∝ 1/w，理论比 → 4.0），
    8×8 的块边界和振铃缩一半就被平均掉了。
    实测：干净 3.5 / 8Mbps 3.3 / 120kbps 2.3 / 噪点 σ14 0.22。
    """
    h, w = gray.shape[:2]
    if w < 64 or h < 64:
        return 4.0
    d = cv2.resize(gray, (max(2, w // 2), max(2, h // 2)), interpolation=cv2.INTER_AREA)
    a = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    b = float(cv2.Laplacian(d, cv2.CV_64F).var())
    return b / max(a, 1e-6)


def art_penalty(r):
    """返回 (锐度折扣系数, 说明)。1.0 = 不打折。"""
    for lim, k, lab in ART_LEVELS:
        if r >= lim:
            return k, lab
    return 0.25, "噪点盖过细节"


def flat_ratio(frame, box, blk=12, thr=6.0):
    """主体框内"平坦块"占比：局部标准差 < thr 的块有多少。
    头发 ≈ 0.44（处处有发丝纹理），瓶身/包装 ≈ 0.74（大片纯色）。向量化，40帧也不卡。"""
    x0, y0, x1, y1 = box
    roi = cv2.cvtColor(frame[max(0, y0):y1, max(0, x0):x1], cv2.COLOR_BGR2GRAY)
    if roi.size < blk * blk * 4:
        return 0.0
    g = roi.astype(np.float32)
    mu = cv2.blur(g, (blk, blk))
    sq = cv2.blur(g * g, (blk, blk))
    sd = np.sqrt(np.maximum(sq - mu * mu, 0))
    return float((sd < thr).mean())


def texture_subject(frame, min_area=0.035):
    """无脸素材（背影/后脑/产品特写）的主体定位。

    人脸检测对背影完全失效，会把"满头卷发"判成空镜。这里用**深色高频块**找主体：
    深色（LAB 的 L 低）+ 有纹理 + 不贴边的大连通域 = 头发/产品。
    返回 (box, area_ratio, conf)；找不到返回 (None, 0.0, 0.0)。
    """
    if frame is None or frame.size == 0:
        return None, 0.0, 0.0
    h, w = frame.shape[:2]
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    L = lab[:, :, 0]
    # 深色区：头发（黑/深棕/深灰）都在 L<105；浅背景（白墙、白T）在 L>150
    dark = (L < 108).astype(np.uint8)
    # 排除贴着画面边缘的暗块（常见于压暗的暗角/背景虚化暗部）
    dark[:int(h * 0.02), :] = 0
    dark[-int(h * 0.02):, :] = 0
    dark[:, :int(w * 0.02)] = 0
    dark[:, -int(w * 0.02):] = 0
    k = max(3, int(min(h, w) * 0.035)) | 1
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, ker, iterations=2)
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lbl, stats, _ = cv2.connectedComponentsWithStats(dark, 8)
    if n <= 1:
        return None, 0.0, 0.0
    idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, bw, bh, area = stats[idx]
    ar = float(area) / (w * h)
    if ar < min_area:
        return None, 0.0, 0.0
    # 主体框要包含纹理：再看框内高频是否足够（纯黑衬衫/黑影不算发型主体）
    x1, y1 = min(w, x + bw), min(h, y + bh)
    roi = cv2.cvtColor(frame[y:y1, x:x1], cv2.COLOR_BGR2GRAY)
    det = lap_norm(roi) if roi.size > 400 else 0.0
    conf = float(np.clip(det / 60.0, 0, 1)) * float(np.clip(ar / 0.18, 0, 1)) ** 0.5
    if conf < 0.12:
        return None, ar, conf
    return (int(x), int(y), int(x1), int(y1)), ar, conf


def clutter_score(frame):
    """背景杂乱度：Canny 边缘密度 + 局部熵，越高越乱"""
    g = cv2.cvtColor(cv2.resize(frame, (320, 568)), cv2.COLOR_BGR2GRAY)
    e = cv2.Canny(g, 60, 150)
    edge = float(e.mean()) / 255.0
    # 4x4 网格边缘密度方差 —— 杂乱背景往往局部扎堆
    gh, gw = g.shape[0] // 4, g.shape[1] // 4
    cells = [e[i * gh:(i + 1) * gh, j * gw:(j + 1) * gw].mean() / 255.0
             for i in range(4) for j in range(4)]
    return {"edge": round(edge * 100, 2), "edge_sd": round(float(np.std(cells)) * 100, 2)}


# ============================================================ 运动分析

def _cam_shifts(seq, max_frames=30):
    """背景块相位相关 → 相机每帧位移序列。**只测相机，不测被摄体**。

    做法：取画面四角 + 上下边中一共 6 块（竖屏人像里这些位置几乎必然是背景：
          墙/门/货架/地面），块内相位相关。块无效（纯色、无纹理、响应<0.15）就跳过。
    降级：1/4 块命中不足 3 个 → 放大到 1/3 块再试（覆盖更大、更可能有纹理）。
    返回空列表 = 画面里没有任何可跟踪的背景，抖动**无法测量**（不是"没有抖动"）。
    """
    for div in (4, 3):
        hh, ww = seq[0].shape[:2]
        cw, ch = max(24, ww // div), max(24, hh // div)
        tiles = [(0, 0), (ww - cw, 0), (0, hh - ch), (ww - cw, hh - ch),
                 (ww // 2 - cw // 2, 0), (ww // 2 - cw // 2, hh - ch)]
        shifts = []
        for i in range(min(len(seq) - 1, max_frames)):
            vals = []
            for (tx, ty) in tiles:
                pa = seq[i][ty:ty + ch, tx:tx + cw]
                pb = seq[i + 1][ty:ty + ch, tx:tx + cw]
                if pa.size < 256:
                    continue
                a = np.float32(pa); b = np.float32(pb)
                a -= a.mean(); b -= b.mean()
                if a.std() < 2.0:            # 纯色块，相关结果无意义
                    continue
                try:
                    (dx, dy), resp = cv2.phaseCorrelate(a, b)
                except Exception:
                    continue
                if resp >= 0.15:
                    vals.append((dx, dy))
            if len(vals) >= 3:
                vs = np.array(vals)
                # 一致性闸门：相机运动是整体的，各块位移应该接近。
                # 纯色/重复纹理（白墙+网格线）会让各块各说各话，离散度大 → 整帧丢弃。
                if float(np.std(np.hypot(vs[:, 0], vs[:, 1]))) > 2.5:
                    continue
                shifts.append((float(np.median(vs[:, 0])), float(np.median(vs[:, 1]))))
        if len(shifts) >= max(3, int((len(seq) - 1) * 0.5)):
            return shifts
    return []


_MOT_EMPTY = {"ok": False, "speed_px": None, "speed_pct_w": None, "speed_max_pct_w": None,
              "natural": None, "smooth": None, "dir_consist": None, "cam_moving": None,
              "cam_speed_px": None, "jitter": None, "measured": False,
              "is_static": None, "is_whip": False}


def motion_analysis(seq, size):
    """连续帧光流：返回 速度序列 / 自然度 / 抖动 / 方向一致性。

    测不出时返回 _MOT_EMPTY：字段一个不少、值全是 None。
    早退只给 {"ok": False} 会让下游 d['jitter'] 直接 KeyError——宁可给空值也别给空洞。
    """
    if len(seq) < 4:
        return dict(_MOT_EMPTY)
    w, h = size
    mags, angs = [], []
    for i in range(len(seq) - 1):
        p0 = cv2.goodFeaturesToTrack(seq[i], 90, 0.01, 7)
        if p0 is None or len(p0) < 12:
            continue
        p1, st, _ = cv2.calcOpticalFlowPyrLK(seq[i], seq[i + 1], p0, None)
        if p1 is None:
            continue
        ok = st.ravel() == 1
        d = (p1 - p0).reshape(-1, 2)[ok]
        if len(d) < 10:
            continue
        m = np.linalg.norm(d, axis=1)
        # 用中位数抗前景局部运动
        mags.append(float(np.median(m)))
        angs.append(float(np.median(np.arctan2(d[:, 1], d[:, 0]))))

    if len(mags) < 3:
        return dict(_MOT_EMPTY)

    m = np.array(mags)
    # 抖动 + 运镜自然度：必须只看**相机自己**在不在动。
    # 坑：整帧相位相关会把"模特甩头发"算成"画面位移"。实测固定机位素材
    # 整帧位移能读到 1.6~2.2，全是头发在晃。所以改成只取四角背景块做相关——
    # 背景（墙/门/货架）只会因相机而动，这才是真正的运镜与抖动。
    shifts = _cam_shifts(seq)

    speed = float(np.median(m))                      # 画面内活动量（含被摄体）
    speed_max = float(np.percentile(m, 90))
    n_need = max(3, int((len(seq) - 1) * 0.5))
    measured = len(shifts) >= n_need
    if measured:
        jit = float(np.median([math.hypot(*s_) for s_ in shifts])) * 15.0 / w * 100
        cam_mag = float(np.median([math.hypot(*s_) for s_ in shifts]))
        # 相机自身在动吗？背景位移中位数 <1.0px/帧(在320宽上) ≈ 三脚架/桌面固定
        cam_moving = cam_mag >= 1.0
        if not cam_moving:
            smooth, dir_consist = 1.0, 1.0
        else:
            sm = np.array([math.hypot(*s_) for s_ in shifts])
            d1 = np.abs(np.diff(sm))
            d2 = np.abs(np.diff(sm, n=2))
            jitter_ratio = float(np.mean(d2) / (np.mean(d1) + 0.35)) if len(d1) else 0.0
            smooth = float(np.clip(1.0 - jitter_ratio * 0.9, 0, 1))
            av = np.exp(1j * np.array([math.atan2(s_[1], s_[0]) for s_ in shifts]))
            dir_consist = float(np.abs(np.mean(av)))
        natural = float(np.clip(0.62 * smooth + 0.38 * dir_consist, 0, 1))
    else:
        # 画面里找不到可跟踪的背景（纯白棚、纯色墙、满屏虚化）——测不出就报测不出。
        # 绝不能返回 0：那等于告诉下游"很稳"，是撒谎，比不测更危险。
        jit, cam_mag, cam_moving = None, None, None
        smooth = dir_consist = natural = None
    return {
        "ok": True,
        "speed_px": round(speed, 2),
        "speed_pct_w": round(speed / w * 100, 2),
        "speed_max_pct_w": round(speed_max / w * 100, 2),
        "natural": None if natural is None else round(natural, 3),
        "smooth": None if smooth is None else round(smooth, 3),
        "dir_consist": None if dir_consist is None else round(dir_consist, 3),
        "cam_moving": cam_moving,
        "cam_speed_px": None if cam_mag is None else round(cam_mag, 2),
        "jitter": None if jit is None else round(jit, 2),
        "measured": measured,
        "is_static": speed < 1.2,
        # 甩镜：瞬时位移超过画面宽 6% / 帧，画面必然拖影，发型细节全废
        "is_whip": speed_max / w * 100 > 5.5,
    }


# ============================================================ D1 镜头审美

def shot_analysis(path, frames, size, seq, seq_size, src_w=None, is_final=False):
    """一个镜头值不值得留：清晰 / 主体突出 / 发型细节 / 动作自然 / 技术细节 / 视觉吸引力"""
    w, h = size
    grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    if src_w is None:                      # 素材原始宽度：判"够不够 1080 输出"要用它，不能用抽帧宽
        src_w = int(probe(path)["w"])
    res_ok = src_w >= 1080

    # 原始尺寸帧：噪声估计和伪影校验都必须在原图上做。
    # 抽帧统一缩到 640，而缩放本身就是低通——等于把要检测的东西提前擦掉。
    _srcf = [g for g in grab_gray_src(path, n=4) if min(g.shape[:2]) >= 64] or grays
    _sig = float(np.median([noise_sigma_lap(g) for g in _srcf]))
    # 噪声理论贡献 20σ²，折算到归一尺度（与 lap_norm 同一个系数）
    _nz = 20.0 * _sig * _sig * (w / 640.0)

    # 尺度归一：小尺寸素材不放大，测完按 lap×(w/640) 折算到同一把尺子上
    # 再扣掉噪声贡献：噪点会把 lap 撑到天上（实测内容不变、只加 σ14 噪声，470→4268）
    sharp = max(0.0, float(np.median([lap_norm(g) for g in grays])) - _nz)
    sharp_p10 = max(0.0, float(np.percentile([lap_norm(g) for g in grays], 10)) - _nz)

    # 伪影校验：跨尺度能量比。只作诊断输出（与分辨率强耦合，不参与打分）
    _arts = [art_ratio(g) for g in _srcf]
    art_r = float(np.median(_arts))
    art_k, art_lab = art_penalty(art_r)

    # 画质（BRISQUE）：唯一能同时反映 模糊/噪声/压缩损伤 的指标。
    # 单帧波动大（实测 std 12~14），抽 8 帧取中位数才稳。
    _bq = [brisque(g) for g in grab_gray_src(path, n=8)]
    _bq = [x for x in _bq if x is not None]
    bq = float(np.median(_bq)) if _bq else None
    qual_k, qual_lab = quality_factor(bq)

    subj = [subject_masks(f) for f in frames]
    face_cov = sum(1 for s in subj if s["n_face"]) / max(1, len(subj))
    face_area = float(np.mean([s["face_area"] for s in subj]))
    hair_area = float(np.mean([s["hair_area"] for s in subj]))
    subj_src = "face" if face_cov >= 0.3 else ("texture" if hair_area > 0.03 else "none")
    _ks = [s_.get("subj_kind") for s_ in subj if s_.get("subj_kind")]
    if subj_src == "face":
        subj_kind = "face"
    elif _ks:
        subj_kind = max(set(_ks), key=_ks.count)      # 多数投票
    else:
        subj_kind = "none"
    # 主体突出度：脸+头发合计占画面比（毛发对发型展示才是主角）
    subject_ratio = float(np.mean([min(1.0, s["face_area"] * 1.35 + s["hair_area"] * 0.85)
                                   for s in subj]))

    # 发型细节：头发区域的高频纹理。黑发最怕死黑丢失纹理
    hair_det, hair_hl, hair_dark = [], [], []
    for f, s in zip(frames, subj):
        if not s["hair_box"]:
            continue
        x0, y0, x1, y1 = s["hair_box"]
        roi = f[y0:y1, x0:x1]
        if roi.size < 400:
            continue
        g = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        hair_det.append(lap_norm(g))
        hair_hl.append(float((g > 245).mean()) * 100)
        hair_dark.append(float((g < 12).mean()) * 100)
    hair_detail = max(0.0, (float(np.median(hair_det)) if hair_det else 0.0) - _nz)
    hair_clip_hi = float(np.mean(hair_hl)) if hair_hl else 0.0
    hair_clip_lo = float(np.mean(hair_dark)) if hair_dark else 0.0

    # 中心区纹理密度：均匀纹理的特写（满头卷发）局部集中度不高，但绝对细节量大
    core_txt = []
    for g in grays[:10]:
        hh, ww = g.shape
        c0, c1 = int(hh*0.22), int(hh*0.78)
        d0, d1 = int(ww*0.18), int(ww*0.82)
        core_txt.append(float(cv2.Laplacian(g[c0:c1, d0:d1], cv2.CV_64F).var()))
    texture_core = max(0.0, (float(np.median(core_txt)) if core_txt else 0.0) - _nz)

    # 技术细节：局部高频能量集中度（剪刀/梳子/发丝特写会明显偏高）
    detail_peak = 0.0
    for g in grays[:12]:
        gs = cv2.resize(g, (320, 568))
        lap = np.abs(cv2.Laplacian(gs, cv2.CV_64F))
        gh, gw = lap.shape[0] // 4, lap.shape[1] // 4
        cells = [lap[i * gh:(i + 1) * gh, j * gw:(j + 1) * gw].mean()
                 for i in range(4) for j in range(4)]
        detail_peak = max(detail_peak, max(cells) / (np.mean(cells) + 1e-6))

    mot = motion_analysis(seq, seq_size)

    # 视觉吸引力（组内绝对参考）：清晰 + 主体 + 色彩张力 + 运动
    lab = [lab_stats(f) for f in frames[:12]]
    sat = float(np.mean([l["sat"] for l in lab]))
    color_tension = float(np.mean([max(l["a"] - 128, 0) ** 2 + max(l["b"] - 128, 0) ** 2
                                   for l in lab]) ** 0.5)

    cl = [clutter_score(f) for f in frames[:8]]
    edge = float(np.mean([c["edge"] for c in cl]))

    # 构图：主体（脸优先，无脸用纹理主体）离中心 / 三分线哪个更近
    thirds = [(1/3, 1/3), (2/3, 1/3), (1/3, 2/3), (2/3, 2/3)]
    ce, te, hr = [], [], []
    for s_ in subj:
        bx = s_["subj_box"]
        if not bx:
            continue
        x0, y0, x1, y1 = bx
        cx, cy = (x0 + x1) / 2 / w, (y0 + y1) / 2 / h
        ce.append(math.hypot(cx - 0.5, cy - 0.5))
        te.append(min(math.hypot(cx - tx, cy - ty) for tx, ty in thirds))
        hr.append(y0 / h)

    # 字幕安全区：抖音字幕/贴纸通常压在底部 18% 和右侧 12%（按钮区）。
    # 只对"露脸"镜头算——背影/产品特写的主体本来就铺满画面，按这条判全是误报。
    sub_hit = []
    ui_hit = []
    if subj_src == "face":
        for s_ in subj:
            bx = s_["subj_box"]
            if not bx:
                continue
            x0, y0, x1, y1 = bx
            sub_hit.append(1.0 if y1 / h > 0.82 else 0.0)
            ui_hit.append(1.0 if x1 / w > 0.86 else 0.0)
    sub_conflict = float(np.mean(sub_hit)) if sub_hit else 0.0
    ui_conflict = float(np.mean(ui_hit)) if ui_hit else 0.0

    thirds_err = float(np.median(te)) if te else None
    center_err = float(np.median(ce)) if ce else None
    headroom = float(np.median(hr)) if hr else None

    return {
        "sharpness": round(sharp, 1),
        "sharpness_p10": round(sharp_p10, 1),
        "art_ratio": round(art_r, 2),
        "art_penalty": art_k,
        "art_label": art_lab,
        "noise_sigma": round(_sig, 2),
        "is_final": bool(is_final),
        "brisque": None if bq is None else round(bq, 1),
        "qual_penalty": qual_k,
        "qual_label": qual_lab,
        "src_w": int(src_w),
        "subj_src": subj_src,
        "subj_kind": subj_kind,
        "res_ok": bool(res_ok),
        "face_cover": round(face_cov * 100, 0),
        "face_area_pct": round(face_area * 100, 2),
        "hair_area_pct": round(hair_area * 100, 2),
        "subject_ratio": round(subject_ratio, 3),
        "hair_detail": round(hair_detail, 1),
        "hair_clip_hi_pct": round(hair_clip_hi, 2),
        "hair_clip_lo_pct": round(hair_clip_lo, 2),
        "craft_peak": round(detail_peak, 2),
        "texture_core": round(texture_core, 1),
        "motion": mot,
        "sat": round(sat, 1),
        "color_tension": round(color_tension, 1),
        "edge_density": round(edge, 2),
        "clutter_sd": round(float(np.mean([c["edge_sd"] for c in cl])), 2),
        "subtitle_conflict": round(sub_conflict, 2),
        "ui_conflict": round(ui_conflict, 2),
        "thirds_err": round(thirds_err, 3) if thirds_err is not None else None,
        "center_err": round(center_err, 3) if center_err is not None else None,
        "headroom": round(headroom, 3) if headroom is not None else None,
    }


# ============================================================ D1 打分

def score_shot(f):
    """镜头价值分 = 三维加权（清晰 22 + 主体 16 + 质感 12 + 构图 6 = 56）+ 基线 44 - 缺陷扣分。
    不用"100 分起扣"：那样没缺陷的镜头全是 100，失去区分度。
    清晰度分两套口径——人像看发丝，环境看整体。这是本次标定最关键的修正。
    """
    s, why = 44.0, []
    hd = f["hair_detail"]
    kind = f.get("subj_kind", "none")
    is_obj = kind == "object"                 # 深色产品/包装：有主体，但不是头发
    is_portrait = (kind in ("face", "hair") or (kind == "none" and f["hair_area_pct"] >= 2.0)) and hd > 0

    # ---------- 1) 清晰 0-22（阈值按尺度归一后的口径重标）
    if is_obj:
        c, unit, bad, soft, good, great = hd, "主体细节", 15, 40, 62, 340
    elif is_portrait:
        c, unit, bad, soft, good, great = hd, "发丝锐度", 15, 40, 62, 340
    else:
        c, unit, bad, soft, good, great = f["sharpness"], "整体锐度", 14, 32, 55, 260
    if c < bad:
        q = 0.0; why.append(("模糊", f"{unit} {c}（<{bad}）", "对焦跑偏，弃"))
    elif c < soft:
        q = 0.36; why.append(("偏软", f"{unit} {c}", "unsharp=5:5:0.7 可救，但救不回细节"))
    elif c < good:
        q = 0.70; why.append(("略欠锐", f"{unit} {c}", "锐化可补"))
    elif c <= great:
        q = 1.0
    else:
        q = 0.82; why.append(("锐化过度/噪点", f"{unit} {c}", "降锐 + hqdn3d=2:1:3:3"))
    # 画质折扣：BRISQUE 是唯一同时正确反映 模糊/噪声/压缩损伤 的指标。
    # 手搓的跨尺度比只作诊断输出——它与分辨率强耦合（1080 素材 1.1-2.7，406 素材 3.0-4.0），
    # 同一把尺子量不了两种尺寸，不能参与打分。
    # 画质问题只报警告、不从绝对分里扣，原因很实在：
    # BRISQUE 按自然照片建模，画面上的花字/贴纸会被当成"结构异常"——
    # 自家成片实测 78~94 分（比 120kbps 压缩片还差），一刀切扣分会把好片全打死。
    # 所以绝对分只管"这条清楚不清楚"，"这条干不干净"交给 rank_pool 做组内比较，
    # 以及 qa_loop 的素材闸门做硬拦截。同一个池子里的素材画面性质相近，相对比较才可靠。
    # 画质折扣只在**素材**上生效。成片（is_final）必须关掉：
    # BRISQUE 按自然照片建模，画面上的花字/贴纸会被当成"结构异常"，
    # 自家成片实测 78~94 分，比 120kbps 压缩片还差 —— 对成片用它等于乱杀。
    _qk = f.get("qual_penalty", 1.0)
    _ak = f.get("art_penalty", 1.0)
    _k = min(_qk, _ak) if not f.get("is_final") else 1.0
    _lab = f.get("qual_label") or f.get("art_label")
    if _k < 0.9 and q > 0.3 and _lab:
        why.append((_lab, f"BRISQUE {f.get('brisque')}", "压缩/噪声吃掉了细节，尽量换高码率源"))
    s += 22 * q * _k

    # ---------- 1b) 分辨率硬伤：清晰≠够用。406 宽的发丝再锐，放大到 1080 也是糊的
    sw = f.get("src_w", 1080)
    if sw < 1080:
        pen = 10 if sw >= 720 else 18
        s -= pen
        why.append(("分辨率不足", f"源宽 {sw}px",
                    f"输出 1080 需放大 {1080/sw:.1f}× → 只能降级输出或用原片"))

    # ---------- 2) 主体 0-16（占比 × 绝对大小，双约束）
    sr = f["subject_ratio"]
    fa = f["face_area_pct"] / 100.0
    is_tex = f.get("subj_src") == "texture"
    if sr >= 0.015:
        if is_tex:
            # 背影/产品特写：没有脸，不能用"人脸大小"打折。面积够大就是主体突出
            subj_q = min(1.0, sr / 0.30)
        else:
            subj_q = min(1.0, sr / 0.30) * (min(1.0, fa / 0.10) ** 0.5 if fa > 0.005 else 0.55)
    else:
        # 无主体：看中心区纹理——满屏发丝是特写，满屏虚化是空镜
        tc = f.get("texture_core", 0)
        if tc > 260:
            subj_q = 0.55; why.append(("满屏纹理特写", f"中心纹理 {tc}", "DETAIL 素材，适合慢放"))
        elif f["craft_peak"] > 2.4:
            subj_q = 0.40; why.append(("局部细节特写", f"集中度 {f['craft_peak']}×", "作 DETAIL 用"))
        else:
            subj_q = 0.0; why.append(("无主体", f"主体 {sr*100:.1f}% 中心纹理 {tc:.0f}",
                                      "空镜，只能做转场或垫底"))
    s += 16 * subj_q * (0.48 + 0.52 * q)      # 糊的镜头主体分打折：看不清就不算"主体突出"
    if sr > 0.40:
        why.append(("主体饱满", f"{sr*100:.0f}%", "构图有力"))

    # ---------- 3) 质感 0-12（发丝层次 + 技术细节 + 光影跨度）
    tex = 0.0
    if is_portrait:
        hdc = min(1.0, max(0.0, (hd - 30) / 260))
        tex += 0.5 * hdc
        if hd > 150:
            why.append(("发丝质感强", f"{hd}", "适合 DETAIL 慢放"))
        if f["hair_clip_lo_pct"] > 16:
            tex -= 0.18; why.append(("头发死黑", f"{f['hair_clip_lo_pct']}% 压到 0",
                                     "colorlevels=rimin=0.05，否则层次全丢"))
        if f["hair_clip_hi_pct"] > 12:
            _nm = "主体高光" if is_obj else "头发高光"
            tex -= 0.12; why.append((_nm + "爆了", f"{f['hair_clip_hi_pct']}%",
                                     "压高光，强光下发丝糊成白片"))
    tex += 0.30 * min(1.0, max(0.0, (f["craft_peak"] - 1.6) / 1.8))
    if f["craft_peak"] > 2.8:
        why.append(("有技术细节", f"局部能量 {f['craft_peak']}×", "0.5x 慢放特写的好素材"))
    lsd = f.get("_Lsd")
    s += 12 * float(np.clip(tex, -0.3, 1.0))

    # ---------- 4) 构图 0-6
    te = f.get("thirds_err")
    cr = f.get("center_err")
    if te is not None and cr is not None:
        best = min(te, cr)
        if best < 0.06:   s += 6
        elif best < 0.12: s += 4.6
        elif best < 0.20: s += 3.0
        elif best < 0.30: s += 1.4
        else:
            s += 0; why.append(("构图偏", f"离中心/三分 {best:.2f}", "重新取景或裁切"))
        hr = f.get("headroom")
        if hr is not None and (hr < 0.03 or hr > 0.28):
            s -= 4; why.append(("头顶留白失衡", f"{hr*100:.0f}%",
                                "头顶太挤会压抑，太空会空；控制在 5-20%"))

    # ---------- 5) 缺陷扣分
    m = f["motion"]
    if m.get("ok"):
        if m.get("is_whip"):
            s -= 30; why.append(("甩镜废片", f"峰值 {m['speed_max_pct_w']}%W/帧",
                                 "拖影严重，发型全糊，弃"))
        jv = m.get("jitter")
        if jv is not None:
            if jv > 3.0:
                s -= 17; why.append(("抖得厉害", f"{jv}", "deshake 或弃"))
            elif jv > 1.8:
                s -= 7; why.append(("轻微晃", f"{jv}", "可接受"))
        elif m.get("ok"):
            why.append(("抖动未测", "画面无可跟踪背景", "纯色/虚化背景测不出，这项不扣分但别当真"))
        nv = m.get("natural")
        if nv is not None and nv < 0.35 and not m.get("is_static"):
            s -= 10; why.append(("动作生硬", f"自然度 {nv}",
                                 "急停急起/方向乱跳，剪掉起止两端"))
    if f.get("subtitle_conflict", 0) > 0.35:
        s -= 10; why.append(("字幕会挡主体", f"{f['subtitle_conflict']*100:.0f}% 帧的下巴低于 80% 线",
                             "重构图把人物上移，或字幕改放顶部"))
    if f.get("ui_conflict", 0) > 0.35:
        s -= 6; why.append(("右侧按钮区压到人物", f"{f['ui_conflict']*100:.0f}% 帧",
                            "抖音右侧点赞/评论会盖住，主体左移"))
    if f["edge_density"] > 9:
        s -= 9; why.append(("背景杂乱", f"边缘密度 {f['edge_density']}", "裁切或虚化背景"))
    elif f["edge_density"] > 6.5:
        s -= 4

    return {"score": round(float(np.clip(s, 0, 100)), 1), "reasons": why,
            "clarity": round(c, 1), "clarity_unit": unit, "is_portrait": is_portrait}


# ============================================================ D4 叙事：镜头分类

KIND_RULES = """
BEFORE  原貌：正面人脸 + 发丝无造型感(细节低) + 静止
PROCESS 操作：有手/工具 + 有运动 + 脸不完整
DETAIL  特写：主体极小 + 局部细节极高 + 常配慢放
AFTER   成果：完整人脸 + 发丝细节高 + 构图端正面
CTA     收尾：静止 + 留白多 + 细节低（可放品牌字）

关键：判断"这是什么镜头"永远是【跟同批素材比】，不是绝对阈值。
      所以用组内百分位排名，不用 clip 归一化。
"""


def _pct(arr, v):
    """组内百分位 0..1。中点法：并列值取中位，最高值给 1.0
    坑：早期用 (a < v).mean() 会让组内最大值返回 0，导致最好的镜头被判最差。"""
    a = np.asarray(arr, dtype=float)
    return float((a < v).mean() + 0.5 * (a == v).mean())


def assign_kinds(recs):
    """给整池镜头打叙事标签。必须在有整池数据后调用。"""
    if not recs:
        return recs
    fa = [r["shot"]["face_area_pct"] for r in recs]
    hd = [max(0.01, r["shot"]["hair_detail"]) for r in recs]
    sr = [r["shot"]["subject_ratio"] for r in recs]
    cf = [r["shot"]["craft_peak"] for r in recs]
    fc = [r["shot"]["face_cover"] for r in recs]
    mv = [r["shot"].get("motion", {}).get("speed_pct_w", 0) if r["shot"].get("motion", {}).get("ok") else 0
          for r in recs]
    ed = [r["shot"]["edge_density"] for r in recs]

    for r in recs:
        sh = r["shot"]
        m = sh.get("motion", {})
        st = 1.0 if m.get("is_static", False) else 0.0
        fa_n = _pct(fa, sh["face_area_pct"])
        hd_n = _pct(hd, max(0.01, sh["hair_detail"]))
        sr_n = _pct(sr, sh["subject_ratio"])
        cf_n = _pct(cf, sh["craft_peak"])
        fc_n = _pct(fc, sh["face_cover"])
        mv_n = _pct(mv, m.get("speed_pct_w", 0) if m.get("ok") else 0)
        ed_n = _pct(ed, sh["edge_density"])
        # 手部/操作证据：主体大但脸占比小 → 大概率是手在动
        is_obj = sh.get("subj_kind") == "object"
        is_tex = (sh.get("subj_src") == "texture" and sh.get("hair_area_pct", 0) >= 10
                  and not is_obj)
        handish = 0.0 if is_tex else float(np.clip(
            (sh["subject_ratio"] - sh["face_area_pct"] / 100 * 0.6) * 5, 0, 1))
        locality = 1.0 - sr_n

        # 绝对归一化（跨素材可比），与组内百分位混合
        # 注意：hd 检测不到时为 0，那是【缺失】不是【没细节】——用中心纹理兜底
        hd_eff = sh["hair_detail"]
        if hd_eff < 3:
            hd_eff = max(sh.get("texture_core", 0) * 0.6, sh["sharpness"] * 0.7)
        a_fa = float(np.clip(sh["face_area_pct"] / 14, 0, 1))
        a_hd = float(np.clip((hd_eff - 45) / 195, 0, 1))   # 45→0, 240→1，与 score 口径一致
        a_sr = float(np.clip(sh["subject_ratio"] / 0.32, 0, 1))
        a_cf = float(np.clip((sh["craft_peak"] - 1.6) / 1.8, 0, 1))
        a_mv = float(np.clip((m.get("speed_pct_w", 0) if m.get("ok") else 0) / 8, 0, 1))

        def mix(g, a_):
            return 0.5 * g + 0.5 * a_

        p = {
            "AFTER":   mix(0.42 * fa_n + 0.38 * hd_n + 0.20 * fc_n,
                           0.42 * a_fa + 0.38 * a_hd + 0.20 * float(np.clip(sh["face_cover"] / 100, 0, 1))),
            "BEFORE":  mix(0.40 * fa_n + 0.34 * (1 - hd_n) + 0.26 * st,
                           0.40 * a_fa + 0.34 * (1 - a_hd) + 0.26 * st),
            "PROCESS": mix(0.42 * mv_n + 0.32 * handish + 0.26 * (1 - fa_n),
                           0.42 * a_mv + 0.32 * handish + 0.26 * (1 - a_fa)),
            "DETAIL":  mix(0.42 * cf_n + 0.32 * locality + 0.26 * hd_n,
                           0.42 * a_cf + 0.32 * (1 - a_sr) + 0.26 * a_hd),
            "CTA":     mix(0.40 * st + 0.28 * (1 - hd_n) + 0.20 * (1 - sr_n) + 0.12 * (1 - ed_n),
                           0.40 * st + 0.28 * (1 - a_hd) + 0.20 * (1 - a_sr) + 0.12 * (1 - float(np.clip(sh["edge_density"] / 10, 0, 1)))),
        }
        # ---- 结构硬规则：比软加权可靠得多
        fc_ = sh["face_cover"]
        skin_ = sh.get("skin_pct", 0)
        # 背影/后脑的成品展示：一整个画面就是做好的头发，这就是 AFTER，
        # 不是"没脸所以只能当空镜"。这条规则缺了，全店最值钱的展示镜头会被判成 CTA。
        if is_obj:
            # 深色产品/包装特写：主体小、局部细节集中 → DETAIL，不是"成品展示"
            p["DETAIL"] += 0.38
            p["AFTER"] *= 0.45
            p["CTA"] *= 0.60
            p["PROCESS"] *= 0.70
        if is_tex:
            p["AFTER"] += 0.34
            p["PROCESS"] *= 0.55
            p["DETAIL"] *= 0.55
            p["CTA"] *= 0.45
            if a_mv > 0.45:          # 画面里动作大（在剪/在吹）→ 才退回过程镜头
                p["AFTER"] -= 0.12
                p["PROCESS"] += 0.22
            else:                    # 几乎不动、就是站着展示：原貌镜头不会这么安静地占满画面
                p["AFTER"] += 0.08
                p["BEFORE"] *= 0.72
        # 没有完整脸但大片肤色 → 局部特写（发丝/侧脸/耳边）
        if fc_ < 12 and skin_ > 0.15 and not is_tex and not is_obj:
            p["DETAIL"] += 0.40
            p["CTA"] *= 0.25
            p["BEFORE"] *= 0.4
        # 没脸也没肤色 → 环境/空镜，只能做 CTA 底或转场
        if fc_ < 12 and skin_ < 0.08 and not is_tex and not is_obj:
            p["CTA"] += 0.25
            p["DETAIL"] *= 0.4
        # 稳定露脸 + 发丝好 → 成果
        if fc_ >= 60 and a_hd > 0.45:
            p["AFTER"] += 0.30
            p["CTA"] *= 0.30
        # 稳定露脸 + 发丝差 → 原貌
        if fc_ >= 60 and a_hd < 0.28:
            p["BEFORE"] += 0.28
        if fc_ < 20 and not is_tex and not is_obj:
            p["AFTER"] *= 0.25
            p["BEFORE"] *= 0.40
        # softmax 放大差异
        ex = {k: math.exp(v * 3.2) for k, v in p.items()}
        tot = sum(ex.values()) or 1
        pr = {k: round(v / tot, 3) for k, v in ex.items()}
        best = max(pr, key=pr.get)
        r["kind"] = best
        r["conf"] = pr[best]
        r["probs"] = pr
    return recs


def classify(f):
    """单镜头兜底分类（无整池时用经验阈值）"""
    p = {"AFTER": 0.0, "BEFORE": 0.0, "PROCESS": 0.0, "DETAIL": 0.0, "CTA": 0.0}
    hd = f["hair_detail"]
    hd_n = float(np.clip((hd - 45) / 195, 0, 1))
    fa_n = float(np.clip(f["face_area_pct"] / 14, 0, 1))
    sr_n = float(np.clip(f["subject_ratio"] / 0.30, 0, 1))
    cf_n = float(np.clip((f["craft_peak"] - 1.6) / 2.2, 0, 1))
    m = f.get("motion", {})
    mv_n = float(np.clip(m.get("speed_pct_w", 0) / 8, 0, 1)) if m.get("ok") else 0.25
    st = 1.0 if m.get("is_static", False) else 0.0
    is_obj = f.get("subj_kind") == "object"
    is_tex = (f.get("subj_src") == "texture" and f.get("hair_area_pct", 0) >= 10
              and not is_obj)
    handish = 0.0 if is_tex else float(np.clip(
        (f["subject_ratio"] - f["face_area_pct"] / 100 * 0.6) * 5, 0, 1))

    p["AFTER"] = 0.42 * fa_n + 0.38 * hd_n + 0.20 * float(np.clip(f["face_cover"] / 100, 0, 1))
    p["BEFORE"] = 0.40 * fa_n + 0.34 * (1 - hd_n) + 0.26 * st
    p["PROCESS"] = 0.42 * mv_n + 0.32 * handish + 0.26 * (1 - fa_n)
    p["DETAIL"] = 0.42 * cf_n + 0.32 * (1 - sr_n) + 0.26 * hd_n
    p["CTA"] = 0.40 * st + 0.28 * (1 - hd_n) + 0.20 * (1 - sr_n)

    if is_obj:                       # 产品/包装特写
        p["DETAIL"] += 0.38
        p["AFTER"] *= 0.45
        p["CTA"] *= 0.60
        p["PROCESS"] *= 0.70
    if is_tex:                       # 背影成品展示：不靠脸也要认得出
        p["AFTER"] += 0.34
        p["PROCESS"] *= 0.55
        p["DETAIL"] *= 0.55
        p["CTA"] *= 0.45
        if mv_n > 0.45:
            p["AFTER"] -= 0.12
            p["PROCESS"] += 0.22
        else:
            p["AFTER"] += 0.08
            p["BEFORE"] *= 0.72

    ex = {k: math.exp(v * 3.2) for k, v in p.items()}
    tot = sum(ex.values()) or 1
    pr = {k: round(v / tot, 3) for k, v in ex.items()}
    best = max(pr, key=pr.get)
    return {"kind": best, "conf": pr[best], "probs": pr}


# ============================================================ 综合单镜头

def analyze(path, n=32, verbose=False, is_final=False):
    info = probe(path)
    frames, size = grab(path, n=n)
    if not frames:
        raise RuntimeError(f"抽帧失败: {path}")
    seq, ssize = grab_seq(path)
    shot = shot_analysis(path, frames, size, seq, ssize, src_w=int(info["w"]), is_final=is_final)
    score = score_shot(shot)
    # 同一镜头的"成片口径"分：不合画质折扣。用于渲染后对比——
    # 成片里可能有花字，BRISQUE 会把花字当结构异常，实测时必须关掉这个折扣，
    # 预测也得跟着关，否则两边口径不同，对账永远在漂。
    shot["score_final"] = score_shot({**shot, "is_final": True})["score"]
    # 补 skin_pct 给分类器
    subj = [subject_masks(f) for f in frames[:10]]
    shot["skin_pct"] = round(float(np.mean([s["skin_pct"] for s in subj])), 4)
    shot["_Lsd"] = round(float(np.mean([lab_stats(f)["Lsd"] for f in frames[:10]])), 1)
    shot["n_face_frames"] = int(sum(1 for s in subj if s["n_face"]))
    kind = classify(shot)
    labs = [lab_stats(f) for f in frames[:14]]
    look = {
        "L": round(float(np.mean([l["L"] for l in labs])), 1),
        "a": round(float(np.mean([l["a"] for l in labs])), 1),
        "b": round(float(np.mean([l["b"] for l in labs])), 1),
        "Lsd": round(float(np.mean([l["Lsd"] for l in labs])), 1),
        "sat": round(float(np.mean([l["sat"] for l in labs])), 1),
        "deltaE_ref": None,
    }
    rec = {"path": path, "name": os.path.basename(path), "dur": info["dur"],
           "w": info["w"], "h": info["h"], "fps": info["fps"],
           "shot": shot, "score": score["score"], "reasons": score["reasons"],
           "kind": kind["kind"], "conf": kind["conf"], "probs": kind["probs"],
           "look": look, "_lab": labs[0]}
    if verbose:
        print(f"  {rec['name']:<28} 分 {rec['score']:>5}  {rec['kind']:<8}"
              f"({rec['conf']:.0%})  {info['dur']:.1f}s")
    return rec


# ============================================================ D1 组内排名

def rank_pool(recs):
    """组内相对吸引力：绝对分只做筛选，相对分决定谁上"
    关键点：好片子是比出来的。同一批素材里，谁的分最高谁就是钩子。"""
    if not recs:
        return recs

    # 画质劣化只在**池内**比较：BRISQUE 的绝对值不可跨场景用（自家成片 78~94，
    # 因为花字被当成结构异常），但同一批素材的画面性质相近，相对高低是可靠的。
    # 实测同一素材：8Mbps 36.9 / 800k 48.1 / 300k 58.7 / 120k 62.4。
    _bq = [r["shot"].get("brisque") for r in recs if r.get("shot", {}).get("brisque") is not None]
    if len(_bq) >= 3:
        _mid = float(np.median(_bq))
        for r in recs:
            _b = r.get("shot", {}).get("brisque")
            if _b is None:
                continue
            d = _b - _mid
            if d >= 18:
                r["quality_flag"] = "画质明显劣于同批"
                r["score"] = round(r["score"] - 8, 1)
            elif d >= 10:
                r["quality_flag"] = "画质略逊于同批"
                r["score"] = round(r["score"] - 4, 1)

    vals = np.array([r["score"] for r in recs])
    mu, sd = float(vals.mean()), float(vals.std() + 1e-6)
    for r in recs:
        z = (r["score"] - mu) / sd
        # 相对吸引力映射到 0..1
        r["rel"] = round(float(1 / (1 + math.exp(-z * 1.5))), 3)
        r["tier"] = "S" if z >= 1.0 else "A" if z >= 0.15 else "B" if z >= -0.8 else "C"
    return sorted(recs, key=lambda r: -r["score"])


# ============================================================ D3 跨镜头一致性

def cross_look_check(recs):
    """色调统一性：相邻镜头 ΔE + 全片离散度"""
    if not recs:
        return {}
    labs = [r["_lab"] for r in recs]
    adj = []
    for i in range(len(labs) - 1):
        adj.append(delta_e(labs[i], labs[i + 1]))
    allL = [l["L"] for l in labs]
    alla = [l["a"] for l in labs]
    allb = [l["b"] for l in labs]
    # 主色调（全片基准）
    base = {"L": float(np.median(allL)), "a": float(np.median(alla)),
            "b": float(np.median(allb))}
    dev = [delta_e(l, base) for l in labs]
    out = {
        "adjacent_dE_mean": round(float(np.mean(adj)), 2) if adj else 0,
        "adjacent_dE_max": round(float(np.max(adj)), 2) if adj else 0,
        "spread_dE_mean": round(float(np.mean(dev)), 2),
        "spread_dE_max": round(float(np.max(dev)), 2),
        "L_range": round(float(max(allL) - min(allL)), 1),
        "sat_range": round(float(max(l["sat"] for l in labs) -
                                 min(l["sat"] for l in labs)), 1),
        "base": {k: round(v, 1) for k, v in base.items()},
    }
    # 逐镜头的偏色方向（判断是不是被某个 LUT 带歪了）
    flags = []
    for r in recs:
        L = r["_lab"]
        dL, da, db = L["L"] - base["L"], L["a"] - base["a"], L["b"] - base["b"]
        if abs(da) > 5 or abs(db) > 5:
            tone = "偏" + ("红" if da > 5 else "青绿" if da < -5 else "") + \
                   ("黄" if db > 5 else "蓝" if db < -5 else "")
            flags.append({"name": r["name"], "tone": tone,
                          "dE": round(math.sqrt(dL**2 + da**2 + db**2), 1)})
    out["tone_flags"] = flags
    return out


# ============================================================ D3 发色真实性

def hair_color_check(rec, path):
    """发色是否被滤镜带偏：头发区域色相 vs 肤色区域色相的关系。
    黑发在 LAB 里 a/b 应接近 128；若头发整体 a/b 偏移与全图同向，
    说明是全局调色带偏的（不是真的染了色）。"""
    frames, _ = grab(path, n=10)
    if not frames:
        return {}
    devs = []
    for f in frames:
        s = subject_masks(f)
        if not s["hair_box"]:
            continue
        x0, y0, x1, y1 = s["hair_box"]
        roi = f[y0:y1, x0:x1]
        if roi.size < 400:
            continue
        lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB)
        L, A, B = lab[..., 0], lab[..., 1], lab[..., 2]
        # 只取暗部像素（头发本身）
        m = L < 110
        if m.sum() < 200:
            continue
        devs.append((float(A[m].mean()) - 128, float(B[m].mean()) - 128,
                     float(L[m].mean())))
    if not devs:
        return {"ok": False}
    da = float(np.median([d[0] for d in devs]))
    db = float(np.median([d[1] for d in devs]))
    dL = float(np.median([d[2] for d in devs]))
    chroma = math.hypot(da, db)
    return {
        "ok": True,
        "hair_da": round(da, 1), "hair_db": round(db, 1), "hair_L": round(dL, 1),
        "hair_chroma": round(chroma, 1),
        # 黑发 chroma 应 <6；染发会明显高，但要看是不是全片同向
        "verdict": "偏色" if chroma > 9 else "自然",
    }


# ============================================================ D2 节奏审美

# 专业剪辑的时长先验（秒）。这是经验值，按短视频平台习惯定：
# 观众 1.5 秒内决定划不划走 → 开场必须短；成果要给足时间欣赏 → 结尾必须长。
KIND_DUR = {
    "HOOK":    (0.85, 1.45),
    "BEFORE":  (1.60, 2.40),
    "PROCESS": (0.55, 1.00),
    "DETAIL":  (1.90, 3.00),
    "AFTER":   (2.40, 3.60),
    "CTA":     (1.40, 2.20),
}

KIND_WEIGHT = {"HOOK": 1.00, "BEFORE": 0.72, "PROCESS": 0.58,
               "DETAIL": 0.86, "AFTER": 0.95, "CTA": 0.60}


def info_density(rec):
    """信息密度 0..1：画面里有多少东西在变化、有多少细节要看。
    密度高 → 镜头要短（否则闷）；密度低 → 镜头可以长（给呼吸）。"""
    s = rec["shot"]
    m = s.get("motion", {})
    mv = float(np.clip(m.get("speed_pct_w", 0) / 10.0, 0, 1)) if m.get("ok") else 0.25
    detail = float(np.clip(s["craft_peak"] / 4.0, 0, 1))
    subj = float(np.clip(s["subject_ratio"] / 0.18, 0, 1))
    sharp_n = float(np.clip(s["sharpness"] / 400.0, 0, 1))
    return round(0.34 * mv + 0.26 * detail + 0.24 * subj + 0.16 * sharp_n, 3)


def plan_duration(rec, bpm=None, beat_grid=True, role=None):
    """单镜头时长。区间按【叙事角色】取，不是按镜头类型——
    同一个镜头当钩子要 1.2s，当结尾要 3.4s，这是剪辑的核心判断。"""
    k = role or rec["kind"]
    lo, hi = KIND_DUR.get(k, KIND_DUR.get(rec["kind"], (1.0, 2.0)))
    mid = (lo + hi) / 2
    d = info_density(rec)
    # 密度高往区间下限靠，密度低往上限靠
    raw = hi - (hi - lo) * d
    # 质量加成：S 级镜头可以多给 10%，C 级砍 15%
    raw *= {"S": 1.10, "A": 1.00, "B": 0.90, "C": 0.78}.get(rec.get("tier", "A"), 1.0)
    raw = float(np.clip(raw, lo * 0.8, hi * 1.15))

    if bpm and beat_grid:
        beat = 60.0 / bpm
        # 对齐到半拍网格（0.5 拍的精度对短视频够用，整拍太粗会丢节奏）
        half = beat / 2
        n = max(1, round(raw / half))
        raw = n * half
    return round(raw, 3)


def structure_plan(recs, bpm=None, target=30.0):
    """叙事编排：不是按拍摄顺序拼，是按讲故事的需要排。
    美发探店的标准叙事弧：
        成果前置(悬念) → 原貌(落差) → 操作快切(专业) → 细节慢放(质感) → 完整成果(满足) → 品牌收尾
    """
    if not recs:
        return []

    # 只有一条素材：不做叙事切分。硬凑"钩子+原貌+过程"只会把一条完整的展示镜头
    # 切成几个 0.7 秒的碎片，看起来像卡带。直接取最稳的一段整段用，并说明原因。
    if len(recs) == 1:
        r = recs[0]
        role = r["kind"] if r["kind"] in ("AFTER", "DETAIL", "BEFORE") else "AFTER"
        want = {"AFTER": 3.6, "DETAIL": 2.8, "BEFORE": 2.4}.get(role, 3.2)
        d = round(min(r["dur"], want), 3)
        return [{
            "path": r["path"], "name": r["name"], "role": role, "kind": r["kind"],
            "dur": d, "speed": 1.0, "tier": r.get("tier"), "score": r["score"],
            "score_final": r["shot"].get("score_final", r["score"]),
            "note": "单镜头素材：只取最稳的一段直出，不做叙事切分（硬切会像卡带）",
            "src_in": round(max(0.0, r["dur"] - d), 3), "src_dur": round(r["dur"], 3),
            "timeline_in": 0.0, "in": round(max(0.0, r["dur"] - d), 3),
            "out": round(r["dur"], 3),
        }]

    pool = {}
    for r in recs:
        pool.setdefault(r["kind"], []).append(r)
    for k in pool:
        pool[k].sort(key=lambda r: -r["score"])

    used = set()

    def take(kind, n=1, min_score=0):
        """按分数取镜头。先按门槛取，取不到就降级——宁可降标准，也不能缺叙事功能。"""
        for thr in (min_score, min_score * 0.82, 0):
            out = []
            for r in pool.get(kind, []):
                if id(r) in used or r["score"] < thr:
                    continue
                out.append(r)
                if len(out) >= n:
                    break
            if out:
                for r in out:
                    used.add(id(r))
                return out
        return []

    def take_best(kind, n=1, floor=70):
        return take(kind, n, floor)

    seq = []
    afters_all = sorted([r for r in recs if r["kind"] in ("AFTER", "DETAIL")],
                        key=lambda r: -r["score"])

    # ---- 1) 钩子：先给结果。优先拿第 2 好的成果镜头，留给结尾用第 1 好的
    hook = None
    if len(afters_all) >= 2:
        hook = afters_all[1]
    elif afters_all:
        hook = afters_all[0]
        hook["_reuse"] = True          # 唯一成果镜头：开头取尾部、结尾用完整段
    if hook:
        used.add(id(hook))
        seq.append((hook, "HOOK", "成品前置，制造'她做完会是什么样'的悬念"))

    # ---- 2) 原貌
    for r in (take_best("BEFORE", 1, 68) or take_best("PROCESS", 1, 68)):
        seq.append((r, "BEFORE", "交代起点，建立对比基准"))

    # ---- 3) 过程快切。素材不够就【切分长镜头】——专业剪辑本来就这么干：
    #         一条 4 秒操作镜头切成 3 刀 0.8s，节奏立刻起来。
    procs = take_best("PROCESS", 4, 70)
    if len(procs) < 2:
        procs += take_best("AFTER", 2 - len(procs), 70)    # 用成果镜头冒充过程，别动用 DETAIL
    procs.sort(key=lambda r: r["shot"].get("subject_ratio", 0))
    for r in procs:
        seq.append((r, "PROCESS", "关键操作，快切堆出专业密度"))

    have_p = len([x for x in seq if x[1] == "PROCESS"])
    if have_p < 3:
        need = 3 - have_p
        # 注意 id(r) not in used：漏了这一条，同一个成果镜头会被反复切去冒充过程，
        # 结果 9.6 秒的成品展示被切成 4 个 0.7 秒碎片，观众根本看不清。
        cand = [r for r in sorted(recs, key=lambda r: -r["dur"])
                if id(r) not in used and r["dur"] >= 2.2 and r["score"] >= 55
                and r["kind"] not in ("PROCESS", "DETAIL")]     # 特写要留着做慢镜
        for r in cand:
            if need <= 0:
                break
            n = int(min(need, max(2, min(3, r["dur"] // 1.05))))
            for k in range(n):
                seq.append((r, "PROCESS", f"一镜切 {k+1}/{n} 刀，制造节奏"))
            need -= n

    # ---- 4) 细节慢放
    for r in take_best("DETAIL", 2, 66):
        seq.append((r, "DETAIL", "慢放特写，让观众看清手法与发丝"))

    # ---- 5) 成果完整展示
    for r in take_best("AFTER", 2, 72):
        seq.append((r, "AFTER", "完整成果，给足欣赏时间"))

    # ---- 6) 兜底补位
    if len(seq) < 4:
        rest = sorted([r for r in recs if id(r) not in used], key=lambda r: -r["score"])
        for r in rest:
            if len(seq) >= 6:
                break
            seq.append((r, r["kind"], "补位"))
            used.add(id(r))

    if not seq:
        return []

    # ---- 时长分配
    shots = []
    seg_count = {}
    for r, role, note in seq:
        # 同一素材多次出现 → 分别取不同入点，避免看起来卡带
        key = r["path"]
        idx = seg_count.get(key, 0)
        seg_count[key] = idx + 1
        d = plan_duration(r, bpm, role=role)
        d *= {"AFTER": 1.08, "DETAIL": 1.04}.get(role, 1.0)
        d = max(0.5, d)
        src_dur = max(0.1, r["dur"])
        speed = 1.0
        tail = r.get("_reuse") and role == "HOOK"
        avail = src_dur
        if d > avail - 0.05:
            d = max(0.6, avail - 0.05)
        if role == "DETAIL" and avail >= d / 0.62:
            speed = 0.62                       # 慢放，突出质感
        if role == "PROCESS":
            d = min(d, 0.95)                   # 过程镜头一律压到 1 秒内
        # 同一素材第 idx 次使用：入点顺移，取不同片段
        seg_off = 0.0
        if idx > 0 and avail > d * speed + 0.3:
            seg_off = min(avail - d * speed - 0.05,
                          idx * (d * speed + 0.12))
        shots.append({
            "path": r["path"], "name": r["name"], "role": role, "kind": r["kind"],
            "dur": round(d, 3), "speed": speed, "tier": r.get("tier"),
            "score": r["score"], "score_final": r["shot"].get("score_final", r["score"]),
            "note": note,
            "src_in": round(max(0.0, avail - d * speed - 0.02), 3) if tail
                      else round(seg_off, 3),
            "src_dur": round(avail, 3),
        })

    # ---- 时长不足时补镜头：观众不会因为你剪短而满意
    cur = sum(x["dur"] for x in shots)
    if cur < target * 0.88:
        # 补位只补合格素材：失焦/甩镜这类有硬伤的绝不进正片
        def _ok(r):
            bad = {"模糊", "甩镜废片", "抖得厉害"}
            return not any(t in bad for t, _, _ in r["reasons"])
        rest = [r for r in sorted(recs, key=lambda r: -r["score"])
                if id(r) not in used and r["score"] >= 66 and _ok(r)]
        for r in rest:
            if cur >= target * 0.98:
                break
            role = "DETAIL" if r["kind"] == "DETAIL" else "AFTER"
            d = plan_duration(r, bpm, role=role)
            d = max(0.8, min(d, r["dur"] - 0.05))
            new = {"path": r["path"], "name": r["name"], "role": role,
                   "kind": r["kind"], "dur": round(d, 3),
                   "speed": 0.62 if role == "DETAIL" and r["dur"] > d / 0.62 else 1.0,
                   "tier": r.get("tier"), "score": r["score"],
                   "score_final": r["shot"].get("score_final", r["score"]),
                   "note": "补足时长", "src_in": 0.0, "src_dur": round(r["dur"], 3)}
            # 插在最后一个 AFTER 之前：结尾要收在完整成果上，不能一串慢镜拖死
            pos = len(shots)
            for j in range(len(shots) - 1, -1, -1):
                if shots[j]["role"] == "AFTER":
                    pos = j
            shots.insert(pos, new)
            used.add(id(r)); cur += d

    t = 0.0
    for s_ in shots:
        s_["timeline_in"] = round(t, 3)
        s_["in"] = s_["src_in"]
        s_["out"] = round(min(s_["src_dur"], s_["src_in"] + s_["dur"] * s_["speed"]), 3)
        t += s_["dur"]

    total = t
    # 超时砍 B/C 级过程镜头
    while total > target * 1.15 and len(shots) > 5:
        cand = [i for i, x in enumerate(shots)
                if x["role"] in ("PROCESS", "BEFORE") and x["tier"] in ("B", "C")]
        if not cand:
            break
        i = min(cand, key=lambda j: shots[j]["score"])
        total -= shots[i]["dur"]
        shots.pop(i)
        t = 0.0
        for x in shots:
            x["timeline_in"] = round(t, 3); t += x["dur"]
        total = t

    for x in shots:
        x.pop("src_in", None)
    return shots


def rhythm_report(shots, bpm=None):
    """节奏分：快慢是否有设计，而不是平均主义"""
    if len(shots) < 3:
        return {"ok": False}
    durs = [s["dur"] for s in shots]
    iv = durs
    n = len(iv)
    third = max(1, n // 3)
    a = float(np.mean(iv[:third]))
    b = float(np.mean(iv[third:2 * third])) if n >= 3 else a
    c = float(np.mean(iv[2 * third:])) if n >= 3 else a
    # 段落级对比：中间应该比两头短（高潮在前中段）
    contrast = (max(a, c) - b) / max(1e-6, max(a, c))
    # 方差：全片同一长度 = 平（观众会困）
    cv = float(np.std(iv) / (np.mean(iv) + 1e-6))
    # 最短/最长比：专业剪辑的节奏张力
    ratio = max(iv) / max(0.1, min(iv))

    score = 100.0
    why = []
    if cv < 0.18:
        score -= 26
        why.append(("节奏平均", f"变异系数 {cv:.2f}", "每刀时长几乎一样，观众会疲劳；按镜头价值拉开差距"))
    if contrast < 0.03:
        score -= 14
        why.append(("没有段落起伏", f"中段/两端差 {contrast:.2f}", "开场快切→中段推进→结尾拉长，要有三个阶段"))
    if ratio < 1.6:
        score -= 14
        why.append(("缺张弛", f"最长/最短 {ratio:.2f}", "至少有一个 0.6s 快切和一个 3s 长镜"))
    if ratio > 6:
        score -= 8
        why.append(("忽快忽慢", f"最长/最短 {ratio:.2f}", "极端悬殊会跳，控制在 2-4 倍"))
    # 判定阈值必须和提示文案一致：原来代码卡 0.7s、文案写 0.8s、返修又按 0.55s，
    # 三处对不上，导致返修"改对了"但判定仍报不合格。
    fast = sum(1 for d in durs if d < 0.8)
    if fast < 2:
        score -= 10
        why.append(("没有真正的快切", f"{fast} 刀 <0.8s", "冲击力靠快切，至少 2 刀 <0.8s"))
    if sum(1 for d in durs if d > 2.6) == 0:
        score -= 10
        why.append(("没有停留", f"最长 {max(durs):.2f}s", "成果镜头要 >=2.8s 让观众看清"))

    return {
        "ok": True, "score": round(float(np.clip(score, 0, 100)), 1),
        "n_shots": n, "mean_dur": round(float(np.mean(iv)), 2),
        "cv": round(cv, 3), "contrast": round(contrast, 3),
        "ratio": round(ratio, 2),
        "section_mean": {"head": round(a, 2), "mid": round(b, 2), "tail": round(c, 2)},
        "why": why,
    }


def beat_curve(shots, bpm=None, step=0.1):
    """节奏能量曲线：用来画图、也用来跟理想曲线比。
    能量 = 该时刻镜头的冲击力（价值 × 权重）/ 时长倒数"""
    if not shots:
        return []
    total = max(s["timeline_in"] + s["dur"] for s in shots)
    pts = []
    for i, s in enumerate(shots):
        t0 = s["timeline_in"]
        w = KIND_WEIGHT.get(s["role"], 0.7)
        e = (s["score"] / 100.0) * w / max(0.4, s["dur"]) * 1.6
        pts.append({"t": round(t0, 2), "e": round(e, 3), "role": s["role"]})
    return {"total": round(total, 2), "points": pts}


# ============================================================ D4 叙事校验

def story_check(shots):
    """叙事完整度：一个美发视频该有的六拍齐不齐，顺序对不对"""
    roles = [s["role"] for s in shots]
    need = ["HOOK", "BEFORE", "PROCESS", "DETAIL", "AFTER"]
    have = set(roles)
    miss = [r for r in need if r not in have]
    s, why = 100.0, []

    for m in miss:
        s -= {"HOOK": 20, "BEFORE": 14, "PROCESS": 22, "DETAIL": 16, "AFTER": 24}.get(m, 8)
        why.append((f"缺 {m}", "结构不完整",
                    {"HOOK": "开场没有结果前置，完播率会掉",
                     "BEFORE": "没有原貌，看不出改变多少",
                     "PROCESS": "没有过程，显得不真实/不专业",
                     "DETAIL": "没有细节特写，技术感出不来",
                     "AFTER": "没有完整成果，等于白剪"}[m]))

    # 顺序：钩子必须在最前
    if roles and roles[0] != "HOOK":
        s -= 12
        why.append(("开头不是钩子", f"实际开头 {roles[0]}", "把最有冲击力的成果镜头提到 0 秒"))
    # BEFORE 必须在第一个 PROCESS 之前
    if "BEFORE" in roles and "PROCESS" in roles:
        if roles.index("BEFORE") > roles.index("PROCESS"):
            s -= 8
            why.append(("原貌在过程后", "-", "观众会搞不清改了什么"))
    # PROCESS 之后必须有 AFTER
    if "AFTER" in roles and "PROCESS" in roles:
        if roles.index("AFTER") < roles.index("PROCESS"):
            s -= 10
            why.append(("成果在过程前", "-", "只剩开头一秒能看，后面全废"))
    # 过程镜头数量：少于 2 个显得敷衍
    np_ = roles.count("PROCESS")
    if np_ < 2:
        s -= 10
        why.append(("过程太短", f"{np_} 个操作镜头", "至少 2-3 个，观众才信这是真做了"))
    if np_ > 5:
        s -= 6
        why.append(("过程拖沓", f"{np_} 个", "超过 5 个会腻，留最有力的"))

    return {"score": round(float(np.clip(s, 0, 100)), 1),
            "roles": roles, "missing": miss, "why": why}


# ============================================================ D5 商业审美

def business_check(shots, recs, total=None):
    """观众为什么愿意看完：第一眼 / 看得懂 / 显专业 / 记得住 / 不是艺术片"""
    s, why = 100.0, []
    detail = {}

    if not shots:
        return {"score": 0, "why": [("空", "-", "-")]}

    first = shots[0]
    # ---- 第一眼（前 3 秒）
    hook_ok = first["role"] == "HOOK"
    first_score = first["score"]
    three_sec = sum(x["dur"] for x in shots if x["timeline_in"] < 3.0)
    n_in_3s = sum(1 for x in shots if x["timeline_in"] < 3.0)
    detail["first3s"] = {"first_role": first["role"], "first_score": first_score,
                         "shots_in_3s": n_in_3s}
    if not hook_ok:
        s -= 22; why.append(("前 3 秒没钩子", f"开头是 {first['role']}", "把成果提到第一镜"))
    if first_score < 80:
        s -= 12; why.append(("首镜质量不够", f"{first_score} 分", "换 S 级镜头开场"))
    if n_in_3s < 2:
        s -= 8; why.append(("前 3 秒太静", f"只有 {n_in_3s} 刀", "抖音前 3 秒至少 2 刀，否则像静态图"))

    # ---- 看得懂：BEFORE / AFTER 是否同机位可比
    bef = [x for x in shots if x["role"] == "BEFORE"]
    aft = [x for x in shots if x["role"] == "AFTER"]
    readability = 0.0
    if bef and aft:
        rb = next((r for r in recs if r["path"] == bef[0]["path"]), None)
        ra = next((r for r in recs if r["path"] == aft[0]["path"]), None)
        if rb and ra:
            fb, fa_ = rb["shot"]["face_area_pct"], ra["shot"]["face_area_pct"]
            sim = 1.0 - min(1.0, abs(fb - fa_) / max(1.0, max(fb, fa_)))
            # 人脸占比接近 = 同机位/同景别，对比最直观
            readability = round(sim, 2)
            detail["readability"] = {"before_face": fb, "after_face": fa_, "sim": sim}
            if sim < 0.45:
                s -= 16
                why.append(("前后景别差太多", f"人脸 {fb}% vs {fa_}%",
                            "原貌和成果用同一机位/同一景别，观众才看得出变化"))
    else:
        s -= 14
        why.append(("缺前后对比", "没有 BEFORE 或 AFTER", "这是美发视频的命根子"))

    # ---- 显专业：过程+细节镜头数量
    craft_n = sum(1 for x in shots if x["role"] in ("PROCESS", "DETAIL"))
    detail["craft_shots"] = craft_n
    if craft_n < 3:
        s -= 16; why.append(("专业证据不足", f"{craft_n} 个过程/细节镜头",
                             "至少 3 个，观众才信这是真手法而非摆拍"))

    # ---- 记得住：品牌露出 + 结尾停留
    tail_dur = shots[-1]["dur"] if shots else 0
    detail["tail_dur"] = tail_dur
    if tail_dur < 1.2:
        s -= 8; why.append(("结尾一闪而过", f"{tail_dur}s", "留 1.5s+ 给品牌/团购信息"))

    # ---- 不是艺术片：全片是否过暗过灰
    if recs:
        Ls = [r["look"]["L"] for r in recs if "look" in r]
        sats = [r["look"]["sat"] for r in recs if "look" in r]
        meanL = float(np.mean(Ls)) if Ls else 128
        meanSat = float(np.mean(sats)) if sats else 60
        detail["meanL"], detail["meanSat"] = round(meanL, 1), round(meanSat, 1)
        # 用户的原话：高级感 ≠ 全片调暗 + 统一电影滤镜
        if meanL < 62 and meanSat < 42:
            s -= 18
            why.append(("压暗+去饱和过头", f"L={meanL:.0f} 饱和={meanSat:.0f}",
                        "手机小屏看会糊成灰片；高级感靠光影层次，不靠压黑"))
        if meanL > 205:
            s -= 8; why.append(("整体过亮发白", f"L={meanL:.0f}", "压曝光，肤色容易糊"))

    # ---- 完播长度：15-35s 是本地生活黄金区间
    tot = total if total else (shots[-1]["timeline_in"] + shots[-1]["dur"] if shots else 0)
    detail["total"] = round(tot, 2)
    if tot > 45:
        s -= 10; why.append(("太长", f"{tot:.0f}s", "本地生活 20-35s 完播最佳"))
    elif tot < 12:
        s -= 10; why.append(("太短", f"{tot:.0f}s", "信息量不够，看着像广告"))

    return {"score": round(float(np.clip(s, 0, 100)), 1), "detail": detail, "why": why}


# ============================================================ 汇总评分

DIM_NAME = {"shot": "镜头审美", "rhythm": "节奏审美", "look": "构图色彩",
            "story": "叙事审美", "business": "商业审美"}

# 权重：镜头是地基，节奏是灵魂，商业是目的
DIM_WEIGHT = {"shot": 0.24, "rhythm": 0.24, "look": 0.16, "story": 0.18, "business": 0.18}


def grade(total):
    if total >= 88: return "S", "可直接发"
    if total >= 78: return "A", "小修可发"
    if total >= 66: return "B", "需重排"
    if total >= 50: return "C", "需重剪"
    return "D", "废片"


def review(recs, shots, total=None):
    """五维总评"""
    if shots:
        rh = rhythm_report(shots)
        st = story_check(shots)
        bs = business_check(shots, recs, total)
    else:
        rh, st, bs = {"score": 0, "why": []}, {"score": 0, "why": []}, {"score": 0, "why": []}

    # 镜头维度：用入选镜头的均分 + 是否有 S 级
    if shots:
        used_paths = {s["path"] for s in shots}
        used = [r for r in recs if r["path"] in used_paths] or recs
    else:
        used = recs
    sh_score = float(np.mean([r["score"] for r in used])) if used else 0
    # 有 S 级加 4 分，说明素材里有能打的
    if any(r.get("tier") == "S" for r in used):
        sh_score = min(100, sh_score + 4)

    # 构图色彩维度：统一性 + 发色 + 亮度层次
    look = cross_look_check(recs)
    lk = 100.0
    lk_why = []
    if look:
        if look["spread_dE_mean"] > 9:
            lk -= 22
            lk_why.append(("全片色调不统一", f"平均 ΔE {look['spread_dE_mean']}",
                           "统一白平衡/LUT，暖冷别混着用"))
        elif look["spread_dE_mean"] > 5:
            lk -= 10
            lk_why.append(("色调略跳", f"ΔE {look['spread_dE_mean']}", "建议统一一级调色"))
        if look["adjacent_dE_max"] > 14:
            lk -= 12
            lk_why.append(("相邻切点色差大", f"最大 ΔE {look['adjacent_dE_max']}",
                           "切点两侧色温对齐，否则像两段片子"))
        if look["L_range"] > 55:
            lk -= 10
            lk_why.append(("明暗反差过大", f"L 跨度 {look['L_range']}",
                           "有的镜头极暗有的极亮，中间调缺失"))
        if look.get("tone_flags"):
            lk -= min(14, 4 * len(look["tone_flags"]))
            lk_why.append(("个别镜头偏色", f"{len(look['tone_flags'])} 条",
                           "；".join(f"{f['name'][:12]} {f['tone']}" for f in look["tone_flags"][:3])))
    lk = float(np.clip(lk, 0, 100))

    dims = {
        "shot": round(sh_score, 1),
        "rhythm": rh.get("score", 0),
        "look": round(lk, 1),
        "story": st.get("score", 0),
        "business": bs.get("score", 0),
    }
    tot = sum(dims[k] * DIM_WEIGHT[k] for k in DIM_WEIGHT)
    g, verdict = grade(tot)
    return {"dims": dims, "total": round(tot, 1), "grade": g, "verdict": verdict,
            "rhythm": rh, "story": st, "business": bs, "look_detail": look,
            "look_why": lk_why, "weight": DIM_WEIGHT}


# ============================================================ 报告渲染

def bar(v, width=20):
    n = int(round(width * v / 100))
    return "█" * n + "·" * (width - n)


def render_single(rec, path):
    s = rec["shot"]
    m = s.get("motion", {})
    print(f"\n{'='*70}")
    print(f"{rec['name']}   {rec['dur']:.1f}s  {rec['w']}x{rec['h']} @{rec['fps']:.0f}fps")
    print(f"{'='*70}")

    print(f"\n【D1 镜头审美】价值 {rec['score']}  类型 {rec['kind']}"
          f"（置信 {rec['conf']:.0%}）  层级 {rec.get('tier','-')}")
    print(f"  清晰度 {s['sharpness']} (p10 {s['sharpness_p10']})   "
          f"主体占比 {s['subject_ratio']*100:.1f}%   人脸占比 {s['face_area_pct']}%")
    print(f"  发型区 {s['hair_area_pct']}%  发丝细节 {s['hair_detail']}   "
          f"死黑 {s['hair_clip_lo_pct']}%  高光爆 {s['hair_clip_hi_pct']}%")
    if m.get("ok"):
        print(f"  运动 {m['speed_pct_w']}%W/帧  自然度 {m['natural']} "
              f"(平滑 {m['smooth']} 方向一致 {m['dir_consist']})  抖动 {m['jitter']}")
    print(f"  局部细节集中度 {s['craft_peak']}×   背景边缘密度 {s['edge_density']}")
    if rec["reasons"]:
        print("  判定：")
        for tag, val, fix in rec["reasons"]:
            print(f"    · {tag}：{val}  → {fix}")

    print(f"\n【D4 叙事功能概率】")
    for k, v in sorted(rec["probs"].items(), key=lambda x: -x[1])[:3]:
        print(f"    {k:<8} {bar(v*100, 16)} {v:.0%}")

    print(f"\n【D3 色彩】L={rec['look']['L']} a={rec['look']['a']} b={rec['look']['b']} "
          f"饱和={rec['look']['sat']} 明暗跨度={rec['look']['Lsd']}")
    hc = hair_color_check(rec, path)
    if hc.get("ok"):
        print(f"    发色：a偏移 {hc['hair_da']} b偏移 {hc['hair_db']} "
              f"彩度 {hc['hair_chroma']} → {hc['verdict']}")


def render_plan(recs, shots, bpm=None):
    print(f"\n{'='*74}")
    print("叙事编排（不是按拍摄顺序，是按讲故事的需要）")
    print(f"{'='*74}")
    print(f"{'#':<3}{'角色':<9}{'时长':>6}{'起':>7}{'变速':>6}{'层级':>5}  说明")
    print("-" * 74)
    for i, s in enumerate(shots, 1):
        print(f"{i:<3}{s['role']:<9}{s['dur']:>6.2f}{s['timeline_in']:>7.2f}"
              f"{s['speed']:>6.2f}{str(s['tier']):>5}  {s['note'][:26]}")
    tot = shots[-1]["timeline_in"] + shots[-1]["dur"] if shots else 0
    print("-" * 74)
    print(f"合计 {tot:.1f}s   镜头数 {len(shots)}")
    if bpm:
        beat = 60 / bpm
        print(f"BPM {bpm} → 每拍 {beat:.3f}s   全片 {tot/beat:.1f} 拍")
        # 检查切点是否落在拍上
        offs = []
        for s in shots:
            r = (s["timeline_in"] / beat) % 1
            offs.append(min(r, 1 - r) * beat)
        if offs:
            print(f"切点对拍偏差：中位 {np.median(offs)*1000:.0f}ms  最大 {max(offs)*1000:.0f}ms")


def render_review(rv, recs=None):
    print(f"\n{'='*70}")
    print(f"五维审美总评   {rv['total']} 分   【{rv['grade']}】 {rv['verdict']}")
    print(f"{'='*70}")
    for k, v in rv["dims"].items():
        w = rv["weight"][k]
        print(f"  {DIM_NAME[k]}  {bar(v)} {v:>5.1f}  ×{w:.0%}")
    print()
    blocks = [("节奏", rv["rhythm"].get("why", [])),
              ("叙事", rv["story"].get("why", [])),
              ("商业", rv["business"].get("why", [])),
              ("色彩", rv["look_why"])]
    n = 0
    for name, whys in blocks:
        for tag, val, fix in whys:
            n += 1
            print(f"  ✗ [{name}] {tag}：{val}")
            print(f"       → {fix}")
    rd = rv["rhythm"]
    if rd.get("ok"):
        print(f"\n  节奏数据：均长 {rd['mean_dur']}s  变异 {rd['cv']}  "
              f"张弛比 {rd['ratio']}  段落 {rd['section_mean']}")
    bd = rv["business"].get("detail", {})
    if bd:
        f3 = bd.get("first3s", {})
        rdb = bd.get("readability")
        rdb_s = f"{rdb['sim']:.0%}" if isinstance(rdb, dict) else "-"
        satv = bd.get("meanSat")
        print(f"  商业数据：前3秒 {f3.get('shots_in_3s','-')} 刀  "
              f"专业镜头 {bd.get('craft_shots','-')} 个  "
              f"前后同景别 {rdb_s}  "
              f"L={bd.get('meanL','-')} 饱和={round(satv*100/255) if isinstance(satv,(int,float)) else '-'}%")
    if not n:
        print("  无问题")


# ============================================================ CLI

def gather(target, glob_ext=(".mp4", ".mov", ".m4v", ".MP4", ".MOV")):
    if os.path.isdir(target):
        fs = []
        for f in sorted(os.listdir(target)):
            if f.lower().endswith(tuple(e.lower() for e in glob_ext)):
                fs.append(os.path.join(target, f))
        return fs
    return [target]


def main():
    ap = argparse.ArgumentParser(description="五维审美引擎")
    ap.add_argument("target", nargs="?", help="视频文件或素材目录")
    ap.add_argument("--pool", action="store_true", help="整池排序 + 编排方案")
    ap.add_argument("--plan", type=float, default=None, help="按 BPM 出节奏方案")
    ap.add_argument("--target-dur", type=float, default=30.0, help="目标成片时长")
    ap.add_argument("--json", default=None, help="结果写入 JSON")
    ap.add_argument("--dump", default=None, help="导出编排方案 JSON（给渲染用）")
    ap.add_argument("--top", type=int, default=0, help="只分析前 N 个")
    a = ap.parse_args()

    if not a.target:
        ap.print_help()
        return

    files = gather(a.target)
    if a.top:
        files = files[:a.top]
    if not files:
        print("没找到视频文件")
        return

    print(f"分析 {len(files)} 条素材…")
    recs = []
    for i, f in enumerate(files, 1):
        try:
            r = analyze(f)
            recs.append(r)
            print(f"  [{i}/{len(files)}] {os.path.basename(f):<30} "
                  f"分 {r['score']:>5.1f}  {r['kind']:<8} {r['dur']:.1f}s")
        except Exception as e:
            print(f"  [{i}/{len(files)}] 失败 {os.path.basename(f)}: {e}")

    recs = assign_kinds(rank_pool(recs))

    if not a.pool:
        if len(recs) == 1:
            render_single(recs[0], recs[0]["path"])
        else:
            print(f"\n{'素材':<30}{'分':>6}{'相对':>7}{'层':>4}  类型")
            print("-" * 62)
            for r in recs:
                print(f"{r['name'][:28]:<30}{r['score']:>6.1f}{r['rel']:>7.2f}"
                      f"{r['tier']:>4}  {r['kind']}")
        return

    # ---- 整池模式
    print(f"\n{'素材':<30}{'分':>6}{'相对':>7}{'层':>4}  类型     时长  建议")
    print("-" * 78)
    for r in recs:
        adv = "留（S/A）" if r["tier"] in ("S", "A") else \
              "留（补位）" if r["tier"] == "B" else "弃"
        print(f"{r['name'][:28]:<30}{r['score']:>6.1f}{r['rel']:>7.2f}"
              f"{r['tier']:>4}  {r['kind']:<8} {r['dur']:>5.1f}s  {adv}")

    shots = structure_plan(recs, bpm=a.plan, target=a.target_dur)
    render_plan(recs, shots, a.plan)

    tot = shots[-1]["timeline_in"] + shots[-1]["dur"] if shots else 0
    rv = review(recs, shots, tot)
    render_review(rv, recs)

    # 色彩一致性单列
    ld = rv["look_detail"]
    if ld:
        print(f"\n  色调一致：相邻 ΔE 均 {ld['adjacent_dE_mean']} 最大 {ld['adjacent_dE_max']}"
              f"  全片离散 {ld['spread_dE_mean']}  基准 L={ld['base']['L']} "
              f"a={ld['base']['a']} b={ld['base']['b']}")

    if a.dump:
        with open(a.dump, "w", encoding="utf-8") as fh:
            json.dump({"shots": shots, "review": rv,
                       "bpm": a.plan, "total": tot}, fh, ensure_ascii=False, indent=1)
        print(f"\n方案已导出 → {a.dump}")

    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump({"clips": [{k: v for k, v in r.items() if not k.startswith("_")}
                                 for r in recs],
                       "review": rv, "total": tot}, fh, ensure_ascii=False, indent=1)
        print(f"报告已导出 → {a.json}")


if __name__ == "__main__":
    main()
