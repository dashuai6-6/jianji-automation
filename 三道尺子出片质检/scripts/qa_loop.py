# -*- coding: utf-8 -*-
"""发布前三道闸门 + 自动返修闭环。

核心原则：三把尺子各管一段，绝不混算。
  A 素材尺（能不能用）：单镜价值 0-100 + 硬拒线。只做筛选和角色分配，不出"总分"。
  B 成品尺（好不好）  ：五维加权 0.24/0.24/0.16/0.18/0.18，S/A/B/C/D，合格线 A(78)。
  C 质检尺（有没有事故）：qc 技术指标，一票否决，不参与加权。

为什么不能混：同一条素材，qc 给 A 91.8、五维给 62.9，两个数都"对"，但回答的是不同问题。
混在一起算平均，等于把"能不能播"和"好不好看"揉成一个说不清的数。

闭环：
  素材池 --A--> 编排 --B--> [不合格] 定向返修 --> 回到 B
                              [合格] --> 渲染 --C--> [不合格] 技术返修 --> 重渲
"""
import os
import sys
import json
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import aesthetic as A

# ============================================================ 尺子 A：素材

# 硬拒线：这些是"物理上不能用"，不是"分低了"。低于线的一律不进池，不参与排序。
GATE = {
    "min_src_w": 720,        # 输出 1080 竖屏，源宽 720 以下放大必糊
    "max_jitter": 3.0,       # %W/s，超过 3 就是肉眼可见的手抖
    "min_detail": 25,        # 发丝/主体锐度（已按尺度归一）
    "max_whip": True,        # 甩镜直接弃
    # 压缩损伤：BRISQUE 0-100，越低越干净。只在素材层用（成片有花字，会被误判）。
    # 实测：用户原片 44.7 / 800kbps 48.1 / 300kbps 58.7 / 120kbps 62.4
    # 为什么超线只警告不硬拒：BRISQUE 按自然照片建模，画面里文字多（菜单、价目表、
    # 海报）也会被判高——实测文字海报 70~83，比 120kbps 压缩片还高。
    # 硬拒会误杀"菜单特写"这类正当素材，所以真正的压缩判定交给 rank_pool 的组内比较。
    "max_brisque": 75.0,
    "warn_brisque": 52.0,
}

# 分档：同一把尺子，不同用途
TIER_RULE = [
    (78, "S", "主用：钩子/成果/细节都行"),
    (66, "A", "补位：过程、过渡"),
    (50, "B", "仅快切：0.6s 以内一闪而过"),
    (0,  "C", "弃用"),
]


def material_audit(recs, verbose=False):
    """尺子 A：这条素材能不能用、能当什么用。

    注意这里**不出总分**。素材的"总分"没有意义——一条 9.6 秒的展示镜头
    拿五维一算就是 35.4 分废片，扣的全是"你只给了我一条素材"。
    """
    usable, rejected = [], []
    for r in recs:
        sh = r["shot"]
        m = sh.get("motion", {})
        reasons = []

        if sh.get("src_w", 0) < GATE["min_src_w"]:
            reasons.append(f"源宽 {sh['src_w']}px < {GATE['min_src_w']}")
        jt = m.get("jitter")
        if jt is not None and jt > GATE["max_jitter"]:
            reasons.append(f"抖动 {jt} > {GATE['max_jitter']}")
        if m.get("is_whip"):
            reasons.append("甩镜")
        # 锐度按介质取口径：产品看主体细节，人看发丝
        det = sh.get("hair_detail", 0)
        if sh.get("subj_kind") == "object":
            det = max(det, sh.get("texture_core", 0))
        if det and det < GATE["min_detail"]:
            reasons.append(f"细节锐度 {det:.0f} < {GATE['min_detail']}")
        bq = sh.get("brisque")
        warns = []
        if bq is not None and bq > GATE["warn_brisque"]:
            warns.append(f"画质 BRISQUE {bq:.0f}（>52 偏高，建议换高码率源）")

        if reasons:
            rejected.append({"name": r["name"], "score": r["score"], "why": reasons})
        else:
            tier = next(t for lo, t, _ in TIER_RULE if r["score"] >= lo)
            use = next(u for lo, _, u in TIER_RULE if r["score"] >= lo)
            usable.append({"name": r["name"], "score": r["score"], "kind": r["kind"],
                           "tier": tier, "use": use, "dur": round(r["dur"], 2),
                           "warn": warns})

    if verbose:
        print(f"\n[尺子A 素材] 可用 {len(usable)} / 拒 {len(rejected)}")
        for u in sorted(usable, key=lambda x: -x["score"]):
            w = ("  ⚠ " + u["warn"][0]) if u.get("warn") else ""
            print(f"  ✓ {u['name'][:22]:24} {u['score']:5} {u['tier']} {u['kind']:8} {u['use']}{w}")
        for x in rejected:
            print(f"  ✗ {x['name'][:22]:24} {x['score']:5}        {'；'.join(x['why'])}")
    return {"usable": usable, "rejected": rejected,
            "can_build": len(usable) >= 3,
            "coverage": sorted({u["kind"] for u in usable})}


# ============================================================ 尺子 B：成品

PASS_LINE = 78      # A 级：小修可发。低于此不进渲染。


def _relayout(plan):
    """改过时长后重算时间轴。忘了这一步，后面对齐全是错的。"""
    t = 0.0
    for s in plan:
        s["timeline_in"] = round(t, 3)
        t += s["dur"]
    return plan


def _set_dur(seg, d, src_dur):
    """给一段设置时长，并守住素材边界。
    注意要先扣掉入点偏移：src_in=1.1 的段，能用的只剩 src_dur-1.1，
    只按 src_dur 卡会算出 out 超过素材长度的非法区间（渲染时黑帧或冻结）。"""
    room = max(0.35, float(src_dur) - float(seg.get("src_in", 0.0)))
    d = max(0.35, min(float(d), room))
    seg["dur"] = round(d, 3)
    seg["in"] = round(seg.get("src_in", 0.0), 3)
    seg["out"] = round(seg["in"] + d, 3)
    return seg


def plan_gate(plan):
    """成品硬门槛：这几条不是"分低"，是"播出去会出问题"。"""
    bad = []
    if not plan:
        return ["空 plan"]
    tot = plan[-1]["timeline_in"] + plan[-1]["dur"]
    if plan[0]["role"] != "HOOK":
        bad.append(f"开头不是钩子（{plan[0]['role']}）")
    if tot < 12:
        bad.append(f"总时长 {tot:.1f}s < 12s，信息量不够")
    if tot > 45:
        bad.append(f"总时长 {tot:.1f}s > 45s，完播率崩")
    roles = {s["role"] for s in plan}
    for need in ("PROCESS", "AFTER"):
        if need not in roles:
            bad.append(f"缺 {need}")
    return bad


def plan_review(recs, plan):
    """尺子 B：五维。总时长由 plan 自己算，不传外层。"""
    tot = plan[-1]["timeline_in"] + plan[-1]["dur"] if plan else 0
    res = A.review(recs, plan, total=tot)
    res["gate"] = plan_gate(plan)
    res["pass"] = (res["total"] >= PASS_LINE) and not res["gate"]
    return res


# ============================================================ 返修：改什么

def _used_names(plan):
    return {s["name"] for s in plan}


def repair(recs, plan, res, log):
    """定向返修：不是重排一遍碰运气，是照着扣分项改。

    只做能靠"换镜头 / 调时长 / 换顺序"解决的事。
    需要重拍的（前后景别差太多、素材本身不够）如实say出来，进死循环没意义。
    """
    acts = []
    why_items = [w[0] for w in res["story"]["why"] + res["business"]["why"] + res["rhythm"].get("why", [])]
    used = _used_names(plan)

    # ---- 1) 开头不是钩子 / 首镜分低：拿池里最强的一条置顶
    if any("钩子" in w or "首镜" in w for w in why_items) or (plan and plan[0]["score"] < 80):
        cand = [r for r in recs if r["score"] >= max(70, plan[0]["score"]) and r["kind"] in ("AFTER", "DETAIL", "HOOK")]
        cand = [r for r in cand if r["dur"] >= 1.0]
        if cand:
            best = max(cand, key=lambda r: r["score"])
            src = next((s for s in plan if s["name"] == best["name"]), None)
            head = plan[0]
            if src is None:      # 池里有但没用上 → 造一段插到最前
                d = round(min(best["dur"], A.KIND_DUR["HOOK"][1]), 3)
                seg = {"path": best["path"], "name": best["name"], "role": "HOOK",
                       "kind": best["kind"], "dur": d, "speed": 1.0,
                       "tier": best.get("tier"), "score": best["score"],
                       "note": "返修：提升开场冲击力", "src_in": 0.0,
                       "src_dur": round(best["dur"], 3), "timeline_in": 0.0,
                       "in": 0.0, "out": d}
                plan.insert(0, seg)
                acts.append(f"前置 {best['name'][:14]}（{best['score']} 分）作钩子")
            elif head["role"] != "HOOK" or head["score"] < best["score"]:
                head["role"] = "HOOK"
                _set_dur(head, A.KIND_DUR["HOOK"][1], head["src_dur"])
                acts.append(f"开头镜头改判 HOOK 收短到 {head['dur']}s")

    # ---- 2) 缺角色：从池里按 kind 补
    for miss in res["story"].get("missing", []):
        want = {"HOOK": ("AFTER",), "BEFORE": ("BEFORE",), "PROCESS": ("PROCESS",),
                "DETAIL": ("DETAIL", "object"), "AFTER": ("AFTER",)}.get(miss, (miss,))
        cand = [r for r in recs if r["kind"] in want and r["name"] not in used and r["score"] >= 55]
        if not cand:
            # 池里没有了，但可能同一个镜头正在被别处用着。真实剪辑里这是常态：
            # 同一个成果镜头，开头切 1 秒当钩子，结尾放完整 3 秒——**同素材不同入点**。
            reuse = [s for s in plan if s["role"] == "HOOK" and s["kind"] in want
                     and s.get("src_dur", 0) - s.get("src_in", 0) >= 1.2]
            if reuse:
                src = reuse[0]
                hi = A.KIND_DUR.get(miss, (1.2, 3.0))[1]
                start = round(src.get("src_in", 0) + src["dur"], 3)
                room = src.get("src_dur", 0) - start
                if room >= 0.8:
                    d = round(min(hi, room), 3)
                    seg = dict(src)
                    seg.update({"role": miss, "dur": d, "src_in": start, "in": start,
                                "out": round(start + d, 3), "timeline_in": 0.0,
                                "note": f"返修：同素材不同入点补 {miss}（{start}s 起）"})
                    plan.append(seg)
                    acts.append(f"复用 {src['name'][:14]} 的 {start}s 之后 {d}s 补 {miss}")
                    continue
            acts.append(f"素材不足：池里没有可用的 {miss} 镜头")
            continue
        pick = max(cand, key=lambda r: r["score"])
        lo, hi = A.KIND_DUR.get(miss, (1.0, 2.0))
        d = round(min(pick["dur"], hi), 3)
        seg = {"path": pick["path"], "name": pick["name"], "role": miss, "kind": pick["kind"],
               "dur": d, "speed": 1.0, "tier": pick.get("tier"), "score": pick["score"],
               "note": f"返修：补 {miss}", "src_in": 0.0, "src_dur": round(pick["dur"], 3),
               "timeline_in": 0.0, "in": 0.0, "out": d}
        # 插到该在的位置
        pos = {"HOOK": 0, "BEFORE": 1, "PROCESS": None, "DETAIL": None, "AFTER": len(plan)}[miss]
        if pos is None:      # PROCESS/DETAIL 插在最后一个 PROCESS 后面
            idx = max([i for i, s in enumerate(plan) if s["role"] in ("PROCESS", "DETAIL")], default=1)
            pos = idx + 1
        plan.insert(min(pos, len(plan)), seg)
        used.add(pick["name"])
        acts.append(f"补 {miss}：{pick['name'][:14]}（{pick['score']} 分）")

    # ---- 3) 专业证据不足：补过程/细节
    craft = sum(1 for s in plan if s["role"] in ("PROCESS", "DETAIL"))
    if craft < 3:
        cand = [r for r in recs if r["kind"] in ("PROCESS", "DETAIL") and r["name"] not in used and r["score"] >= 55]
        for pick in sorted(cand, key=lambda r: -r["score"])[:3 - craft]:
            d = round(min(pick["dur"], 0.9 if pick["kind"] == "PROCESS" else 2.2), 3)
            seg = {"path": pick["path"], "name": pick["name"],
                   "role": "PROCESS" if pick["kind"] == "PROCESS" else "DETAIL",
                   "kind": pick["kind"], "dur": d, "speed": 1.0,
                   "tier": pick.get("tier"), "score": pick["score"],
                   "note": "返修：补专业证据", "src_in": 0.0, "src_dur": round(pick["dur"], 3),
                   "timeline_in": 0.0, "in": 0.0, "out": d}
            idx = max([i for i, s in enumerate(plan) if s["role"] in ("PROCESS", "DETAIL")], default=1)
            plan.insert(idx + 1, seg)
            used.add(pick["name"])
            acts.append(f"补专业证据：{pick['name'][:14]}")

    # ---- 4) 节奏平（时长平均主义）：拉开快慢
    rh = res["rhythm"]
    if rh.get("ok") is False or rh.get("score", 100) < 70:
        for s in plan:
            lo, hi = A.KIND_DUR.get(s["role"], (1.0, 2.0))
            if s["role"] == "PROCESS":
                _set_dur(s, 0.62, s["src_dur"])    # 与 rhythm_report 的 <0.8s 判定对齐
            elif s["role"] in ("AFTER", "DETAIL"):
                _set_dur(s, hi, s["src_dur"])
        acts.append("节奏返修：过程压到 0.62s、成果/细节放到区间上限，拉开张弛")

    # ---- 5) 前 3 秒太静：把第二刀提前（不是凭空加一刀，那会破坏叙事）
    n3 = sum(1 for s in plan if s["timeline_in"] < 3.0)
    if n3 < 2:
        for s in plan[:3]:
            if s["role"] in ("AFTER", "DETAIL") and s["dur"] > 1.6:
                _set_dur(s, 1.4, s["src_dur"])
                acts.append("前 3 秒太静：把首镜收短，让第二刀提前进来")
                break

    # ---- 6) 总时长不够：能拉长的先拉满，还差再用池里没用过的镜头补
    _relayout(plan)                       # 先重排，否则 tot 算的是未重排的旧值
    tot = plan[-1]["timeline_in"] + plan[-1]["dur"]
    if tot < 12.0:
        for s in plan:
            if s["role"] == "PROCESS":
                continue        # 过程镜头短本身就是节奏武器，拉长它等于把张弛抹平
            hi = A.KIND_DUR.get(s["role"], (1.0, 2.0))[1]
            if s["dur"] < hi - 0.05:
                _set_dur(s, min(hi, s.get("src_dur", hi)), s.get("src_dur", hi))
        _relayout(plan)
        grew = plan[-1]["timeline_in"] + plan[-1]["dur"]
        if grew > tot + 0.2:
            acts.append(f"时长不足：各段拉到区间上限，{tot:.1f}s → {grew:.1f}s")
        # 还差就加镜头（优先过程，最有信息量）
        tot = grew
        spare = [r for r in recs if r["name"] not in _used_names(plan) and r["score"] >= 55]
        if tot < 12.0 and spare:
            for r in sorted(spare, key=lambda x: -x["score"])[:3]:
                d = round(min(r["dur"], A.KIND_DUR.get(r["kind"], (1.0, 2.0))[1]), 3)
                seg = {"path": r["path"], "name": r["name"], "role": r["kind"], "kind": r["kind"],
                       "dur": d, "speed": 1.0, "tier": r.get("tier"), "score": r["score"],
                       "note": "返修：补足时长", "src_in": 0.0, "src_dur": round(r["dur"], 3),
                       "timeline_in": 0.0, "in": 0.0, "out": d}
                plan.insert(len(plan) - 1, seg)
                acts.append(f"补时长：加 {r['name'][:14]} {d}s")
                if plan[-1]["timeline_in"] + plan[-1]["dur"] >= 12.0:
                    break
        if plan[-1]["timeline_in"] + plan[-1]["dur"] < 12.0:
            short = 12.0 - (plan[-1]["timeline_in"] + plan[-1]["dur"])
            acts.append(f"素材不足：全池拉满仍差 {short:.1f}s，需再补一段（总素材只有 "
                        f"{sum(r['dur'] for r in recs):.1f}s）")

    # ---- 7) 不可修的，如实报
    for w in res["business"]["why"]:
        if "景别差太多" in w[0]:
            acts.append("需重拍：原貌与成果景别差太大，剪不出来")
    for w in res["story"]["why"]:
        if "素材不足" in str(w):
            acts.append("素材不足")

    _relayout(plan)
    log.append(list(dict.fromkeys(acts)))     # 去重：同一句别每轮报一次
    return plan


def screen(recs):
    """尺子 A 的过滤结果落回 recs 层。**必须在上游做**：
    否则返修时"从池里补镜头"会把刚被拒掉的废片又拉回来——
    同一套流程里闸门放行、返修放回，等于没闸门。"""
    audit = material_audit(recs)
    bad = {x["name"] for x in audit["rejected"]}
    return [r for r in recs if r["name"] not in bad], audit


def beat_align(plan, bpm):
    """成片时间轴与节拍网格的偏差。bpm=None 返回 None。

    为什么单独算：structure_plan 会按半拍网格给时长，但 repair 改时长时用的是
    节奏判断（0.62s 快切、1.45s 钩子），不是拍点判断——返修几轮后必然会偏离网格。
    卡点靠耳朵听，偏差 <50ms 可忽略，>120ms 就是"踩空"。
    """
    if not bpm or not plan:
        return None
    half = 60.0 / bpm / 2.0
    rows, t = [], 0.0
    for s in plan:
        t += float(s["dur"])
        n = t / half
        rows.append({"role": s.get("role"), "dur": round(s["dur"], 3),
                     "t": round(t, 3), "beat": round(n, 2),
                     "off_ms": round((n - round(n)) * half * 1000.0)})
    return {"bpm": bpm, "half_beat": round(half, 3), "total": round(t, 3),
            "max_off_ms": int(max(abs(r["off_ms"]) for r in rows)) if rows else 0,
            "rows": rows}


def loop(recs, target=20.0, max_iter=6, min_gain=1.0, verbose=True, bpm=None):
    """自动返修闭环：出 plan → 打分 → 不合格就定向修 → 再打分。

    收敛判据：连续两轮提升 < min_gain 就停。硬撑到 6 轮只会把片子改烂。
    bpm：整拍速度。给了就按半拍网格排时长（卡点），并在返回里报偏差。
    """
    recs, audit = screen(recs)          # 闸门只放行一次，后面全程只见合格素材
    if len(recs) < 3:
        return {"plan": [], "res": None, "history": [], "actions": [],
                "audit": audit, "beat": None,
                "blocked": "合格素材不足 3 条，无法编排"}
    plan = A.structure_plan(recs, bpm=bpm, target=target)
    hist, log = [], []
    prev, stale = -1.0, 0

    for i in range(max_iter):
        res = plan_review(recs, plan)
        hist.append({"round": i + 1, "total": res["total"], "grade": res["grade"],
                     "dims": res["dims"], "pass": res["pass"], "gate": res["gate"]})
        if verbose:
            print(f"  第{i+1}轮  {res['total']:5.1f} {res['grade']}  通过={res['pass']}  "
                  f"五维={res['dims']}  {'；'.join(res['gate'])}")

        if res["pass"]:
            break
        gain = res["total"] - prev
        prev = res["total"]
        stale = stale + 1 if gain < min_gain else 0
        if stale >= 2:
            if verbose:
                print(f"  收敛：连续两轮提升 < {min_gain} 分，停止返修")
            break
        if not A.KIND_DUR:
            break
        plan = repair(recs, plan, res, log)

    return {"plan": plan, "res": res, "history": hist, "actions": log,
            "audit": audit, "beat": beat_align(plan, bpm)}


# ============================================================ 成片实测

def verify_render(video, plan, res=None, verbose=True):
    """把渲染好的成片按 plan 的切点重新切开，逐段重测一遍，跟预测对账。

    为什么必须做：plan 层的分数是在**原始素材**上算的。渲染过程会重新编码、
    加色校、加转场、可能压缩到更低的码率——这些都会让画面变软、色偏。
    "预测 83.5 分"和"成片值 83.5 分"是两件事，不实测就是自欺。
    """
    import subprocess
    import tempfile
    d = tempfile.mkdtemp(prefix="verify_")
    rows = []
    for i, s in enumerate(plan):
        p = os.path.join(d, f"seg{i:02d}.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin",
                        "-ss", f"{s['timeline_in']:.3f}", "-t", f"{s['dur']:.3f}",
                        "-i", video, "-an", "-c:v", "libopenh264", "-b:v", "8M",
                        "-pix_fmt", "yuv420p", p, "-y"], capture_output=True)
        if not os.path.exists(p):
            continue
        # is_final=True：这是成片切出来的段落，画面里可能有花字/贴纸，
        # 不能让 BRISQUE 按"自然照片"去判它
        a = A.analyze(p, n=10, is_final=True)
        rows.append({"role": s["role"],
                     "pred": s.get("score_final", s["score"]), "real": a["score"],
                     "pred_kind": s.get("kind"), "real_kind": a["kind"],
                     "detail": a["shot"].get("hair_detail"),
                     "sharp": a["shot"].get("sharpness")})
    if not rows:
        return {"ok": False}

    pred_avg = float(np.mean([r["pred"] for r in rows]))
    real_avg = float(np.mean([r["real"] for r in rows]))
    drift = [round(r["real"] - r["pred"], 1) for r in rows]

    # 实测总分：镜头维换成实测均分，其余维度沿用 plan 的（结构没变，只是画面变了）
    real_total = None
    if res:
        dims = dict(res["dims"])
        dims["shot"] = round(real_avg, 1)
        real_total = round(sum(dims[k] * A.DIM_WEIGHT[k] for k in A.DIM_WEIGHT), 1)
        if verbose:
            print(f"  预测总分 {res['total']} → 实测总分 {real_total}"
                  f"（{real_total - res['total']:+.1f}）")
    if verbose:
        print(f"\n[成片实测] 逐段对账  预测均 {pred_avg:.1f} → 实测均 {real_avg:.1f}"
              f"（{real_avg - pred_avg:+.1f}）")
        for r in rows:
            flag = "" if abs(r["real"] - r["pred"]) <= 8 else "  ←偏差大"
            print(f"  {r['role']:8} 预测 {r['pred']:5.1f} 实测 {r['real']:5.1f}"
                  f" {r['real']-r['pred']:+6.1f}  锐度 {r['sharp']}{flag}")
    return {"ok": True, "rows": rows, "pred_avg": round(pred_avg, 1),
            "real_avg": round(real_avg, 1), "real_total": real_total,
            "drift_avg": round(real_avg - pred_avg, 1),
            "drift_max": max(drift, key=abs) if drift else 0}


# ============================================================ 尺子 C：质检

# 一票否决：这些问题发出去直接吃亏，跟片子好不好没关系
VETO = {
    "true_peak_max": -1.0,     # 峰值超 -1.0 dBTP = 削波，平台会压音
    "lufs_range": (-16.0, -11.0),
    "min_total": 70,           # qc 总分低于 70 不交付
}


def tech_gate(video):
    """尺子 C：渲染后的技术体检。与五维完全独立。"""
    import qc
    r = qc.check(video, quiet=True)
    veto = []
    au = r.get("audio", {})
    tp = au.get("true_peak")
    if tp is not None and tp > VETO["true_peak_max"]:
        veto.append(f"音频削波：峰值 {tp} dBTP > {VETO['true_peak_max']}")
    lufs = au.get("lufs")
    if lufs is None or lufs == float("-inf"):
        veto.append("没有音轨：抖音静音片基本没有完播，必须配乐（分工上这步由你在剪映加）")
    elif not (VETO["lufs_range"][0] <= lufs <= VETO["lufs_range"][1]):
        veto.append(f"响度 {lufs} LUFS 不在 {VETO['lufs_range']} 区间")
    if r["scores"]["total"] < VETO["min_total"]:
        veto.append(f"质检总分 {r['scores']['total']} < {VETO['min_total']}")

    # 技术返修建议（这些能自动做）
    fixes = []
    if tp is not None and tp > VETO["true_peak_max"]:
        fixes.append("loudnorm=I=-14:TP=-1.5:LRA=9 -ar 44100")
    if r["tech"].get("jitter") and r["tech"]["jitter"] > 3:
        fixes.append("deshake（会掉一点清晰度）")
    if r["tech"]["sharpness"] < 45:
        fixes.append("unsharp=5:5:0.6")
    return {"qc": r, "veto": veto, "fixes": fixes, "pass": not veto}


# ============================================================ 报告

def report(audit, res_loop, tech=None):
    """一页纸说清：素材什么情况、成品什么分、卡在哪。"""
    L = []
    L.append("=" * 62)
    L.append("素材体检（尺子A：能不能用）")
    L.append("=" * 62)
    L.append(f"可用 {len(audit['usable'])} 条 / 拒 {len(audit['rejected'])} 条，"
             f"覆盖角色：{audit['coverage']}")
    for u in sorted(audit["usable"], key=lambda x: -x["score"]):
        L.append(f"  {u['tier']} {u['score']:5.1f}  {u['name'][:24]:26} {u['kind']:8} {u['use']}")
    for x in audit["rejected"]:
        L.append(f"  ✗ {x['score']:5.1f}  {x['name'][:24]:26} {'；'.join(x['why'])}")

    r = res_loop.get("res")
    L.append("")
    L.append("=" * 62)
    L.append("成品评审（尺子B：好不好）")
    L.append("=" * 62)
    if not r:
        L.append(f"未进入编排：{res_loop.get('blocked', '没有可用的评审结果')}")
        L.append("素材层不过线时不出成品分——这是设计，不是故障。"
                 "补素材或重拍，别在素材不够的情况下硬凑一条片子。")
        if tech:
            L.append("")
            L.append(f"技术质检（尺子C）：{tech['qc']['grade']} {tech['qc']['scores']['total']}  "
                     f"通过={tech['pass']}")
        return "\n".join(L)
    L.append(f"总分 {r['total']}  {r['grade']}  {r['verdict']}   通过={r['pass']}")
    for k, v in r["dims"].items():
        L.append(f"  {A.DIM_NAME[k]:6} {v:5.1f}  ×{A.DIM_WEIGHT[k]:.2f}")
    if r["gate"]:
        L.append(f"  硬门槛未过：{'；'.join(r['gate'])}")
    for d in ("rhythm", "story", "business"):
        for w in r[d].get("why", []):
            L.append(f"  ! [{w[0]}] {w[1]} → {w[2]}")

    L.append("")
    L.append(f"返修过程：{len(res_loop['history'])} 轮")
    for h in res_loop["history"]:
        L.append(f"  第{h['round']}轮 {h['total']:5.1f} {h['grade']} 通过={h['pass']}")
    for i, acts in enumerate(res_loop["actions"], 1):
        for a in acts:
            L.append(f"  轮{i}: {a}")

    bt = res_loop.get("beat")
    if bt:
        L.append("")
        L.append(f"节拍对齐（{bt['bpm']} BPM，半拍 {bt['half_beat']}s，总长 {bt['total']}s）")
        L.append(f"  最大偏差 {bt['max_off_ms']} ms"
                 + ("  ✓ 听不出来" if bt["max_off_ms"] <= 50 else
                    ("  ! 返修后有偏离，剪映里微调切点" if bt["max_off_ms"] <= 120
                     else "  ✗ 明显踩空，按 0.62s/半拍 重排")))
        for row in bt["rows"]:
            L.append(f"    {row['role'] or '-':8} {row['t']:6.2f}s  第{row['beat']:.2f}拍  偏差{row['off_ms']:+d}ms")

    if tech:
        L.append("")
        L.append("=" * 62)
        L.append("技术质检（尺子C：有没有事故）")
        L.append("=" * 62)
        q = tech["qc"]
        L.append(f"{q['grade']} {q['scores']['total']}  通过={tech['pass']}")
        for v in tech["veto"]:
            L.append(f"  ✗ {v}")
        for f in tech["fixes"]:
            L.append(f"  → 修：{f}")
    return "\n".join(L)
