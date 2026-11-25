import sys
import pymupdf
SRC = "/root/.claude/uploads/64095e88-5c73-5a92-a8c8-b9b2ef758b19/1ad5d914-1st_page...pdf"

def cover(doc_type: str, out: str) -> None:
    src = pymupdf.open(SRC)
    doc = pymupdf.open()
    doc.insert_pdf(src, from_page=0, to_page=0)
    p = doc[0]
    # remove only the old title block (y 300–415), keep logo, border, university, school, semester, name, year
    p.add_redact_annot(pymupdf.Rect(60, 300, 552, 416))
    p.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
    W = p.rect.width
    def center(y, text, size, bold):
        font = "tibo" if bold else "tiro"
        w = pymupdf.get_text_length(text, fontname=font, fontsize=size)
        p.insert_text(((W - w) / 2, y), text, fontname=font, fontsize=size)
    center(323, doc_type, 12, True)
    for i, line in enumerate(["FINRAG: AI-POWERED FINANCIAL DATA ANALYTICS", "USING RAG AND DASHBOARD GENERATION"]):
        center(350 + i * 23, line, 17, True)
    center(402, "Multi-format extraction, validation, RAG, automatic dashboards and a dashboard-aware AI assistant", 10.5, False)
    doc.save(out)

cover("PROJECT SYNOPSIS", "cover_synopsis.pdf")
cover("PROJECT REPORT", "cover_report.pdf")
img = pymupdf.open(SRC).extract_image(23)
open("logo." + img["ext"], "wb").write(img["image"])
d = pymupdf.open("cover_report.pdf"); d[0].get_pixmap(dpi=80).save("cover_report.png")
print("ok", img["ext"], img["width"], img["height"])
