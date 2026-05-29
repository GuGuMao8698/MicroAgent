# Academic PDF Fixtures

Deterministic academic PDF fixtures for Docling probe testing.

## Fixtures

| File | Purpose | Key Signals |
|---|---|---|
| `sample_academic.pdf` | Standard single-column academic paper | Title, abstract, sections, table with caption, figure with caption, references |
| `two_column_academic.pdf` | Two-column layout paper | Reading order preservation, table in column layout, section headings across columns |
| `ambiguous_caption.pdf` | Caption binding ambiguity test | Table and figure pairs with parallel caption structure, reversed ordering case |

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
