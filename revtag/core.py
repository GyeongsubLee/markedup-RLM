"""Core logic: find red revision clouds in ISO PDFs and stamp XX_YY_ZZ revision tags.

The tag graphic (parallelogram + leader + text) is not drawn by this program.
It is copied from the annotations of a SAMPLE PDF, so whatever the drafter
drew in Bluebeam / Acrobat is reproduced exactly; only the text is replaced
and the copy is moved so that the leader tip touches the cloud's top-left corner.
"""

from __future__ import annotations

import csv
import math
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import pikepdf
from pikepdf import Array, Dictionary, Name, String

TAG_RE = re.compile(r"[A-Za-z0-9]+_[A-Za-z0-9]+_[A-Za-z0-9]+")
SHAPE_SUBTYPES = {"/Polygon", "/PolyLine", "/Square", "/Circle", "/Ink"}
IGNORED_SUBTYPES = {"/Popup", "/Link", "/Widget"}
MARK_PREFIX = "REVTAG-"
SKIP_KEYS = {"/P", "/Popup", "/Parent", "/NM", "/StructParent"}

Log = Callable[[str], None]


# --------------------------------------------------------------------------- #
# Geometry: raw PDF space  <->  "visual" space (as seen on screen, y down,
# origin at the top-left of the CropBox, page /Rotate applied).
# --------------------------------------------------------------------------- #
def _inherited(obj, key):
    while obj is not None:
        if key in obj:
            return obj[key]
        obj = obj.get("/Parent")
    return None


class PageGeom:
    def __init__(self, page_obj):
        box = _inherited(page_obj, "/CropBox") or _inherited(page_obj, "/MediaBox")
        x0, y0, x1, y1 = [float(v) for v in box]
        self.x0, self.y0 = min(x0, x1), min(y0, y1)
        self.x1, self.y1 = max(x0, x1), max(y0, y1)
        rot = _inherited(page_obj, "/Rotate")
        self.rotate = int(rot) % 360 if rot is not None else 0

    def to_visual(self, x, y):
        r = self.rotate
        if r == 0:
            return x - self.x0, self.y1 - y
        if r == 90:
            return y - self.y0, x - self.x0
        if r == 180:
            return self.x1 - x, y - self.y0
        return self.y1 - y, self.x1 - x  # 270

    def to_raw(self, vx, vy):
        r = self.rotate
        if r == 0:
            return vx + self.x0, self.y1 - vy
        if r == 90:
            return vy + self.x0, vx + self.y0
        if r == 180:
            return self.x1 - vx, vy + self.y0
        return self.x1 - vy, self.y1 - vx  # 270

    def visual_bbox(self, rect):
        x0, y0, x1, y1 = rect
        pts = [self.to_visual(x, y) for x in (x0, x1) for y in (y0, y1)]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)


def _rect(annot):
    r = [float(v) for v in annot.get("/Rect", [0, 0, 0, 0])]
    return min(r[0], r[2]), min(r[1], r[3]), max(r[0], r[2]), max(r[1], r[3])


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, pikepdf.Stream):
        try:
            return v.read_bytes().decode("utf-8", "replace")
        except Exception:
            return ""
    try:
        return str(v)
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# Cloud detection
# --------------------------------------------------------------------------- #
def is_red(annot, tol: float = 0.35) -> bool:
    c = annot.get("/C")
    if c is None:
        return False
    c = [float(v) for v in c]
    if len(c) == 3:
        r, g, b = c
    elif len(c) == 4:  # CMYK
        cc, m, y, k = c
        r, g, b = (1 - cc) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)
    else:
        return False
    return r >= 1 - tol and g <= tol and b <= tol


def is_cloudy(annot) -> bool:
    be = annot.get("/BE")
    if be is not None and be.get("/S") == Name.C:
        return True
    it = str(annot.get("/IT", ""))
    if "Cloud" in it:
        return True
    return "cloud" in _text(annot.get("/Subj")).lower()


def is_our_tag(annot) -> bool:
    return _text(annot.get("/NM")).startswith(MARK_PREFIX)


@dataclass
class Cloud:
    page_index: int
    raw_rect: tuple            # raw PDF coords x0,y0,x1,y1
    vis_bbox: tuple            # visual coords x0,y0,x1,y1 (y down)
    method: str                # "annot" | "raster"
    order_key: int = 0
    tip_vis: tuple | None = None  # point ON the cloud outline nearest its top-left corner (visual)

    def tip(self):
        return self.tip_vis or (self.vis_bbox[0], self.vis_bbox[1])


def find_annotation_clouds(page_obj, geom: PageGeom, page_index: int,
                           require_cloudy: bool = False, any_color: bool = False) -> list[Cloud]:
    clouds = []
    for i, a in enumerate(page_obj.get("/Annots", [])):
        try:
            if str(a.get("/Subtype")) not in SHAPE_SUBTYPES or is_our_tag(a):
                continue
            if not any_color and not is_red(a):
                continue
            if require_cloudy and not is_cloudy(a):
                continue
            r = _rect(a)
            vb = geom.visual_bbox(r)
            pts = []
            if "/Vertices" in a:
                v = [float(x) for x in a["/Vertices"]]
                pts = list(zip(v[0::2], v[1::2]))
            elif "/InkList" in a:
                for st in a["/InkList"]:
                    v = [float(x) for x in st]
                    pts += list(zip(v[0::2], v[1::2]))
            tip = None
            if pts:
                vis = [geom.to_visual(x, y) for x, y in pts]
                tip = min(vis, key=lambda p: math.hypot(p[0] - vb[0], p[1] - vb[1]))
            clouds.append(Cloud(page_index, r, vb, "annot", i, tip))
        except Exception:
            continue
    return clouds


@dataclass
class RasterParams:
    zoom: float = 2.0            # render scale (2.0 = 144 dpi)
    red_min: int = 170           # R >= red_min
    other_max: int = 110         # G, B <= other_max
    join_pt: float = 1.5         # close small gaps in the cloud outline (pt)
    min_size_pt: float = 10.0    # ignore blobs smaller than this (pt)
    min_hole_ratio: float = 0.15 # enclosed area / bbox area: outlines enclose space, text doesn't


def red_mask(fitz_page, rp: RasterParams):
    import fitz
    import numpy as np

    pix = fitz_page.get_pixmap(matrix=fitz.Matrix(rp.zoom, rp.zoom), alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    r, g, b = (img[..., i].astype(np.int16) for i in range(3))
    return (r >= rp.red_min) & (g <= rp.other_max) & (b <= rp.other_max)


def find_raster_clouds(fitz_page, geom: PageGeom, page_index: int,
                       rp: RasterParams | None = None) -> list[Cloud]:
    """Find red clouds by colour: render the page, keep red pixels, and treat each
    closed red outline (a red blob that encloses an area) as one cloud."""
    import numpy as np
    from scipy import ndimage as ndi

    rp = rp or RasterParams()
    mask = red_mask(fitz_page, rp)
    if not mask.any():
        return []
    k = max(1, int(round(rp.join_pt * rp.zoom)))
    closed = ndi.binary_closing(mask, structure=np.ones((3, 3), bool), iterations=k)
    closed |= mask
    labels, n = ndi.label(closed, structure=np.ones((3, 3), bool))
    clouds = []
    for i, sl in enumerate(ndi.find_objects(labels), start=1):
        if sl is None:
            continue
        blob = labels[sl] == i
        h, w = blob.shape
        min_px = rp.min_size_pt * rp.zoom
        if max(h, w) < min_px or min(h, w) < min_px / 3:
            continue
        holes = ndi.binary_fill_holes(blob) & ~blob
        if holes.sum() < rp.min_hole_ratio * h * w:
            continue  # not a closed outline (red text, a lone line, a leader...)
        ys, xs = sl
        red = np.argwhere(mask[sl] & blob)          # (row, col) of the real outline pixels
        if len(red) == 0:
            continue
        j = int(np.argmin(red[:, 0].astype(float) ** 2 + red[:, 1].astype(float) ** 2))
        tip = (float(xs.start + red[j, 1] + 0.5) / rp.zoom, float(ys.start + red[j, 0] + 0.5) / rp.zoom)
        vx0, vy0 = xs.start / rp.zoom, ys.start / rp.zoom
        vx1, vy1 = xs.stop / rp.zoom, ys.stop / rp.zoom
        p0, p1 = geom.to_raw(vx0, vy0), geom.to_raw(vx1, vy1)
        raw = (min(p0[0], p1[0]), min(p0[1], p1[1]), max(p0[0], p1[0]), max(p0[1], p1[1]))
        clouds.append(Cloud(page_index, raw, (vx0, vy0, vx1, vy1), "raster", len(clouds), tip))
    return clouds


def sort_clouds(clouds: list[Cloud], order: str, row_tol: float = 40.0) -> list[Cloud]:
    """order: 'annot' (drawing order), 'rows' (top->bottom, left->right), 'cols' (left->right, top->bottom)."""
    if order == "rows":
        cl = sorted(clouds, key=lambda c: (c.page_index, c.vis_bbox[1]))
        rows, cur, ref = [], [], None
        for c in cl:
            if cur and (c.page_index != cur[0].page_index or c.vis_bbox[1] - ref > row_tol):
                rows.append(cur)
                cur = []
            if not cur:
                ref = c.vis_bbox[1]
            cur.append(c)
        if cur:
            rows.append(cur)
        return [c for row in rows for c in sorted(row, key=lambda c: c.vis_bbox[0])]
    if order == "cols":
        return sorted(clouds, key=lambda c: (c.page_index, c.vis_bbox[0], c.vis_bbox[1]))
    return sorted(clouds, key=lambda c: (c.page_index, c.order_key))


# --------------------------------------------------------------------------- #
# Annotation cloning
# --------------------------------------------------------------------------- #
class _Cloner:
    """Clones a group of annotations (with their appearance streams) into `pdf`,
    optionally replacing text `old` -> `new` in Contents/RC and appearance streams."""

    def __init__(self, pdf, old: str | None = None, new: str | None = None):
        self.pdf = pdf
        self.old, self.new = old, new
        self.memo = {}
        self.ap_replaced = 0

    def _sub(self, s: str) -> str:
        return s.replace(self.old, self.new) if self.old and self.new is not None else s

    def _sub_bytes(self, data: bytes) -> bytes:
        if not self.old or self.new is None:
            return data
        n = 0
        ob, nb = self.old.encode("latin-1"), self.new.encode("latin-1")
        n += data.count(ob)
        data = data.replace(ob, nb)
        for oh, nh in ((ob.hex().upper(), nb.hex().upper()), (ob.hex(), nb.hex())):
            oh_b, nh_b = oh.encode(), nh.encode()
            n += data.count(oh_b)
            data = data.replace(oh_b, nh_b)
        # UTF-16BE hex (some CID-keyed fonts with Identity/Unicode CMaps)
        o16, n16 = self.old.encode("utf-16-be").hex().upper().encode(), self.new.encode("utf-16-be").hex().upper().encode()
        n += data.count(o16)
        data = data.replace(o16, n16)
        self.ap_replaced += n
        return data

    def clone_group(self, annots: list) -> list:
        news = []
        for a in annots:
            na = self.pdf.make_indirect(Dictionary())
            self.memo[a.objgen] = na
            news.append(na)
        for a, na in zip(annots, news):
            for k, v in a.items():
                if k in SKIP_KEYS:
                    continue
                if k == "/IRT":
                    if v.is_indirect and v.objgen in self.memo:
                        na[k] = self.memo[v.objgen]
                    continue
                if k == "/AP":
                    na[k] = self._clone_ap(v)
                elif k == "/Contents":
                    na[k] = String(self._sub(_text(v)))
                elif k == "/RC":
                    na[k] = String(self._sub(_text(v)))
                else:
                    na[k] = self._copy(v)
        return news

    def _copy(self, v):
        # direct containers are re-created so copies never share mutable arrays
        if isinstance(v, pikepdf.Array) and not v.is_indirect:
            return Array([self._copy(x) for x in v])
        if isinstance(v, pikepdf.Dictionary) and not v.is_indirect:
            return Dictionary({k: self._copy(x) for k, x in v.items()})
        return v

    def _clone_ap(self, ap):
        out = Dictionary()
        for k, v in ap.items():
            if isinstance(v, pikepdf.Stream):
                out[k] = self._clone_form(v)
            elif isinstance(v, pikepdf.Dictionary):
                out[k] = Dictionary({s: (self._clone_form(x) if isinstance(x, pikepdf.Stream) else x)
                                     for s, x in v.items()})
        return out

    def _clone_form(self, s):
        if s.is_indirect and s.objgen in self.memo:
            return self.memo[s.objgen]
        try:
            data = self._sub_bytes(s.read_bytes())
            ns = pikepdf.Stream(self.pdf, data)
            skip = {"/Length", "/Filter", "/DecodeParms"}
        except Exception:
            ns = pikepdf.Stream(self.pdf, b"")
            ns.write(s.read_raw_bytes(), filter=s.get("/Filter"), decode_parms=s.get("/DecodeParms"))
            skip = {"/Length", "/Filter", "/DecodeParms"}
        if s.is_indirect:
            self.memo[s.objgen] = ns
        for k, v in s.stream_dict.items():
            if k in skip:
                continue
            ns[k] = self._clone_resources(v) if k == "/Resources" else self._copy(v)
        return ns

    def _clone_resources(self, res):
        out = Dictionary({k: v for k, v in res.items()})
        xo = res.get("/XObject")
        if xo is not None:
            out["/XObject"] = Dictionary({
                n: (self._clone_form(x) if isinstance(x, pikepdf.Stream) and x.get("/Subtype") == Name.Form else x)
                for n, x in xo.items()})
        return out


def place_annot(a, anchor, target, angle_deg: int):
    """Rotate annotation `a` by angle_deg (counter-clockwise, raw PDF space) about
    `anchor`, then move `anchor` onto `target`."""
    t = math.radians(angle_deg)
    cs, sn = round(math.cos(t), 10), round(math.sin(t), 10)
    ax, ay = anchor
    tx, ty = target

    def f(x, y):
        x, y = x - ax, y - ay
        return cs * x - sn * y + tx, sn * x + cs * y + ty

    def map_pairs(arr):
        v = [float(x) for x in arr]
        out = []
        for x, y in zip(v[0::2], v[1::2]):
            out += f(x, y)
        return Array(out)

    for key in ("/Vertices", "/L", "/CL", "/QuadPoints"):
        if key in a:
            a[key] = map_pairs(a[key])
    if "/InkList" in a:
        a["/InkList"] = Array([map_pairs(s) for s in a["/InkList"]])
    x0, y0, x1, y1 = _rect(a)
    corners = [f(x, y) for x in (x0, x1) for y in (y0, y1)]
    a["/Rect"] = Array([min(p[0] for p in corners), min(p[1] for p in corners),
                        max(p[0] for p in corners), max(p[1] for p in corners)])
    if angle_deg % 360 and "/AP" in a:
        # appearance streams: append the rotation to each form's /Matrix
        # (the viewer then fits the rotated BBox into the rotated /Rect)
        for v in a["/AP"].values():
            forms = [v] if isinstance(v, pikepdf.Stream) else \
                [x for x in v.values() if isinstance(x, pikepdf.Stream)]
            for fm in forms:
                m = [float(x) for x in fm.get("/Matrix", [1, 0, 0, 1, 0, 0])]
                a_, b_, c_, d_, e_, f_ = m
                fm["/Matrix"] = Array([a_ * cs - b_ * sn, a_ * sn + b_ * cs,
                                       c_ * cs - d_ * sn, c_ * sn + d_ * cs,
                                       e_ * cs - f_ * sn, e_ * sn + f_ * cs])


def translate_annot(a, dx: float, dy: float):
    def shift_pairs(arr):
        return Array([float(v) + (dx if i % 2 == 0 else dy) for i, v in enumerate(arr)])

    for key in ("/Rect", "/Vertices", "/L", "/CL", "/QuadPoints"):
        if key in a:
            a[key] = shift_pairs(a[key])
    if "/InkList" in a:
        a["/InkList"] = Array([shift_pairs(s) for s in a["/InkList"]])


# --------------------------------------------------------------------------- #
# Template (from SAMPLE pdf)
# --------------------------------------------------------------------------- #
@dataclass
class Template:
    pdf: pikepdf.Pdf
    annots: list                  # cleaned, indirect annots inside self.pdf
    text: str                     # placeholder text to be replaced (e.g. "01_01_01")
    anchor: tuple                 # raw point (leader tip) that goes to the cloud corner
    rotate: int
    text_annot_index: int

    def master_for(self, target: pikepdf.Pdf) -> list:
        return [target.copy_foreign(a) for a in self.annots]


def load_template(sample_path, page_number: int | None = None, log: Log = print) -> Template:
    pdf = pikepdf.open(str(sample_path))
    pages = range(len(pdf.pages)) if page_number is None else [page_number - 1]
    for pi in pages:
        page_obj = pdf.pages[pi].obj
        annots = [a for a in page_obj.get("/Annots", []) if str(a.get("/Subtype")) not in IGNORED_SUBTYPES]
        if not annots:
            continue
        text_a = None
        for pred in (
            lambda a: a.get("/Subtype") == Name.FreeText and TAG_RE.search(_text(a.get("/Contents"))),
            lambda a: a.get("/Subtype") == Name.FreeText and _text(a.get("/Contents")).strip(),
            lambda a: TAG_RE.search(_text(a.get("/Contents"))),
        ):
            text_a = next((a for a in annots if pred(a)), None)
            if text_a is not None:
                break
        if text_a is None:
            continue

        geom = PageGeom(page_obj)
        contents = _text(text_a.get("/Contents")).strip()
        m = TAG_RE.search(contents)
        placeholder = m.group(0) if m else contents

        # grow a cluster of touching annotations around the text (excluding clouds)
        group = [text_a]
        bbox = list(_rect(text_a))
        margin = 3.0
        changed = True
        while changed:
            changed = False
            for a in annots:
                if any(a.objgen == g.objgen for g in group) or is_cloudy(a):
                    continue
                r = _rect(a)
                linked = a.get("/IRT") is not None and any(a["/IRT"].objgen == g.objgen for g in group)
                touch = not (r[0] > bbox[2] + margin or r[2] < bbox[0] - margin or
                             r[1] > bbox[3] + margin or r[3] < bbox[1] - margin)
                if touch or linked:
                    group.append(a)
                    bbox = [min(bbox[0], r[0]), min(bbox[1], r[1]), max(bbox[2], r[2]), max(bbox[3], r[3])]
                    changed = True
        group.sort(key=lambda a: [x.objgen for x in annots].index(a.objgen))

        anchor = _find_anchor(group, text_a, geom, bbox)
        cleaned = _Cloner(pdf).clone_group(group)
        idx = [g.objgen for g in group].index(text_a.objgen)
        kinds = ", ".join(str(a.get("/Subtype"))[1:] for a in group)
        log(f"[sample] page {pi + 1}: tag template = {len(group)} annotation(s) ({kinds}), "
            f"text '{placeholder}', leader tip at ({anchor[0]:.1f}, {anchor[1]:.1f})")
        return Template(pdf, cleaned, placeholder, anchor, geom.rotate, idx)
    raise ValueError("SAMPLE PDF에서 태그 주석(텍스트가 있는 FreeText 등)을 찾지 못했습니다.")


def _find_anchor(group, text_a, geom: PageGeom, bbox) -> tuple:
    tr = _rect(text_a)
    cx, cy = (tr[0] + tr[2]) / 2, (tr[1] + tr[3]) / 2
    cands = []
    for a in group:
        st = a.get("/Subtype")
        if st == Name.Line and "/L" in a:
            l = [float(v) for v in a["/L"]]
            cands += [(l[0], l[1]), (l[2], l[3])]
        if st == Name.FreeText and "/CL" in a and a.get("/IT") == Name.FreeTextCallout:
            cl = [float(v) for v in a["/CL"]]
            cands.append((cl[0], cl[1]))
        if st == Name.PolyLine and "/Vertices" in a:
            v = [float(x) for x in a["/Vertices"]]
            cands += [(v[0], v[1]), (v[-2], v[-1])]
        if st == Name.Ink and "/InkList" in a:
            for s in a["/InkList"]:
                v = [float(x) for x in s]
                cands += [(v[0], v[1]), (v[-2], v[-1])]
    if cands:
        return max(cands, key=lambda p: math.hypot(p[0] - cx, p[1] - cy))
    # no leader: use the visual bottom-right corner of the whole tag
    vb = geom.visual_bbox(bbox)
    return geom.to_raw(vb[2], vb[3])


# --------------------------------------------------------------------------- #
# Excel
# --------------------------------------------------------------------------- #
def _norm(s: str) -> str:
    return re.sub(r"[\s_\-.]+", "", str(s)).upper()


def load_iso_list(xlsx_path) -> dict[str, str]:
    import openpyxl

    wb = openpyxl.load_workbook(str(xlsx_path), data_only=True, read_only=True)
    ws = wb.active
    out = {}
    for row in ws.iter_rows(values_only=True):
        if not row or row[0] is None or len(row) < 2 or row[1] is None:
            continue
        iso, rev = str(row[0]).strip(), str(row[1]).strip()
        if iso.upper() == "ISO" or rev.upper() == "XX_YY":
            continue
        out[iso] = rev
    wb.close()
    return out


def match_iso(pdf_path: Path, iso_map: dict[str, str], page_text: Callable[[], str] | None = None):
    stem = _norm(pdf_path.stem)
    hits = [iso for iso in iso_map if _norm(iso) and _norm(iso) in stem]
    if not hits and page_text is not None:
        txt = _norm(page_text())
        hits = [iso for iso in iso_map if _norm(iso) and _norm(iso) in txt]
    if not hits:
        return None, None
    iso = max(hits, key=lambda s: len(_norm(s)))
    return iso, iso_map[iso]


# --------------------------------------------------------------------------- #
# Main processing
# --------------------------------------------------------------------------- #
@dataclass
class Options:
    order: str = "rows"             # rows | cols | annot
    detect: str = "raster"          # raster (red colour) | annot (PDF annotations) | auto
    require_cloudy: bool = False    # only annotations with cloudy border
    any_color: bool = False         # accept non-red shape annotations
    start: int = 1
    digits: int = 2
    remove_existing: bool = True    # remove tags placed by a previous run
    offset: tuple = (0.0, 0.0)      # extra visual offset (pt) of the tag, +x right, +y down
    raster: RasterParams = field(default_factory=RasterParams)


@dataclass
class PlacedTag:
    file: str
    iso: str
    page: int
    tag: str
    method: str
    cloud_bbox: tuple


def process_pdf(src: Path, dst: Path, template: Template, iso_map: dict[str, str],
                opts: Options, log: Log = print) -> list[PlacedTag]:
    import fitz

    fdoc = fitz.open(str(src))
    iso, xxyy = match_iso(src, iso_map, lambda: fdoc[0].get_text() if len(fdoc) else "")
    if iso is None:
        log(f"[skip] {src.name}: 엑셀 리스트에 해당 ISO 번호가 없습니다.")
        fdoc.close()
        return []

    pdf = pikepdf.open(str(src))
    placed: list[PlacedTag] = []
    regen: dict[str, str] = {}
    counter = opts.start
    master = None

    for pi, page in enumerate(pdf.pages):
        page_obj = page.obj
        geom = PageGeom(page_obj)
        if opts.remove_existing and "/Annots" in page_obj:
            keep = [a for a in page_obj.Annots if not is_our_tag(a)]
            if len(keep) != len(page_obj.Annots):
                page_obj.Annots = Array(keep)

        clouds = []
        if opts.detect in ("annot", "auto"):
            clouds = find_annotation_clouds(page_obj, geom, pi, opts.require_cloudy, opts.any_color)
        if opts.detect == "raster" or (opts.detect == "auto" and not clouds):
            fpage = fdoc[pi]
            for an in list(fpage.annots() or []):  # tags from an earlier run must not count as clouds
                if an.info.get("id", "").startswith(MARK_PREFIX):
                    fpage.delete_annot(an)
            clouds = find_raster_clouds(fpage, geom, pi, opts.raster)
            log(f"  page {pi + 1}: 빨간색 분석으로 cloud {len(clouds)}개 검출")
        if not clouds:
            continue
        if geom.rotate != template.rotate:
            log(f"  page {pi + 1}: 페이지 회전 {geom.rotate}° (SAMPLE {template.rotate}°) → 태그를 회전해서 배치")

        if "/Annots" not in page_obj:
            page_obj.Annots = Array()
        if master is None:
            master = template.master_for(pdf)

        for c in sort_clouds(clouds, opts.order):
            tag = f"{xxyy}_{counter:0{opts.digits}d}"
            counter += 1
            cl = _Cloner(pdf, template.text, tag)
            news = cl.clone_group(master)
            # target point: on the cloud outline, nearest its visual top-left corner
            vx, vy = c.tip()
            vx, vy = vx + opts.offset[0], vy + opts.offset[1]
            target = geom.to_raw(vx, vy)
            angle = (geom.rotate - template.rotate) % 360
            group_id = uuid.uuid4().hex[:12]
            for k, na in enumerate(news):
                place_annot(na, template.anchor, target, angle)
                nm = f"{MARK_PREFIX}{group_id}-{k}"
                na["/NM"] = String(nm)
                na["/P"] = page_obj
                page_obj.Annots.append(na)
            text_annot = news[template.text_annot_index]
            if "/AP" in text_annot and cl.ap_replaced == 0:
                regen[_text(text_annot["/NM"])] = tag
            placed.append(PlacedTag(src.name, iso, pi + 1, tag, c.method,
                                    tuple(round(v, 1) for v in c.vis_bbox)))

    dst.parent.mkdir(parents=True, exist_ok=True)
    pdf.save(str(dst))
    pdf.close()
    fdoc.close()

    if regen:
        _regenerate_appearances(dst, regen)

    if placed:
        log(f"[ok] {src.name}: ISO {iso} → {len(placed)}개 태그 ({placed[0].tag} ~ {placed[-1].tag})")
    else:
        log(f"[ok] {src.name}: ISO {iso} → 빨간 cloud 없음 (태그 0개)")
    return placed


def _regenerate_appearances(path: Path, regen: dict[str, str]):
    """Text could not be patched inside the copied appearance stream (e.g. kerned TJ
    arrays); let PyMuPDF rebuild the FreeText appearance from its /DA instead."""
    import fitz

    doc = fitz.open(str(path))
    for page in doc:
        for annot in page.annots() or []:
            nm = annot.info.get("id", "")
            if nm in regen:
                annot.set_info(content=regen[nm])
                annot.update()
    tmp = path.with_suffix(".tmp.pdf")
    doc.save(str(tmp), garbage=1, deflate=True)
    doc.close()
    tmp.replace(path)


def collect_pdfs(inputs: Iterable[str]) -> list[Path]:
    out = []
    for s in inputs:
        p = Path(s)
        if p.is_dir():
            out += sorted(x for x in p.rglob("*") if x.suffix.lower() == ".pdf")
        elif p.suffix.lower() == ".pdf":
            out.append(p)
    return out


def run(sample: str, excel: str, inputs: Iterable[str], out_dir: str,
        opts: Options | None = None, sample_page: int | None = None, log: Log = print) -> list[PlacedTag]:
    opts = opts or Options()
    template = load_template(sample, sample_page, log)
    iso_map = load_iso_list(excel)
    log(f"[excel] ISO {len(iso_map)}건 로드")
    out = Path(out_dir)
    all_placed: list[PlacedTag] = []
    sample_resolved = Path(sample).resolve()
    for src in collect_pdfs(inputs):
        if src.resolve() == sample_resolved or out.resolve() in src.resolve().parents:
            continue
        try:
            all_placed += process_pdf(src, out / src.name, template, iso_map, opts, log)
        except Exception as e:  # keep going with the other drawings
            log(f"[error] {src.name}: {e}")
    if all_placed:
        report = out / "revtag_report.csv"
        with open(report, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["file", "iso", "page", "tag", "method", "cloud_bbox(x0,y0,x1,y1)"])
            for p in all_placed:
                w.writerow([p.file, p.iso, p.page, p.tag, p.method, p.cloud_bbox])
        log(f"[report] {report}")
    log(f"완료: 총 {len(all_placed)}개 태그")
    return all_placed
