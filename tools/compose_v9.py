#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compose_v9.py —— V9 合成脚本（分步版）

  Step1: 底片 + 开场花字(zoompan 弹入) + CTA
  Step2: Step1 结果 + 10 条字幕条（逐条叠加）
  Step3: 混入音乐 + 响度标准化

关键坑：一次性把 13 层 overlay 串在一张 filtergraph 里会 OOM（进程被杀但
returncode 仍可能为 0，输出文件 0 字节）。所以必须分步，每步最多 2~3 层。

响度链路：音乐源已 loudnorm 到 -16 LUFS / TP -3.67，混音时只需
volume=-1.5dB + alimiter(limit=0.841) 即可拿到 -16.1 LUFS / TP -3.8 dBTP。
不要再叠 volume=1.0dB，那会把 TP 顶到 0 dBTP。

环境变量
  V9_SRC  工作目录（默认 /root/v9_src）
"""
import json, os, subprocess

FF = "/usr/bin/ffmpeg"
SRC = os.environ.get("V9_SRC", "/root/v9_src")
B = json.load(open(f"{SRC}/bounds.json"))["bounds"]
TXT = f"{SRC}/text"
dur = B[-1]

S1 = f"{SRC}/s1_flower.mp4"
S2 = f"{SRC}/V9_final.mp4"

SUB_FOR = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6, 8: 7, 9: 8, 10: 9}


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print("ERR:", r.stderr[-2500:])
    return r.returncode == 0


def step1():
    """底片 + 花字 + CTA"""
    inp = ["-i", f"{SRC}/v9_concat.mp4",
           "-loop", "1", "-framerate", "30", "-t", f"{dur:.2f}", "-i", f"{TXT}/open_flower.png",
           "-loop", "1", "-framerate", "30", "-t", f"{dur:.2f}", "-i", f"{TXT}/cta.png"]
    fc = [
        "[0:v]fps=30,format=rgba[base]",
        # 花字：先放大到 1.14x 再 zoompan 拉回，模拟弹入
        "[1:v]scale=1232:2190:flags=lanczos,format=rgba,"
        "zoompan=z='if(lt(on,16),1.14-0.14*on/16,1.0)':"
        "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30,"
        f"trim=duration={dur:.2f},setpts=PTS-STARTPTS,"
        "fade=t=in:st=0.05:d=0.18:alpha=1,fade=t=out:st=1.62:d=0.28:alpha=1[open]",
        "[base][open]overlay=0:0:format=auto[v1]",
        # CTA
        "[2:v]scale=1080:1920,format=rgba,"
        f"trim=duration={dur:.2f},setpts=PTS-STARTPTS,"
        f"fade=t=in:st={B[-2]:.3f}:d=0.35:alpha=1[cta]",
        "[v1][cta]overlay=0:0:format=auto[vout]",
    ]
    cmd = [FF, "-y", "-v", "error"] + inp + [
        "-filter_complex", ";".join(fc), "-map", "[vout]",
        "-t", f"{dur:.2f}", "-r", "30",
        "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-an", S1]
    return run(cmd)


def step2():
    """逐条叠加字幕（一条一命令，避免内存峰值）"""
    cur = S1
    for i in sorted(SUB_FOR):
        si = SUB_FOR[i]
        st, en = B[i], B[i + 1]
        out = f"{SRC}/_s2_{i}.mp4"
        fc = [
            "[0:v]format=rgba[base]",
            f"[1:v]scale=1080:1920,format=rgba,trim=duration={dur:.2f},setpts=PTS-STARTPTS,"
            f"fade=t=in:st={st+0.04:.3f}:d=0.10:alpha=1,"
            f"fade=t=out:st={en-0.12:.3f}:d=0.12:alpha=1[s]",
            "[base][s]overlay=0:0:format=auto[vout]",
        ]
        cmd = [FF, "-y", "-v", "error", "-i", cur,
               "-loop", "1", "-framerate", "30", "-t", f"{dur:.2f}", "-i", f"{TXT}/sub_{si:02d}.png",
               "-filter_complex", ";".join(fc), "-map", "[vout]",
               "-t", f"{dur:.2f}", "-r", "30",
               "-c:v", "libx264", "-crf", "17", "-preset", "veryfast", "-pix_fmt", "yuv420p",
               "-an", out]
        if not run(cmd):
            return False
        os.replace(out, cur)
    if cur != S2:
        os.replace(cur, S2)
    if os.path.exists(S1) and S1 != S2:
        os.remove(S1)
    return True


def step3():
    """混音乐 + 响度标准化"""
    cmd = [FF, "-y", "-v", "error",
           "-i", S2, "-i", f"{SRC}/music_v9.mp3",
           "-filter_complex",
           "[1:a]volume=-1.5dB,alimiter=level_in=1:level_out=1:limit=0.841:attack=3:release=50[a]",
           "-map", "0:v", "-map", "[a]",
           "-t", f"{dur:.2f}", "-c:v", "copy",
           "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
           f"{SRC}/V9_with_audio.mp4"]
    if not run(cmd):
        return False
    os.replace(f"{SRC}/V9_with_audio.mp4", S2)
    return True


if __name__ == "__main__":
    for f, name in [(step1, "Step1 花字+CTA"), (step2, "Step2 字幕"), (step3, "Step3 音乐")]:
        print(f"--- {name} ---")
        if not f():
            print("失败")
            raise SystemExit(1)
        print("完成")
    print("合成完成:", S2)
