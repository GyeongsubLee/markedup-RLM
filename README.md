# markedup-RLM — Rev Tag 자동 표시

ISO 도면 PDF에서 **빨간색 rev cloud**를 찾아, 각 cloud의 **왼쪽 위**에 `XX_YY_ZZ` rev 태그(평행사변형 + 지시선)를 자동으로 붙입니다.

- `XX_YY` : 엑셀 리스트(A열 ISO 번호, B열 XX_YY)에서 가져옴
- `ZZ` : 도면(파일) 안에서 cloud 하나당 01, 02, 03 … 증가
- 태그 모양 : SAMPLE PDF에 그려둔 **주석(평행사변형·지시선·텍스트)을 그대로 복사**해서 텍스트만 바꿉니다

## 설치

```bash
pip install -r requirements.txt
```

## 사용법

### GUI
```bash
python -m revtag
```
SAMPLE PDF, 엑셀, 결과 폴더, ISO PDF(파일 또는 폴더)를 지정하고 **실행**.

### 명령줄
```bash
python -m revtag --sample sample.pdf --excel list.xlsx --out result  iso_folder/
```

| 옵션 | 설명 |
|---|---|
| `--order rows` (기본) | ZZ 순서: 위→아래, 같은 줄은 왼→오 |
| `--order cols` | 왼→오, 같은 열은 위→아래 |
| `--order annot` | cloud가 PDF 주석일 때 그린 순서 |
| `--detect raster` (기본) | 화면에 그려진 **빨간색**으로 cloud 검출 (주석/평탄화 상관없음) |
| `--detect annot` | 빨간 PDF 도형 주석만 cloud로 인정 |
| `--start N`, `--digits N` | ZZ 시작 번호 / 자릿수 |
| `--offset DX DY` | 태그 위치 미세 조정(pt) |

결과 폴더에 같은 파일명으로 저장되고, `revtag_report.csv`에 파일/페이지/태그/cloud 위치가 기록됩니다.
이 프로그램이 넣은 태그는 `NM`이 `REVTAG-`로 시작하므로, 다시 실행하면 이전 태그를 지우고 새로 매깁니다.

## SAMPLE PDF 준비
- 태그 **한 세트**(평행사변형 + 지시선 + 텍스트 `01_01_01` 등)를 PDF 주석으로 그려둔 파일.
- 텍스트는 `A_B_C` 형태(FreeText)면 자동 인식되고, 이 텍스트가 새 태그 번호로 바뀝니다.
- 지시선(Line/PolyLine 주석)의 **텍스트에서 먼 쪽 끝**이 cloud의 왼쪽 위 모서리에 놓입니다.
  지시선이 없으면 태그 묶음의 오른쪽 아래 모서리를 기준으로 합니다.
- 텍스트 주석과 맞닿아 있는 주석들이 하나의 태그로 묶이므로, SAMPLE에는 태그 외의 주석이 붙어 있지 않게 해 주세요.

## ISO 번호 매칭
PDF 파일명에 엑셀 A열의 ISO 번호가 들어 있으면 매칭합니다(공백/`-`/`_` 무시).
파일명에 없으면 첫 페이지 텍스트에서 찾습니다.

## cloud 검출 방식 (raster)
1. 페이지를 144dpi로 **안티앨리어싱 없이, 최소 선두께 1px**로 렌더링 → CAD의 가는 선(hairline)도 진한 빨간색으로 나옴
2. 빨간 픽셀 판정: `R ≥ 140` 이고 `R − max(G,B) ≥ 80` (분홍/어두운 빨강도 허용)
3. 선을 1.5pt → 4pt → 8pt 순서로 두껍게 해 보며, **안쪽 공간을 둘러싼 닫힌 윤곽**이 되는 덩어리만 cloud로 인정
   (점선·끊긴 cloud도 인식, 빨간 글자·직선은 제외)

검출이 안 되면 `--debug`(GUI: "디버그 이미지 저장")를 켜고 결과폴더/debug 의 PNG를 확인하세요.
빨강 = 빨간색으로 인식된 픽셀, 초록 = cloud로 인정, 파랑 사각형 = cloud 범위.
로그의 `빨간 픽셀 N개`가 0이면 색 기준 문제 → `--red-delta 50` 처럼 낮춰 보세요.

## exe 만들기 (Windows)
```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name RevTag revtag_app.py
```
