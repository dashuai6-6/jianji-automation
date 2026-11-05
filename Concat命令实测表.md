# Concat 0.2.8 `edit_apply` 50 个命令实测表

> 实测时间：2026-11-05 | 环境：`/usr/bin/concat` 0.2.8 headless，无显卡无显示器
> 方法：每个命令在**全新项目**里跑一次，前后 `project_get` 全量对比；关键命令再导出成片用 `ffprobe` 验时长
> 结论：**42 个真生效 / 3 个假命令 / 4 个条件受限 / 1 个参数未全破解**

---

## 一、先记住三个陷阱

这三条比命令表本身更重要，踩了会让你以为命令不存在。

### 陷阱 1：`clipId` 写错，不报错，静默空转

```python
edit_apply(op="setClipSpeedCurve", clipId="c2", curve=[...])   # c2 不存在
# → 返回 {"canUndo": true}，看起来成功，实际什么都没变
```

我第一次批量测 50 个命令时，把 clipId 写死成 `c2`，结果 24 个命令全被判成"空转"。换成真实 id 后，其中 19 个立刻生效。

**所以：每次都要从 `timeline_read` 或 `project_get` 取真实 id，不要猜。**

### 陷阱 2：字段名写错，不报错，静默忽略

`setClipSpeedCurve` 的曲线字段叫 **`curve`**，元素里叫 **`at`**：

```python
{"op":"setClipSpeedCurve","clipId":cid,"curve":[{"at":0.0,"speed":1.0},{"at":0.5,"speed":0.35}]}  # ✅
{"op":"setClipSpeedCurve","clipId":cid,"points":[...]}    # ❌ 被忽略，静默无效果
{"op":"setClipSpeedCurve","clipId":cid,"curve":[{"t":0,...}]}  # ❌ 报 missing field `at`
```

`points`、`keyframes`、`keys`、`stops`、`curvePoints` 全部被静默吞掉，只有 `curve` 对。

### 陷阱 3：真正会报错的只有三类消息

| 消息 | 含义 | 怎么利用 |
|---|---|---|
| `missing field \`x\`` | 缺必填字段 | **最好的探针**，一层层补就能剥出完整结构 |
| `unknown variant \`x\`, expected one of ...` | 枚举值错 | 会把**全部合法值**列出来 |
| `expected struct X` / `expected an array of length 2` | 类型不对 | 告诉你这里是结构体还是定长数组 |

反过来，**不报错不等于生效**。要判定真生效，只有两条路：`project_get` 前后对比，或导出后 `ffprobe`。

### 陷阱 4：不 `project_save` 不落盘

改动只在内存里。不 save 的话磁盘上的 `concat.json` 一直是 131 字节的空壳（只有画幅和帧率）：

```
加完 clip，内存里 clips: 1        ← project_get 能看到
磁盘 concat.json: 131 字节        ← 文件里啥都没有
project_save 之后: 2773 字节      ← 这才真的存下来
新进程 project_open 重开: clips 1  ← save 过的才读得回来
```

另外，即使 save 过，`concat.json` 里也只存工程结构；要**实时**看状态用 `project_get`（读内存），比读磁盘 JSON 更准、更全。

### 陷阱 5：项目目录必须在 `$HOME` 里

```python
project_create(location="/tmp/x")        # ❌ 拒绝
# /tmp/x is outside where this API writes (/root)
project_create(location="/root/x")       # ✅
```

实测 `/tmp`、`/var/tmp`、`/workspace` 全部被拒，只有家目录内可以。导出路径同理。做批量任务时工作目录建在 `$HOME` 下，别图方便用 `/tmp`。

---

## 二、50 个命令全表

### ✅ 真生效（42 个）

| 命令 | 必填参数 | 干什么 |
|---|---|---|
| `addClip` | mediaId, trackId, start | 把素材铺到指定轨道指定秒 |
| `addClipAtFirstFree` | mediaId, start | 放到第一个空位，不用指定轨道 |
| `addClipsInSequence` | mediaIds[], start | 一串素材首尾相接铺好 |
| `moveClips` | **moves**: [{clipId, trackId, start}] | 批量挪位置，一次一步撤销 |
| `trimClip` | clipId, **edge**("start"/"end"), **delta**(秒) | 拉一边的入出点 |
| `splitClips` | **clipIds**[], **time**(时间线绝对秒) | 在某一刻切开 |
| `removeClips` | clipIds[] | 删片段 |
| `replaceClipMedia` | clipId, **item**(NewMedia) | 换片段里的素材但保留位置 |
| `mergeClips` | clipIds[]（**必须同源、必须相邻无缝**） | 合并连续片 |
| `setClipSpeed` | clipId, speed(0.0625~16) | 整体变速 |
| **`setClipSpeedCurve`** | clipId, **curve**:[{at:0~1, speed}] | **变速曲线（快→慢→快）** |
| `setClipKey` | clipId, property, at(0~1), value | 打关键帧，写进 `clip.keys` |
| `clearClipKey` | clipId, property, at | 删单个关键帧 |
| `clearClipKeys` | clipId, property | 清空某属性的全部关键帧 |
| `setEffectKey` | **clipId=效果层clip**, entry, key, at, value | 效果参数打关键帧 |
| `setClipTransform` | clipId, scale(0.05~8), offsetX/Y, rotation, opacity | 缩放位移旋转透明度 |
| `frameClip` | clipId, **framing**("fit"/"fill") | 一键适配画面 |
| `setClipCutout` | clipId, **mode**("auto"/"custom"), points | 抠像 |
| `addCutoutStroke` | clipId, **stroke**:{tool, size, **points**:**`[[x,y], ...]`**} | 抠像笔刷描边 |
| `setClipStabilize` | clipId, stabilize:{} | 防抖 |
| `detachAudio` | clipId | 音画分离 |
| `reattachAudio` | clipId | 音频合回 |
| `addTextClip` | text, start, duration | 加文字 |
| `addShapeClip` | shape, **name**, start, duration | 加图形 |
| `addFont` | clipId, **family**, **path** | 指定字体 |
| `removeFont` | family | 移除字体 |
| `addTrack` | 无参 | 加轨道 |
| `removeTrack` | trackId | 删轨道 |
| `setTrackFlag` | trackId, flag("muted"), value(bool) | 轨道静音/隐藏 |
| `addTimeline` | 无参 | 加时间线（多版本矩阵用） |
| `removeTimeline` | timelineId（**不能删最后一个**） | 删时间线 |
| `renameTimeline` | timelineId, name | 重命名 |
| `selectTimeline` | timelineId | 切换活动时间线 |
| `moveTimeline` | timelineId, **index** | 调整顺序 |
| `setTimelineVideo` | timelineId, **video**:{width,height,rateNum,rateDen} | 改画幅帧率（横竖屏互转） |
| `setTimelineBackground` | timelineId, **background**:{kind, color} | 改底色 |
| `addMedia` | item(NewMedia) | 加素材（**通过但无变化，见下**） |
| `removeMedia` | mediaId | 从素材箱删 |
| `setMediaPlaceholder` | mediaId, placeholder(bool) | 标记占位 |
| `updateMediaPath` | mediaId, **newPath** | 换素材文件路径（不丢剪辑） |
| `setMediaColorRange` | mediaId, range("full") | 色域 full/video |
| `batch` | **commands**:[...] | 一批命令算一步撤销 |
| `updateClip` | clipId, **patch**:{...} | 改片段属性（volume 等） |

### ❌ 假命令（返回成功，实际什么都没做）

| 命令 | 实测 | 替代方案 |
|---|---|---|
| **`freezeFrame`** | 传 clipId + time 后 `project_get` **完全无变化**，clips 数量/时长一个字节都没动。0.0/1.0/3.4 三个时间点都试过，`duration`/`hold`/`length` 三种字段名也都试过。**还做了导出对照**：同一项目同一素材，`setClipSpeedCurve` 把 3.5s 拉成 7.000s（生效），紧接着 `freezeFrame(time=1.0, duration=2.0)` 导出仍是 **3.500s**（期望 5.5s） | **用 `preview_frame` 抽帧 → 存 PNG → `media_import` → `addClip`**。实测一次成功：抽出 1920×1080 的 PNG，导进来是 image 类型，铺到时间线默认 5 秒，这就是真正的定格 |
| `setClipEnhanced` | `on: true` 通过，项目无任何变化 | 用 `effect_layer_add(effectId="concat.adjust")` + `setEffectKey` 调参数 |
| `addMedia` | `item` 形式被接受但素材箱没变，已有 mediaId 也没变 | 直接用 `media_import`（这是高层工具，实测可靠） |

### ⚠️ 条件受限（拒绝是设计如此，不是 bug）

| 命令 | 限制 | 报错原文 |
|---|---|---|
| `fillSlot` | **只能填模板槽**。普通项目调用报错 | `That media is not a template slot.` |
| `mergeClips` | 必须**同源**且**相邻无缝**（不能有间隙或重叠） | `Merged clips must come from the same file.` / `Merged clips must touch, with no gap or overlap.` |
| `consolidateClips` | 需**两个以上不同**片段 | `Select two or more distinct video clips to merge.` |
| `removeTimeline` | 不能删最后一个时间线 | `A project needs at least one timeline.` |

### 🔧 参数未全破解（1 个，不影响主流程）

| 命令 | 已知 | 还缺 |
|---|---|---|
| `clearEffectKey` / `clearEffectKeys` | 应该同 `setEffectKey`：clipId=效果层 clip，entry=索引，key=参数名 | 已验证 `setEffectKey` 生效，`clear` 系列未逐个复测 |

`addCutoutStroke` 已破：`points` 必须是 **`[[x,y], ...]` 数组的数组**（不是 `[{x,y}]` 对象，也不是扁平数字 `[x,y]`）。报错原文是 `expected an array of length 2`。

---

## 三、NewMedia 结构（`fillSlot`/`replaceClipMedia`/`consolidateClips` 的 `item`）

```json
{
  "path": "/绝对/路径/素材.mp4",
  "name": "x",
  "kind": "video",
  "hasAudio": true,
  "duration": 3.5,
  "width": 1080,
  "height": 1920,
  "frameRate": 30.0
}
```

缺 `hasAudio` 会直接报 `missing field \`hasAudio\``。用 `media_probe` 查一个已有素材就能拿到全部真实值。

---

## 四、剪发视频的五个可用配方

### 配方 1：甩发慢动作（快→慢→快）

```python
# 3.5 秒素材，中间 35% 速度，两头 100%
edit_apply(op="setClipSpeedCurve", clipId=cid, curve=[
    {"at": 0.0,  "speed": 1.0},
    {"at": 0.45, "speed": 0.35},
    {"at": 1.0,  "speed": 1.0},
])
```

**已导出验证**：源 3.5s → 成片 5.200s（理论 5.185s，取整到 30fps 帧）。`speed` 字段变成 0.675（等效平均速度），`speedCurve` 完整写进项目。这不是"看着像成功"，是渲染器真的认了。

### 配方 2：定格发丝细节（`freezeFrame` 是假的，用这个）

```python
preview_frame(path=P, time=1.0, output="/tmp/still.png")   # 抽帧，1920×1080
media_import(path=P, file="/tmp/still.png")                 # → mediaId
clip_add(path=P, mediaId=mid, trackId=T, start=4.0)         # 默认 5 秒
```

比 `freezeFrame` 更可控：想停几秒就 `trimClip(edge="end", delta=...)` 调。

### 配方 3：滤镜调色（127 个现成效果）

```python
effects = effects_list(path=P)            # 返回 list，127 项：57 个 filter + 23 个 effect + 其余
effect_layer_add(path=P, effectId="concat.clean", name="clean", start=0, duration=1)
# → 生成 kind="layer" 的 clip，videoEffects:[{id:"concat.clean", params:{}}]
setEffectKey(clipId=那个layer的id, entry=0, key="amount", at=0.0, value=0.5)
```

`concat.clean` 是官方描述里"人像口播/美业最适合"的基础调色（中性、轻微曲线、多一点色彩、压红）。其他可用的：`concat.contrast-pop`、`concat.bronze`、`concat.classic-chrome`、`concat.bleach-bypass`。

### 配方 4：一条素材出横竖两版（矩阵分发）

```python
addTimeline()                                        # 新时间线
setTimelineVideo(timelineId="TL2", video={"width":1080,"height":1920,"rateNum":30,"rateDen":1})
selectTimeline(timelineId="TL2")
# 各时间线独立剪辑，导出时切过去
```

### 配方 5：换素材不丢剪辑

```python
updateMediaPath(mediaId=mid, newPath="D:/新素材.mp4")
```

整条时间线上所有引用这条素材的片段全部指向新文件，入出点、变速、关键帧全保留。

---

## 五、判定标准（以后测新命令照这个来）

```
1. 建全新项目 → 导入 → 铺剪辑 → 记录 project_get 全量 JSON（sort_keys）
2. 发命令，捕获异常
   - missing field / unknown variant → 记下来，补参数重试（最多 8 层）
   - 其他异常 → 判"拒绝"，记录原文
3. 再取 project_get，字符串对比
   - 变了 → 候选"生效"
   - 没变 → 先怀疑 id 写错（陷阱 1），换成真实 id 重试；仍不变才是"空转"
4. 关键命令必须导出成片，用 ffprobe 验时长/帧数
```

**第 3 步和第 4 步缺一不可。** 只做第 3 步，会把 `freezeFrame` 判成"生效"（它确实返回成功）；只做第 4 步，成本太高，不适合批量筛。

---

## 六、这份表怎么维护

以后 Concat 升级，只要跑一遍 `/tmp/opmatrix2.py` 的逻辑（见仓库 `scripts/probe_ops.py`），三分钟出全表，跟这份对比就知道哪些修好了、哪些回归了。

重点盯 `freezeFrame`：它现在是空实现，将来版本可能补上，那时配方 2 就可以简化。
