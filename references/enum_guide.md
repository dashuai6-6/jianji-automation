# pyJianYingDraft v0.2.7 枚举值参考手册

> 基于实测验证，剪映10.9.0兼容

## KeyframeProperty（关键帧属性）

| 属性 | 说明 | 适用 |
|------|------|------|
| `uniform_scale` | 等比缩放 | 视频/图片/贴纸/文本 |
| `scale_x` | X轴缩放 | 视频/图片/贴纸/文本 |
| `scale_y` | Y轴缩放 | 视频/图片/贴纸/文本 |
| `alpha` | 透明度 (0.0~1.0) | 所有 |
| `position_x` | X轴位置 | 视频/图片/贴纸/文本 |
| `position_y` | Y轴位置 | 视频/图片/贴纸/文本 |
| `rotation` | 旋转角度 | 视频/图片/贴纸/文本 |
| `saturation` | 饱和度 | 视频/图片 |
| `contrast` | 对比度 | 视频/图片 |
| `brightness` | 亮度 | 视频/图片 |
| `volume` | 音量 | 音频 |

**使用示例**：
```python
seg.add_keyframe(KeyframeProperty.uniform_scale, 0, 1.0)       # 开始：100%
seg.add_keyframe(KeyframeProperty.uniform_scale, tim("3s"), 1.10)  # 3秒后：110%
seg.add_keyframe(KeyframeProperty.alpha, seg.duration, 0.0)    # 淡出
```

## TransitionType（转场）

常用值：
- `TransitionType.叠化` — 叠化，最常用
- `TransitionType.推近` — 推进运镜（注意：不是"推进"）
- `TransitionType.闪白` / `TransitionType.闪黑` — 黑白闪场
- `TransitionType.故障` — 故障效果
- `TransitionType.叠化扭曲` — 带扭曲的叠化
- `TransitionType.信号故障` — 信号故障风格

**注意**：转场加在「前一个」片段上，参数 `duration=tim("0.5s")` 控制时长。

## FilterType（滤镜）

常用值：
- `FilterType.胶片电影` — 胶片质感（注意：不是单纯的"胶片"）
- `FilterType.古早感胶片` — 复古胶片
- `FilterType.原生肤` — 人像美化

**使用**：
```python
# 片段滤镜
seg.add_filter(FilterType.胶片电影, 40)  # 强度40
# 全局滤镜轨道
script.add_filter(FilterType.胶片电影, trange(0, script.duration), track_name="global_filter", intensity=40)
```

## VideoSceneEffectType（视频特效）

| 效果 | 参数量 | 使用示例 |
|------|--------|---------|
| `闪耀星光` | 2 | `add_effect(VideoSceneEffectType.闪耀星光, [None, None])` |
| `胶片漏光` | 2 | `add_effect(VideoSceneEffectType.胶片漏光, [None, None])` |
| `闪白` | 1 | `add_effect(VideoSceneEffectType.闪白, [None])` |
| `全息扫描` | 6 | `add_effect(VideoSceneEffectType.全息扫描, [None]*6)` |
| `故障` | N | 检查 `e.value.params` 长度 |
| `发光` | N | 同上 |
| `烟花` | N | 同上 |

**特效参数规则**：参数数量必须精确匹配 `e.value.params` 的长度，可以用 `[None] * n` 传入默认值。

## TextIntro（文字入场动画）

| 值 | 效果描述 |
|----|---------|
| `TextIntro.弹入` | 弹入 |
| `TextIntro.弹入跳动` | 弹入跳动 |
| `TextIntro.弹簧` | 弹簧效果 |
| `TextIntro.放大` | 放大出现 |
| `TextIntro.渐显` | 渐显（最朴素） |
| `TextIntro.向上滑动` | 从下方滑入 |
| `TextIntro.向下滑动` | 从上方滑入 |
| `TextIntro.飞入` | 飞入 |
| `TextIntro.复古打字机` | 打字机逐字 |
| `TextIntro.故障闪动` | 故障风格 |
| `TextIntro.随机弹跳` | 随机弹跳 |

## TextOutro（文字出场动画）

常用：`TextOutro.渐隐`、`TextOutro.缩小`、`TextOutro.故障闪动`

## IntroType（视频入场动画）

常用：`IntroType.斜切`、`IntroType.放大`、`IntroType.渐显`

## OutroType（视频出场动画）

常用：`OutroType.渐隐`、`OutroType.缩小`

## TextStyle 构造参数

```python
TextStyle(
    size=8.0,              # 字号（默认8.0！不是像素！）
    bold=False,            # 加粗
    italic=False,          # 斜体
    underline=False,       # 下划线
    color=(1.0, 1.0, 1.0), # RGB颜色 (0~1)
    alpha=1.0,             # 不透明度
    align=0,               # 0=左 1=中 2=右
    vertical=False,        # 竖排
    letter_spacing=0,
    line_spacing=0,
    auto_wrapping=False,
    max_line_width=0.82,
)
```

**没有 outline_color/outline_width/shadow 参数！** 描边/阴影需通过花字 `add_effect(resource_id)` 实现。

### ⚠️ 字号 size 参考表（重要！）

**默认值是 8.0，不是像素值！** 设大了文字会撑出屏幕。

| 用途 | 推荐size | 说明 |
|------|---------|------|
| 小字幕/标签 | 5~7 | 比默认略小 |
| 常规字幕 | 8~10 | 默认大小附近 |
| 章节标题 | 10~14 | 明显但不夸张 |
| 大标题 | 14~18 | 片头片尾主标题 |
| 超大标题 | 18~22 | 极少使用，可能撑屏 |

**绝对不要超过 25！** 30以上文字会严重超出屏幕。

## ClipSettings 坐标系统（重要！）

```python
ClipSettings(
    alpha=1.0,
    flip_horizontal=False,
    flip_vertical=False,
    rotation=0.0,
    scale_x=1.0,
    scale_y=1.0,
    transform_x=0.0,  # 水平: -1=左边缘, 0=居中, 1=右边缘
    transform_y=0.0,  # 垂直: -1=底部, 0=居中, 1=顶部
)
```

**常见位置参数**:
| 描述 | transform_x | transform_y |
|------|------------|-------------|
| 左上角 | -0.72 | 0.72 |
| 右上角 | 0.65 | 0.65 |
| 居中偏上 | 0.0 | 0.5 |
| 居中偏下 | 0.0 | -0.5 |
| 底部字幕 | 0.0 | -0.8 |

⚠️ 注意 `transform_y` 正向=上方，负向=下方。这是剪映的坐标系，与常规屏幕坐标相反。

## 常见错误速查

| 错误 | 原因 | 修复 |
|------|------|------|
| **文字超出屏幕** | **字号太大！默认8.0，30以上必撑屏** | 标题12~18，标签7~10，字幕8~10 |
| `SegmentOverlap` 文字重叠 | 同一文字轨道上两段文字时间重叠 | 加额外文字轨道（如 `text_overlay`），或缩短 duration |
| `PermissionError [WinError 32]` | 剪映正在占用草稿目录 | 先生成到临时目录，加密后复制 |
| 剪映10.x提示"草稿损坏" | 草稿未加密 | 用 jy-draftc -e 加密 draft_content.json 和 draft_meta_info.json |
| `ValueError: 传入了过多的参数` | 特效参数数量错误 | 用 `[None]*N` 匹配 `e.value.params` 长度 |
| `TypeError: unexpected keyword argument 'outline_color'` | TextStyle 无此参数 | 移除，改用花字 resource_id |
| `AttributeError: no attribute` | 枚举值名称不对 | 参照上方枚举表 |

## 黑场卡片 / 结尾画面

pyJianYingDraft 不支持纯色片段，用 ffmpeg 生成黑场视频作为替代：

```bash
ffmpeg -y -f lavfi -i "color=c=black:s=1080x1920:d=1.5:r=30" \
  -c:v libx264 -preset ultrafast black_card.mp4
```

然后作为普通 VideoSegment 添加到轨道末尾，叠加结尾文字。
**注意**：黑场卡片素材不需要复制到剪映草稿目录（剪映会引用相对路径即可）。

## 多条文字同时显示

同一文字轨道上时段不能重叠。需要同时显示多条文字时，建多条文字轨道：

```python
script.add_track(TrackType.text, "text", relative_index=0)
script.add_track(TrackType.text, "text_overlay", relative_index=1)
```

不同文字放到不同轨道即可同时显示。

## 花字（文字描边/金边效果）

通过 `TextSegment.add_effect(resource_id)` 实现，**不通过 TextStyle 参数**。

### 已知的花字 resource_id（免费）

| 名称 | resource_id | 效果 |
|------|------------|------|
| 简约黑白花字 | `6896137924853648648` | 白字+黑色描边 |

**使用**：
```python
seg = TextSegment("标题", timerange, style=TextStyle(size=10, color=(1,1,1)))
seg.add_effect("6896137924853648648")  # 添加花字效果
```
或在 `add_text_overlay` 辅助函数中传入 `effect_id` 参数。

### 如何发现新的花字 resource_id
用户在剪映中给文字添加花字效果 → 解密草稿 → 查看 text segment 的 `extra_material_refs` → 找到引用的 effect material

## 贴纸 (Stickers)

通过 `StickerSegment(resource_id, timerange, clip_settings=...)` 添加到 sticker 轨道。

### 已知的贴纸 resource_id（免费）

| 名称 | resource_id |
|------|------------|
| 卡通剪刀 | `6914596591491943693` |
| 通用符号 黑白线条 省略号 | `7075693932138581289` |
| 星星 跳动 闪烁 六芒星 | `7058607780063677703` |
| 综艺贴纸-无语 | `6895924436822773000` |

**如何搜索新贴纸**：通过 capcut-mate search_sticker API
```bash
curl -s -X POST 'https://capcut-mate.jcaigc.cn/openapi/capcut-mate/v1/search_sticker' \
  -H 'Content-Type: application/json; charset=utf-8' \
  -d '{"keyword":"星星"}' | python -c "import sys,json;[print(f'{i[\"sticker_id\"]} | {i[\"title\"]}') for i in json.load(sys.stdin)['data']]"
```

**使用**：
```python
script.add_track(TrackType.sticker, "stickers", relative_index=0)
cs = ClipSettings(transform_x=0.6, transform_y=-0.6, scale_x=0.8, scale_y=0.8)
seg = StickerSegment("6914596591491943693", timerange, clip_settings=cs)
script.add_segment(seg, track_name="stickers")
```

### 如何发现新贴纸 resource_id
与花字相同：用户拖入贴纸到草稿 → 解密 → 读取 stickers 材料列表。

## 3D运镜 / 画面特效（后处理注入）

pyJianYingDraft 的 `EffectSegment` 不支持直接传 resource_id。
需要在生成 JSON 后，通过后处理注入。

### 已知的运镜 resource_id（免费）

| 名称 | resource_id |
|------|------------|
| 3D环绕运镜 | `7641495996966505766` |

**后处理步骤**：
1. pyJianYingDraft 生成草稿 → `script.save()`
2. 打开 `draft_content.json`
3. 在 `materials.video_effects` 中添加 effect material
4. 在 effect 轨道添加 segment，`material_id` 指向该 material
5. 加密部署

## 曲线变速（后处理注入）

同样需要后处理：在 `materials.speeds` 中注入 `curve_speed.speed_points`。

### speed_points 格式

```json
{
  "curve_speed": {
    "speed_points": [
      {"x": 0.0, "y": 1.0},    // 开始 100%
      {"x": 0.25, "y": 1.0},   // 25%处仍 100%
      {"x": 0.53, "y": 0.6},   // 53%处降到 60%
      {"x": 0.75, "y": 1.0},   // 75%处回升 100%
      {"x": 1.0, "y": 1.0}     // 结尾 100%
    ]
  }
}
```

参数：`x` 为时间比例(0~1)，`y` 为速度倍率。

遇到不确定的枚举名时，运行：
```python
import pyJianYingDraft as draft
# 列出所有成员
for m in draft.TransitionType:
    print(m.name)
# 或搜索
[name for name in dir(draft.TransitionType) if '叠' in name]
```
