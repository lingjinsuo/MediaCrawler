#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Markdown -> Word (.docx) 转换工具

用法:
    uv run --with python-docx python tools/md2docx.py <input.md> [output.docx]

支持语法:
    # ~ ###### 标题        | 表格(含对齐/表头底纹)      | ``` 围栏代码块
    - / 1. 列表(支持嵌套)  | `行内代码` / **粗体** / *斜体* | > 引用块
    --- 分隔线            | 文档标题/元信息表/目录(TOC)

设计要点:
    - 中文字体通过 w:rFonts 的 eastAsia 属性设置,避免 Word 回退到宋体默认样式
    - 表格宽度铺满页面 (tblW=100%), 列数越多字号越小,保证不溢出
    - 不依赖项目依赖,通过 uv run --with python-docx 临时环境执行
"""

import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

CN_FONT = "微软雅黑"
MONO_FONT = "Consolas"
MONO_CN_FONT = "宋体"
BODY_SIZE = 10.5
CODE_SIZE = 9

HEADING_SPEC = {
    1: (16, 18, 10),
    2: (14, 14, 8),
    3: (12, 12, 6),
    4: (11, 10, 5),
    5: (10.5, 8, 4),
    6: (10.5, 8, 4),
}

INLINE_RE = re.compile(r"(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\*[^*\n]+\*|_[^_\n]+_)")
LIST_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
FENCE_RE = re.compile(r"^\s*```+\s*(\w*)\s*$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
HR_RE = re.compile(r"^\s*([-*_])\s*(\1\s*){2,}$")
ALIGN_RE = re.compile(r"^:?-{1,}:?$")


def style_run(run, *, size=None, bold=False, italic=False, mono=False,
              color=None, font=None):
    if mono:
        name, cn = MONO_FONT, MONO_CN_FONT
    else:
        name = cn = font or CN_FONT
    run.font.name = name
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:ascii"), name)
    rFonts.set(qn("w:hAnsi"), name)
    rFonts.set(qn("w:eastAsia"), cn)
    rFonts.set(qn("w:cs"), name)
    if size:
        run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    if color is not None:
        run.font.color.rgb = color


def shade_cell(cell, hex_color):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def set_cell_valign(cell, val="center"):
    tcPr = cell._tc.get_or_add_tcPr()
    vAlign = OxmlElement("w:vAlign")
    vAlign.set(qn("w:val"), val)
    tcPr.append(vAlign)


def set_repeat_header(row):
    trPr = row._tr.get_or_add_trPr()
    tblHeader = OxmlElement("w:tblHeader")
    tblHeader.set(qn("w:val"), "true")
    trPr.append(tblHeader)


def set_table_full_width(table):
    tblPr = table._tbl.tblPr
    tblW = tblPr.find(qn("w:tblW"))
    if tblW is None:
        tblW = OxmlElement("w:tblW")
        tblPr.append(tblW)
    tblW.set(qn("w:type"), "pct")
    tblW.set(qn("w:w"), "5000")


def add_bottom_border(paragraph, color="BFBFBF", sz="6"):
    pPr = paragraph._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), sz)
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), color)
    pbdr.append(bottom)
    pPr.append(pbdr)


def add_left_border(paragraph, color="D0D7E5", sz="12"):
    pPr = paragraph._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    left = OxmlElement("w:left")
    left.set(qn("w:val"), "single")
    left.set(qn("w:sz"), sz)
    left.set(qn("w:space"), "6")
    left.set(qn("w:color"), color)
    pbdr.append(left)
    pPr.append(pbdr)


def set_para_shading(paragraph, hex_color):
    pPr = paragraph._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    pPr.append(shd)


def add_inline(paragraph, text, *, size=None, base_bold=False, base_italic=False,
               color=None):
    if not text:
        return
    pos = 0
    for m in INLINE_RE.finditer(text):
        if m.start() > pos:
            _plain(paragraph, text[pos:m.start()], size, base_bold, base_italic, color)
        token = m.group(0)
        if token.startswith("`"):
            style_run(paragraph.add_run(token[1:-1]), size=size, mono=True,
                      bold=base_bold, color=color)
        elif token.startswith("**") or token.startswith("__"):
            style_run(paragraph.add_run(token[2:-2]), size=size, bold=True,
                      italic=base_italic, color=color)
        else:
            style_run(paragraph.add_run(token[1:-1]), size=size,
                      bold=base_bold, italic=True, color=color)
        pos = m.end()
    if pos < len(text):
        _plain(paragraph, text[pos:], size, base_bold, base_italic, color)


def _plain(paragraph, text, size, bold, italic, color):
    if not text:
        return
    style_run(paragraph.add_run(text), size=size, bold=bold, italic=italic,
              color=color)


def init_document():
    doc = Document()
    sec = doc.sections[0]
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    sec.left_margin = Cm(2.2)
    sec.right_margin = Cm(2.2)
    sec.top_margin = Cm(2.2)
    sec.bottom_margin = Cm(2.2)

    normal = doc.styles["Normal"]
    normal.font.name = CN_FONT
    normal.font.size = Pt(BODY_SIZE)
    rPr = normal.element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:eastAsia"), CN_FONT)
    rFonts.set(qn("w:ascii"), CN_FONT)
    rFonts.set(qn("w:hAnsi"), CN_FONT)
    normal.paragraph_format.space_after = Pt(4)
    normal.paragraph_format.line_spacing = 1.25

    for level, (size, before, after) in HEADING_SPEC.items():
        st = doc.styles[f"Heading {level}"]
        st.font.name = CN_FONT
        st.font.size = Pt(size)
        st.font.bold = True
        st.font.color.rgb = RGBColor(0x1A, 0x1A, 0x1A)
        r = st.element.get_or_add_rPr()
        rf = r.get_or_add_rFonts()
        rf.set(qn("w:eastAsia"), CN_FONT)
        rf.set(qn("w:ascii"), CN_FONT)
        rf.set(qn("w:hAnsi"), CN_FONT)
        st.paragraph_format.space_before = Pt(before)
        st.paragraph_format.space_after = Pt(after)
        st.paragraph_format.keep_with_next = True
    return doc


def add_footer_page_number(doc):
    footer = doc.sections[0].footer
    p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    style_run(run, size=9)
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = "PAGE"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(end)


def split_table_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def parse_align_row(line):
    aligns = []
    for c in split_table_row(line):
        c = c.strip()
        if c.startswith(":") and c.endswith(":"):
            aligns.append("center")
        elif c.endswith(":"):
            aligns.append("right")
        else:
            aligns.append("left")
    return aligns


def table_font_size(col_count):
    if col_count <= 3:
        return 10
    if col_count <= 4:
        return 9.5
    if col_count <= 5:
        return 9
    if col_count <= 6:
        return 8.5
    return 8


def render_table(doc, header, rows, aligns):
    col_count = len(header)
    if col_count == 0:
        return
    table = doc.add_table(rows=1, cols=col_count)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    set_table_full_width(table)
    size = table_font_size(col_count)

    hdr_cells = table.rows[0].cells
    for i, text in enumerate(header):
        cell = hdr_cells[i]
        cell.text = ""
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.space_before = Pt(1)
        add_inline(p, text, size=size, base_bold=True)
        shade_cell(cell, "E8EDF7")
        set_cell_valign(cell)
    set_repeat_header(table.rows[0])

    for r_i, row in enumerate(rows):
        cells = table.add_row().cells
        for i in range(col_count):
            text = row[i] if i < len(row) else ""
            cell = cells[i]
            cell.text = ""
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(1)
            p.paragraph_format.space_before = Pt(1)
            align = aligns[i] if i < len(aligns) else "left"
            p.alignment = {
                "left": WD_ALIGN_PARAGRAPH.LEFT,
                "center": WD_ALIGN_PARAGRAPH.CENTER,
                "right": WD_ALIGN_PARAGRAPH.RIGHT,
            }.get(align, WD_ALIGN_PARAGRAPH.LEFT)
            add_inline(p, text, size=size)
            set_cell_valign(cell, "center")
            if r_i % 2 == 1:
                shade_cell(cell, "F7F9FC")
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def render_code_block(doc, code_lines):
    if not code_lines:
        return
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.left_indent = Cm(0.3)
    p.paragraph_format.line_spacing = 1.1
    for idx, line in enumerate(code_lines):
        if idx > 0:
            p.add_run().add_break()
        style_run(p.add_run(line if line else " "), size=CODE_SIZE, mono=True)
    set_para_shading(p, "F2F3F5")
    add_left_border(p)


def render_quote(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.5)
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after = Pt(5)
    add_inline(p, text, size=BODY_SIZE, color=RGBColor(0x44, 0x55, 0x66))
    set_para_shading(p, "F7F9FC")
    add_left_border(p, color="9DB2CE", sz="18")


def render_hr(doc):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(6)
    add_bottom_border(p, color="C9D2E0", sz="8")


def render_heading(doc, level, text):
    h = doc.add_heading(level=level)
    add_inline(h, text)
    for run in h.runs:
        run.font.name = CN_FONT
        rPr = run._element.get_or_add_rPr()
        rFonts = rPr.get_or_add_rFonts()
        rFonts.set(qn("w:eastAsia"), CN_FONT)
        rFonts.set(qn("w:ascii"), CN_FONT)
        rFonts.set(qn("w:hAnsi"), CN_FONT)
        run.font.color.rgb = RGBColor(0x1A, 0x1A, 0x1A)
        run.bold = True
    if level == 1:
        add_bottom_border(h, color="3B6FD4", sz="12")
    return h


def render_list_item(doc, indent_level, text, ordered, marker):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.75 + 0.6 * indent_level)
    p.paragraph_format.first_line_indent = Cm(-0.45)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.line_spacing = 1.25
    prefix = f"{marker} " if ordered else "• "
    style_run(p.add_run(prefix), size=BODY_SIZE)
    add_inline(p, text)
    return p


def convert(md_path, docx_path):
    text = md_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    doc = init_document()
    add_footer_page_number(doc)

    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        fence = FENCE_RE.match(line)
        if fence:
            i += 1
            code_lines = []
            while i < n and not FENCE_RE.match(lines[i]):
                code_lines.append(lines[i])
                i += 1
            if i < n:
                i += 1
            render_code_block(doc, code_lines)
            continue

        if HR_RE.match(line) and not LIST_RE.match(line):
            render_hr(doc)
            i += 1
            continue

        if stripped.startswith("|") and i + 1 < n:
            sep_cells = split_table_row(lines[i + 1])
            if sep_cells and all(ALIGN_RE.match(c) for c in sep_cells):
                header = split_table_row(lines[i])
                aligns = parse_align_row(lines[i + 1])
                i += 2
                rows = []
                while i < n and lines[i].strip().startswith("|"):
                    rows.append(split_table_row(lines[i]))
                    i += 1
                render_table(doc, header, rows, aligns)
                continue

        h = HEADING_RE.match(stripped)
        if h:
            render_heading(doc, len(h.group(1)), h.group(2).strip())
            i += 1
            continue

        if stripped.startswith(">"):
            quote_lines = []
            while i < n and lines[i].strip().startswith(">"):
                quote_lines.append(lines[i].strip().lstrip(">").strip())
                i += 1
            render_quote(doc, " ".join(q for q in quote_lines if q))
            continue

        m = LIST_RE.match(line)
        if m:
            indent_str, marker, content = m.group(1), m.group(2), m.group(3)
            indent_level = len(indent_str.replace("\t", "  ")) // 2
            ordered = bool(re.match(r"^\d", marker))
            render_list_item(doc, indent_level, content, ordered, marker)
            i += 1
            continue

        para_lines = [stripped]
        i += 1
        while i < n:
            nxt = lines[i]
            s = nxt.strip()
            if (not s or FENCE_RE.match(nxt) or HEADING_RE.match(s)
                    or s.startswith("|") or s.startswith(">")
                    or LIST_RE.match(nxt) or HR_RE.match(nxt)):
                break
            para_lines.append(s)
            i += 1

        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(5)
        p.paragraph_format.line_spacing = 1.3
        add_inline(p, " ".join(para_lines))

    doc.save(docx_path)
    return doc


def main(argv):
    if len(argv) < 2:
        print("用法: uv run --with python-docx python tools/md2docx.py <input.md> [output.docx]")
        return 1
    md_path = Path(argv[1])
    if not md_path.exists():
        print(f"错误: 文件不存在 -> {md_path}")
        return 1
    docx_path = Path(argv[2]) if len(argv) > 2 else md_path.with_suffix(".docx")
    convert(md_path, docx_path)
    size_kb = docx_path.stat().st_size / 1024
    print(f"转换完成: {md_path.name} -> {docx_path}  ({size_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))


