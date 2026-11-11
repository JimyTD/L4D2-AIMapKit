"""Satellite imagery under the review pages and planning views: web map tiles, cached per project.

Provider and attribution come from campaign.json geo.imagery ({"url": ".../{z}/{x}/{y}", "attribution": "..."});
without one, the Esri World Imagery service is used. A fictional project (no geo.origin) has no imagery:
every function returns None and the pages draw without an underlay. Imagery is evidence for people, never
an input to design data.
"""

from __future__ import annotations

import base64
import hashlib
import io
import math
import urllib.request
from functools import lru_cache

from PIL import Image, ImageEnhance

from project import geo_conf, root

ESRI = {"url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "attribution": "Imagery (c) Esri, Maxar, Earthstar Geographics"}


def conf() -> dict | None:
    g = geo_conf()
    if not g.get("origin") or g.get("imagery") is False:
        return None
    return {**ESRI, **g.get("imagery", {})}


def attribution() -> str:
    c = conf()
    return c["attribution"] if c else ""


def _txy(lat, lon, z):
    n = 2 ** z
    return (lon + 180) / 360 * n, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n


@lru_cache(None)
def _tile(url, z, x, y):
    c = root() / "sources" / "geodata" / "tiles" / hashlib.md5(url.encode()).hexdigest()[:8] / f"{z}_{x}_{y}.jpg"
    if not c.exists():
        c.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url.format(z=z, x=x, y=y), headers={"User-Agent": "Mozilla/5.0"})
        c.write_bytes(urllib.request.urlopen(req, timeout=30).read())
    return Image.open(c).convert("RGB")


def crop(minx, miny, maxx, maxy, px_per_m=2.0, max_px=None):
    """North-up crop of a metre box. Returns (image or None, (minx, miny, maxx, maxy))."""
    c = conf()
    ext = (minx, miny, maxx, maxy)
    if not c:
        return None, ext
    from geo import to_latlon
    want = px_per_m
    if max_px:
        want = min(want, max_px / max(maxx - minx, maxy - miny))
    lat0 = to_latlon(0, (miny + maxy) / 2)[0]
    # metres per pixel at zoom z is 156543 * cos(lat) / 2^z; take the first zoom at least as sharp as wanted
    z = max(1, min(21, math.ceil(math.log2(156543.03 * math.cos(math.radians(lat0)) * want))))
    x0, y0 = _txy(*to_latlon(minx, maxy), z)
    x1, y1 = _txy(*to_latlon(maxx, miny), z)
    tx, ty = range(int(x0), int(x1) + 1), range(int(y0), int(y1) + 1)
    mos = Image.new("RGB", (len(tx) * 256, len(ty) * 256))
    for yy in ty:
        for xx in tx:
            mos.paste(_tile(c["url"], z, xx, yy), ((xx - tx[0]) * 256, (yy - ty[0]) * 256))
    img = mos.crop((int((x0 - tx[0]) * 256), int((y0 - ty[0]) * 256), int((x1 - tx[0]) * 256), int((y1 - ty[0]) * 256)))
    img = img.resize((max(1, round((maxx - minx) * want)), max(1, round((maxy - miny) * want))), Image.LANCZOS)
    return img, ext


def data_url(minx, miny, maxx, maxy, px_per_m=2.0, bright=1.0):
    img, _ = crop(minx, miny, maxx, maxy, px_per_m)
    if img is None:
        return None
    if bright != 1.0:
        img = ImageEnhance.Brightness(img).enhance(bright)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def mean_rgb(x, y, r=6.0):
    img, _ = crop(x - r, y - r, x + r, y + r, px_per_m=2.0)
    return None if img is None else img.resize((1, 1)).getpixel((0, 0))


COLOR_RULES = {
    "green": lambda c: c[1] > c[0] and c[1] > c[2],
    "water": lambda c: c[2] >= c[0] and c[2] + c[1] > 2 * c[0],
    "bright": lambda c: sum(c) / 3 > 150,
    "dark": lambda c: sum(c) / 3 < 80,
}


def mirror_check():
    """Pixel test against mirroring and shifts: each landmark in campaign.json geo.landmarks
    ({"name", "at": [x, y], "expect": green|water|bright|dark}) must show its colour on the imagery,
    and the same point mirrored north-south and east-west about the origin must not show it."""
    out = []
    if not conf():
        return out
    for lm in geo_conf().get("landmarks", []):
        rule = COLOR_RULES[lm["expect"]]
        x, y = lm["at"]
        here = mean_rgb(x, y)
        out.append((f"影像配准：{lm['name']} 处是 {lm['expect']}", rule(here), f"RGB {here}"))
        for tag, (mx, my) in (("南北镜像", (x, -y)), ("东西镜像", (-x, y))):
            if math.dist((mx, my), (x, y)) < 30:
                continue
            c = mean_rgb(mx, my)
            out.append((f"影像配准：{lm['name']} 的{tag}位置不是 {lm['expect']}", not rule(c), f"RGB {c}"))
    return out

