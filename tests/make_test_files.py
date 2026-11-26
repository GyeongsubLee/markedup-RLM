"""Build synthetic test inputs: ISO PDFs with red clouds, a SAMPLE tag PDF and the Excel list."""

import math
import sys
from pathlib import Path

import fitz
import openpyxl

RED = (1, 0, 0)
ISO = "GCC-DLM-DDD-12200-07-4302-TKM-ISO-00010"


def cloud_points(x0, y0, x1, y1, arc=8.0):
    """Points of a cloud outline as a list of bumps along the rectangle."""
    pts = []
    for (ax, ay), (bx, by) in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)),
                               ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
        n = max(1, int(math.hypot(bx - ax, by - ay) / arc))
        for i in range(n):
            pts.append(fitz.Point(ax + (bx - ax) * i / n, ay + (by - ay) * i / n))
    return pts


def draw_vector_cloud(page, rect):
    """A flattened cloud: plain red bezier bumps in the page content (no annotation)."""
    sh = page.new_shape()
    pts = cloud_points(*rect)
    cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
    for a, b in zip(pts, pts[1:] + pts[:1]):
        m = fitz.Point((a.x + b.x) / 2, (a.y + b.y) / 2)
        d = fitz.Point(m.x - cx, m.y - cy)
        ln = math.hypot(d.x, d.y) or 1
        bulge = fitz.Point(m.x + d.x / ln * 5, m.y + d.y / ln * 5)
        sh.draw_curve(a, bulge, b)
    sh.finish(color=RED, width=1.2)
    sh.commit()


def base_drawing(page):
    w, h = page.rect.width, page.rect.height
    page.draw_rect(fitz.Rect(20, 20, w - 20, h - 20), color=(0, 0, 0), width=1)
    page.draw_line((100, 400), (500, 250), color=(0, 0, 0), width=2)
    page.draw_line((500, 250), (500, 120), color=(0, 0, 0), width=2)
    for i in range(12):  # BOM table rows
        y = 60 + i * 14
        page.draw_line((700, y), (1150, y), color=(0, 0, 0), width=0.5)
        page.insert_text((705, y + 10), f"{i + 1}  PIPE, BE, SMLS, A333-6, XS   50   PPSL00{i}", fontsize=7)
    page.insert_text((80, 700), ISO, fontsize=10)
    page.insert_text((300, 600), "RED NOTE TEXT", fontsize=12, color=RED)  # must NOT be a cloud


def make_iso(path: Path, rotate=0):
    doc = fitz.open()
    page = doc.new_page(width=1191, height=842)
    base_drawing(page)
    draw_vector_cloud(page, (180, 330, 260, 390))        # drawing area, left
    draw_vector_cloud(page, (430, 200, 560, 300))        # drawing area, middle
    draw_vector_cloud(page, (700, 102, 1150, 116))       # BOM row 4 (thin)
    draw_vector_cloud(page, (700, 130, 1150, 144))       # BOM row 6 (thin, close to previous)
    # one cloud that is a real PDF annotation
    an = page.add_polygon_annot(cloud_points(1000, 400, 1100, 470, 30))
    an.set_colors(stroke=RED)
    an.set_border(width=1.5, clouds=2)
    an.update()
    if rotate:
        page.set_rotation(rotate)
    doc.save(str(path))


def make_sample(path: Path):
    doc = fitz.open()
    page = doc.new_page(width=1191, height=842)
    base_drawing(page)
    # tag: parallelogram + leader with arrow + text; leader tip at (300, 300)
    para = [fitz.Point(205, 268), fitz.Point(265, 268), fitz.Point(257, 282), fitz.Point(197, 282)]
    a = page.add_polygon_annot(para)
    a.set_colors(stroke=RED)
    a.set_border(width=1)
    a.update()
    ln = page.add_line_annot((257, 282), (300, 300))
    ln.set_colors(stroke=RED)
    ln.set_line_ends(fitz.PDF_ANNOT_LE_NONE, fitz.PDF_ANNOT_LE_OPEN_ARROW)
    ln.update()
    ft = page.add_freetext_annot(fitz.Rect(207, 269, 258, 281), "01_01_01", fontsize=7,
                                 text_color=RED, align=fitz.TEXT_ALIGN_CENTER)
    ft.update()
    doc.save(str(path))


def main(out_dir):
    out = Path(out_dir)
    (out / "iso").mkdir(parents=True, exist_ok=True)
    make_iso(out / "iso" / f"{ISO}.pdf")
    make_iso(out / "iso" / "GCC-DLM-DDD-12200-07-4302-TKM-ISO-00011_rot90.pdf", rotate=90)
    make_sample(out / "sample.pdf")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ISO", "XX_YY"])
    ws.append([ISO, "01_01"])
    ws.append(["GCC-DLM-DDD-12200-07-4302-TKM-ISO-00011", "02_03"])
    wb.save(out / "list.xlsx")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "test_data")
