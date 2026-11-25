"""Standalone Docling table extractor, run in its OWN virtualenv.

Docling's dependency set (docling-ibm-models requires huggingface_hub<2 and a
specific torchvision) conflicts with the main backend's transformers 5.x, so it
is executed as a subprocess:

    $DOCLING_PYTHON docling_runner.py <file.pdf>  ->  JSON on stdout

Output: {"tables": [{"page": int, "bbox": [l,t,r,b] | null, "header": [...], "rows": [[...]]}], "docling_version": "..."}
This file must not import anything from the FinRAG `app` package.
"""
import json
import sys


def main(path: str) -> None:
    import docling
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions()
    opts.do_ocr = False  # FinRAG performs OCR itself with Tesseract
    opts.do_table_structure = True
    conv = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
    res = conv.convert(path)
    out = []
    for t in res.document.tables:
        df = t.export_to_dataframe(doc=res.document)
        prov = t.prov[0] if t.prov else None
        bbox = None
        if prov is not None and prov.bbox is not None:
            b = prov.bbox
            bbox = [round(b.l, 1), round(b.t, 1), round(b.r, 1), round(b.b, 1)]
        out.append({
            "page": prov.page_no if prov is not None else None,
            "bbox": bbox,
            "header": [str(c) for c in df.columns],
            "rows": [[("" if v is None else str(v)) for v in row] for row in df.itertuples(index=False, name=None)],
        })
    print(json.dumps({"tables": out, "docling_version": getattr(docling, "__version__", "unknown")}))


if __name__ == "__main__":
    main(sys.argv[1])
