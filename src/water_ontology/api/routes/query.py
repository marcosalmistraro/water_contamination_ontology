"""POST /query — raw SPARQL passthrough for power users / debugging."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from water_ontology.api.deps import get_engine
from water_ontology.api.models import QueryRequest, QueryResponse
from water_ontology.query.engine import QueryEngine
from water_ontology.query.guardrails import GuardrailError

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/query", response_model=QueryResponse)
def query(body: QueryRequest, engine: QueryEngine = Depends(get_engine)) -> QueryResponse:
    """Execute a raw SPARQL SELECT query against the knowledge graph."""
    logger.info("[/query] sparql=%.120s...", body.sparql)
    try:
        result = engine.run(body.sparql)
    except GuardrailError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("[/query] SPARQL execution error")
        raise HTTPException(status_code=400, detail=f"Query error: {exc}") from exc

    return QueryResponse(
        sparql=result.sparql,
        columns=result.columns,
        rows=result.rows,
        row_count=result.row_count,
    )
