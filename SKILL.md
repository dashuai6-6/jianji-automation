---
name: jianying-automation
description: >
  剪映/CapCut 自动化剪辑技能。通过 pyJianYingDraft 库生成剪映草稿文件，
  支持视频拼接、分段卡点、变速、关键帧动画、文字叠加、转场、滤镜、特效、
  蒙版等操作。适用场景：Vlog剪辑、短视频混剪、批量模板化出片。
  当用户提出"帮我剪辑视频""用剪映自动剪辑""生成剪映草稿""自动化做视频"
  等意图时触发。剪映5~10.x版本均兼容（自动导出仅支持6及以下）。
agent_created: true
---

# 剪映自动化剪辑技能

## 前置条件

执行任何剪辑任务前，先确认环境：

1. **Python 虚拟环境**：检查 `<workspace>/venv/Scripts/python` 是否存在且已安装 `pyJianYingDraft`
2. 若未安装，运行：
   ```
   python -m venv venv/ && venv/Scripts/pip install pyJianYingDraft
   ```
3. **剪映草稿目录**（Windows）：`C:\Users\<用户名>\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft`
4. **素材验证**：所有视频素材路径必须存在，用 ffprobe 验证时长/分辨率/帧率

## 工作流程

### Phase 1：理解需求 → 设计分镜

收到用户的剪辑指令后，不要直接写代码。先：
1. 逐条理清用户要求的每个段落/时间点
2. 用 ffprobe 确认所有素材的时长和分辨率
3. 画出一个分段时间线（可用文字表格）
4. 向用户确认分镜方案后再写代码

### Phase 2：编写脚本

参考模板 `scripts/vlog_template.py`，必须：

- 从 `pyJianYingDraft` 导入所有需要的枚举
- 用 `DraftFolder(path).create_draft(name, w, h, allow_replace=True)` 创建草稿，**先生成到临时目录**（避免剪映锁定文件导致 PermissionError）
- 为每段 `VideoSegment` 精确设置 `source_timerange`（素材截取范围）
- **所有文字使用 `add_text_overlay` 辅助函数**，避免重复代码
- **字号参考**：TextStyle.size 默认8.0，不是像素！标题用12~15，标签用7~8，字幕8~10，绝对不超18
- **段落间不能有时间重叠**（`SegmentOverlap` 是最常见错误）
- 总时长控制在 15~30 秒（短视频黄金时长）

### Phase 2.5：未知功能的攻克

如果用户的指令中包含当前技能**不会的功能**（如曲线变速、贴纸、花字描边、3D运镜等），按以下优先级处理：

1. **先查 pyJianYingDraft 源码**：`inspect.getsource()` 或查看库是否有隐藏 API
2. **WebSearch 搜索**：搜 "pyJianYingDraft 贴纸/曲线变速/花字" 或 "剪映 draft_content.json 贴纸 格式"
3. **逆向真实草稿**：让用户在剪映中手动做一个该效果的草稿 → 用 jy-draftc 解密 → 分析 JSON 结构 → 找到数据规律 → 用代码复现
4. **变通实现**：如果上述都走不通，找近似替代方案（如用透明度关键帧替代曲线变速的氛围感）
5. **攻克后立即更新技能**：把新学到的参数格式/API 写进 `references/enum_guide.md`，脚本模板同步更新

> 原则：不轻易说"不支持"，先搜、先拆、先试。

### Phase 3：运行调试

1. 用 `python -u script.py` 运行（`-u` 确保实时输出）
2. 生成成功后，用 jy-draftc 对 `draft_content.json` 和 `draft_meta_info.json` 加密后复制到剪映草稿目录
3. 常见错误修复：
   - `SegmentOverlap`：缩短或位移文本段落的 duration
   - `ValueError: 传入了过多的参数`：特效参数数量不对，参考 `references/enum_guide.md`
   - `TypeError: unexpected keyword argument`：TextStyle 不接受 outline/shadow 参数，改用花字 resource_id
   - `AttributeError: no attribute`：枚举值名称不对，运行 `check_enums.py` 验证
   - `PermissionError [WinError 32]`：剪映锁定了草稿文件 → 先生成到临时目录再加密复制
   - 剪映提示"草稿损坏"：草稿未加密 → 用 jy-draftc -e 加密后再放入剪映目录
4. 成功标志：看到 `✅ 草稿已加密并部署到剪映目录`

### Phase 4：交付

1. 告知用户草稿名称和位置
2. 列出"用户需要手动做的"（加BGM、音效等）
3. 提供 `edit_vlog.py` 脚本文件，说明如何改素材路径复用
4. **技能自省**：如果本次执行中发现了新知识（新的枚举值、新的踩坑修复、新的 JSON 规律），在交付前更新 `references/enum_guide.md` 和 SKILL.md 本身

## 已知限制

| 限制 | 说明 | 变通方案 |
|------|------|---------|
| 曲线变速 | pyJianYingDraft 不支持非匀速变速 | 用透明度关键帧模拟氛围；或逆向真实草稿的变速 JSON |
| 自动导出 | 剪映7+无法自动导出MP4 | 手动在剪映中导出 |
| 像素擦除 | 不能擦除原视频烧录的文字/水印 | 用裁剪缩放或蒙版遮盖 |
| 文字描边/阴影 | `TextStyle` 无此参数 | 逆向花字 resource_id 的 JSON 结构后实现 |
| 贴纸 | 未探索完整 API | 逆向真实贴纸草稿的 JSON 后实现 |
| 3D运镜 | 未探索 | 逆向或 WebSearch |
| BGM/音效 | 需要本地文件路径 | 用户提供文件，或用 ffmpeg 生成简单音效 |
| 自动卡点 | 需外部音频分析 | 用 librosa/ffmpeg 分析波形找拍点 |

## 脚本复用

生成的 `edit_vlog.py` 是可复用的：修改顶部的 `ASSET_DIR`、`VIDEO_FILES` 和 `BGM_FILE` 即可换素材出片。脚本本身不需要改动。
