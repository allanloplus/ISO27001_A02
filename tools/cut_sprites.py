"""從角色設定圖切出動畫用素材（全身去背 PNG＋表情頭像）。
用法：python3 tools/cut_sprites.py <Allan設定圖> <阿拉蕾設定圖>
"""
import sys, os
import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "chars")

def cutout(img, box, thr=232):
    im = img.crop(box).convert("RGB")
    a = np.asarray(im).astype(int)
    white = (a.min(axis=2) >= thr)
    lab, _ = ndimage.label(white)
    edge = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    bg = np.isin(lab, list(edge))
    bg = ndimage.binary_opening(bg, iterations=1)
    alpha = Image.fromarray(((~bg) * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(0.8))
    fg, n = ndimage.label(~bg)
    if n > 1:  # 只保留最大的人物區塊，去掉相鄰圖的殘片
        sizes = ndimage.sum(np.ones_like(fg), fg, range(1, n + 1))
        keep = fg == (1 + int(np.argmax(sizes)))
        keep = ndimage.binary_fill_holes(keep)
        alpha = Image.fromarray((keep * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(0.8))
    rgba = im.convert("RGBA"); rgba.putalpha(alpha)
    return rgba.crop(rgba.getbbox())

def face(img, box, size=320):
    im = img.crop(box).convert("RGB")
    w, h = im.size; s = min(w, h)
    im = im.crop(((w - s) // 2, 0, (w - s) // 2 + s, s))
    return im.resize((size, size), Image.LANCZOS)

allan, arale = Image.open(sys.argv[1]), Image.open(sys.argv[2])
cutout(allan, (70, 80, 780, 1480)).save(f"{OUT}/allan.png")
cutout(arale, (60, 800, 410, 1475)).save(f"{OUT}/arale.png")
A = ["smile", "laugh", "think", "worry", "wow", "point", "wink", "shock"]
cols = [(770, 1020), (1078, 1330), (1385, 1640), (1645, 1965)]
rows = [(795, 1118), (1138, 1462)]
for i, n in enumerate(A):
    (x0, x1), (y0, y1) = cols[i % 4], rows[i // 4]
    face(allan, (x0, y0, x1, y1)).convert("RGB").save(f"{OUT}/allan_{n}.jpg", quality=90)
R = ["laugh", "think", "wow", "confused", "explain", "cry", "wink", "cheer"]
cols = [(440, 794), (826, 1180), (1212, 1566), (1597, 1951)]
rows = [(810, 1112), (1147, 1449)]
for i, n in enumerate(R):
    (x0, x1), (y0, y1) = cols[i % 4], rows[i // 4]
    face(arale, (x0, y0, x1, y1)).convert("RGB").save(f"{OUT}/arale_{n}.jpg", quality=90)
print("ok")
