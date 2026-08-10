"""Tests for SPARQL guardrails."""

from __future__ import annotations

import pytest

from water_ontology.query.guardrails import (
    GuardrailError,
    DEFAULT_LIMIT,
    MAX_LIMIT,
    validate_sparql,
)

_VALID = (
    "PREFIX wc: <https://w3id.org/water-contamination/>\n"
    "SELECT ?f WHERE { ?f a wc:IndustrialFacility . } LIMIT 10"
)


class TestGroundingRules:
    def test_guardrail_file_has_grounding_rules(self) -> None:
        from water_ontology.query.guardrails import GROUNDING_RULES
        assert "general knowledge" in GROUNDING_RULES.lower()
        assert "no results" in GROUNDING_RULES.lower()

    def test_answer_grounding_present(self) -> None:
        from water_ontology.query.guardrails import ANSWER_GROUNDING
        assert "ONLY" in ANSWER_GROUNDING
        assert "empty" in ANSWER_GROUNDING.lower()


class TestWriteBlocking:
    @pytest.mark.parametrize("kw", ["DELETE", "INSERT", "DROP", "CLEAR", "CREATE"])
    def test_blocks_write_keywords(self, kw: str) -> None:
        with pytest.raises(GuardrailError, match="write operation"):
            validate_sparql(f"SELECT ?x WHERE {{}} {kw} WHERE {{ ?s ?p ?o }}")

    def test_case_insensitive(self) -> None:
        with pytest.raises(GuardrailError):
            validate_sparql("select ?x where {} delete where { ?s ?p ?o }")


class TestSelectOnly:
    def test_construct_rejected(self) -> None:
        with pytest.raises(GuardrailError, match="SELECT"):
            validate_sparql(
                "PREFIX wc: <https://w3id.org/water-contamination/>\n"
                "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o } LIMIT 10"
            )

    def test_ask_rejected(self) -> None:
        with pytest.raises(GuardrailError, match="SELECT"):
            validate_sparql("ASK { ?s ?p ?o }")

    def test_select_accepted(self) -> None:
        result = validate_sparql(_VALID)
        assert "SELECT" in result


class TestLimitEnforcement:
    def test_injects_limit_when_missing(self) -> None:
        sparql = (
            "PREFIX wc: <https://w3id.org/water-contamination/>\n"
            "SELECT ?f WHERE { ?f a wc:IndustrialFacility . }"
        )
        result = validate_sparql(sparql)
        assert f"LIMIT {DEFAULT_LIMIT}" in result

    def test_caps_excessive_limit(self) -> None:
        sparql = (
            "PREFIX wc: <https://w3id.org/water-contamination/>\n"
            f"SELECT ?f WHERE {{ ?f a wc:IndustrialFacility . }} LIMIT {MAX_LIMIT + 9999}"
        )
        result = validate_sparql(sparql)
        assert f"LIMIT {MAX_LIMIT}" in result

    def test_valid_limit_unchanged(self) -> None:
        result = validate_sparql(_VALID)
        assert "LIMIT 10" in result


class TestLengthCap:
    def test_rejects_oversized_query(self) -> None:
        huge = "SELECT ?x WHERE { " + ("?x ?p ?o . " * 500) + "} LIMIT 10"
        with pytest.raises(GuardrailError, match="length"):
            validate_sparql(huge)


class TestIriScope:
    def test_rejects_external_iri(self) -> None:
        sparql = (
            "SELECT ?x WHERE { "
            "?x <http://malicious.example.com/steal> ?o . "
            "} LIMIT 10"
        )
        with pytest.raises(GuardrailError, match="out-of-scope"):
            validate_sparql(sparql)

    def test_allows_ontology_iri(self) -> None:
        sparql = (
            "SELECT ?x WHERE { "
            "?x a <https://w3id.org/water-contamination/IndustrialFacility> . "
            "} LIMIT 10"
        )
        result = validate_sparql(sparql)
        assert result is not None
