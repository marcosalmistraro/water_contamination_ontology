"""Unit tests for IED PDF ingester."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from rdflib import RDF, Literal, URIRef, XSD

from water_ontology.ingesters.pdf_ingester import (
    PdfIngester,
    RawThreshold,
    _iter_annex_ii,
    _safe,
)

WCD = "https://w3id.org/water-contamination/data/"
WC = "https://w3id.org/water-contamination/"


def _make_ingester(empty_graph):  # type: ignore[no-untyped-def]
    cfg = MagicMock()
    cfg.url = "http://example.com/ied.pdf"
    cfg.local_file = None
    return PdfIngester(empty_graph, cfg, raw_dir=MagicMock(), regulation_label="Test Regulation")


class TestPdfIngester:
    def test_add_threshold_creates_individual(self, empty_graph) -> None:  # type: ignore[no-untyped-def]
        ingester = _make_ingester(empty_graph)
        raw = RawThreshold(name="Arsenic", value_kg=5.0, medium="water", regulation="Test Regulation")
        ingester._add_threshold(raw)

        threshold_class = URIRef(f"{WC}ComplianceThreshold")
        assert any(True for _ in empty_graph.subjects(RDF.type, threshold_class))

    def test_add_threshold_links_regulation_document(self, empty_graph) -> None:  # type: ignore[no-untyped-def]
        ingester = _make_ingester(empty_graph)
        raw = RawThreshold(name="Lead", value_kg=20.0, medium="water", regulation="Test Regulation")
        ingester._add_threshold(raw)

        reg_class = URIRef(f"{WC}RegulationDocument")
        assert any(True for _ in empty_graph.subjects(RDF.type, reg_class))

    def test_add_threshold_stores_value(self, empty_graph) -> None:  # type: ignore[no-untyped-def]
        ingester = _make_ingester(empty_graph)
        raw = RawThreshold(name="Mercury", value_kg=1.0, medium="water", regulation="Test Regulation")
        ingester._add_threshold(raw)

        threshold_iri = next(empty_graph.subjects(RDF.type, URIRef(f"{WC}ComplianceThreshold")))
        values = list(empty_graph.objects(threshold_iri, URIRef(f"{WC}thresholdKgPerYear")))
        assert len(values) == 1
        assert float(values[0]) == pytest.approx(1.0)

    def test_ingest_loads_all_annex_ii_thresholds(self, empty_graph) -> None:  # type: ignore[no-untyped-def]
        ingester = _make_ingester(empty_graph)
        counts = ingester.ingest()

        expected = sum(1 for _ in _iter_annex_ii(ingester.regulation_label))
        assert counts["thresholds"] == expected

        threshold_class = URIRef(f"{WC}ComplianceThreshold")
        in_graph = sum(1 for _ in empty_graph.subjects(RDF.type, threshold_class))
        assert in_graph == expected

    def test_ingest_creates_one_regulation_document(self, empty_graph) -> None:  # type: ignore[no-untyped-def]
        ingester = _make_ingester(empty_graph)
        ingester.ingest()

        reg_class = URIRef(f"{WC}RegulationDocument")
        reg_count = sum(1 for _ in empty_graph.subjects(RDF.type, reg_class))
        assert reg_count == 1

    def test_known_water_threshold_present(self, empty_graph) -> None:  # type: ignore[no-untyped-def]
        """Mercury water threshold is 1 kg/year per Annex II."""
        ingester = _make_ingester(empty_graph)
        ingester.ingest()

        threshold_class = URIRef(f"{WC}ComplianceThreshold")
        threshold_kg = URIRef(f"{WC}thresholdKgPerYear")
        medium_prop = URIRef(f"{WC}medium")
        pollutant_prop = URIRef(f"{WC}pollutantName")

        found = any(
            str(next(empty_graph.objects(s, pollutant_prop), "")) == "Mercury and compounds (as Hg)"
            and str(next(empty_graph.objects(s, medium_prop), "")) == "water"
            and float(next(empty_graph.objects(s, threshold_kg), 0)) == pytest.approx(1.0)
            for s in empty_graph.subjects(RDF.type, threshold_class)
        )
        assert found


class TestPdfUtilities:
    def test_safe_replaces_special_chars(self) -> None:
        result = _safe("Arsenic (compounds): water/air")
        assert " " not in result
        assert "(" not in result

    def test_iter_annex_ii_yields_only_non_none_mediums(self) -> None:
        rows = list(_iter_annex_ii("Test Reg"))
        # Every row must have a non-zero positive value
        assert all(r.value_kg > 0 for r in rows)
        # All mediums must be one of air/water/land
        assert all(r.medium in {"air", "water", "land"} for r in rows)

    def test_iter_annex_ii_includes_mercury_water(self) -> None:
        rows = list(_iter_annex_ii("Test Reg"))
        hg_water = [r for r in rows if "Mercury" in r.name and r.medium == "water"]
        assert len(hg_water) == 1
        assert hg_water[0].value_kg == pytest.approx(1.0)
