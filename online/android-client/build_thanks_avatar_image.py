"""Lay out supplied, unmodified TIM avatars with their displayed member names."""
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT = Path(__file__).resolve().parents[1]
DESKTOP = Path('E:/Desktop')
OUTPUT = DESKTOP/'魔女兵器公告素材/感谢名单-测试群成员.png'
MEMBERS = (
    ('琴音', 'QQ图片20261004094922.jpg'),
    ('不死扶苏', 'QQ图片20261004094904.jpg'),
    ('~¿?', 'QQ图片20261004095037.jpg'),
    ('子爷', 'QQ图片20261004094936.jpg'),
    ('歌廷', 'QQ图片20261004095016.jpg'),
    ('萝', 'QQ图片20261004094943.jpg'),
    ('宁静的彼岸', 'QQ图片20261004094950.jpg'),
    ('守林人的意大利炮', 'QQ图片20261004094914.jpg'),
    ('真理的钥匙', 'QQ图片20261004095009.jpg'),
    ('芜烤', 'QQ图片20261004094930.jpg'),
    ('晴空', 'QQ图片20261004095003.jpg'),
    ('薯饼', 'QQ图片20261004094957.jpg'),
)


def build():
    font_path = 'C:/Windows/Fonts/msyh.ttc'
    title = ImageFont.truetype(font_path, 30)
    caption = ImageFont.truetype(font_path, 22)
    small = ImageFont.truetype(font_path, 16)
    canvas = Image.new('RGB', (946, 744), '#172838')
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, 945, 3), fill='#65c6ce')
    draw.text((30, 17), '感谢每一位同行的朋友', font=title, fill='#f2f5ed')
    draw.text((31, 57), '魔女兵器编辑器测试', font=small, fill='#a8c5cf')
    record = []
    for index, (name, filename) in enumerate(MEMBERS):
        source = DESKTOP/filename
        raw = source.read_bytes()
        with Image.open(source) as image:
            assert image.width == image.height
            avatar = image.convert('RGB').resize((156, 156), Image.Resampling.LANCZOS)
        x, y = 22+(index % 4)*230, 94+(index // 4)*218
        draw.rounded_rectangle((x, y, x+211, y+203), radius=8, fill='#23384a', outline='#3c5968')
        canvas.paste(avatar, (x+28, y+12))
        draw.text((x+106, y+178), name, font=caption, fill='#ecf1f3', anchor='mt')
        record.append(dict(name=name, source=str(source), sha256=hashlib.sha256(raw).hexdigest()))
    OUTPUT.parent.mkdir(exist_ok=True)
    canvas.save(OUTPUT, optimize=True)
    assert Image.open(OUTPUT).size == (946, 744)
    report = dict(image=str(OUTPUT), members=record, excludedMembers=['YANG301'],
        nameReference=str(DESKTOP/'QQ截图20261004095107.png'),
        imageSha256=hashlib.sha256(OUTPUT.read_bytes()).hexdigest())
    (PROJECT/'验收/感谢名单头像素材.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(image=str(OUTPUT), members=len(record), dimensions=[946,744]), ensure_ascii=False))
    return OUTPUT


if __name__ == '__main__': build()
