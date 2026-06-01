# Academic PDF Fixtures

Deterministic academic PDF fixtures for Docling probe testing and integration regression.

## Fixture Classification

| File | Purpose | Used by | Expected signal | Not an eval |
|---|---|---|---|---|
| `sample_academic.pdf` | Automated regression + probe | `test_v0_endpoints.py` (Gate A integration), `scripts/probe_docling_pdf.py` | Academic sparse fields (`paper_title_tks`, `caption_tks`) populated after full ingestion; title, abstract, sections, table/figure with captions, references | Yes -- fixtures verify signal presence, not retrieval quality |
| `two_column_academic.pdf` | Probe | `scripts/probe_docling_pdf.py --input <path>` | Left-column-before-right reading order, table in column flow, section headings across columns | Yes |
| `ambiguous_caption.pdf` | Probe | `scripts/probe_docling_pdf.py --input <path>` | Parallel caption structure with reversed ordering; table/figure pairs with similar captions | Yes |

Supporting artifacts:

| File | Purpose |
|---|---|
| `_probe_fig_*.png` | Deterministic PNG images embedded in PDFs by `generate_fixtures.py` |
| `generate_fixtures.py` | ReportLab-based generator; single source of truth for fixture content |

## Fixtures

| File | Key Signals |
|---|---|
| `sample_academic.pdf` | Title, abstract, sections, table with caption, figure with caption, references |
| `two_column_academic.pdf` | Reading order preservation, table in column layout, section headings across columns |
| `ambiguous_caption.pdf` | Table and figure pairs with parallel caption structure, reversed ordering case |

## Generation

These fixtures are generated programmatically by `generate_fixtures.py` using ReportLab.

```bash
.venv/bin/python tests/fixtures/documents/academic_pdf/generate_fixtures.py
```

Do not edit PDFs directly. Regenerate from the script if changes are needed.

## Content Design

### sample_academic.pdf

- Title: "GraphRAG: Retrieval-Augmented Generation with Graph-Based Evidence Aggregation"
- Authors: Alice Zhang, Bob Smith, Carol Lee
- Abstract section
- Four numbered sections: Introduction, Method, Results, Conclusion
- Table 1 with caption comparing retrieval methods (4 rows x 4 columns)
- Figure 1 with caption showing accuracy improvement
- Three references

### two_column_academic.pdf

- Title page with single-column layout (title, authors, abstract)
- Body pages with two-column layout
- Four numbered sections spanning columns: Introduction, Related Work, Experimental Results, Conclusion
- Table 1 embedded within column flow
- Tests that Docling preserves left-column-before-right-column reading order

### ambiguous_caption.pdf

- Title: "Caption Binding Ambiguity in Academic Document Parsing"
- Two ambiguous pairs:
  1. Table with "Overview of the dataset statistics..." followed immediately by figure with "Overview of the data distribution..."
  2. Figure with "Summary of the model architecture..." followed by table with "Summary of the training hyperparameters..."
- Parallel caption structure is intentional to test caption binding heuristics
