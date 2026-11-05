#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Concat edit_apply 全命令探针：判定 真生效 / 空转 / 拒绝，输出 markdown 表。

用法：
    python3 probe_ops.py --src /path/素材1.mp4 --src2 /path/素材2.mp4
    python3 probe_ops.py --src a.mp4 --src2 b.mp4 --md > 表.md

判定口径（顺序不能反）：
    1. 每个命令在全新项目里跑，前后 project_get 全量对比
    2. clipId 必须从 timeline_read 现取，写死会静默空转（这是最容易犯的错）
    3. 报告"空转"之前，先排除 id 写错；关键命令再导出用 ffprobe 验时长
"""
import argparse
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from concat_client import Concat  # noqa: E402

STR_KEYS = {"name", "kind", "path", "newPath", "text", "family", "tool", "property",
            "key", "label", "file", "shape", "edge", "framing", "range", "id",
            "clipId", "mediaId", "trackId", "timelineId", "filename", "color", "flag"}
GUESS = {"name": "x", "kind": "video", "tool": "brush", "property": "scale",
         "key": "scale", "color": "#000000", "timelineId": "TL1",
         "framing": "fill", "edge": "end", "flag": "muted"}


def build(c, src, src2, extra=None):
    d = tempfile.mkdtemp(prefix="probe_", dir="/root")
    c.call("project_create", {"location": d, "name": "p", "width": 1080, "height": 1920})
    P = os.path.join(d, "p")
    m1 = c.call("media_import", {"path": P, "file": src})["createdId"]
    m2 = c.call("media_import", {"path": P, "file": src2})["createdId"]
    T = c.call("timeline_read", {"path": P})["timeline"]["tracks"][0]["id"]
    c1 = c.call("clip_add", {"path": P, "mediaId": m1, "trackId": T, "start": 0})["createdId"]
    c2 = c.call("clip_add", {"path": P, "mediaId": m2, "trackId": T, "start": 3.5})["createdId"]
    c3 = c.call("clip_add", {"path": P, "mediaId": m1, "trackId": T, "start": 7.0})["createdId"]
    env = {"d": d, "P": P, "T": T, "m1": m1, "m2": m2, "c1": c1, "c2": c2, "c3": c3}
    if extra:
        extra(c, env)
    return env


def cases(src, src2):
    """(命令名, 参数构造函数, 前置操作)"""
    NM = lambda s: {"path": s, "name": "x", "kind": "video", "hasAudio": True,
                    "duration": 3.5, "width": 1080, "height": 1920, "frameRate": 30.0}
    pre_key = lambda c, e: c.call("edit_apply", {"path": e["P"], "command": {
        "op": "setClipKey", "clipId": e["c1"], "property": "scale", "at": 0.0, "value": 1.2}})
    pre_tl = lambda c, e: c.call("edit_apply", {"path": e["P"], "command": {"op": "addTimeline"}})
    pre_font = lambda c, e: c.call("edit_apply", {"path": e["P"], "command": {
        "op": "addFont", "clipId": e["c1"], "family": "F", "path": src}})
    pre_det = lambda c, e: c.call("edit_apply", {"path": e["P"], "command": {
        "op": "detachAudio", "clipId": e["c1"]}})
    return [
        ("addMedia",              lambda e: {"item": NM(src2)}, None),
        ("removeMedia",           lambda e: {"mediaId": e["m2"]}, None),
        ("setMediaPlaceholder",   lambda e: {"mediaId": e["m2"], "placeholder": True}, None),
        ("fillSlot",              lambda e: {"mediaId": e["m1"], "item": NM(src2)}, None),
        ("updateMediaPath",       lambda e: {"mediaId": e["m2"], "newPath": src}, None),
        ("setMediaColorRange",    lambda e: {"mediaId": e["m1"], "range": "full"}, None),
        ("addClip",               lambda e: {"mediaId": e["m2"], "trackId": e["T"], "start": 30.0}, None),
        ("addClipAtFirstFree",    lambda e: {"mediaId": e["m2"], "start": 30.0}, None),
        ("addClipsInSequence",    lambda e: {"mediaIds": [e["m1"], e["m2"]], "start": 30.0}, None),
        ("moveClips",             lambda e: {"moves": [{"clipId": e["c2"], "trackId": e["T"], "start": 9.0}]}, None),
        ("trimClip",              lambda e: {"clipId": e["c1"], "edge": "end", "delta": -0.5}, None),
        ("splitClips",            lambda e: {"clipIds": [e["c1"]], "time": 1.0}, None),
        ("removeClips",           lambda e: {"clipIds": [e["c2"]]}, None),
        ("replaceClipMedia",      lambda e: {"clipId": e["c1"], "item": NM(src2)}, None),
        ("mergeClips",            lambda e: {"clipIds": [e["c1"], e["c3"]]}, None),
        ("consolidateClips",      lambda e: {"clipIds": [e["c1"], e["c2"]], "item": NM(src2)}, None),
        ("setClipSpeed",          lambda e: {"clipId": e["c1"], "speed": 0.5}, None),
        ("setClipSpeedCurve",     lambda e: {"clipId": e["c1"], "curve": [
            {"at": 0.0, "speed": 1.0}, {"at": 0.5, "speed": 0.35}, {"at": 1.0, "speed": 1.0}]}, None),
        ("freezeFrame",           lambda e: {"clipId": e["c1"], "time": 1.0}, None),
        ("setClipKey",            lambda e: {"clipId": e["c1"], "property": "scale", "at": 0.0, "value": 1.2}, None),
        ("clearClipKey",          lambda e: {"clipId": e["c1"], "property": "scale", "at": 0.0}, pre_key),
        ("clearClipKeys",         lambda e: {"clipId": e["c1"], "property": "scale"}, pre_key),
        ("setEffectKey",          lambda e: {"clipId": e["c1"], "entry": 0, "key": "amount", "at": 0.0, "value": 0.5}, None),
        ("setClipTransform",      lambda e: {"clipId": e["c1"], "scale": 1.3}, None),
        ("frameClip",             lambda e: {"clipId": e["c1"], "framing": "fill"}, None),
        ("setClipCutout",         lambda e: {"clipId": e["c1"], "cutout": {"mode": "custom", "points": [{"x": 0.5, "y": 0.5}]}}, None),
        ("setClipStabilize",      lambda e: {"clipId": e["c1"], "stabilize": {}}, None),
        ("addCutoutStroke",       lambda e: {"clipId": e["c1"], "stroke": {"tool": "brush", "size": 2, "points": [[0.5, 0.5]]}}, None),
        ("setClipEnhanced",       lambda e: {"clipId": e["c1"], "on": True}, None),
        ("detachAudio",           lambda e: {"clipId": e["c1"]}, None),
        ("reattachAudio",         lambda e: {"clipId": e["c1"]}, pre_det),
        ("addTextClip",           lambda e: {"text": "测试", "start": 0, "duration": 1}, None),
        ("addShapeClip",          lambda e: {"shape": "rect", "name": "矩形", "start": 0, "duration": 1}, None),
        ("addFont",               lambda e: {"clipId": e["c1"], "family": "F", "path": src}, None),
        ("removeFont",            lambda e: {"family": "F"}, pre_font),
        ("addTrack",              lambda e: {}, None),
        ("removeTrack",           lambda e: {"trackId": e["T"]}, None),
        ("setTrackFlag",          lambda e: {"trackId": e["T"], "flag": "muted", "value": True}, None),
        ("addTimeline",           lambda e: {}, None),
        ("removeTimeline",        lambda e: {"timelineId": "TL1"}, pre_tl),
        ("renameTimeline",        lambda e: {"timelineId": "TL1", "name": "probe"}, None),
        ("selectTimeline",        lambda e: {"timelineId": "TL1"}, pre_tl),
        ("moveTimeline",          lambda e: {"timelineId": "TL1", "index": 1}, pre_tl),
        ("setTimelineVideo",      lambda e: {"timelineId": "TL1", "video": {
            "width": 720, "height": 1280, "rateNum": 30, "rateDen": 1}}, None),
        ("setTimelineBackground", lambda e: {"timelineId": "TL1", "background": {
            "kind": "color", "color": "#101010"}}, None),
        ("batch",                 lambda e: {"commands": []}, None),
        ("updateClip",            lambda e: {"clipId": e["c1"], "patch": {"volume": 0.5}}, None),
    ]


def snap(c, P):
    return json.dumps(c.call("project_get", {"path": P})["project"],
                      ensure_ascii=False, sort_keys=True)


def autofill(c, P, cmd, limit=8):
    """缺字段就补，塞进最近一个 dict（结构体）里；返回 (ok, effective, cmd, filled)"""
    filled = []
    before = snap(c, P)
    for _ in range(limit):
        try:
            c.call("edit_apply", {"path": P, "command": cmd})
            return True, snap(c, P) != before, cmd, filled
        except Exception as ex:
            s = str(ex).split("edit_apply:")[-1].strip()
            if "missing field" not in s:
                return False, None, cmd, filled
            f = s.split("missing field `")[1].split("`")[0]
            filled.append(f)
            if f == "hasAudio":
                v = True
            elif f == "size":
                v = 2
            elif f == "index":
                v = 1
            elif f == "start":
                v = 30.0
            elif f == "item":
                v = {"path": "", "name": "x", "kind": "video"}
            elif f == "moves":
                v = []
            else:
                v = GUESS.get(f, "" if f in STR_KEYS else 0)
            placed = False
            for k, val in list(cmd.items()):
                if isinstance(val, dict) and len(val) <= 5:
                    val[f] = v
                    placed = True
                    break
            if not placed:
                cmd[f] = v
    return False, None, cmd, filled


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--src2")
    ap.add_argument("--md", action="store_true", help="输出 markdown 表")
    a = ap.parse_args()
    src2 = a.src2 or a.src
    c = Concat()
    rows = []
    try:
        for name, mk, pre in cases(a.src, src2):
            e = build(c, a.src, src2, pre)
            try:
                cmd = mk(e)
                cmd["op"] = name
                ok, eff, cmd, filled = autofill(c, e["P"], cmd)
                state = "生效" if eff else ("空转" if ok else "拒绝")
                rows.append({"op": name, "state": state, "cmd": cmd, "filled": filled})
            except Exception as ex:
                rows.append({"op": name, "state": "异常", "err": str(ex)[:120], "filled": []})
            finally:
                shutil.rmtree(e["d"], ignore_errors=True)
    finally:
        c.close()

    if a.md:
        print("| 命令 | 判定 | 参数 |")
        print("|---|---|---|")
        icon = {"生效": "✅", "空转": "⚠️ 空转", "拒绝": "❌ 拒绝", "异常": "💥 异常"}
        for r in rows:
            p = json.dumps({k: v for k, v in (r.get("cmd") or {}).items() if k != "op"},
                           ensure_ascii=False)
            print("| `%s` | %s | `%s` |" % (r["op"], icon[r["state"]], p.replace("|", "\\|")[:150]))
    else:
        for r in rows:
            print("%-24s %s" % (r["op"], r["state"]))
    ok = sum(1 for r in rows if r["state"] == "生效")
    print("\n生效 %d / 空转 %d / 拒绝 %d / 共 %d" % (
        ok, sum(1 for r in rows if r["state"] == "空转"),
        sum(1 for r in rows if r["state"] == "拒绝"), len(rows)))


if __name__ == "__main__":
    main()
