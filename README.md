# 剪映自动化剪辑技能

WorkBuddy 剪映/CapCut 自动化剪辑技能。

## 已支持

- ✅ 视频拼接、分段卡点、变速
- ✅ 关键帧动画（缩放/透明度/位移）
- ✅ 文字叠加（多轨道、字体、颜色、动画）
- ✅ 花字金边、贴纸（剪刀/省略号/星光）
- ✅ 画中画 PIP、3D环绕运镜
- ✅ 曲线变速（100%→60%→100%）
- ✅ 结尾黑场卡片 + 自动加密部署到剪映 10.x

## 一键安装

```bash
git clone https://github.com/dashuai6-6/jianying-automation.git
cd jianying-automation
setup.bat
```

`setup.bat` 会自动安装 `pyJianYingDraft` + `ffmpeg` + `jy-draftc`。

## 使用

在 WorkBuddy 中说"帮我剪辑视频"即可触发。

## 项目结构

```
jianying-automation/
├── SKILL.md                     # 技能定义 + 工作流
├── setup.bat                    # 一键安装脚本
├── .gitignore
├── references/
│   └── enum_guide.md            # 枚举值 + 坐标系统 + 资源字典
└── scripts/
    └── vlog_template.py         # 可复用模板（改顶部路径换素材）
```
