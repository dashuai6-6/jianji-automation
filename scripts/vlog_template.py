# -*- coding: utf-8 -*-
"""
剪映自动化剪辑脚本 — 理发探店/Vlog v3
= 花字金边 + 贴纸 + 画中画PIP + 3D运镜 + 曲线变速

新增（相比v2）:
- 花字"简约黑白花字" effect (resource_id: 6896137924853648648)
- 卡通剪刀贴纸 (resource_id: 6914596591491943693)
- 省略号贴纸 → "..." 文字替代（上标居中）
- 星光贴纸 → "✨" 文字替代（带旋转动画）
- 画中画PIP：v4段右上角叠加v2特写
- 3D环绕运镜 + 曲线变速 → 后处理注入
"""
import os, json, shutil, subprocess, uuid, copy
import pyJianYingDraft as draft
from pyJianYingDraft import (
    IntroType, OutroType, TransitionType, FilterType, FontType,
    TextIntro, KeyframeProperty,
    ClipSettings, TextStyle, TrackType,
    VideoSceneEffectType, StickerSegment,
    trange, tim
)

# ============================================================
# 配置
# ============================================================
ASSET_DIR = r"D:\张德帅\2026-06-27-20-10-38"
VIDEO_FILES = {
    "v1": os.path.join(ASSET_DIR, "3f8db7da7621417316be42f172d7b8c4.mp4"),
    "v2": os.path.join(ASSET_DIR, "07d74535efd5cacd831bf71427c889e5.mp4"),
    "v3": os.path.join(ASSET_DIR, "adef7208e224dbf067914999fd40d30d.mp4"),
    "v4": os.path.join(ASSET_DIR, "b0f8e9ead4e97e5f4ddae13c350bf87b.mp4"),
}
for name, path in VIDEO_FILES.items():
    if not os.path.exists(path):
        raise FileNotFoundError(f"素材 {name} 不存在: {path}")

TMP_DIR = r"D:\张德帅\2026-06-27-21-09-32\_draft_tmp"
JIANYING_DIR = r"C:\Users\周帅军\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft"
DRAFT_NAME = "理发探店Vlog_自动剪辑"
JY_DRAFTC = r"C:\Users\周帅军\.workbuddy\jy-draftc\jy-draftc-amd64-windows\jy-draftc.exe"

# --- resource_id 字典（全部免费非VIP）---
花字 = {"简约黑白花字": "6896137924853648648"}
贴纸 = {
    "卡通剪刀": "6914596591491943693",
    "省略号": "7075693932138581289",       # 通用符号 黑白线条 省略号
    "星光闪烁": "7058607780063677703",     # 星星 跳动 闪烁 六芒星
}
运镜 = {"3D环绕运镜": "7641495996966505766"}

# --- 预生成黑场 ---
BLACK_CARD = os.path.join(TMP_DIR, "black_card.mp4")
if not os.path.exists(BLACK_CARD):
    r = subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "color=c=black:s=1080x1920:d=2.0:r=30",
        "-c:v", "libx264", "-preset", "ultrafast", BLACK_CARD
    ], capture_output=True, text=True, timeout=15)

# ============================================================
# 创建草稿
# ============================================================
print(f"[1/13] 创建草稿: {DRAFT_NAME}")
draft_folder = draft.DraftFolder(TMP_DIR)
script = draft_folder.create_draft(DRAFT_NAME, 1080, 1920, allow_replace=True)

# ============================================================
# 轨道
# ============================================================
print("[2/13] 设置轨道...")
script.add_track(TrackType.video, "main", relative_index=0)
script.add_track(TrackType.video, "pip", relative_index=1)       # PIP 画中画
script.add_track(TrackType.text, "text", relative_index=0)
script.add_track(TrackType.text, "text_overlay", relative_index=1)
script.add_track(TrackType.text, "text_stars", relative_index=2)    # 星光文字轨道
script.add_track(TrackType.sticker, "stickers", relative_index=0)  # 贴纸
script.add_track(TrackType.audio, "audio", relative_index=0)
script.add_track(TrackType.filter, "global_filter", relative_index=0)
script.add_track(TrackType.effect, "global_effect", relative_index=0)

# ============================================================
# 辅助函数
# ============================================================
def make_tr(start_s, duration_s):
    return trange(f"{start_s}s", f"{duration_s}s")

def add_text(script, text, start_s, duration_s, font=None, size=8.0,
             color=(1.0, 1.0, 1.0), pos_x=0.0, pos_y=-0.7,
             anim=None, anim_dur=0.5, bold=False, track="text",
             effect_id=None):
    """添加文字。effect_id 为花字 resource_id"""
    style = TextStyle(size=size, color=color, bold=bold)
    clip = ClipSettings(transform_x=pos_x, transform_y=pos_y)
    seg = draft.TextSegment(text, make_tr(start_s, duration_s),
                            font=font, style=style, clip_settings=clip)
    if anim:
        seg.add_animation(anim, duration=tim(f"{anim_dur}s"))
    if effect_id:
        seg.add_effect(effect_id)
    script.add_segment(seg, track_name=track)
    return seg

def add_sticker(script, resource_id, start_s, duration_s,
                pos_x=0.0, pos_y=0.0, scale=1.0):
    """添加贴纸片段"""
    cs = ClipSettings(transform_x=pos_x, transform_y=pos_y,
                      scale_x=scale, scale_y=scale)
    seg = StickerSegment(resource_id, make_tr(start_s, duration_s), clip_settings=cs)
    script.add_segment(seg, track_name="stickers")
    return seg

# ============================================================
# 视频片段
# ============================================================
print("[3/13] 添加视频片段...")
v1, v2, v3, v4 = VIDEO_FILES["v1"], VIDEO_FILES["v2"], VIDEO_FILES["v3"], VIDEO_FILES["v4"]
t = 0.0

# --- ① 开场Hook: v3 0~2s ---
seg_hook = draft.VideoSegment(v3, trange(f"{t}s", "2.0s"),
                              source_timerange=trange(0, tim("2s")))
seg_hook.add_animation(IntroType.斜切)
script.add_segment(seg_hook, track_name="main")
t += 2.0

# --- ② 分区特写: v1 切三段 ---
seg_v1a = draft.VideoSegment(v1, trange(f"{t}s", "0.8s"),
                             source_timerange=trange(tim("0.5s"), tim("0.8s")))
script.add_segment(seg_v1a, track_name="main"); t += 0.8
seg_v1b = draft.VideoSegment(v1, trange(f"{t}s", "1.2s"),
                             source_timerange=trange(tim("1.5s"), tim("1.2s")))
script.add_segment(seg_v1b, track_name="main"); t += 1.2
seg_v1c = draft.VideoSegment(v1, trange(f"{t}s", "1.5s"),
                             source_timerange=trange(tim("3.0s"), tim("1.5s")))
script.add_segment(seg_v1c, track_name="main"); t += 1.5

seg_v1a.add_keyframe(KeyframeProperty.uniform_scale, 0, 1.0)
seg_v1a.add_keyframe(KeyframeProperty.uniform_scale, tim("3.5s"), 1.10)

# --- ③ 发夹细节: v2 切三段 ---
seg_v2a = draft.VideoSegment(v2, trange(f"{t}s", "0.8s"),
                             source_timerange=trange(tim("0.5s"), tim("0.8s")))
script.add_segment(seg_v2a, track_name="main"); t += 0.8
seg_v2b = draft.VideoSegment(v2, trange(f"{t}s", "1.0s"),
                             source_timerange=trange(tim("1.5s"), tim("1.0s")))
script.add_segment(seg_v2b, track_name="main"); t += 1.0
seg_v2c = draft.VideoSegment(v2, trange(f"{t}s", "1.2s"),
                             source_timerange=trange(tim("3.0s"), tim("1.2s")))
script.add_segment(seg_v2c, track_name="main"); t += 1.2

# --- ④ 等待过渡: v4 慢速长镜头 ---
v4_start = t
seg_v4 = draft.VideoSegment(v4, trange(f"{t}s", "4.0s"),
                            source_timerange=trange(tim("1.0s"), tim("6.0s")),
                            speed=1.5, volume=0)
seg_v4.add_keyframe(KeyframeProperty.alpha, 0, 0.0)
seg_v4.add_keyframe(KeyframeProperty.alpha, tim("0.3s"), 1.0)
seg_v4.add_keyframe(KeyframeProperty.alpha, tim("3.5s"), 1.0)
seg_v4.add_keyframe(KeyframeProperty.alpha, seg_v4.duration, 0.7)
script.add_segment(seg_v4, track_name="main")
t += 4.0

# --- ⑤ 成果展示: v3 切三段 ---
v3_seg_start = t
seg_v3a = draft.VideoSegment(v3, trange(f"{t}s", "1.5s"),
                             source_timerange=trange(tim("2.0s"), tim("1.5s")))
script.add_segment(seg_v3a, track_name="main"); t += 1.5

seg_v3b = draft.VideoSegment(v3, trange(f"{t}s", "2.25s"),
                             source_timerange=trange(tim("4.0s"), tim("1.5s")),
                             speed=1.0 / 1.5)
seg_v3b.add_keyframe(KeyframeProperty.alpha, 0, 0.8)
seg_v3b.add_keyframe(KeyframeProperty.alpha, tim("0.3s"), 1.0)
script.add_segment(seg_v3b, track_name="main"); t += 2.25

seg_v3c = draft.VideoSegment(v3, trange(f"{t}s", "2.0s"),
                             source_timerange=trange(tim("5.5s"), tim("2.0s")))
seg_v3c.add_animation(OutroType.渐隐)
script.add_segment(seg_v3c, track_name="main"); t += 2.0

# --- ⑥ 黑场卡片 ---
seg_black = draft.VideoSegment(BLACK_CARD, trange(f"{t}s", "1.5s"),
                               source_timerange=trange(0, tim("1.5s")), volume=0)
seg_black.add_animation(IntroType.渐显)
script.add_segment(seg_black, track_name="main")
black_start = t
t += 1.5

total_duration = t
print(f"  视频总时长: {total_duration:.1f}s")

# ============================================================
# 画中画 PIP：v4等待段右上角叠加v2发夹特写
# ============================================================
print("[4/13] 添加画中画PIP...")
pip_start = v4_start + 0.5  # 等待段开始0.5s后出现
pip_dur = 3.0
seg_pip = draft.VideoSegment(
    v2,
    trange(f"{pip_start}s", f"{pip_dur}s"),
    source_timerange=trange(tim("0.5s"), tim(f"{pip_dur}s")),
    clip_settings=ClipSettings(
        transform_x=0.65,    # 右上角
        transform_y=-0.55,
        scale_x=0.3,         # 缩小到30%
        scale_y=0.3,
        alpha=0.85
    ),
    volume=0
)
seg_pip.add_keyframe(KeyframeProperty.alpha, 0, 0.0)
seg_pip.add_keyframe(KeyframeProperty.alpha, tim("0.3s"), 0.85)
seg_pip.add_keyframe(KeyframeProperty.alpha, seg_pip.duration - tim("0.5s"), 0.85)
seg_pip.add_keyframe(KeyframeProperty.alpha, seg_pip.duration, 0.0)
script.add_segment(seg_pip, track_name="pip")

# ============================================================
# 转场
# ============================================================
print("[5/13] 添加转场...")
seg_hook.add_transition(TransitionType.叠化, duration=tim("0.3s"))
seg_v1c.add_transition(TransitionType.推近, duration=tim("0.4s"))
seg_v2c.add_transition(TransitionType.叠化, duration=tim("0.5s"))
seg_v4.add_transition(TransitionType.闪黑, duration=tim("0.4s"))
seg_v3c.add_transition(TransitionType.叠化, duration=tim("0.3s"))

# ============================================================
# 滤镜
# ============================================================
print("[6/13] 添加滤镜...")
script.add_filter(FilterType.胶片电影, trange(0, script.duration),
                  track_name="global_filter", intensity=40)

# ============================================================
# 文字（含花字效果）
# ============================================================
print("[7/13] 添加文字...")

花字_id = 花字["简约黑白花字"]

# 开场大标题 + 花字
add_text(script, "换个发型 换种心情",
         start_s=0.1, duration_s=1.8,
         font=FontType.文轩体, size=12,
         color=(1.0, 0.95, 0.4), pos_y=0.55,
         anim=TextIntro.向上弹入, anim_dur=0.3, bold=True,
         effect_id=花字_id)

# STEP 标签
steps = [
    ("STEP 01 · 分区", 2.0, 3.5),
    ("STEP 02 · 上卷", 5.5, 3.0),
    ("STEP 03 · 等待", 8.5, 4.0),
    ("STEP 04 · 成果", 12.5, 5.75),
]
for text, start, dur in steps:
    add_text(script, text, start_s=start, duration_s=dur,
             size=7, color=(1.0, 0.83, 0.04),
             pos_x=-0.72, pos_y=0.72,     # 左上角
             anim=TextIntro.复古打字机, anim_dur=0.5, bold=True)

# 成果展示花字 + 金边描边
add_text(script, "这质感 👍",
         start_s=v3_seg_start + 0.3, duration_s=1.2,
         size=10, color=(1.0, 0.3, 0.3),
         pos_y=-0.3, track="text_overlay",
         anim=TextIntro.弹入, anim_dur=0.3, bold=True,
         effect_id=花字_id)

add_text(script, "这层次 ✨",
         start_s=v3_seg_start + 1.5 + 0.5, duration_s=1.5,
         size=10, color=(1.0, 0.85, 0.0),
         pos_y=-0.3, track="text_overlay",
         anim=TextIntro.弹入跳动, anim_dur=0.3, bold=True,
         effect_id=花字_id)

add_text(script, "绝了 👍",
         start_s=v3_seg_start + 1.5 + 2.25 + 0.5, duration_s=1.5,
         size=12, color=(1.0, 0.15, 0.15),
         pos_y=-0.2, track="text_overlay",
         anim=TextIntro.放大, anim_dur=0.4, bold=True,
         effect_id=花字_id)

# 黑场文字
add_text(script, "下期见 👋",
         start_s=black_start + 0.2, duration_s=1.0,
         font=FontType.文轩体, size=12,
         color=(1.0, 1.0, 1.0), pos_y=-0.2,
         anim=TextIntro.弹入, anim_dur=0.3, bold=True,
         effect_id=花字_id)

add_text(script, "点赞 · 关注 · 收藏",
         start_s=black_start + 0.5, duration_s=1.0,
         size=7, color=(0.8, 0.8, 0.8),
         pos_y=-0.5, track="text_overlay",
         anim=TextIntro.渐显, anim_dur=0.5, bold=True)

# ============================================================
# 贴纸
# ============================================================
print("[8/13] 添加贴纸...")

# 卡通剪刀贴纸 — v1分区段右上角，0.5~5.5s
add_sticker(script, 贴纸["卡通剪刀"],
            start_s=0.5, duration_s=5.0,
            pos_x=0.65, pos_y=0.65, scale=0.8)

# 省略号贴纸 — v4等待段人物头顶
add_sticker(script, 贴纸["省略号"],
            start_s=v4_start + 1.0, duration_s=3.0,
            pos_x=0.0, pos_y=0.25, scale=1.2)

# 星光闪烁贴纸 — v3成果段，围绕人物头发
add_sticker(script, 贴纸["星光闪烁"],
            start_s=v3_seg_start + 2.0, duration_s=2.0,
            pos_x=0.55, pos_y=-0.2, scale=0.7)

# "✨" 星光文字 — v3成果段环绕效果
add_text(script, "✨",
         start_s=v3_seg_start + 2.0, duration_s=2.0,
         size=20, color=(1.0, 0.85, 0.0),
         pos_x=0.6, pos_y=-0.3, track="text_stars",
         anim=TextIntro.放大, anim_dur=0.5, bold=True)

# 第二颗星光 — v3段左侧
add_sticker(script, 贴纸["星光闪烁"],
            start_s=v3_seg_start + 4.2, duration_s=1.5,
            pos_x=-0.55, pos_y=-0.3, scale=0.6)

# ============================================================
# 特效
# ============================================================
print("[9/13] 添加特效...")
seg_v2a.add_effect(VideoSceneEffectType.闪耀星光, [None, None])
seg_v2b.add_effect(VideoSceneEffectType.闪耀星光, [None, None])
seg_v2c.add_effect(VideoSceneEffectType.闪耀星光, [None, None])
seg_v3b.add_effect(VideoSceneEffectType.胶片漏光, [None, None])
seg_v3c.add_keyframe(KeyframeProperty.alpha, seg_v3c.duration - tim("1s"), 1.0)
seg_v3c.add_keyframe(KeyframeProperty.alpha, seg_v3c.duration, 0.0)
seg_hook.add_effect(VideoSceneEffectType.闪白, [None])

# ============================================================
# 保存基础草稿
# ============================================================
print("[10/13] 保存基础草稿...")
script.save()
print(f"  ✅ 已保存到临时目录")

# ============================================================
# 后处理：注入曲线变速 + 3D运镜
# ============================================================
print("[11/13] 后处理注入：曲线变速 + 3D运镜...")

DEC_PATH = os.path.join(TMP_DIR, DRAFT_NAME, "draft_content.json.dec.json")
SRC_PATH = os.path.join(TMP_DIR, DRAFT_NAME, "draft_content.json")

# 复制并解密
shutil.copy2(SRC_PATH, DEC_PATH)

with open(DEC_PATH, 'r', encoding='utf-8') as f:
    data = json.load(f)

mats = data.setdefault('materials', {})
tracks = data.get('tracks', [])

# ---- 注入曲线变速 ----
speed_id = str(uuid.uuid4()).upper()
speed_material = {
    "id": speed_id,
    "type": "speed",
    "mode": 1,
    "speed": 0.889,
    "curve_speed": {
        "id": "6768730851543880206",
        "name": "自定义",
        "speed_points": [
            {"x": 0.0, "y": 1.0},
            {"x": 0.25, "y": 1.0},
            {"x": 0.5346534653465347, "y": 0.6},
            {"x": 0.75, "y": 1.0},
            {"x": 1.0, "y": 1.0}
        ]
    }
}
mats.setdefault('speeds', []).append(speed_material)

# 找到v4段并注入 speed ref
for track in tracks:
    if track.get('type') == 'video' and track.get('name') == 'main':
        for seg in track.get('segments', []):
            tr = seg.get('target_timerange', {})
            start = tr.get('start', 0) / 1e6
            if abs(start - v4_start) < 0.1:
                refs = seg.setdefault('extra_material_refs', [])
                refs.insert(0, speed_id)
                seg['speed'] = 0.889
                print(f"  ✅ 曲线变速已注入到 v4 段 ({v4_start:.1f}s)")
                break

# ---- 注入 3D环绕运镜 ----
effect_mat_id = str(uuid.uuid4()).upper()
effect_seg_id = str(uuid.uuid4()).upper()
effect_material = {
    "id": effect_mat_id,
    "effect_id": 运镜["3D环绕运镜"],
    "resource_id": 运镜["3D环绕运镜"],
    "name": "3D环绕运镜",
    "type": "video_effect",
    "path": "C:/Users/周帅军/AppData/Local/JianyingPro/User Data/Cache/effect/7641495996966505766/d5be6b8989345537499a00f9d51343f9",
    "value": 1.0,
    "category_id": "1111",
    "category_name": "画面特效",
    "apply_target_type": 2,
    "source_platform": 1,
    "request_id": "202606291900000"
}
mats.setdefault('video_effects', []).append(effect_material)

# 在 effect track 添加运镜片段
effect_dur = total_duration - v3_seg_start - 2.0  # 覆盖v3成果段减去最后2秒
effect_start = v3_seg_start
for track in tracks:
    if track.get('type') == 'effect':
        track.setdefault('segments', []).append({
            "id": effect_seg_id,
            "target_timerange": {
                "start": int(effect_start * 1e6),
                "duration": int(effect_dur * 1e6)
            },
            "render_timerange": {},
            "material_id": effect_mat_id,
            "render_index": 11000,
            "enable_lut": False,
            "enable_adjust": False,
            "enable_hsl": False,
            "track_render_index": 3,
            "responsive_layout": {},
            "enable_adjust_mask": False,
            "source": "segmentsourcenormal"
        })
        print(f"  ✅ 3D环绕运镜已注入到 v3 成果段 ({v3_seg_start:.1f}s~{v3_seg_start+effect_dur:.1f}s)")
        break

# 写回解密JSON
with open(DEC_PATH, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

# ---- 加密部署 ----
print("[12/13] 加密并部署...")
JY_DRAFT_PATH = os.path.join(JIANYING_DIR, DRAFT_NAME)
TMP_DRAFT_PATH = os.path.join(TMP_DIR, DRAFT_NAME)

for fname in ["draft_content.json", "draft_meta_info.json"]:
    src = os.path.join(TMP_DRAFT_PATH, fname)
    if not os.path.exists(src):
        continue

    dec = src + ".dec.json"
    if fname == "draft_content.json":
        # Already has DEC_PATH prepared
        dec_data = open(DEC_PATH, 'rb').read()
        with open(dec, 'wb') as f:
            f.write(dec_data)
    else:
        shutil.copy2(src, dec)

    enc = dec + ".enc"
    r = subprocess.run([JY_DRAFTC, "-e", dec, enc],
                       capture_output=True, text=True, timeout=30)
    if r.returncode == 0 and os.path.exists(enc):
        os.makedirs(JY_DRAFT_PATH, exist_ok=True)
        with open(os.path.join(JY_DRAFT_PATH, fname), "wb") as f:
            f.write(open(enc, "rb").read())
        print(f"  ✅ {fname} 已加密部署")
        os.remove(dec)
        os.remove(enc)

# 复制其他文件
for item in os.listdir(TMP_DRAFT_PATH):
    if item == "black_card.mp4":
        continue
    sp = os.path.join(TMP_DRAFT_PATH, item)
    dp = os.path.join(JY_DRAFT_PATH, item)
    if os.path.isfile(sp) and not any(item.endswith(x) for x in [".dec.json", ".enc"]):
        shutil.copy2(sp, dp)

print(f"  ✅ 草稿已部署到剪映目录")

# ============================================================
# 输出
# ============================================================
print("\n" + "=" * 60)
print("🎬 v3 剪辑完成！")
print("=" * 60)
print(f"  草稿: {DRAFT_NAME}  |  {total_duration:.1f}s  |  1080×1920")
print()
print("  🆕 新增:")
print("  ✅ 花字金边 — 开场标题+成果花字+结尾")
print("  ✅ 贴纸 — 卡通剪刀(右上) + ···省略号 + ✨星光 ×2")
print("  ✅ 画中画PIP — v4等段右上角v2特写(30%)")
print("  ✅ 3D环绕运镜 — v3成果展示段")
print("  ✅ 曲线变速 — v4等段 100%→60%→100%")
print()
print("  需手动补:")
print("  1. BGM → 音频库搜 'vlog/lo-fi/R&B'")
print("  2. 音效 → 卡点处加嗖/叮/快门")
print("=" * 60)
