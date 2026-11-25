# Test and evaluation documents (not part of the product)

FinRAG ships with **no documents and no company data**. To reproduce the accuracy tests and the
evaluation runs reported in `docs/EVALUATION.md`, download these publicly available annual reports
from the issuer's official investor-relations website into `$FINRAG_TEST_DOCS` (default
`/opt/finrag_testdocs`) and check the hashes. They are used only as test inputs, in the isolated test
database or a development database.

| File | Official source | SHA-256 |
|---|---|---|
| RIL-Integrated-Annual-Report-2024-25.pdf | https://rilstaticasset.akamaized.net/sites/default/files/2025-08/RIL-Integrated-Annual-Report-2024-25.pdf | bb541a68a0440fd4e27527afbb79f9a0e7584ae430fe9af244700709cacc0769 |
| RIL-Integrated-Annual-Report-2023-24.pdf | https://rilstaticasset.akamaized.net/sites/default/files/2024-08/RIL-Integrated-Annual-Report-2023-24.pdf | d8e3739d2e06f09b83a192e00cefda0113b5da778483e31018cb35429e72eafe |
| RIL-Financial-Highlights-10-years.pdf | https://rilstaticasset.akamaized.net/sites/default/files/2022-12/Fianncial%20Highlights%2010%20years.pdf | 8dd8237e21ce4d6d082e263855eb9c30b072533a9430971b0b005a3e3f96d1df |

(The URLs were linked from https://www.ril.com/investors/financial-reporting when downloaded on
2026-11-23; the CDN redirects to www.ril.com.)

Derived DOCX/XLSX/XLS/CSV inputs are produced from pages 57–58 of the FY2024-25 report:
```bash
cd backend && PYTHONPATH=. python tests/fixtures/build_derived_fixtures.py \
  /opt/finrag_testdocs/RIL-Integrated-Annual-Report-2024-25.pdf 57 58 --out /opt/finrag_testdocs/derived
```

Gold files in this folder:
* `gold_extraction_public_annual_report.jsonl` — 15 statement values with expected basis/period.
* `gold_rag_public_annual_report.jsonl` — 8 questions with expected numbers and PDF pages.

Each expected value was checked against the PDF text before use. Upload the PDF with its original
filename so the `document_filename(s)` references resolve.
