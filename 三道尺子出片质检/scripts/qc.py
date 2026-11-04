#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
成片质检 —— 把"有没有审美"拆成能算出来的指标

三件事：
  1) L1 技术质检：黑帧/冻结/曝光/清晰度/抖动/码率  → 硬门槛，不过就返修
  2) L2 构图层检：人脸位置/大小/头顶留白/三分法/肤色/安全区 → 评分
  3) 给每条问题附一个「怎么改」的动作，供自动返修调用

用法：
  python3.11 qc.py 成片.mp4
  python3.11 qc.py --all 成片/*.mp4
  python3.11 qc.py --json 成片.mp4          # 输出机器可读
"""
import os, sys, json, subprocess, math
import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
FACE_XML = (cv2.data.haarcascades + "haarcascade_frontalface_default.xml") if cv2 else None
_cascade = None


def _casc():
    global _cascade
    if _cascade is None and cv2:
        _cascade = cv2.CascadeClassifier(FACE_XML)
    return _cascade


# ---------------------------------------------------------------- 基础探测
def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration,bit_rate,size:stream=codec_type,width,height,"
                        "r_frame_rate,codec_name,bit_rate,sample_rate,channels",
                        "-of", "json", path], capture_output=True, text=True)
    j = json.loads(r.stdout or "{}")
    fmt = j.get("format", {})
    st = j.get("streams", [])
    v = next((s for s in st if s.get("codec_type") == "video"), {})
    a = next((s for s in st if s.get("codec_type") == "audio"), {})

    def fr(s):
        try:
            num, den = s.split("/")
            return round(int(num) / int(den), 3) if float(den) else 0
        except Exception:
            return 0

    return {
        "path": path, "duration": float(fmt.get("duration") or 0),
        "size_mb": round(int(fmt.get("size") or 0) / 1048576, 2),
        "bitrate_kbps": int(int(fmt.get("bit_rate") or 0) / 1000),
        "w": v.get("width"), "h": v.get("height"),
        "fps": fr(v.get("r_frame_rate") or "0/1"),
        "vcodec": v.get("codec_name"), "vbr_kbps": int(int(v.get("bit_rate") or 0) / 1000),
        "has_audio": bool(a), "acodec": a.get("codec_name"),
        "sr": a.get("sample_rate"), "ch": a.get("channels"),
    }


# ---------------------------------------------------------------- 抽帧
def grab_frames(path, w=720, h=None, n=24):
    """按时长均匀抽 n 帧，返回 (frames, 缩略尺寸)；h 为 None 时按原比例。
    **不放大**：把 406 宽的素材插值到 720，锐度会从 52 掉到 11（插值即低通），
    判出来是"糊"，但原片发丝根根分明。质量必须在原尺寸上测。"""
    info = probe(path)
    srcw = info["w"] or 1080
    if w > srcw:
        w = srcw if srcw % 2 == 0 else srcw - 1
    dur = info["duration"] or 1
    if h is None:
        h = int(w * (info["h"] or 1920) / (info["w"] or 1080) / 2) * 2
    fps_pick = max(0.5, n / dur)
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-i", path, "-vf",
           f"fps={fps_pick:.4f},scale={w}:{h}", "-f", "rawvideo",
           "-pix_fmt", "bgr24", "-"]
    r = subprocess.run(cmd, capture_output=True)
    buf = r.stdout
    fsz = w * h * 3
    cnt = len(buf) // fsz
    frames = [np.frombuffer(buf[i * fsz:(i + 1) * fsz], np.uint8).reshape(h, w, 3)
              for i in range(cnt)]
    return frames, (w, h)


def _jitter(path, fps_pick=15, win=2.4):
    """抖动检测：连续帧 + **四角背景块**相位相关。

    坑（已踩过）：整帧做相位相关，测到的是"画面里什么在动"，不是"相机在动"。
    实测一条相机完全静止、只有模特甩头发的素材，整帧相关读出 54.76 %W/s，
    直接判"手持抖动明显"——好素材被冤枉。背景（墙/货架/门）只会因相机而动，
    所以只取四角和上下边中一共 6 个背景块，取中位数。
    返回：每秒位移占画面宽度的百分比（%W/s），3 以下算稳，6 以上明显抖。
    """
    info = probe(path)
    dur = info["duration"] or 2
    ss = max(0.0, dur * 0.45 - win / 2)
    w = 320
    h = int(w * (info["h"] or 1920) / (info["w"] or 1080) / 2) * 2
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{ss:.2f}", "-t", str(win),
           "-i", path, "-vf", f"fps={fps_pick},scale={w}:{h},gblur=sigma=1.0",
           "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    r = subprocess.run(cmd, capture_output=True)
    fsz = w * h
    cnt = len(r.stdout) // fsz
    if cnt < 3:
        return None
    frames = [np.frombuffer(r.stdout[i * fsz:(i + 1) * fsz], np.uint8).reshape(h, w)
              for i in range(cnt)]
    cw, ch = max(24, w // 4), max(24, h // 4)
    tiles = [(0, 0), (w - cw, 0), (0, h - ch), (w - cw, h - ch),
             (w // 2 - cw // 2, 0), (w // 2 - cw // 2, h - ch)]
    mags = []
    for i in range(len(frames) - 1):
        vals = []
        for (tx, ty) in tiles:
            a = np.float32(frames[i][ty:ty + ch, tx:tx + cw])
            b = np.float32(frames[i + 1][ty:ty + ch, tx:tx + cw])
            a -= a.mean(); b -= b.mean()
            try:
                (dx, dy), resp = cv2.phaseCorrelate(a, b)
            except Exception:
                continue
            if resp >= 0.15:          # 相关性太低 = 该块没背景（纯天空/纯色），不可信
                vals.append(float(math.hypot(dx, dy)))
        if len(vals) >= 3:
            vs = np.array(vals)
            if float(np.std(vs)) > 2.5:      # 各块各说各话 = 没测到真位移，丢帧
                continue
            mags.append(float(np.median(vs)))
    # 一张有效帧都没有 → 画面里没有可跟踪的背景。返回 None，不能返回 0：
    # 0 的意思是"非常稳"，那是假话，会让纯色棚拍的抖动素材混过质检。
    if not mags:
        return None
    return round(float(np.median(mags)) * fps_pick / w * 100, 2)


# ---------------------------------------------------------------- L1 技术指标
def tech_checks(path, frames, size):
    h, w = frames[0].shape[:2] if frames else (0, 0)
    out = {}

    # 曝光：Y 通道均值与分布
    ys = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    means = [float(y.mean()) for y in ys]
    out["luma_mean"] = round(float(np.mean(means)), 1)
    out["luma_min"] = round(float(np.min(means)), 1)
    out["luma_max"] = round(float(np.max(means)), 1)
    # 高光溢出 / 暗部死黑（占画面比例）
    clip_hi = [float((y > 250).mean()) for y in ys]
    clip_lo = [float((y < 8).mean()) for y in ys]
    out["clip_high_pct"] = round(float(np.mean(clip_hi)) * 100, 1)
    out["clip_low_pct"] = round(float(np.mean(clip_lo)) * 100, 1)

    # 清晰度：拉普拉斯方差，按 (实测宽/640) 归一到统一尺子（不同分辨率才可比）
    from aesthetic import lap_norm
    laps = [lap_norm(y) for y in ys]
    out["sharpness"] = round(float(np.median(laps)), 1)
    out["sharpness_p10"] = round(float(np.percentile(laps, 10)), 1)

    # 抖动：必须用【连续帧】测，采样帧之间隔了 1 秒以上会把运镜当成抖动
    out["jitter"] = _jitter(path)

    # 黑帧 / 冻结（交给 ffmpeg 精确检测）
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-i", path, "-vf",
                        "blackdetect=d=0.15:pix_th=0.08", "-an", "-f", "null", "-"],
                       capture_output=True, text=True)
    blacks = [ln for ln in r.stderr.splitlines() if "black_start" in ln]
    out["black_segments"] = len(blacks)
    out["black_desc"] = [ln.split("]")[-1].strip()[:60] for ln in blacks[:3]]

    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-i", path, "-vf",
                        "freezedetect=n=0.002:d=0.4", "-an", "-f", "null", "-"],
                       capture_output=True, text=True)
    out["freeze_segments"] = len([l for l in r.stderr.splitlines() if "freeze_start" in l])
    return out


# ---------------------------------------------------------------- L2 构图
def comp_checks(frames):
    casc = _casc()
    if casc is None or not frames:
        return {"available": False}

    h, w = frames[0].shape[:2]
    faces_per_frame = []
    for f in frames:
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        rects = casc.detectMultiScale(g, 1.08, 4, minSize=(int(h * 0.05), int(h * 0.05)))
        if len(rects) == 0:
            faces_per_frame.append(None)
            continue
        # 取最大的脸
        r = max(rects, key=lambda x: x[2] * x[3])
        x, y, fw, fh = r
        faces_per_frame.append({
            "cx": (x + fw / 2) / w, "cy": (y + fh / 2) / h,
            "area": (fw * fh) / (w * h), "top": y / h, "bottom": (y + fh) / h,
        })

    faces = [x for x in faces_per_frame if x]
    out = {"available": True, "frames_total": len(frames), "frames_with_face": len(faces),
           "subj_mode": "face"}

    # 没脸不等于没主体：背影/后脑/产品特写靠深色纹理块定位，否则永远 55 分。
    # 注意 haarcascade 在卷发/侧脸上会零星误检，8% 覆盖率也算"没脸"，一并走纹理兜底。
    if len(faces) < len(frames) * 0.35:
        from aesthetic import texture_subject
        tex = []
        for f in frames:
            bx, ar, cf = texture_subject(f)
            if bx:
                x0, y0, x1, y1 = bx
                tex.append({"cx": (x0 + x1) / 2 / w, "cy": (y0 + y1) / 2 / h,
                            "area": ar, "top": y0 / h, "bottom": y1 / h})
        if len(tex) >= max(2, len(frames) * 0.5):
            faces = tex
            out["subj_mode"] = "texture"
            out["face_cover_pct_raw"] = round(len([x for x in faces_per_frame if x]) / len(frames) * 100, 0)

    if not faces:
        out.update({"face_cover_pct": 0, "face_area_pct": 0, "headroom_pct": None,
                    "center_off": None, "thirds_err": None, "best_rule": "n/a",
                    "skin_pct": 0.0})
        return out

    out["face_cover_pct"] = round(len(faces) / len(frames) * 100, 0)
    out["face_area_pct"] = round(float(np.mean([f["area"] for f in faces])) * 100, 1)
    out["headroom_pct"] = round(float(np.median([f["top"] for f in faces])) * 100, 1)

    # 构图：人脸中心离「画面中心」和「三分线交点」哪个更近
    thirds = [(1 / 3, 1 / 3), (2 / 3, 1 / 3), (1 / 3, 2 / 3), (2 / 3, 2 / 3)]
    cen, thi = [], []
    for f in faces:
        cen.append(math.hypot(f["cx"] - 0.5, f["cy"] - 0.5))
        thi.append(min(math.hypot(f["cx"] - tx, f["cy"] - ty) for tx, ty in thirds))
    out["center_off"] = round(float(np.median(cen)), 3)
    out["thirds_err"] = round(float(np.median(thi)), 3)
    out["best_rule"] = "center" if np.median(cen) <= np.median(thi) else "thirds"

    # 肤色占比（判断调色是否把皮肤调歪）
    skin = []
    for f in frames:
        ycc = cv2.cvtColor(f, cv2.COLOR_BGR2YCrCb)
        m = cv2.inRange(ycc, (0, 133, 77), (255, 173, 127))
        skin.append(float(m.mean()) / 255)
    out["skin_pct"] = round(float(np.mean(skin)) * 100, 1)
    return out


# ---------------------------------------------------------------- 音频
def audio_checks(path):
    info = probe(path)
    if not info["has_audio"]:
        return {"available": False}
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-i", path,
                        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True)
    out = {"available": True, "lufs": None, "true_peak": None, "lra": None}
    try:
        s = r.stderr[r.stderr.rindex("{"):r.stderr.rindex("}") + 1]
        j = json.loads(s)
        out["lufs"] = round(float(j["input_i"]), 1)
        out["true_peak"] = round(float(j["input_tp"]), 1)
        out["lra"] = round(float(j["input_lra"]), 1)
    except Exception:
        pass
    r2 = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-i", path, "-af",
                         "silencedetect=n=-42dB:d=0.6", "-f", "null", "-"],
                        capture_output=True, text=True)
    out["silence_segments"] = len([l for l in r2.stderr.splitlines() if "silence_start" in l])
    return out


# ---------------------------------------------------------------- 打分
def score(info, tech, comp, audio):
    """0-100 分。扣分逻辑写死在下面，改阈值只改这一处。"""
    issues = []

    def add(level, item, val, fix):
        issues.append({"level": level, "item": item, "value": val, "fix": fix})

    # ---- 技术分 ----
    t = 100
    if tech["black_segments"] > 0:
        t -= 30
        add("red", "黑帧", f"{tech['black_segments']} 段", "剔除黑段素材窗口或缩短入点")
    if tech["freeze_segments"] > 2:
        t -= 12
        add("yellow", "冻结帧", f"{tech['freeze_segments']} 段", "提高选片帧差阈值 MIN_SCORE")
    lm = tech["luma_mean"]
    if lm < 45:
        t -= 22
        add("red", "整体欠曝", f"亮度均值 {lm}", "colorlevels rimin/gimin/bimin 上调，或选更亮素材")
    elif lm < 65:
        t -= 10
        add("yellow", "偏暗", f"亮度均值 {lm}", "提 gamma：eq=gamma=1.12")
    elif lm > 200:
        t -= 18
        add("red", "整体过曝", f"亮度均值 {lm}", "压低 rimax/gimax/bimax，或换素材")
    if tech["clip_high_pct"] > 6:
        t -= 12
        add("yellow", "高光溢出", f"{tech['clip_high_pct']}%", "降曝光 + 高光压缩")
    if tech["clip_low_pct"] > 20:
        t -= 10
        add("yellow", "暗部死黑", f"{tech['clip_low_pct']}%", "提阴影 / 补光")
    sh = tech["sharpness"]
    if sh < 25:
        t -= 25
        add("red", "画面发糊", f"锐度 {sh}", "换清晰素材，或 unsharp=5:5:0.8")
    elif sh < 40:
        t -= 12
        add("yellow", "偏软", f"锐度 {sh}", "锐化 unsharp=5:5:0.6，注意别出白边")
    elif sh < 62:
        t -= 6
        add("yellow", "略软", f"锐度 {sh}", "轻度锐化 unsharp=5:5:0.4")
    jt = tech.get("jitter")
    if jt is not None and jt > 3.0:
        t -= 15
        add("red", "手持抖动明显", f"{jt}", "开 deshake，或改用轻量稳定（会掉清晰度）")
    elif jt is not None and jt > 1.8:
        t -= 7
        add("yellow", "轻微晃动", f"{jt}", "可接受；要求稳就开 deshake")
    elif jt is None:
        add("yellow", "抖动未测", "无可跟踪背景", "纯色/虚化背景测不出，这一项不扣分但不代表稳")
    t = max(0, min(100, t))

    # ---- 构图分 ----
    c = 100
    if not comp.get("available"):
        c = 60
        add("yellow", "人脸检测不可用", "-", "检查 opencv 与 haarcascade")
    elif comp.get("subj_mode") == "texture" and comp.get("face_area_pct", 0) > 5:
        c -= 6                      # 背影/产品展示：主体够大就不算构图失分，只轻扣"无人脸记忆点"
        add("yellow", "无脸镜头", f"主体占 {comp.get('face_area_pct')}%",
            "纯背影/产品可用，但全片要有露脸镜头建立信任")
    elif comp.get("face_cover_pct", 0) < 15:
        c = 55
        add("yellow", "几乎没露脸", f"{comp.get('face_cover_pct')}% 帧有脸", "探店片建议 30%+ 帧有人脸/手部主体")
    else:
        fa = comp["face_area_pct"]
        if fa < 2:
            c -= 30
            add("red", "人脸极小（远景）", f"占画面 {fa}%", "推近景或裁切放大，目标 10-25%")
        elif fa < 6:
            c -= 18
            add("yellow", "人脸太小", f"占画面 {fa}%", "推近景或裁切放大，目标 10-25%")
        elif fa > 45:
            c -= 15
            add("yellow", "人脸过大挤压画面", f"占画面 {fa}%", "拉远或裁切留环境")
        hr = comp["headroom_pct"]
        if hr is not None:
            if hr < 4:
                c -= 12
                add("yellow", "头顶贴边", f"留白 {hr}%", "下移构图，头顶留 6-14%")
            elif hr > 30:
                c -= 8
                add("yellow", "头顶留白过多", f"留白 {hr}%", "上移构图或裁切")
        if comp["best_rule"] == "center" and comp["center_off"] > 0.22:
            c -= 8
            add("yellow", "主体偏离", f"偏移 {comp['center_off']}", "裁切居中，或按三分线重排")
        sp = comp["skin_pct"]
        if sp < 2:
            c -= 6
            add("yellow", "肤色占比过低", f"{sp}%", "调色过冷，检查白平衡")
        elif sp > 40:
            c -= 10
            add("yellow", "肤色占比过高/偏红", f"{sp}%", "降饱和或校正肤色")
    c = max(0, min(100, c))

    # ---- 音频分 ----
    a = 100
    if not audio.get("available"):
        a = 0
        add("red", "无音轨", "-", "补 BGM 或静音轨")
    else:
        lu = audio["lufs"]
        if lu is None:
            a = 50
            add("yellow", "响度测不出", "-", "检查音频流")
        elif lu < -20:
            a -= 30
            add("red", "音量过小", f"{lu} LUFS", f"标准化到 -14 LUFS（当前差 {abs(lu + 14):.0f} dB）")
        elif lu < -16:
            a -= 15
            add("yellow", "音量偏小", f"{lu} LUFS", "loudnorm 提到 -14")
        elif lu > -11:
            a -= 20
            add("red", "音量过大有爆音风险", f"{lu} LUFS", "压到 -14 LUFS，TP ≤ -1.5")
        tp = audio["true_peak"]
        if tp is not None and tp > -1.0:
            a -= 15
            add("red", "真峰值超限", f"{tp} dBTP", "限幅到 -1.5 dBTP，抖音会二次压缩")
        if audio["silence_segments"] > 2:
            a -= 10
            add("yellow", "静音段多", f"{audio['silence_segments']} 段", "补 BGM 铺底")
    a = max(0, min(100, a))

    total = round(t * 0.40 + c * 0.35 + a * 0.25, 1)
    grade = "A" if total >= 88 else "B" if total >= 78 else "C" if total >= 66 else "D"
    return {"tech": round(t, 1), "comp": round(c, 1), "audio": round(a, 1),
            "total": total, "grade": grade, "issues": issues}


# ---------------------------------------------------------------- 主入口
def check(path, quiet=False):
    info = probe(path)
    frames, size = grab_frames(path)
    if not frames:
        raise RuntimeError("抽帧失败")
    tech = tech_checks(path, frames, size)
    comp = comp_checks(frames)
    audio = audio_checks(path)
    sc = score(info, tech, comp, audio)
    rep = {"file": os.path.basename(path), "meta": info,
           "tech": tech, "comp": comp, "audio": audio,
           "scores": {"tech": sc["tech"], "comp": sc["comp"],
                      "audio": sc["audio"], "total": sc["total"]},
           "grade": sc["grade"], "issues": sc["issues"]}
    if not quiet:
        render(rep)
    return rep


BAR = {"A": "🟢", "B": "🟡", "C": "🟠", "D": "🔴"}
LEVEL = {"red": "✗", "yellow": "!"}


def render(r):
    m, t, c, a = r["meta"], r["tech"], r["comp"], r["audio"]
    print(f"\n{'='*66}")
    print(f"{r['file']}   [{r['grade']}] 总分 {r['scores']['total']}")
    print(f"{'='*66}")
    print(f"  规格  {m['w']}x{m['h']} @{m['fps']}fps  {m['duration']:.1f}s  "
          f"{m['size_mb']}MB  {m['bitrate_kbps']}kbps  {m['vcodec']}")
    sc = r["scores"]
    print(f"  技术 {sc['tech']:>5}   构图 {sc['comp']:>5}   音频 {sc['audio']:>5}")
    print(f"  ├ 亮度 {t['luma_mean']} (min {t['luma_min']} / max {t['luma_max']})  "
          f"高光溢出 {t['clip_high_pct']}%  暗部 {t['clip_low_pct']}%")
    _jt = "未测" if t["jitter"] is None else t["jitter"]
    print(f"  ├ 锐度 {t['sharpness']}  p10 {t['sharpness_p10']}  抖动 {_jt}  "
          f"黑帧 {t['black_segments']}  冻结 {t['freeze_segments']}")
    if c.get("available"):
        lab = "主体覆盖" if c.get("subj_mode") == "texture" else "露脸"
        print(f"  ├ {lab} {c['face_cover_pct']:.0f}% 面积 {c['face_area_pct']}%  "
              f"头顶留白 {c['headroom_pct']}%  构图 {c['best_rule']}")
    if a.get("available"):
        print(f"  └ 响度 {a['lufs']} LUFS  峰值 {a['true_peak']} dBTP  "
              f"LRA {a['lra']}  静音 {a['silence_segments']} 段")
    if r["issues"]:
        print(f"  问题 {len(r['issues'])} 条：")
        for i in r["issues"]:
            print(f"    {LEVEL.get(i['level'],'?')} [{i['item']}] {i['value']}  → {i['fix']}")
    else:
        print("  无问题")


def compare(paths):
    rows = [check(p, quiet=True) for p in paths]
    hdr = f"{'文件':<34}{'总分':>6}{'技术':>6}{'构图':>6}{'音频':>6}  等级  问题"
    print(hdr); print("-" * len(hdr))
    for r in sorted(rows, key=lambda x: -x["scores"]["total"]):
        n = len(r["name"] if "name" in r else r["file"])
        sc = r["scores"]
        print(f"{r['file'][:32]:<34}{sc['total']:>6}{sc['tech']:>6}{sc['comp']:>6}"
              f"{sc['audio']:>6}   {r['grade']}    {len(r['issues'])}")
    return rows


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
    elif args[0] == "--all":
        compare(args[1:])
    elif args[0] == "--json":
        print(json.dumps(check(args[1], quiet=True), ensure_ascii=False, indent=1))
    elif args[0] == "--compare":
        compare(args[1:])
    else:
        for p in args:
            check(p)
