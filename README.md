# Concat 命令实测库

把 [Concat](https://github.com/jub0t/Concat) 0.2.8 的 `edit_apply` **50 个命令**逐个跑了一遍，记下哪些真能用、哪些是空壳、参数到底要怎么写。

不是抄文档——是发命令、读返回值、对比项目状态、导出成片验时长，一步步试出来的。

---

## 先说结论

| 分类 | 数量 | 说明 |
|---|---|---|
| ✅ 真生效 | 42 | 改了项目状态，关键命令导出验证过 |
| ❌ 假命令 | 3 | 返回成功，什么都没做（`freezeFrame` 最坑） |
| ⚠️ 条件受限 | 4 | 拒绝是设计如此，不是 bug |
| 🔧 参数未全破解 | 1 | `clearEffectKey` 系列 |

完整表在 **[Concat命令实测表.md](Concat命令实测表.md)**。

## 三个必踩的坑

**1. `clipId` 写错不报错。** 我第一轮把 id 写死成 `c2`，24 个命令全被判成"空转"；换成真实 id，19 个立刻生效。

**2. 字段名写错不报错。** `setClipSpeedCurve` 只有 `curve` 是对的，`points`/`keyframes`/`keys`/`stops` 全部被 serde 静默吞掉。

**3. 只有三种报错是可信的**：`missing field`、`unknown variant`、`expected struct / an array of length N`。其余"成功"都要自己验。

## 最值钱的两条

### 变速曲线真的能出片

```python
edit_apply(op="setClipSpeedCurve", clipId=cid, curve=[
    {"at": 0.0,  "speed": 1.0},
    {"at": 0.45, "speed": 0.35},   # 中间慢下来
    {"at": 1.0,  "speed": 1.0},
])
```

源 3.5s → 成片 **5.200s**（理论 5.185，取整到 30fps）。不是返回值好看，是 `ffprobe` 量出来的。

### `freezeFrame` 是假的，定格要用抽帧

```python
preview_frame(path=P, time=1.0, output="/tmp/still.png")   # 1920×1080 PNG
media_import(path=P, file="/tmp/still.png")
clip_add(path=P, mediaId=mid, trackId=T, start=4.0)        # 默认停 5 秒
```

`freezeFrame` 传 clipId + time 后项目一个字节都没变，三个时间点、四种时长字段名全试过。

## 装

**Linux（x86_64 / aarch64）**

```bash
bash scripts/install_concat.sh
```

一条命令做完四件事：下载官方 deb（147MB）→ 校验 SHA256 → 装依赖 → 冒烟测试（建项目、导出 1 秒、`ffprobe` 对时长）。

先不动系统、只看环境行不行：

```bash
bash scripts/install_concat.sh --check
```

国内下载慢（实测能到 14KB/s）就换镜像：

```bash
CONCAT_MIRROR=https://ghfast.top/ bash scripts/install_concat.sh
```

**Windows / macOS**

同一 release 页有现成的 `.exe` / `.msi` / `.dmg`，直接装：

https://github.com/jub0t/Concat/releases/latest

但下面的 MCP headless 通篇只在 **Linux** 上验证过，Windows 版能不能 `concat --mcp headless` 没测。

## 用法

需要先装 Concat（`concat --mcp headless` 可跑即可）：

```bash
# 跑一遍全量判定，输出对照表
python3 scripts/probe_ops.py \
    --src /path/素材1.mp4 \
    --src2 /path/素材2.mp4

# 输出 markdown 表，方便贴进文档
python3 scripts/probe_ops.py --src a.mp4 --src2 b.mp4 --md
```

`scripts/concat_client.py` 是 60 行的 MCP stdio 客户端，只用标准库：

```python
from concat_client import Concat
c = Concat()
c.call("project_create", {"location": "/root", "name": "p", "width": 1080, "height": 1920})
```

## Concat 升级后怎么办

跑一遍 `probe_ops.py`，跟 [Concat命令实测表.md](Concat命令实测表.md) 对比。三分钟出结果，哪些修好了、哪些回归了，一目了然。

重点盯 `freezeFrame`：现在它是空实现，将来补上了，抽帧那套就可以简化。

## 其他好用的高层工具（不是 `edit_apply` 命令，但更省事）

| 工具 | 用途 |
|---|---|
| `project_get` | **拿项目完整状态**，验证命令是否生效的唯一可靠办法 |
| `preview_frame` | 抽任意时刻的合成帧，定格/封面的来源 |
| `export_start` / `export_wait` | 出片。`export_wait` 的参数是 `job`，不是 `jobId` |
| `effects_list` | 127 个效果（57 个 filter + 23 个 effect），含 `concat.clean` 这类人像调色 |
| `effect_layer_add` | 加效果层，参数 `effectId` + `name` + `start` + `duration` |
| `media_probe` | 查素材真实参数，填 `NewMedia` 结构时用得上 |

## 环境

- Concat 0.2.8，Linux x64，无显卡无显示器（`concat --mcp headless`）
- Python 3.10+，只用标准库
- 实测日期 2026-11-05
