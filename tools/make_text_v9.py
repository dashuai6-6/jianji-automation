#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_text_v9.py —— V9 文字层生成器

  1) 开场花字 PNG（超采样 2x，金边立体）
  2) 逐镜字幕条 PNG（白字+深描边+磨砂底条）
  3) 结尾 CTA 面板 PNG

金边算法要点（踩坑记录）：
  - 逐层缩小描边会形成同心圆环、填糊字腔 -> 改用一次性 stroke_width 描边
  - 不要用缩小字重做「顶部高光」，那会再次糊字腔
  - 外发光用大 alpha 的低透明度圆环，从外往内叠加

字体：/root/.fonts/nsc-black.otf (Noto Sans SC Black)
环境变量
  V9_TEXT  输出目录（默认 /root/v9_src/text）
"""
from PIL import Image, ImageDraw, ImageFont
import os

OUT = os.environ.get("V9_TEXT", "/root/v9_src/text")
os.makedirs(OUT, exist_ok=True)

BLACK = "/root/.fonts/nsc-black.otf"
if not os.path.exists(BLACK):
    import glob
    c = glob.glob("/usr/share/fonts/opentype/noto/NotoSans*Black*")
    BLACK = c[0] if c else "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"

REG = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"

S = 2  # 超采样倍数


def font(path, size):
    return ImageFont.truetype(path, size * S)


def gold_text(img, xy, text, fnt, anchor="mm"):
    """金边立体字：外层深棕描边 + 内层亮金主体 + 外发光"""
    d = ImageDraw.Draw(img)
    x, y = xy
    for r in range(16 * S, 3 * S, -S):
        a = int(52 * (1 - (r - 3 * S) / (13 * S)))
        d.text((x, y), text, font=fnt, fill=(255, 190, 70, a), anchor=anchor,
               stroke_width=r, stroke_fill=(255, 190, 70, a))
    d.text((x + 4 * S, y + 5 * S), text, font=fnt, fill=(0, 0, 0, 130), anchor=anchor)
    d.text((x, y), text, font=fnt, fill=(74, 42, 12, 255), anchor=anchor,
           stroke_width=7 * S, stroke_fill=(74, 42, 12, 255))
    d.text((x, y), text, font=fnt, fill=(255, 219, 118, 255), anchor=anchor)
    return img


def white_text(img, xy, text, fnt, anchor="mm", stroke=4):
    d = ImageDraw.Draw(img)
    x, y = xy
    d.text((x + 2 * S, y + 3 * S), text, font=fnt, fill=(0, 0, 0, 160), anchor=anchor)
    d.text((x, y), text, font=fnt, fill=(255, 255, 255, 255), anchor=anchor,
           stroke_width=stroke * S, stroke_fill=(0, 0, 0, 210))
    return img


def save(img, name):
    p = f"{OUT}/{name}.png"
    img.save(p)
    return p


def make_open():
    W, H = 1080 * S, 1920 * S
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    f1 = font(BLACK, 96)
    f2 = font(BLACK, 52)
    f3 = font(REG, 38)

    gold_text(img, (W // 2, 620 * S), "观感专业", f1)
    gold_text(img, (W // 2, 730 * S), "美发沙龙", f1)

    d = ImageDraw.Draw(img)
    bw, bh = 620 * S, 88 * S
    bx, by = (W - bw) // 2, 830 * S
    d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=bh // 2,
                        fill=(196, 138, 32, 235))
    d.rounded_rectangle([bx + 3 * S, by + 3 * S, bx + bw - 3 * S, by + bh - 3 * S],
                        radius=bh // 2, outline=(255, 226, 150, 255), width=2 * S)
    d.text((W // 2, by + bh // 2), "烫 染 专 门 店", font=f2,
           fill=(255, 248, 232, 255), anchor="mm")

    d.text((W // 2, 980 * S), "安吉 · 实景拍摄", font=f3, fill=(240, 235, 225, 230),
           anchor="mm", stroke_width=2 * S, stroke_fill=(0, 0, 0, 160))
    return save(img, "open_flower")


SUBS = [
    "进门第一眼 · 这面墙",
    "设备到位 · 干发速干",
    "洗剪吹一体 · 不折腾",
    "细节控 · 每一缕都照顾",
    "烫染专门店 · 配色拿捏",
    "绿植角落 · 拍照也好看",
    "洗护用品 · 都是自家配的",
    "一镜到底 · 不换场地",
    "椅子稳当 · 久坐不累",
    "地面干净 · 讲究",
]


def make_sub(text, i):
    W, H = 1080 * S, 1920 * S
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = font(BLACK, 54)

    tmp = Image.new("RGBA", (10, 10))
    td = ImageDraw.Draw(tmp)
    bb = td.textbbox((0, 0), text, font=f)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    bw = tw + 96 * S
    bh = th + 52 * S
    by = 1470 * S   # 底部安全区（抖音下边约 250px）
    bx = (W - bw) // 2

    # 底部再压一层暗色渐变确保文字区足够暗
    grad = Image.new("RGBA", (W, 420 * S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for i2 in range(420 * S):
        a = int(120 * (1 - i2 / (420 * S)) ** 1.4)
        gd.line([(0, i2), (W, i2)], fill=(0, 0, 0, a))
    img.alpha_composite(grad, (0, 1440 * S))
    d = ImageDraw.Draw(img)

    # 半透明磨砂底条（加深保证可读）
    d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=bh // 2,
                        fill=(10, 10, 12, 218))
    # 左侧金色竖条
    d.rounded_rectangle([bx + 18 * S, by + 16 * S, bx + 26 * S, by + bh - 16 * S],
                        radius=4 * S, fill=(255, 196, 70, 255))
    d.text((W // 2 + 8 * S, by + bh // 2 - 2 * S), text, font=f,
           fill=(255, 255, 255, 255), anchor="mm",
           stroke_width=3 * S, stroke_fill=(0, 0, 0, 235))
    return save(img, f"sub_{i:02d}")


def make_cta():
    W, H = 1080 * S, 1920 * S
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f1 = font(BLACK, 84)
    f2 = font(REG, 42)

    grad = Image.new("RGBA", (W, 900 * S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for i in range(900 * S):
        a = int(215 * (i / (900 * S)) ** 1.6)
        gd.line([(0, i), (W, i)], fill=(0, 0, 0, a))
    img.alpha_composite(grad, (0, H - 900 * S))
    d = ImageDraw.Draw(img)

    gold_text(img, (W // 2, 1470 * S), "烫染团购已上线", f1)
    d.text((W // 2, 1590 * S), "到店出示团购码  直接享优惠", font=f2,
           fill=(255, 245, 230, 240), anchor="mm",
           stroke_width=2 * S, stroke_fill=(0, 0, 0, 180))

    bw, bh = 520 * S, 108 * S
    bx, by = (W - bw) // 2, 1690 * S
    d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=bh // 2,
                        fill=(214, 152, 40, 250))
    d.rounded_rectangle([bx + 4 * S, by + 4 * S, bx + bw - 4 * S, by + bh - 4 * S],
                        radius=bh // 2, outline=(255, 232, 168, 255), width=3 * S)
    d.text((W // 2, by + bh // 2), "点击左下角团购", font=font(BLACK, 46),
           fill=(255, 250, 240, 255), anchor="mm")
    return save(img, "cta")


if __name__ == "__main__":
    print(make_open())
    for i, t in enumerate(SUBS):
        print(make_sub(t, i))
    print(make_cta())
    print("字体:", BLACK)
