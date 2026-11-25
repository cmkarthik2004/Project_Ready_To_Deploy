"""Small python-docx helpers shared by the synopsis, report and paper builders."""
from __future__ import annotations

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

FIG = "/tmp/claude-0/sp/papers/fig/"
SHOTS = "/home/user/Ready_To_Deploy/docs/screenshots/"


class Doc:
    def __init__(self, font="Times New Roman", size=12, margins_cm=2.5, line=1.15):
        self.d = Document()
        st = self.d.styles["Normal"]
        st.font.name = font
        st.font.size = Pt(size)
        st.element.rPr.rFonts.set(qn("w:eastAsia"), font)
        st.paragraph_format.space_after = Pt(6)
        st.paragraph_format.line_spacing = line
        for lvl, sz in ((1, size + 4), (2, size + 2), (3, size + 1)):
            h = self.d.styles[f"Heading {lvl}"]
            h.font.name = font
            h.font.size = Pt(sz)
            h.font.bold = True
            h.font.color.rgb = RGBColor(0x10, 0x10, 0x10)
            rf = h.element.rPr.rFonts
            for a in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
                if rf.get(qn(a)) is not None:
                    del rf.attrib[qn(a)]
            for a in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
                rf.set(qn(a), font)
            h.paragraph_format.space_before = Pt(12 if lvl == 1 else 8)
            h.paragraph_format.space_after = Pt(4)
            h.paragraph_format.keep_with_next = True
        for s in self.d.sections:
            s.left_margin = s.right_margin = s.top_margin = s.bottom_margin = Cm(margins_cm)
        self.fig_n = 0
        self.tab_n = 0
        self.size = size
        self.headings: list[tuple[int, str]] = []

    # ------------------------------------------------------------------ text
    def h(self, text, level=1):
        self.headings.append((level, text))
        return self.d.add_heading(text, level)

    def toc_static(self, entries):
        """Static table of contents: entries = [(level, text, page)]; page numbers measured from the rendered PDF."""
        from docx.enum.text import WD_TAB_ALIGNMENT, WD_TAB_LEADER
        for level, text, page in entries:
            para = self.d.add_paragraph()
            para.paragraph_format.tab_stops.add_tab_stop(Cm(16), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
            para.paragraph_format.left_indent = Cm(0 if level == 1 else 0.8)
            para.paragraph_format.space_after = Pt(1)
            r = para.add_run(f"{text}\t{page}")
            r.bold = level == 1
            r.font.size = Pt(self.size - (0 if level == 1 else 1))

    def p(self, text="", bold=False, italic=False, align=None, size=None, after=None):
        para = self.d.add_paragraph()
        self._runs(para, text, bold, italic, size)
        if align == "center":
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif align == "justify" or align is None:
            para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        if after is not None:
            para.paragraph_format.space_after = Pt(after)
        return para

    def _runs(self, para, text, bold=False, italic=False, size=None):
        # **bold** segments inside text
        parts = text.split("**")
        for i, part in enumerate(parts):
            if not part:
                continue
            r = para.add_run(part)
            r.bold = bold or (i % 2 == 1)
            r.italic = italic
            if size:
                r.font.size = Pt(size)

    def bullets(self, items, numbered=False):
        for it in items:
            para = self.d.add_paragraph(style="List Number" if numbered else "List Bullet")
            self._runs(para, it)
            para.paragraph_format.space_after = Pt(2)
            para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    def table(self, header, rows, caption=None, widths=None, size=None):
        if caption:
            self.tab_n += 1
            cp = self.d.add_paragraph()
            r = cp.add_run(f"Table {self.tab_n}: {caption}")
            r.bold = True
            r.font.size = Pt((size or self.size) - 1)
            cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            cp.paragraph_format.keep_with_next = True
        t = self.d.add_table(rows=1, cols=len(header))
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        fs = Pt((size or self.size) - 2)
        for i, hd in enumerate(header):
            c = t.rows[0].cells[i]
            c.text = ""
            run = c.paragraphs[0].add_run(str(hd))
            run.bold = True
            run.font.size = fs
            self._shade(c, "D9E6F5")
        for row in rows:
            cells = t.add_row().cells
            for i, v in enumerate(row):
                cells[i].text = ""
                run = cells[i].paragraphs[0].add_run(str(v))
                run.font.size = fs
        if widths:
            for row in t.rows:
                for i, w in enumerate(widths):
                    row.cells[i].width = Cm(w)
        self.d.add_paragraph().paragraph_format.space_after = Pt(2)
        return t

    @staticmethod
    def _shade(cell, hex_fill):
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), hex_fill)
        tcPr.append(shd)

    def figure(self, path, caption, width_cm=15.5):
        self.fig_n += 1
        para = self.d.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.add_run().add_picture(path, width=Cm(width_cm))
        para.paragraph_format.keep_with_next = True
        cp = self.d.add_paragraph()
        r = cp.add_run(f"Figure {self.fig_n}: {caption}")
        r.italic = True
        r.font.size = Pt(self.size - 1)
        cp.alignment = WD_ALIGN_PARAGRAPH.CENTER

    def page_break(self):
        self.d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def toc(self):
        para = self.d.add_paragraph()
        run = para.add_run()
        for tag, text in (("begin", None), (None, 'TOC \\o "1-2" \\h \\z \\u'), ("separate", None), (None, None), ("end", None)):
            if tag:
                fc = OxmlElement("w:fldChar")
                fc.set(qn("w:fldCharType"), tag)
                run._r.append(fc)
            elif text:
                it = OxmlElement("w:instrText")
                it.set(qn("xml:space"), "preserve")
                it.text = text
                run._r.append(it)
            else:
                t = OxmlElement("w:t")
                t.text = "Table of contents (right-click → Update field if empty)."
                run._r.append(t)

    def columns(self, n):
        """Start a new continuous section with n text columns."""
        sec = self.d.add_section(WD_SECTION.CONTINUOUS)
        cols = sec._sectPr.xpath("./w:cols")
        el = cols[0] if cols else OxmlElement("w:cols")
        el.set(qn("w:num"), str(n))
        el.set(qn("w:space"), "500")
        if not cols:
            sec._sectPr.append(el)
        return sec

    def footer_page_numbers(self):
        for s in self.d.sections[:1]:  # later sections inherit (linked) footers
            para = s.footer.paragraphs[0]
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = para.add_run()
            for tag, text in (("begin", None), (None, "PAGE"), ("end", None)):
                if tag:
                    fc = OxmlElement("w:fldChar")
                    fc.set(qn("w:fldCharType"), tag)
                    run._r.append(fc)
                else:
                    it = OxmlElement("w:instrText")
                    it.set(qn("xml:space"), "preserve")
                    it.text = text
                    run._r.append(it)

    def save(self, path):
        self.d.save(path)


TITLE = "FinRAG: AI-Powered Financial Data Analytics Using RAG and Dashboard Generation"

REFERENCES = [
    "P. Lewis, E. Perez, A. Piktus, F. Petroni, V. Karpukhin, N. Goyal, H. Küttler, M. Lewis, W. Yih, T. Rocktäschel, S. Riedel and D. Kiela, “Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks,” in Advances in Neural Information Processing Systems (NeurIPS), 2020.",
    "Y. Gao, Y. Xiong, X. Gao, K. Jia, J. Pan, Y. Bi, Y. Dai, J. Sun, M. Wang and H. Wang, “Retrieval-Augmented Generation for Large Language Models: A Survey,” arXiv:2312.10997, 2023.",
    "Z. Ji, N. Lee, R. Frieske, T. Yu, D. Su, Y. Xu, E. Ishii, Y. Bang, A. Madotto and P. Fung, “Survey of Hallucination in Natural Language Generation,” ACM Computing Surveys, vol. 55, no. 12, 2023.",
    "Z. Chen, W. Chen, C. Smiley, S. Shah, I. Borova, D. Langdon, R. Moussa, M. Beane, T.-H. Huang, B. Routledge and W. Y. Wang, “FinQA: A Dataset of Numerical Reasoning over Financial Data,” in Proc. EMNLP, 2021.",
    "F. Zhu, W. Lei, Y. Huang, C. Wang, S. Zhang, J. Lv, F. Feng and T.-S. Chua, “TAT-QA: A Question Answering Benchmark on a Hybrid of Tabular and Textual Content in Finance,” in Proc. ACL, 2021.",
    "E. J. Hu, Y. Shen, P. Wallis, Z. Allen-Zhu, Y. Li, S. Wang, L. Wang and W. Chen, “LoRA: Low-Rank Adaptation of Large Language Models,” in Proc. ICLR, 2022.",
    "T. Dettmers, A. Pagnoni, A. Holtzman and L. Zettlemoyer, “QLoRA: Efficient Finetuning of Quantized LLMs,” in Advances in Neural Information Processing Systems (NeurIPS), 2023.",
    "S. Xiao, Z. Liu, P. Zhang and N. Muennighoff, “C-Pack: Packaged Resources To Advance General Chinese Embedding,” arXiv:2309.07597, 2023.",
    "R. Nogueira and K. Cho, “Passage Re-ranking with BERT,” arXiv:1901.04085, 2019.",
    "S. Robertson and H. Zaragoza, “The Probabilistic Relevance Framework: BM25 and Beyond,” Foundations and Trends in Information Retrieval, vol. 3, no. 4, 2009.",
    "S. Es, J. James, L. Espinosa-Anke and S. Schockaert, “RAGAS: Automated Evaluation of Retrieval Augmented Generation,” arXiv:2309.15217, 2023.",
    "R. Smith, “An Overview of the Tesseract OCR Engine,” in Proc. Ninth International Conference on Document Analysis and Recognition (ICDAR), 2007.",
    "Qwen Team, “Qwen3 Technical Report,” arXiv:2505.09388, 2025.",
    "N. Reimers and I. Gurevych, “Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks,” in Proc. EMNLP-IJCNLP, 2019.",
]


def references(doc: Doc, numbered=True):
    for i, r in enumerate(REFERENCES, 1):
        para = doc.d.add_paragraph()
        run = para.add_run(f"[{i}] {r}")
        run.font.size = Pt(doc.size - 1)
        para.paragraph_format.space_after = Pt(3)
        para.paragraph_format.left_indent = Cm(0.6)
        para.paragraph_format.first_line_indent = Cm(-0.6)


def university_cover(doc: Doc, doc_type: str) -> None:
    """Cover page in the university's format (logo, university, school, document type, title, programme, student, year)."""
    def line(text, size, bold=False, before=0, after=4):
        para = doc.d.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.paragraph_format.space_before = Pt(before)
        para.paragraph_format.space_after = Pt(after)
        r = para.add_run(text)
        r.bold = bold
        r.font.size = Pt(size)
    para = doc.d.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para.paragraph_format.space_before = Pt(40)
    para.add_run().add_picture("/tmp/claude-0/sp/cover/logo.jpeg", width=Cm(4))
    line("DAYANANDA SAGAR UNIVERSITY", 26, True, before=10)
    line("School Of Computer Application", 16, True, after=24)
    line(doc_type, 12, True)
    for t in ("FINRAG: AI-POWERED FINANCIAL DATA ANALYTICS", "USING RAG AND DASHBOARD GENERATION"):
        line(t, 17, True, after=0)
    line("Multi-format extraction, validation, RAG, automatic dashboards and a dashboard-aware AI assistant", 10.5, before=4, after=24)
    line("MSc – III Semester  |  Experiential Learning", 11, after=24)
    line("Presented by:", 12, True, after=2)
    line("C M Karthik- SCA25MSD019", 10, True, after=24)
    line("Academic Year: 2026", 10)
    doc.page_break()
