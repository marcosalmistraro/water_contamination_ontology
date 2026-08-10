"""POST /ask — natural-language question → SPARQL → natural-language answer."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from water_ontology.api.deps import get_chain
from water_ontology.api.models import AskRequest, AskResponse
from water_ontology.query.guardrails import GuardrailError
from water_ontology.query.nl_chain import NLChain

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/ask", response_model=AskResponse)
def ask(body: AskRequest, chain: NLChain = Depends(get_chain)) -> AskResponse:
    """Translate a natural-language question into SPARQL, execute it, and return an answer."""
    logger.info("[/ask] question=%r", body.question)
    try:
        result = chain.ask(body.question)
    except GuardrailError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("[/ask] Unexpected error")
        raise HTTPException(status_code=502, detail=f"LLM error: {exc}") from exc

    return AskResponse(
        question=result.question,
        sparql=result.sparql,
        answer=result.answer,
        row_count=result.query_result.row_count,
        rows=result.query_result.rows,
    )
