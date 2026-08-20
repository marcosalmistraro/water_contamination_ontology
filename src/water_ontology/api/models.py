"""Request and response schemas for the FastAPI endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ── /ask ──────────────────────────────────────────────────────────────────────

class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)


class AskResponse(BaseModel):
    question: str
    sparql: str
    answer: str
    row_count: int
    rows: list[dict[str, Any]]


# ── /query ────────────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    sparql: str = Field(..., min_length=10)


class QueryResponse(BaseModel):
    sparql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int


# ── /graph/stats ──────────────────────────────────────────────────────────────

class GraphStats(BaseModel):
    total_triples: int
    class_counts: dict[str, int]
    ontology_file: str


# ── /health ───────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    graph_loaded: bool
    triple_count: int


# ── errors ────────────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    detail: str
