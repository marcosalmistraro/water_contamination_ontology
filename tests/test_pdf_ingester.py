"""Unit tests for IED PDF ingester."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from rdflib import RDF, URIRef

from water_ontology.ingesters.pdf_ingester import (
    PdfIngester,
    RawThreshold,
    _to_kg_per_year,
    _safe,
)

WCD = "https://w3id.org/water-contamination/data/"
WC = "https://w3id.org/water-contamination/"


def _make_ingester(empty_graph):  # type: ignore[no-untyped-def]
    cfg = MagicMock()
    cfg.url = "http://example.com/ied.pdf"
    cfg.local_file = None
    ingester = PdfIngester(
        empty_graph, cfg, raw_dir=MagicMock(), regulation_label="Test Regulation"
    )
    ingester.local_path = MagicMock()
    return ingester


class TestPdfIngester:
    def test_add_threshold_creates_individual(self, empty_graph) -> None:  # type: ignore[no-untyped-def]
        ingester = _make_ingester(empty_graph)
        raw = RawThreshold(
            name="Arsenic", value_kg=5.0, medium="water", page=1, regulation="Test Regulation"
        )
        ingester._add_threshold(raw)

        threshold_class = URIRef(f"{WC}ComplianceThreshold")
        found = any(
            (s, RDF.type, threshold_class) in empty_graph
            for s in empty_graph.subjects(RDF.type, threshold_class)
        )
        assert found

    def test_add_threshold_links_regulation_document(self, empty_graph) -> None:  # type: ignore[no-untyped-def]
        ingester = _make_ingester(empty_graph)
        raw = RawThreshold(
            name="Lead", value_kg=20.0, medium="water", page=2, regulation="Test Regulation"
        )
        ingester._add_threshold(raw)

        reg_class = URIRef(f"{WC}RegulationDocument")
        assert any(True for _ in empty_graph.subjects(RDF.type, reg_class))

    def test_ingest_via_mock_pdf(self, empty_graph) -> None:  # type: ignore[no-untyped-def]
        ingester = _make_ingester(empty_graph)
        sample_lines = [
            "Pollutant    Threshold    Medium",
            "Arsenic and compounds    5    kg/year    water",
            "Lead    20    kg/year    water",
            "Mercury    1    kg/year    water",
        ]

        mock_page = MagicMock()
        mock_page.extract_text.return_value = "\n".join(sample_lines)

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__.return_value = mock_pdf
        mock_pdf.__exit__.return_value = False

        with patch("pdfplumber.open", return_value=mock_pdf):
            counts = ingester.ingest()

        assert counts["thresholds"] >= 1


class TestPdfUtilities:
    def test_to_kg_per_year_identity(self) -> None:
        assert _to_kg_per_year(5.0, "kg/year") == pytest.approx(5.0)

    def test_to_kg_per_year_tonnes(self) -> None:
        assert _to_kg_per_year(2.0, "t/year") == pytest.approx(2000.0)

    def test_to_kg_per_year_grams(self) -> None:
        assert _to_kg_per_year(1000.0, "g/year") == pytest.approx(1.0)

    def test_safe_replaces_special_chars(self) -> None:
        result = _safe("Arsenic (compounds): water/air")
        assert " " not in result
        assert "(" not in result
