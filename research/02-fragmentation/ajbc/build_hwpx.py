"""분절화 논문(../paper.md)을 아태경상저널 양식(HWPX)으로 옮긴다.

양식은 전북대학교 산업경제연구소가 배포한 논문양식샘플이다.
https://riie.chonbuk.ac.kr/sites/riie/down/[4]%20%EB%85%BC%EB%AC%B8%EC%96%91%EC%8B%9D%EC%83%98%ED%94%8C.hwpx
받은 파일을 template.hwpx로 두었다.

양식의 스타일(본문, 장 제목, 표그림제목, 각주 등)과 머리말·꼬리말은 그대로 쓰고
글만 바꾼다. 학술지 규정에 따라 장·절 번호를 아라비아 숫자로(1. 서론, 2.1),
표와 그림 번호를 <표 1>, <그림 1>로 바꾸고 투고규정 부록은 뺀다.
국문·영문 요약처럼 양식이 따로 요구하는 것은 front.md에서 읽는다.

    python build_hwpx.py            # paper.hwpx 생성
    python build_hwpx.py --render   # 한글로 열어 다시 저장하고 paper.pdf도 만든다(pywin32, 한글 필요)

--render는 한글이 줄 배치와 수식 크기를 다시 계산해 저장하게 한다. 투고에는 이 결과를 쓴다.
"""
import copy
import itertools
import re
import sys
import zipfile
from pathlib import Path

from lxml import etree

HERE = Path(__file__).resolve().parent
PAPER = HERE.parent / "paper.md"
FRONT = HERE / "front.md"
TEMPLATE = HERE / "template.hwpx"
OUT = HERE / "paper.hwpx"

NS = {
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hs": "http://www.hancom.co.kr/hwpml/2011/section",
    "hc": "http://www.hancom.co.kr/hwpml/2011/core",
    "hh": "http://www.hancom.co.kr/hwpml/2011/head",
    "opf": "http://www.idpf.org/2007/opf/",
}
HP = "{%s}" % NS["hp"]
HC = "{%s}" % NS["hc"]
HH = "{%s}" % NS["hh"]

# 양식이 정의한 스타일: (paraPr, style, charPr)
BODY = ("19", "2", "30")
BLANK = ("3", "0", "14")
CHAPTER = ("5", "10", "9")
SECTION = ("5", "11", "1")
CAPTION = ("2", "12", "2")
CELL = ("2", "13", "11")
CELL_LEFT = ("5", "13", "11")
NOTE = ("22", "19", "8")
FOOTNOTE = ("13", "14", "20")
REF_HEAD = ("9", "15", "7")
REF_EN = ("4", "17", "32")
ABSTRACT = ("0", "8", "13")

TABLE_WIDTH = 45190
FIG_WIDTH = 42520  # 150mm

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6}

_ids = itertools.count(1_500_000_000)


# ---------------------------------------------------------------- 수식
# 논문에 나오는 LaTeX 식을 한글 수식 스크립트로 옮긴 표. 새 식이 생기면 여기에 더한다.
EQ = {
    "S": "S",
    "I": "I",
    "E": "E",
    "U": "U",
    "C": "C",
    "i": "i",
    "j": "j",
    "w_k": "w _{k}",
    "s_k": "s _{k}",
    "x_U": "x _{U}",
    "m_U": "m _{U}",
    "X_{ij}": "X _{ij}",
    r"\Delta": "DELTA",
    r"\Delta S": "DELTA S",
    r"\bar{w}_k": "{bar{w}} _{k}",
    r"\bar{s}_k": "{bar{s}} _{k}",
    r"\bar{w}_k \Delta s_k": "{bar{w}} _{k} DELTA s _{k}",
    r"\bar{s}_k \Delta w_k": "{bar{s}} _{k} DELTA w _{k}",
    r"\Delta \ln[S/(1-S)]": "DELTA ln LEFT [ S/(1-S) RIGHT ]",
    "I = S/E": "I=S/E",
    r"S = \sum_k w_k s_k": "S= sum _{k} w _{k} s _{k}",
    "E = x_U(1-m_U) + (1-x_U)m_U": "E=x _{U} (1-m _{U} )+(1-x _{U} )m _{U}",
    r"S = \frac{\sum_{i \in U, j \in C} X_{ij} + \sum_{i \in C, j \in U} X_{ij}}{\sum_{i, j \in U \cup C} X_{ij}}":
        "S= {sum _{i in U,`j in C} X _{ij} + sum _{i in C,`j in U} X _{ij}} over {sum _{i,`j in U cup C} X _{ij}}",
    r"\Delta S = \sum_k \bar{s}_k \Delta w_k + \sum_k \bar{w}_k \Delta s_k":
        "DELTA S= sum _{k} {bar{s}} _{k} DELTA w _{k} + sum _{k} {bar{w}} _{k} DELTA s _{k}",
}


def equation(latex, base):
    latex = latex.strip()
    if latex not in EQ:
        raise KeyError(f"수식 표에 없는 식: {latex}")
    e = etree.Element(HP + "equation", {
        "id": str(next(_ids)), "zOrder": "0", "numberingType": "EQUATION",
        "textWrap": "TOP_AND_BOTTOM", "textFlow": "BOTH_SIDES", "lock": "0",
        "dropcapstyle": "None", "version": "Equation Version 60", "baseLine": "86",
        "textColor": "#000000", "baseUnit": str(base), "lineMode": "CHAR", "font": "HYhwpEQ",
    })
    etree.SubElement(e, HP + "sz", {"width": str(600 * max(1, len(EQ[latex]) // 2)),
                                    "widthRelTo": "ABSOLUTE", "height": str(base),
                                    "heightRelTo": "ABSOLUTE", "protect": "0"})
    etree.SubElement(e, HP + "pos", {"treatAsChar": "1", "affectLSpacing": "0", "flowWithText": "1",
                                     "allowOverlap": "0", "holdAnchorAndSO": "0", "vertRelTo": "PARA",
                                     "horzRelTo": "PARA", "vertAlign": "TOP", "horzAlign": "LEFT",
                                     "vertOffset": "0", "horzOffset": "0"})
    etree.SubElement(e, HP + "outMargin", {"left": "56", "right": "56", "top": "0", "bottom": "0"})
    etree.SubElement(e, HP + "shapeComment").text = "수식입니다."
    etree.SubElement(e, HP + "script").text = EQ[latex]
    return e


# ---------------------------------------------------------------- 문단
def para(style, pagebreak=False):
    ppr, st, _ = style
    return etree.Element(HP + "p", {"id": "2147483648", "paraPrIDRef": ppr, "styleIDRef": st,
                                    "pageBreak": "1" if pagebreak else "0",
                                    "columnBreak": "0", "merged": "0"})


def fill(p, text, style, footnotes=None, base=None):
    """text의 $..$는 수식으로, [^n]은 각주로 넣는다."""
    char = style[2]
    base = base or {"30": 1250, "11": 1000, "8": 800, "20": 900, "13": 1100}.get(char, 1000)
    run = etree.SubElement(p, HP + "run", {"charPrIDRef": char})
    for tok in re.split(r"(\$[^$]+\$|\[\^\d+\])", text):
        if not tok:
            continue
        if tok.startswith("$"):
            run.append(equation(tok[1:-1], base))
        elif tok.startswith("[^"):
            n = tok[2:-1]
            ctrl = etree.SubElement(run, HP + "ctrl")
            ctrl.append(footnote(footnotes, n))
        else:
            etree.SubElement(run, HP + "t").text = tok
    return p


_fn_count = itertools.count(1)


def footnote(footnotes, key):
    num = str(next(_fn_count))
    fn = etree.Element(HP + "footNote", {"number": num, "userChar": "0", "suffixChar": "41",
                                         "instId": str(next(_ids))})
    sub = etree.SubElement(fn, HP + "subList", {
        "id": "", "textDirection": "HORIZONTAL", "lineWrap": "BREAK", "vertAlign": "TOP",
        "linkListIDRef": "0", "linkListNextIDRef": "0", "textWidth": "0", "textHeight": "0",
        "hasTextRef": "0", "hasNumRef": "0"})
    p = para(FOOTNOTE)
    run = etree.SubElement(p, HP + "run", {"charPrIDRef": FOOTNOTE[2]})
    ctrl = etree.SubElement(run, HP + "ctrl")
    an = etree.SubElement(ctrl, HP + "autoNum", {"num": num, "numType": "FOOTNOTE"})
    etree.SubElement(an, HP + "autoNumFormat", {"type": "DIGIT", "userChar": "", "prefixChar": "",
                                                "suffixChar": ")", "supscript": "0"})
    p.remove(run)
    fill(p, " " + journal_text(footnotes[key]), FOOTNOTE)
    p[0].insert(0, ctrl)
    sub.append(p)
    return fn


# ---------------------------------------------------------------- 표
class Borders:
    """표 칸의 테두리 조합을 header.xml의 borderFill로 등록한다."""

    def __init__(self, header_root):
        self.root = header_root
        self.box = header_root.find(".//hh:borderFills", NS)
        self.proto = self.box.find("hh:borderFill[@id='24']", NS)
        self.cache = {}

    def get(self, left, right, top, bottom):
        key = (left, right, top, bottom)
        if key not in self.cache:
            bf = copy.deepcopy(self.proto)
            bf.set("id", str(len(self.box) + 1))
            for side, (typ, width) in zip(("left", "right", "top", "bottom"), key):
                el = bf.find(f"hh:{side}Border", NS)
                el.set("type", typ)
                el.set("width", width)
            self.box.append(bf)
            self.box.set("itemCnt", str(len(self.box)))
            self.cache[key] = bf.get("id")
        return self.cache[key]


NONE = ("NONE", "0.1 mm")
THICK = ("SOLID", "0.12 mm")
THIN = ("SOLID", "0.1 mm")
DASH = ("DASH", "0.1 mm")


def table(rows, widths, nhead, borders, left_cols=()):
    """rows: 칸의 목록. 칸은 글, (글, rowspan, colspan), 또는 병합으로 덮인 자리의 None."""
    nrow, ncol = len(rows), len(widths)
    assert sum(widths) == TABLE_WIDTH, sum(widths)
    tbl = etree.Element(HP + "tbl", {
        "id": str(next(_ids)), "zOrder": "0", "numberingType": "TABLE", "textWrap": "TOP_AND_BOTTOM",
        "textFlow": "BOTH_SIDES", "lock": "0", "dropcapstyle": "None", "pageBreak": "CELL",
        "repeatHeader": "1", "rowCnt": str(nrow), "colCnt": str(ncol), "cellSpacing": "0",
        "borderFillIDRef": borders.get(NONE, NONE, NONE, NONE), "noAdjust": "1"})
    etree.SubElement(tbl, HP + "sz", {"width": str(TABLE_WIDTH), "widthRelTo": "ABSOLUTE",
                                      "height": str(1778 * nrow), "heightRelTo": "ABSOLUTE", "protect": "0"})
    etree.SubElement(tbl, HP + "pos", {"treatAsChar": "1", "affectLSpacing": "0", "flowWithText": "1",
                                       "allowOverlap": "0", "holdAnchorAndSO": "0", "vertRelTo": "PARA",
                                       "horzRelTo": "PARA", "vertAlign": "TOP", "horzAlign": "LEFT",
                                       "vertOffset": "0", "horzOffset": "0"})
    for tag in ("outMargin", "inMargin"):
        etree.SubElement(tbl, HP + tag, {"left": "141", "right": "141", "top": "141", "bottom": "141"})

    def hline(r):
        if r in (0, nhead, nrow):
            return THICK
        return THIN if r < nhead else DASH

    def vline(c):
        if c in (0, ncol):
            return NONE
        return THIN if c == 1 else DASH

    for r, row in enumerate(rows):
        tr = etree.SubElement(tbl, HP + "tr")
        for c, cell in enumerate(row):
            if cell is None:
                continue
            text, rs, cs = cell if isinstance(cell, tuple) else (cell, 1, 1)
            tc = etree.SubElement(tr, HP + "tc", {
                "name": "", "header": "1" if r < nhead else "0", "hasMargin": "0", "protect": "0",
                "editable": "0", "dirty": "0",
                "borderFillIDRef": borders.get(vline(c), vline(c + cs), hline(r), hline(r + rs))})
            sub = etree.SubElement(tc, HP + "subList", {
                "id": "", "textDirection": "HORIZONTAL", "lineWrap": "BREAK", "vertAlign": "CENTER",
                "linkListIDRef": "0", "linkListNextIDRef": "0", "textWidth": "0", "textHeight": "0",
                "hasTextRef": "0", "hasNumRef": "0"})
            style = CELL_LEFT if (c in left_cols and r >= nhead) else CELL
            sub.append(fill(para(style), text, style))
            etree.SubElement(tc, HP + "cellAddr", {"colAddr": str(c), "rowAddr": str(r)})
            etree.SubElement(tc, HP + "cellSpan", {"colSpan": str(cs), "rowSpan": str(rs)})
            etree.SubElement(tc, HP + "cellSz", {"width": str(sum(widths[c:c + cs])),
                                                 "height": str(1778 * rs)})
            etree.SubElement(tc, HP + "cellMargin", {"left": "141", "right": "141", "top": "141",
                                                     "bottom": "141"})
    p = para(CAPTION)
    run = etree.SubElement(p, HP + "run", {"charPrIDRef": CELL[2]})
    run.append(tbl)
    etree.SubElement(run, HP + "t")
    return p


def md_rows(lines):
    """마크다운 표의 본문 행(머리글과 구분선 제외)."""
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines]
    return rows[2:]


# 머리글 병합은 paper.md의 <!-- Word 변환 지침 --> 주석을 옮긴 것이다.
def spec_table(num, body):
    if num == 1:
        head = [[("교역", 2, 1), ("사전 수준(%)", 2, 1), ("변화(%p)", 1, 2), None, ("로그 오즈 변화", 2, 1)],
                [None, None, "무역분쟁", "사후", None]]
        return head + body, [9000, 9000, 9000, 9000, 9190], 2, ()
    if num == 2:
        head = [[("범주", 2, 1), ("교역 비중(%)", 1, 2), None, ("블록 간 비중(%)", 1, 2), None,
                 ("전체 변화 기여(%p)", 1, 3), None, None],
                [None, "사전", "사후", "사전", "사후",
                 r"구성 효과 $\bar{s}_k \Delta w_k$", r"범주 내 효과 $\bar{w}_k \Delta s_k$", "합"]]
        return head + body, [6790, 4800, 4800, 4800, 4800, 6800, 6800, 5600], 2, ()
    if num == 3:
        head = [[("교역", 2, 1), ("사전 2015~2017년", 1, 3), None, None, ("사후 2022~2024년", 1, 3), None, None,
                 ("$I$ 변화(%)", 2, 1)],
                [None, "$S$(%)", "$E$(%)", "$I$", "$S$(%)", "$E$(%)", "$I$", None]]
        return head + body, [6190, 5000, 5000, 5000, 5000, 5000, 5000, 9000], 2, ()
    if num == 4:
        head = [[("정의", 2, 1), ("규칙", 2, 1), ("경제 수", 2, 1), ("서비스", 1, 2), None, ("상품", 1, 2), None],
                [None, None, None, "전체", "러시아·벨라루스 제외", "전체", "러시아·벨라루스 제외"]]
        body = [[row[0], row[1], row[2].replace(" · ", "·")] + row[3:] for row in body]
        return head + body, [6400, 15590, 5400, 4450, 4450, 4450, 4450], 2, (1,)
    if num == 5:
        head = [["교역", "계열", "사전 수준(%)", "사후 변화(%p)", "집약도 변화율(%)"]]
        split = []
        groups = {"서비스": 2, "상품": 3}
        seen = set()
        for row in body:
            kind, series = row[0].split(" ", 1)
            first = None if kind in seen else (kind, groups[kind], 1)
            seen.add(kind)
            split.append([first, series] + row[1:])
        return head + split, [7000, 11190, 9000, 9000, 9000], 1, ()
    raise ValueError(num)


# ---------------------------------------------------------------- 그림
def picture(path, bin_id):
    from PIL import Image
    w_px, h_px = Image.open(path).size
    org_w, org_h = w_px * 75, h_px * 75  # 96dpi 기준 HWPUNIT
    cur_w = FIG_WIDTH
    cur_h = round(FIG_WIDTH * h_px / w_px)
    sx, sy = cur_w / org_w, cur_h / org_h
    pic = etree.Element(HP + "pic", {
        "id": str(next(_ids)), "zOrder": "0", "numberingType": "PICTURE", "textWrap": "TOP_AND_BOTTOM",
        "textFlow": "BOTH_SIDES", "lock": "0", "dropcapstyle": "None", "href": "", "groupLevel": "0",
        "instid": str(next(_ids)), "reverse": "0"})
    etree.SubElement(pic, HP + "offset", {"x": "0", "y": "0"})
    etree.SubElement(pic, HP + "orgSz", {"width": str(org_w), "height": str(org_h)})
    etree.SubElement(pic, HP + "curSz", {"width": str(cur_w), "height": str(cur_h)})
    etree.SubElement(pic, HP + "flip", {"horizontal": "0", "vertical": "0"})
    etree.SubElement(pic, HP + "rotationInfo", {"angle": "0", "centerX": str(cur_w // 2),
                                                "centerY": str(cur_h // 2), "rotateimage": "1"})
    ri = etree.SubElement(pic, HP + "renderingInfo")
    ident = {"e1": "1", "e2": "0", "e3": "0", "e4": "0", "e5": "1", "e6": "0"}
    etree.SubElement(ri, HC + "transMatrix", ident)
    etree.SubElement(ri, HC + "scaMatrix", {**ident, "e1": f"{sx:.6f}", "e5": f"{sy:.6f}"})
    etree.SubElement(ri, HC + "rotMatrix", ident)
    etree.SubElement(pic, HC + "img", {"binaryItemIDRef": bin_id, "bright": "0", "contrast": "0",
                                       "effect": "REAL_PIC", "alpha": "0"})
    rect = etree.SubElement(pic, HP + "imgRect")
    for i, (x, y) in enumerate([(0, 0), (org_w, 0), (org_w, org_h), (0, org_h)]):
        etree.SubElement(rect, HC + f"pt{i}", {"x": str(x), "y": str(y)})
    etree.SubElement(pic, HP + "imgClip", {"left": "0", "right": str(org_w), "top": "0", "bottom": str(org_h)})
    etree.SubElement(pic, HP + "inMargin", {"left": "0", "right": "0", "top": "0", "bottom": "0"})
    etree.SubElement(pic, HP + "imgDim", {"dimwidth": str(org_w), "dimheight": str(org_h)})
    etree.SubElement(pic, HP + "effects")
    etree.SubElement(pic, HP + "sz", {"width": str(cur_w), "widthRelTo": "ABSOLUTE", "height": str(cur_h),
                                      "heightRelTo": "ABSOLUTE", "protect": "0"})
    etree.SubElement(pic, HP + "pos", {"treatAsChar": "1", "affectLSpacing": "0", "flowWithText": "1",
                                       "allowOverlap": "0", "holdAnchorAndSO": "0", "vertRelTo": "PARA",
                                       "horzRelTo": "PARA", "vertAlign": "TOP", "horzAlign": "LEFT",
                                       "vertOffset": "0", "horzOffset": "0"})
    etree.SubElement(pic, HP + "outMargin", {"left": "0", "right": "0", "top": "0", "bottom": "0"})
    p = para(CAPTION)
    run = etree.SubElement(p, HP + "run", {"charPrIDRef": CAPTION[2]})
    run.append(pic)
    etree.SubElement(run, HP + "t")
    return p


def display_equation(latex, number, borders):
    """식은 가운데, 번호는 오른쪽 끝. 테두리 없는 1행 3열 표로 놓는다."""
    p = table([["", f"${latex}$", f"({number})"]], [5000, 35190, 5000], 0, borders)
    tbl = p.find(".//hp:tbl", NS)
    none = borders.get(NONE, NONE, NONE, NONE)
    for tc in tbl.iter(HP + "tc"):
        tc.set("borderFillIDRef", none)
        for q in tc.iter(HP + "p"):
            q.set("paraPrIDRef", CAPTION[0])
            for r in q.iter(HP + "run"):
                r.set("charPrIDRef", BODY[2])
            for e in q.iter(HP + "equation"):
                e.set("baseUnit", "1250")
    last = list(tbl.iter(HP + "tc"))[-1]
    for q in last.iter(HP + "p"):
        q.set("paraPrIDRef", "7")  # 오른쪽 정렬
    return p


# ---------------------------------------------------------------- 본문 변환
def journal_text(s):
    """paper.md의 표기를 학술지 표기로 바꾼다."""
    s = s.replace(r"\~", "~")
    s = re.sub(r'"([^"]*)"', r"“\1”", s)
    s = re.sub(r"(?<![A-Za-z])(VI|IV|V|I{1,3})\.(\d)절", lambda m: f"{ROMAN[m[1]]}.{m[2]}절", s)
    s = re.sub(r"(?<![A-Za-z])(VI|IV|V|I{1,3})장", lambda m: f"{ROMAN[m[1]]}장", s)
    s = re.sub(r"(?<![<\w])(표|그림) (\d+)", r"<\1 \2>", s)
    return s


def parse_front():
    txt = FRONT.read_text(encoding="utf-8")
    parts = re.split(r"^## (.+)$", txt, flags=re.M)
    return {parts[i].strip(): parts[i + 1].strip() for i in range(1, len(parts), 2)}


def blocks(md):
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    return [b.strip("\n") for b in re.split(r"\n\s*\n", md) if b.strip()]


def build_body(md, borders, images):
    footnotes = dict(re.findall(r"^\[\^(\d+)\]: (.+)$", md, flags=re.M))
    body_md = md.split("## I. 서론", 1)[1]
    body_md, refs_md = body_md.split("## 참고문헌", 1)
    out = []
    chapter = 1
    pending_img = None
    first = True
    for b in blocks("## I. 서론" + body_md):
        if b.startswith("[^") or b == "---":
            continue
        m = re.match(r"^## (\w+)\. (.+)$", b)
        if m:
            chapter = ROMAN[m[1]]
            if not first:
                out.append(para(BLANK))
                out.append(fill(para(CHAPTER), f"{chapter}. {m[2]}", CHAPTER))
            first = False
            continue
        m = re.match(r"^### (\d+)\. (.+)$", b)
        if m:
            if out and out[-1].get("styleIDRef") != CHAPTER[1]:
                out.append(para(BLANK))
            out.append(fill(para(SECTION), f"{chapter}.{m[1]} {m[2]}", SECTION))
            continue
        m = re.match(r"^\$\$\n(.+?)\s*\\qquad \((\d+)\)\n\$\$$", b, flags=re.S)
        if m:
            out.append(display_equation(m[1].strip(), m[2], borders))
            continue
        m = re.match(r"^!\[.*\]\((.+)\)$", b)
        if m:
            pending_img = m[1]
            continue
        m = re.match(r"^\*\*(표|그림) (\d+)\. (.+)\*\*$", b)
        if m:
            out.append(para(BODY))
            out.append(fill(para(CAPTION), f"<{m[1]} {m[2]}> {journal_text(m[3])}", CAPTION))
            if m[1] == "그림":
                bin_id = f"image{len(images) + 1}"
                images[bin_id] = HERE.parent / pending_img
                out.append(picture(images[bin_id], bin_id))
                pending_img = None
            else:
                caption_num = int(m[2])
            continue
        if b.startswith("|"):
            rows, widths, nhead, left = spec_table(caption_num, md_rows(b.splitlines()))
            rows = [[journal_text(c) if isinstance(c, str) else
                     (journal_text(c[0]),) + c[1:] if c else c for c in row] for row in rows]
            out.append(table(rows, widths, nhead, borders, left))
            continue
        if b.startswith("주:") or b.startswith("자료:"):
            for line in b.split("\\\n"):
                out.append(fill(para(NOTE), journal_text(line.strip()), NOTE))
            out.append(para(BODY))
            continue
        out.append(fill(para(BODY), journal_text(b.replace("\n", " ")), BODY, footnotes))

    refs = [ln[2:].strip() for ln in refs_md.strip().splitlines() if ln.startswith("- ")]
    out.append(fill(para(REF_HEAD, pagebreak=True), "참 고 문 헌", REF_HEAD))
    for r in refs:
        out.append(fill(para(REF_EN), apa(r), REF_EN))
    return out


# ---------------------------------------------------------------- 참고문헌
REFS_APA = {
    "Airaudo": "Airaudo, F. S., de Soyres, F., Richards, K., & Santacreu, A. M. (2025). Fragmentation? Revisiting the ideal point distance measure of geopolitical distance. FEDS Notes, Board of Governors of the Federal Reserve System, March 21.",
    "Aiyar": "Aiyar, S., Chen, J., Ebeke, C., Garcia-Saltos, R., Gudmundsson, T., Ilyina, A., Kangur, A., Kunaratskul, T., Rodriguez, S., Ruta, M., Schulze, T., Soderberg, G., & Trevino, J. (2023). Geoeconomic fragmentation and the future of multilateralism (IMF Staff Discussion Note SDN/2023/001). International Monetary Fund.",
    "Bailey": "Bailey, M. A., Strezhnev, A., & Voeten, E. (2017). Estimating dynamic state preferences from United Nations voting data. Journal of Conflict Resolution, 61(2), 430-456.",
    "Drysdale": "Drysdale, P., & Garnaut, R. (1982). Trade intensities and the analysis of bilateral trade flows in a many-country world: A survey. Hitotsubashi Journal of Economics, 22(2), 62-84.",
    "Gaulier": "Gaulier, G., & Zignago, S. (2010). BACI: International trade database at the product-level. The 1994-2007 version (CEPII Working Paper 2010-23). CEPII.",
    "Gopinath": "Gopinath, G., Gourinchas, P.-O., Presbitero, A. F., & Topalova, P. (2025). Changing global linkages: A new Cold War? Journal of International Economics, 153, 104042.",
    "Li,": "Li, N., Meleshchuk, S., Yin, Q., Zhao, D., & Zymek, R. (2026). Bilateral trade in services: Insights from a new research dataset. IMF Economic Review, 1-39.",
    "OECD and WTO": "OECD & WTO. (2025). The OECD-WTO balanced trade in services database (BaTIS), December 2025 edition. OECD Publishing.",
    "OECD (2026)": "OECD. (2026). The OECD balanced international merchandise trade dataset (BIMTS), May 2026 edition. OECD Publishing.",
    "WTO (2023)": "WTO. (2023). World trade report 2023: Re-globalization for a secure, inclusive and sustainable future. World Trade Organization.",
}


def apa(ref):
    for key, text in REFS_APA.items():
        if ref.startswith(key):
            return text
    raise KeyError(f"REFS_APA에 없는 문헌: {ref[:40]}")


# ---------------------------------------------------------------- 표지
def texts(root):
    return list(root.iter(HP + "t"))


def set_text(root, old, new):
    for t in texts(root):
        if t.text and t.text.startswith(old):
            t.text = new
            return t
    raise KeyError(old)


def top_para(root, t):
    p = t
    while p.getparent() is not root:
        p = p.getparent()
    return p


def remove_para(root, startswith):
    for t in texts(root):
        if t.text and t.text.startswith(startswith):
            root.remove(top_para(root, t))
            return
    raise KeyError(startswith)


def cover_ko(root, front):
    set_text(root, "가상의 데이터가", front["국문제목"] + "*")
    set_text(root, "김지구", front["저자"])
    set_text(root, "지구별대학교", front["소속"])
    # 공저자 칸(이름·소속과 그 앞 빈 줄)은 지운다
    who = top_para(root, next(t for t in texts(root) if t.text == "최화성"))
    prev = who.getprevious()
    remove_para(root, "화성대학교")
    root.remove(who)
    root.remove(prev)
    set_text(root, "본 연구는 '안드로메다", front["국문요약"])
    set_text(root, "우주경제", front["핵심주제어"])
    for label in ("논문접수일", "심사완료일", "게재확정일"):
        set_text(root, label, f"{label} 0000년 00월 00일")


def cover_en(root, front):
    set_text(root, "A Study on the Non-linear", front["영문제목"] + "*")
    set_text(root, "Kim, Gee Gu", front["Author"])
    set_text(root, "Assistant Professor", front["Affiliation"])
    who = top_para(root, next(t for t in texts(root) if (t.text or "").startswith("Kim, Hwa Sung")))
    prev = who.getprevious()
    remove_para(root, "Professor, Business")
    root.remove(who)
    root.remove(prev)
    t = set_text(root, "This study investigates", "")
    p = top_para(root, t)
    paras = front["Abstract"].split("\n\n")
    t.text = paras[0]
    anchor = p
    for extra in paras[1:]:
        gap = copy.deepcopy(p)
        texts(gap)[0].text = ""
        q = copy.deepcopy(p)
        texts(q)[0].text = extra
        anchor.addnext(gap)
        gap.addnext(q)
        anchor = q
    set_text(root, "Space Economy", front["Keywords"])
    # 영문 제목이 두 줄이라 국문 표지보다 길다. 날짜가 다음 쪽으로 밀리지 않도록 앞의 빈 줄을 모두 뺀다
    for q in [q for q in root if q.get("styleIDRef") == "6" and not "".join(x.text or "" for x in texts(q))]:
        root.remove(q)
    for label, new in (("Received", "Received Month 00, 0000"), ("Revised", "Revised Month 00, 0000"),
                       ("Accepted", "Accepted Month 00, 0000")):
        set_text(root, label, new)


# ---------------------------------------------------------------- 조립
def body_section(root, paras, front):
    # 첫 두 문단(1. 서론 제목과 머리말·번호 제어 문단)은 양식의 것을 쓰고 나머지를 바꾼다
    kids = list(root)
    for p in kids[2:]:
        root.remove(p)
    for t in texts(kids[1]):
        if t.text and t.text.startswith("가상의 데이터가"):
            t.text = front["국문제목"]
        elif t.text and t.text.startswith("김지구"):
            t.text = front["저자"]
    for p in paras:
        root.append(p)


def strip_layout(xml_root):
    for ls in list(xml_root.iter(HP + "linesegarray")):
        ls.getparent().remove(ls)


def keep_caption_with_next(header):
    """표·그림 제목이 쪽 끝에 홀로 남지 않도록 다음 문단과 붙이는 문단 모양을 더한다."""
    global CAPTION
    box = header.find(".//hh:paraProperties", NS)
    pp = copy.deepcopy(box.find("hh:paraPr[@id='2']", NS))
    pp.set("id", str(len(box)))
    for bs in pp.iter(HH + "breakSetting"):
        bs.set("keepWithNext", "1")
    box.append(pp)
    box.set("itemCnt", str(len(box)))
    CAPTION = (pp.get("id"),) + CAPTION[1:]


def build():
    md = PAPER.read_text(encoding="utf-8")
    front = parse_front()
    zin = zipfile.ZipFile(TEMPLATE)
    header = etree.fromstring(zin.read("Contents/header.xml"))
    borders = Borders(header)
    keep_caption_with_next(header)
    images = {}

    sec0 = etree.fromstring(zin.read("Contents/section0.xml"))
    sec1 = etree.fromstring(zin.read("Contents/section1.xml"))
    sec2 = etree.fromstring(zin.read("Contents/section2.xml"))
    cover_ko(sec0, front)
    body_section(sec1, build_body(md, borders, images), front)
    cover_en(sec2, front)
    for s in (sec0, sec1, sec2):
        strip_layout(s)

    hpf = etree.fromstring(zin.read("Contents/content.hpf"))
    manifest = hpf.find("opf:manifest", NS)
    spine = hpf.find("opf:spine", NS)
    for item in list(manifest):
        if item.get("id") in ("image1", "section3"):
            manifest.remove(item)
    for ref in list(spine):
        if ref.get("idref") == "section3":
            spine.remove(ref)
    for bin_id, path in images.items():
        etree.SubElement(manifest, "{%s}item" % NS["opf"], {
            "id": bin_id, "href": f"BinData/{bin_id}.png", "media-type": "image/png", "isEmbeded": "1"})

    # 부록 절을 빼면 머리의 절 수와 패키지 목록(container.rdf)도 맞춰야 한글이 파일을 연다
    header.set("secCnt", "3")
    rdf = zin.read("META-INF/container.rdf").decode("utf-8")
    rdf = re.sub(r'<rdf:Description rdf:about=""><ns0:hasPart[^>]*section3\.xml"/></rdf:Description>'
                 r'<rdf:Description rdf:about="Contents/section3\.xml">.*?</rdf:Description>', "", rdf)

    decl = b'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
    ser = lambda el: decl + etree.tostring(el, encoding="UTF-8")
    replaced = {
        "Contents/header.xml": ser(header),
        "Contents/section0.xml": ser(sec0),
        "Contents/section1.xml": ser(sec1),
        "Contents/section2.xml": ser(sec2),
        "Contents/content.hpf": ser(hpf),
        "META-INF/container.rdf": rdf.encode("utf-8"),
        "Preview/PrvText.txt": (front["국문제목"] + "\r\n").encode("utf-8"),
    }
    skip = {"Contents/section3.xml", "BinData/image1.bmp"}
    with zipfile.ZipFile(OUT, "w") as zout:
        for info in zin.infolist():
            if info.filename in skip:
                continue
            data = replaced.get(info.filename, zin.read(info.filename))
            method = zipfile.ZIP_STORED if info.filename == "mimetype" else zipfile.ZIP_DEFLATED
            zout.writestr(info.filename, data, compress_type=method)
        for bin_id, path in images.items():
            zout.write(path, f"BinData/{bin_id}.png", compress_type=zipfile.ZIP_STORED)
    print(f"{OUT.name}: 각주 {next(_fn_count) - 1}개, 그림 {len(images)}개")


def render():
    """한글로 열어 줄 배치를 다시 계산해 저장하고 PDF를 뽑는다."""
    import win32com.client
    hwp = win32com.client.Dispatch("HWPFrame.HwpObject")
    try:
        hwp.XHwpWindows.Item(0).Visible = False
        if not hwp.Open(str(OUT), "HWPX", "forceopen:true"):
            raise RuntimeError(f"한글이 {OUT.name}을 열지 못했다")
        hwp.SaveAs(str(OUT), "HWPX", "")
        hwp.SaveAs(str(OUT.with_suffix(".pdf")), "PDF", "")
        print(f"{OUT.name} 다시 저장, {OUT.with_suffix('.pdf').name}: {hwp.PageCount}쪽")
    finally:
        hwp.Clear(1)
        hwp.Quit()


if __name__ == "__main__":
    build()
    if "--render" in sys.argv:
        render()
