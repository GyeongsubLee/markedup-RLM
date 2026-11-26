"""Command line:  python -m revtag --sample SAMPLE.pdf --excel list.xlsx --out OUT  ISO.pdf|folder ...
Without arguments the GUI is started."""

import argparse
import sys

from pathlib import Path

from .core import Options, RasterParams, run


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        from .gui import main as gui_main
        return gui_main()

    p = argparse.ArgumentParser(prog="revtag", description="빨간 rev cloud에 XX_YY_ZZ rev 태그 자동 표시")
    p.add_argument("inputs", nargs="+", help="ISO PDF 파일 또는 폴더")
    p.add_argument("--sample", required=True, help="태그(평행사변형+지시선+텍스트) 주석이 들어있는 SAMPLE PDF")
    p.add_argument("--sample-page", type=int, help="SAMPLE PDF에서 태그가 있는 페이지 (기본: 자동)")
    p.add_argument("--excel", required=True, help="A열 ISO, B열 XX_YY 엑셀")
    p.add_argument("--out", required=True, help="결과 저장 폴더")
    p.add_argument("--order", choices=["rows", "cols", "annot"], default="rows",
                   help="ZZ 번호 순서: rows=위→아래/왼→오, cols=왼→오/위→아래, annot=주석 그린 순서")
    p.add_argument("--detect", choices=["raster", "annot", "auto"], default="raster",
                   help="cloud 검출: raster=화면의 빨간색으로 검출(기본), annot=PDF 주석, auto=주석 없으면 빨간색")
    p.add_argument("--cloudy-only", action="store_true", help="구름 테두리(cloudy) 주석만 cloud로 인정")
    p.add_argument("--any-color", action="store_true", help="빨간색이 아닌 도형 주석도 cloud로 인정")
    p.add_argument("--start", type=int, default=1, help="ZZ 시작 번호 (기본 1)")
    p.add_argument("--digits", type=int, default=2, help="ZZ 자릿수 (기본 2 → 01)")
    p.add_argument("--keep-existing", action="store_true", help="이전 실행에서 넣은 태그를 지우지 않음")
    p.add_argument("--offset", type=float, nargs=2, default=(0.0, 0.0), metavar=("DX", "DY"),
                   help="태그 추가 이동량(pt, 화면 기준 +x 오른쪽, +y 아래)")
    p.add_argument("--debug", action="store_true",
                   help="결과 폴더/debug 에 빨간색 검출 이미지 저장 (빨강=검출된 빨간 픽셀, 초록=cloud로 인정, 파랑=cloud 범위)")
    p.add_argument("--red-min", type=int, default=140, help="빨간색 판정: R 최소값 (기본 140)")
    p.add_argument("--red-delta", type=int, default=80, help="빨간색 판정: R-max(G,B) 최소값 (기본 80, 낮출수록 관대)")
    a = p.parse_args(argv)
    opts = Options(order=a.order, detect=a.detect, require_cloudy=a.cloudy_only, any_color=a.any_color,
                   start=a.start, digits=a.digits, remove_existing=not a.keep_existing,
                   offset=tuple(a.offset),
                   raster=RasterParams(red_min=a.red_min, red_delta=a.red_delta,
                                       debug_dir=str(Path(a.out) / "debug") if a.debug else None))
    run(a.sample, a.excel, a.inputs, a.out, opts, a.sample_page)


if __name__ == "__main__":
    main()
