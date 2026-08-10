"""
Guardrails for the NL-to-SPARQL chain — two layers:

1. PROMPT-LEVEL (primary): text injected into system prompts that instructs the
   LLM to stay grounded to graph data and never answer from general knowledge.

2. OUTPUT-LEVEL (defence-in-depth): validate the generated SPARQL before it
   touches the graph — blocks write operations and enforces a row cap.
"""

from __future__ import annotations

import re

# ── 1. Prompt-level grounding ─────────────────────────────────────────────────

# Injected into the system prompt before the schema description.
GROUNDING_RULES = """
RULES — read carefully before every response:

1. You may ONLY report facts that appear in the SPARQL query results provided to you.
   Never use your general knowledge about water contamination, facilities, or pollutants
   to supplement, infer, or fill gaps in the data.

2. If the query returns no results, say exactly:
   "I found no data in the knowledge graph to answer that question."
   Do not speculate about why or suggest what the answer might be.

3. If you cannot translate the question into a valid SPARQL query against the schema
   below, say exactly:
   "I cannot answer that question from this knowledge graph."
   Do not attempt a partial or approximate answer.

4. Never present numbers, facility names, country statistics, or pollutant levels
   that are not directly present in the query results.

5. If the user asks something outside the domain of industrial emissions and water
   quality (e.g. general chemistry, history, geography), say:
   "That question is outside the scope of this system."
"""

# Injected between query results and the answer generation step.
ANSWER_GROUNDING = """
Answer the user's question using ONLY the data in the query results above.
If the results are empty or do not fully answer the question, say so explicitly.
Do not add context, caveats, or background knowledge from outside the results.
"""

# ── 2. Output-level validation ────────────────────────────────────────────────

MAX_QUERY_LENGTH = 4_000
MAX_LIMIT = 1_000
DEFAULT_LIMIT = 100

_WRITE_KEYWORDS = re.compile(
    r"\b(INSERT|DELETE|DROP|CLEAR|CREATE|COPY|MOVE|ADD|LOAD|MODIFY)\b",
    re.IGNORECASE,
)
# Matches SELECT anywhere after optional PREFIX/BASE declarations
_SELECT_RE = re.compile(r"^\s*(PREFIX\s+\S+\s*<[^>]+>\s*)*SELECT\b", re.IGNORECASE | re.DOTALL)
_LIMIT_RE = re.compile(r"\bLIMIT\s+(\d+)", re.IGNORECASE)
_IRI_RE = re.compile(r"<(https?://[^>]+)>")

_ALLOWED_IRI_PREFIXES = (
    "https://w3id.org/water-contamination/",
    "http://www.w3.org/",
    "http://www.opengis.net/",
    "http://purl.org/",
    "https://schema.org/",
)


class GuardrailError(ValueError):
    """Raised when a generated SPARQL query violates a safety rule."""


def validate_sparql(sparql: str) -> str:
    """Validate LLM-generated SPARQL and return a (possibly amended) safe version."""
    _check_length(sparql)
    _check_no_write_ops(sparql)
    _check_is_select(sparql)
    _check_iri_scope(sparql)
    return _enforce_limit(sparql)


def _check_length(sparql: str) -> None:
    if len(sparql) > MAX_QUERY_LENGTH:
        raise GuardrailError(
            f"Query exceeds maximum length ({len(sparql)} > {MAX_QUERY_LENGTH} chars)."
        )


def _check_no_write_ops(sparql: str) -> None:
    m = _WRITE_KEYWORDS.search(sparql)
    if m:
        raise GuardrailError(
            f"Query contains forbidden write operation '{m.group()}'. "
            "Only SELECT queries are permitted."
        )


def _check_is_select(sparql: str) -> None:
    if not _SELECT_RE.match(sparql):
        raise GuardrailError(
            "Only SPARQL SELECT queries are supported. "
            "CONSTRUCT, ASK, and DESCRIBE are not permitted."
        )


def _check_iri_scope(sparql: str) -> None:
    for iri in _IRI_RE.findall(sparql):
        if not any(iri.startswith(p) for p in _ALLOWED_IRI_PREFIXES):
            raise GuardrailError(
                f"Query references an out-of-scope IRI: <{iri}>."
            )


def _enforce_limit(sparql: str) -> str:
    m = _LIMIT_RE.search(sparql)
    if not m:
        return sparql.rstrip().rstrip(";") + f"\nLIMIT {DEFAULT_LIMIT}"
    if int(m.group(1)) > MAX_LIMIT:
        return _LIMIT_RE.sub(f"LIMIT {MAX_LIMIT}", sparql)
    return sparql
