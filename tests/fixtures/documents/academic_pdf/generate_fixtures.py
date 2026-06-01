"""Generate deterministic academic PDF fixtures for Docling probe testing.

Run: .venv/bin python tests/fixtures/documents/academic_pdf/generate_fixtures.py

Produces:
  - sample_academic.pdf: title, abstract, >=1 section, >=1 table with caption,
    >=1 figure with caption
  - two_column_academic.pdf: two-column layout (tests reading order)
  - ambiguous_caption.pdf: table and figure near each other with similar-looking
    caption text (tests caption binding ambiguity)
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from reportlab.lib.colors import black
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus import (
    Image as RLImage,
)

OUT_DIR = Path(__file__).resolve().parent


def _make_dummy_figure(
    width: int = 200, height: int = 120, color: tuple = (100, 150, 200)
) -> Path:
    """Create a small deterministic PNG for figure fixtures."""
    img = Image.new("RGB", (width, height), color=color)
    path = OUT_DIR / f"_probe_fig_{width}x{height}.png"
    img.save(path, "PNG")
    return path


def _body_style() -> ParagraphStyle:
    return ParagraphStyle(
        "Body",
        parent=getSampleStyleSheet()["Normal"],
        fontSize=10,
        leading=14,
        alignment=TA_JUSTIFY,
        spaceAfter=6,
    )


def _title_style() -> ParagraphStyle:
    return ParagraphStyle(
        "PaperTitle",
        parent=getSampleStyleSheet()["Title"],
        fontSize=16,
        leading=20,
        alignment=TA_CENTER,
        spaceAfter=4,
    )


def _author_style() -> ParagraphStyle:
    return ParagraphStyle(
        "Author",
        parent=getSampleStyleSheet()["Normal"],
        fontSize=11,
        leading=14,
        alignment=TA_CENTER,
        spaceAfter=2,
    )


def _section_style() -> ParagraphStyle:
    return ParagraphStyle(
        "SectionHeading",
        parent=getSampleStyleSheet()["Heading1"],
        fontSize=12,
        leading=16,
        spaceBefore=12,
        spaceAfter=6,
    )


def _subsection_style() -> ParagraphStyle:
    return ParagraphStyle(
        "SubsectionHeading",
        parent=getSampleStyleSheet()["Heading2"],
        fontSize=11,
        leading=14,
        spaceBefore=8,
        spaceAfter=4,
    )


def _caption_style() -> ParagraphStyle:
    return ParagraphStyle(
        "Caption",
        parent=getSampleStyleSheet()["Normal"],
        fontSize=9,
        leading=12,
        alignment=TA_CENTER,
        spaceBefore=4,
        spaceAfter=8,
    )


def _abstract_style() -> ParagraphStyle:
    return ParagraphStyle(
        "AbstractBody",
        parent=getSampleStyleSheet()["Normal"],
        fontSize=9,
        leading=12,
        alignment=TA_JUSTIFY,
        leftIndent=36,
        rightIndent=36,
        spaceAfter=6,
    )


# ---------------------------------------------------------------------------
# Fixture 1: sample_academic.pdf
# ---------------------------------------------------------------------------

LOREM = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod "
    "tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim "
    "veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea "
    "commodo consequat. Duis aute irure dolor in reprehenderit in voluptate "
    "velit esse cillum dolore eu fugiat nulla pariatur."
)

BODY_PARAS = [
    "Retrieval-augmented generation (RAG) has emerged as a leading approach for "
    "grounding language model outputs in external knowledge. Despite significant "
    "progress, current systems struggle with multi-hop reasoning over heterogeneous "
    "document collections. In this work we propose GraphRAG, a method that combines "
    "dense retrieval with graph-based evidence aggregation.",
    "Our experiments on three benchmark datasets show that GraphRAG improves "
    "answer accuracy by 12.3% over dense retrieval baselines. The gains are "
    "most pronounced on questions requiring cross-document evidence synthesis.",
    "The model architecture consists of three components: a dense retriever, a "
    "graph constructor, and an answer generator. Each component can be trained "
    "independently or end-to-end. We found that end-to-end training provides "
    "marginal improvements at significantly higher computational cost.",
]


def build_sample_academic() -> list:
    """Build story for sample_academic.pdf."""
    story: list = []

    # Title
    story.append(
        Paragraph(
            "GraphRAG: Retrieval-Augmented Generation with Graph-Based Evidence Aggregation",
            _title_style(),
        )
    )

    # Authors
    story.append(Paragraph("Alice Zhang, Bob Smith, Carol Lee", _author_style()))
    story.append(
        Paragraph(
            "University of Example, Department of Computer Science", _author_style()
        )
    )
    story.append(Spacer(1, 12))

    # Abstract
    story.append(Paragraph("Abstract", _section_style()))
    story.append(
        Paragraph(
            "We present GraphRAG, a novel method combining dense retrieval with graph-based "
            "evidence aggregation for multi-hop question answering. Experiments on three "
            "benchmarks show 12.3% accuracy improvement over dense retrieval baselines. "
            "Our approach is particularly effective for cross-document reasoning tasks.",
            _abstract_style(),
        )
    )

    # Section 1: Introduction
    story.append(Paragraph("1. Introduction", _section_style()))
    story.append(Paragraph(BODY_PARAS[0], _body_style()))
    story.append(Paragraph(BODY_PARAS[1], _body_style()))

    # Section 2: Method
    story.append(Paragraph("2. Method", _section_style()))
    story.append(Paragraph("2.1 Architecture Overview", _subsection_style()))
    story.append(Paragraph(BODY_PARAS[2], _body_style()))

    # Table with caption
    table_data = [
        ["Method", "EM", "F1", "Recall"],
        ["Dense Retrieval", "45.2", "52.1", "48.7"],
        ["BM25 + Rerank", "41.8", "48.9", "45.3"],
        ["GraphRAG (ours)", "57.5", "63.4", "59.1"],
    ]
    t = Table(table_data, colWidths=[1.8 * inch, 0.8 * inch, 0.8 * inch, 0.8 * inch])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), (0.85, 0.85, 0.85)),
                ("GRID", (0, 0), (-1, -1), 0.5, black),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        KeepTogether(
            [
                t,
                Paragraph(
                    "Table 1: Comparison of retrieval methods on the MultiHopQA benchmark.",
                    _caption_style(),
                ),
            ]
        )
    )
    story.append(Spacer(1, 8))

    # Section 3: Results
    story.append(Paragraph("3. Results", _section_style()))
    story.append(
        Paragraph(
            "Our main results are summarized in Table 1. GraphRAG achieves the highest "
            "scores across all three metrics. The improvement is statistically significant "
            "with p < 0.01 under paired bootstrap resampling.",
            _body_style(),
        )
    )

    # Figure with caption
    fig_path = _make_dummy_figure(240, 140, (80, 130, 180))
    story.append(Spacer(1, 8))
    story.append(
        KeepTogether(
            [
                RLImage(str(fig_path), width=240, height=140),
                Paragraph(
                    "Figure 1: Accuracy improvement of GraphRAG over baselines across benchmark datasets.",
                    _caption_style(),
                ),
            ]
        )
    )
    story.append(Spacer(1, 8))

    # Section 4: Conclusion
    story.append(Paragraph("4. Conclusion", _section_style()))
    story.append(
        Paragraph(
            "We introduced GraphRAG, a method that augments dense retrieval with graph-based "
            "evidence aggregation. Our experiments demonstrate consistent improvements over "
            "strong baselines on multi-hop question answering benchmarks. Future work will "
            "explore scaling to larger document collections and incorporating structured "
            "knowledge sources.",
            _body_style(),
        )
    )

    # References
    story.append(Paragraph("References", _section_style()))
    for _, ref in enumerate(
        [
            "[1] Lewis, P. et al. Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. NeurIPS 2020.",
            "[2] Borgeaud, S. et al. Improving Language Models by Retrieving from Trillions of Tokens. ICML 2022.",
            "[3] Asai, A. et al. Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection. ICLR 2024.",
        ],
        start=1,
    ):
        story.append(
            Paragraph(
                ref,
                ParagraphStyle(
                    "Ref", parent=_body_style(), fontSize=9, leading=12, spaceAfter=3
                ),
            )
        )

    return story


def generate_sample_academic() -> Path:
    out = OUT_DIR / "sample_academic.pdf"
    doc = BaseDocTemplate(
        str(out),
        pagesize=letter,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
        topMargin=1 * inch,
        bottomMargin=1 * inch,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="single", frames=[frame])])
    doc.build(build_sample_academic())
    return out


# ---------------------------------------------------------------------------
# Fixture 2: two_column_academic.pdf
# ---------------------------------------------------------------------------

LEFT_COL_TEXT = [
    "The study of information retrieval has a long and rich history in computer "
    "science. Early systems relied on boolean queries and inverted indices to "
    "match documents to user needs. With the advent of statistical methods and "
    "machine learning, ranking functions became more sophisticated.",
    "In recent years, neural retrieval models have achieved remarkable "
    "improvements. Dense passage retrieval using bi-encoder architectures "
    "enables semantic matching beyond lexical overlap. Cross-encoder rerankers "
    "further improve precision at the cost of additional computation.",
]

RIGHT_COL_TEXT = [
    "The transformer architecture has become the dominant model for both "
    "retrieval and generation tasks. Pre-trained language models such as BERT "
    "and T5 provide strong initialization for domain-specific fine-tuning. "
    "Scaling laws suggest that performance continues to improve with model "
    "size and training data.",
    "Despite these advances, challenges remain in handling long documents, "
    "multi-modal content, and cross-lingual retrieval. The cost of deploying "
    "large models at inference time is also a significant practical concern. "
    "Efficient architectures such as ColBERT and PLAID aim to address these "
    "issues.",
]

SECTION_INTRO_LEFT = [
    "Knowledge-intensive NLP tasks such as question answering, fact checking, "
    "and dialogue require access to external information. Retrieval-augmented "
    "generation (RAG) systems address this by grounding generation in retrieved "
    "documents.",
]

SECTION_INTRO_RIGHT = [
    "However, naive RAG systems struggle with complex queries that require "
    "reasoning across multiple documents. Graph-based approaches have shown "
    "promise in aggregating evidence from heterogeneous sources.",
]

RESULTS_LEFT = [
    "We evaluated our approach on three standard benchmarks: MultiHopQA, "
    "HotpotQA, and MuSiQue. Table 1 summarizes the main results. Our method "
    "outperforms all baselines on MultiHopQA and HotpotQA.",
]

RESULTS_RIGHT = [
    "On MuSiQue, our method is competitive with the state of the art despite "
    "using a smaller retrieval model. Ablation studies show that the graph "
    "construction module contributes the most to performance gains, followed "
    "by the evidence aggregation strategy.",
]


def generate_two_column_academic() -> Path:
    out = OUT_DIR / "two_column_academic.pdf"
    doc = BaseDocTemplate(
        str(out),
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=1 * inch,
        bottomMargin=1 * inch,
    )

    # Single-column frame for title/abstract
    single_frame = Frame(
        doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="single"
    )

    # Two-column frames
    col_width = (doc.width - 0.3 * inch) / 2
    left_frame = Frame(
        doc.leftMargin, doc.bottomMargin, col_width, doc.height, id="left"
    )
    right_frame = Frame(
        doc.leftMargin + col_width + 0.3 * inch,
        doc.bottomMargin,
        col_width,
        doc.height,
        id="right",
    )

    doc.addPageTemplates(
        [
            PageTemplate(id="single", frames=[single_frame]),
            PageTemplate(id="twocol", frames=[left_frame, right_frame]),
        ]
    )

    story: list = []

    # Title page (single column)
    story.append(
        Paragraph(
            "Two-Column Academic Paper: A Study in Reading Order Preservation",
            _title_style(),
        )
    )
    story.append(Paragraph("David Chen, Eve Williams", _author_style()))
    story.append(Paragraph("Institute for Advanced Retrieval Studies", _author_style()))
    story.append(Spacer(1, 12))

    # Abstract
    story.append(Paragraph("Abstract", _section_style()))
    story.append(
        Paragraph(
            "This paper presents a two-column layout fixture designed to test whether "
            "PDF parsing tools correctly preserve reading order. The left column should "
            "be read before the right column on each page. The introduction continues "
            "in the left column of the next section.",
            _abstract_style(),
        )
    )
    story.append(Spacer(1, 8))

    # Switch to two-column layout
    story.append(NextPageTemplate("twocol"))
    story.append(Spacer(1, 1))

    # Page 2+: Two-column content
    story.append(Paragraph("1. Introduction", _section_style()))

    for para in SECTION_INTRO_LEFT:
        story.append(Paragraph(para, _body_style()))
    for para in LEFT_COL_TEXT:
        story.append(Paragraph(para, _body_style()))

    for para in SECTION_INTRO_RIGHT:
        story.append(Paragraph(para, _body_style()))
    for para in RIGHT_COL_TEXT:
        story.append(Paragraph(para, _body_style()))

    story.append(Paragraph("2. Related Work", _section_style()))

    story.append(
        Paragraph(
            "Neural retrieval models have shown impressive performance gains over "
            "traditional methods. DPR, ANCE, and ColBERT represent different points "
            "in the design space of dense retrieval systems.",
            _body_style(),
        )
    )
    story.append(
        Paragraph(
            "Graph neural networks have been applied to various NLP tasks including "
            "relation extraction, document classification, and multi-hop reasoning. "
            "Recent work explores combining retrieval with graph-based reasoning.",
            _body_style(),
        )
    )

    story.append(Paragraph("3. Experimental Results", _section_style()))

    for para in RESULTS_LEFT:
        story.append(Paragraph(para, _body_style()))

    # Small table
    table_data = [
        ["Method", "F1", "EM"],
        ["DPR", "62.3", "48.1"],
        ["ColBERT", "65.7", "51.4"],
        ["Ours", "71.2", "56.8"],
    ]
    t = Table(table_data, colWidths=[1.2 * inch, 0.6 * inch, 0.6 * inch])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), (0.85, 0.85, 0.85)),
                ("GRID", (0, 0), (-1, -1), 0.5, black),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    story.append(Spacer(1, 4))
    story.append(t)
    story.append(
        Paragraph("Table 1: Main results on multi-hop QA benchmarks.", _caption_style())
    )

    for para in RESULTS_RIGHT:
        story.append(Paragraph(para, _body_style()))

    story.append(Paragraph("4. Conclusion", _section_style()))
    story.append(
        Paragraph(
            "We demonstrated that reading order preservation is critical for two-column "
            "academic papers. Our results show consistent improvements when the correct "
            "reading order is maintained. Future work will explore more complex layouts.",
            _body_style(),
        )
    )

    doc.build(story)
    return out


# ---------------------------------------------------------------------------
# Fixture 3: ambiguous_caption.pdf
# ---------------------------------------------------------------------------


def generate_ambiguous_caption() -> Path:
    """Table and figure near each other with similar-looking captions."""
    out = OUT_DIR / "ambiguous_caption.pdf"
    doc = BaseDocTemplate(
        str(out),
        pagesize=letter,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
        topMargin=1 * inch,
        bottomMargin=1 * inch,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="single", frames=[frame])])

    story: list = []

    # Title
    story.append(
        Paragraph(
            "Caption Binding Ambiguity in Academic Document Parsing",
            _title_style(),
        )
    )
    story.append(Paragraph("Frank Miller, Grace Park", _author_style()))
    story.append(Spacer(1, 12))

    # Abstract
    story.append(Paragraph("Abstract", _section_style()))
    story.append(
        Paragraph(
            "This fixture tests whether parsers correctly bind captions to their parent "
            "elements when a table and a figure appear in close proximity with "
            "similar-looking caption text. The captions below intentionally use "
            "parallel structure: both start with 'Overview of' followed by a "
            "description of their respective content.",
            _abstract_style(),
        )
    )

    # Introduction
    story.append(Paragraph("1. Introduction", _section_style()))
    story.append(
        Paragraph(
            "Academic documents often place tables and figures in close proximity, "
            "especially in results sections. This creates ambiguity for automated "
            "parsers that must decide which caption belongs to which element. We "
            "present a controlled fixture that exercises this ambiguity.",
            _body_style(),
        )
    )

    # A paragraph of text before the ambiguous pair
    story.append(
        Paragraph(
            "The following table and figure present our experimental setup and "
            "a visualization of the data distribution. Both elements carry captions "
            "with parallel structure to maximize binding ambiguity.",
            _body_style(),
        )
    )
    story.append(Spacer(1, 8))

    # Table with ambiguous caption
    table_data = [
        ["Dataset", "Samples", "Classes"],
        ["MNIST", "70000", "10"],
        ["CIFAR-10", "60000", "10"],
        ["ImageNet", "1.2M", "1000"],
    ]
    t = Table(table_data, colWidths=[1.5 * inch, 1 * inch, 1 * inch])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), (0.85, 0.85, 0.85)),
                ("GRID", (0, 0), (-1, -1), 0.5, black),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    story.append(t)
    story.append(
        Paragraph(
            "Overview of the dataset statistics used in our evaluation.",
            _caption_style(),
        )
    )
    story.append(Spacer(1, 12))

    # Figure with ambiguous caption right after
    fig_path = _make_dummy_figure(200, 100, (150, 100, 100))
    story.append(RLImage(str(fig_path), width=200, height=100))
    story.append(
        Paragraph(
            "Overview of the data distribution across training and test splits.",
            _caption_style(),
        )
    )
    story.append(Spacer(1, 12))

    # More text
    story.append(Paragraph("2. Analysis", _section_style()))
    story.append(
        Paragraph(
            "The key challenge in caption binding is determining whether 'Overview of "
            "the dataset statistics' belongs to the table and 'Overview of the data "
            "distribution' belongs to the figure, or vice versa. A robust parser "
            "should use element type cues (table vs. figure) and proximity to make "
            "the correct assignment.",
            _body_style(),
        )
    )
    story.append(
        Paragraph(
            "In this fixture, the table appears first with its caption immediately "
            "below, followed by the figure with its caption. The parallel caption "
            "structure is the intended ambiguity signal.",
            _body_style(),
        )
    )

    # Second ambiguous pair on a different page area
    story.append(Paragraph("3. Additional Ambiguity Case", _section_style()))
    story.append(
        Paragraph(
            "We include a second case with reversed ordering: figure first, then "
            "table, again with parallel captions.",
            _body_style(),
        )
    )
    story.append(Spacer(1, 8))

    fig_path2 = _make_dummy_figure(180, 90, (100, 160, 120))
    story.append(RLImage(str(fig_path2), width=180, height=90))
    story.append(
        Paragraph(
            "Summary of the model architecture components.",
            _caption_style(),
        )
    )
    story.append(Spacer(1, 8))

    table_data2 = [
        ["Component", "Parameters", "Layer Type"],
        ["Encoder", "85M", "Transformer"],
        ["Decoder", "92M", "Transformer"],
        ["Classifier", "1.2M", "Linear"],
    ]
    t2 = Table(table_data2, colWidths=[1.3 * inch, 1 * inch, 1.2 * inch])
    t2.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), (0.85, 0.85, 0.85)),
                ("GRID", (0, 0), (-1, -1), 0.5, black),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    story.append(t2)
    story.append(
        Paragraph(
            "Summary of the training hyperparameters and optimization settings.",
            _caption_style(),
        )
    )

    story.append(Spacer(1, 12))
    story.append(Paragraph("4. Conclusion", _section_style()))
    story.append(
        Paragraph(
            "This fixture provides a controlled test for caption binding ambiguity "
            "resolution. Parsers should be able to distinguish between table and "
            "figure captions even when they share similar sentence structure.",
            _body_style(),
        )
    )

    doc.build(story)
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    fixtures = [
        generate_sample_academic(),
        generate_two_column_academic(),
        generate_ambiguous_caption(),
    ]
    for path in fixtures:
        size = path.stat().st_size
        print(f"  {path.name}: {size:,} bytes")


if __name__ == "__main__":
    main()
