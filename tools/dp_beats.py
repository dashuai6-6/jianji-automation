#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dp_beats.py —— 卡点剪辑切镜点求解器（可复用）

用途：给定一段配乐，自动求出「落在音乐重音上的镜头切点」，
      用于抖音/短视频的 beat-sync 剪辑。

核心算法
  1. 低频(35-200Hz)频谱通量 -> 瞬态强度包络
  2. 局部峰值 -> 候选切点
  3. 动态规划(DP)求最优切分序列：
       约束 镜头时长 ∈ [MIN_D, MAX_D]
       代价  = -重音强度 + 0.35 * |时长 - 目标时长|
  4. 输出边界数组，直接喂给剪辑脚本

用法
  python3 dp_beats.py music.mp3 --start 44.63 --total 20.5 --shots 14 --out bounds.json
"""
import argparse, json, os, subprocess, sys, wave
import numpy as np


def to_wav(src, dst="/tmp/_dp_beats.wav"):
    if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
        subprocess.run(["/usr/bin/ffmpeg", "-y", "-v", "error", "-i", src,
                        "-ac", "1", "-ar", "22050", dst], check=True)
    return dst


def envelope(wav):
    w = wave.open(wav, "rb")
    sr, n = w.getframerate(), w.getnframes()
    d = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768
    hop, win = 128, 512
    freqs = np.fft.rfftfreq(win, 1 / sr)
    band = (freqs >= 35) & (freqs <= 200)
    prev = np.zeros(len(freqs))
    on, ts = [], []
    for i in range(0, len(d) - win, hop):
        seg = d[i:i + win] * np.hanning(win)
        sp = np.abs(np.fft.rfft(seg))
        fl = np.maximum(0, sp - prev)
        on.append(float(fl[band].sum()))
        ts.append(i / sr)
        prev = sp
    return np.array(on), np.array(ts)


def kick_track(wav):
    w = wave.open(wav, "rb")
    sr, n = w.getframerate(), w.getnframes()
    d = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768
    hop, win = 128, 512
    freqs = np.fft.rfftfreq(win, 1 / sr)
    band = (freqs >= 40) & (freqs <= 100)
    prev = np.zeros(len(freqs))
    k, ts = [], []
    for i in range(0, len(d) - win, hop):
        seg = d[i:i + win] * np.hanning(win)
        sp = np.abs(np.fft.rfft(seg))
        k.append(float(np.maximum(0, sp - prev)[band].sum()))
        ts.append(i / sr)
        prev = sp
    return np.array(k), np.array(ts)


def solve(on, ts, start, total, shots, min_d, max_d, prefer):
    mask = (ts >= start) & (ts <= start + total + 0.6)
    o, t = on[mask], ts[mask] - start
    sm = np.convolve(o, np.ones(5) / 5, mode="same")

    cands = [0.0]
    for i in range(2, len(sm) - 2):
        if sm[i] == max(sm[i - 2:i + 3]):
            tt = float(t[i])
            if tt - cands[-1] >= 0.30:
                cands.append(tt)
    cands = [c for c in cands if c <= total]
    C = np.array(cands)
    E = np.array([sm[min(int(round(c / (128 / 22050))), len(sm) - 1)] for c in cands])

    n = len(C)
    K = shots - 1
    INF = 1e18
    dp = np.full((K + 1, n), INF)
    bk = np.full((K + 1, n), -1, dtype=int)
    dp[0, 0] = 0.0

    def cost(i, j):
        return -E[j] + 0.35 * abs((C[j] - C[i]) - prefer)

    for k in range(1, K + 1):
        for j in range(1, n):
            for i in range(max(0, j - 40), j):
                if dp[k - 1, i] == INF:
                    continue
                dur = C[j] - C[i]
                if dur < min_d or dur > max_d:
                    continue
                c = dp[k - 1, i] + cost(i, j)
                if c < dp[k, j]:
                    dp[k, j] = c
                    bk[k, j] = i

    best = None
    for j in range(n):
        if dp[K, j] == INF:
            continue
        dur = total - C[j]
        if dur < min_d - 0.05 or dur > max_d + 0.35:
            continue
        c = dp[K, j] + 0.35 * abs(dur - prefer)
        if best is None or c < best[1]:
            best = (j, c)
    if best is None:
        raise SystemExit("DP 无解，请放宽 min_d/max_d 或减少镜头数")

    j = best[0]
    path = [j]
    for k in range(K, 0, -1):
        j = bk[k, j]
        path.append(j)
    path = path[::-1]
    bounds = [round(float(C[i]), 3) for i in path] + [round(total, 3)]
    return bounds, float(best[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("music")
    ap.add_argument("--start", type=float, default=None)
    ap.add_argument("--total", type=float, default=None)
    ap.add_argument("--shots", type=int, default=14)
    ap.add_argument("--min-d", type=float, default=0.72)
    ap.add_argument("--max-d", type=float, default=1.85)
    ap.add_argument("--prefer", type=float, default=1.25)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    wav = to_wav(a.music)
    on, ts = envelope(wav)
    k, kts = kick_track(wav)

    total = a.total if a.total else float(ts[-1])
    start = a.start
    if start is None:
        lim = int(len(k) * 0.25)
        start = float(kts[int(np.argmax(k[:lim]))])
        print(f"自动定位音乐起点: {start:.2f}s")

    bounds, c = solve(on, ts, start, total, a.shots, a.min_d, a.max_d, a.prefer)
    print(f"DP 代价: {c:.2f}")
    print(f"切点 ({len(bounds)-1} 镜): {bounds}")
    durs = [round(bounds[i + 1] - bounds[i], 2) for i in range(len(bounds) - 1)]
    print(f"各镜时长: {durs}")
    print(f"总长: {round(sum(durs), 2)}s")

    if a.out:
        json.dump({"start": round(start, 3), "bounds": bounds}, open(a.out, "w"))
        print(f"已写出: {a.out}")


if __name__ == "__main__":
    main()
