"""
NL-to-SPARQL-to-NL chain using LangChain + GPT-4o.

Flow:
  user question
    → [GPT-4o] generate SPARQL (schema-grounded, guardrails in system prompt)
    → QueryEngine.run(sparql)
    → [GPT-4o] turn results into a natural language answer (guardrails in system prompt)
    → answer
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

from rdflib import Graph

from water_ontology.query.engine import QueryEngine, QueryResult
from water_ontology.query.prompts import answer_generation_prompt, sparql_generation_prompt

logger = logging.getLogger(__name__)


@dataclass
class ChainResult:
    question: str
    sparql: str
    query_result: QueryResult
    answer: str


class NLChain:
    """
    Two-step LangChain chain:
    1. NL → SPARQL  (schema + guardrails injected as system prompt)
    2. results → NL (answer grounding injected as system prompt)
    """

    def __init__(
        self,
        graph: Graph,
        model: str = "openai/gpt-oss-120b",
        temperature: float = 0.0,
        api_key: str | None = None,
    ) -> None:
        self.engine = QueryEngine(graph)
        self.model = model
        self.temperature = temperature
        self._api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        self._llm = self._build_llm()

    def ask(self, question: str) -> ChainResult:
        """Run the full chain and return a structured result."""
        logger.info("[NLChain] Question: %s", question)

        sparql = self._generate_sparql(question)
        logger.info("[NLChain] Generated SPARQL:\n%s", sparql)

        query_result = self.engine.run(sparql)
        logger.info("[NLChain] Query returned %d row(s)", query_result.row_count)

        answer = self._generate_answer(question, query_result)
        return ChainResult(
            question=question,
            sparql=sparql,
            query_result=query_result,
            answer=answer,
        )

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _build_llm(self) -> object:
        try:
            from langchain_groq import ChatGroq
        except ImportError as exc:
            raise ImportError("Install langchain-groq to use NLChain") from exc
        return ChatGroq(
            model=self.model,
            temperature=self.temperature,
            api_key=self._api_key,  # type: ignore[arg-type]
        )

    def _generate_sparql(self, question: str) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=sparql_generation_prompt()),
            HumanMessage(content=question),
        ]
        response = self._llm.invoke(messages)  # type: ignore[union-attr]
        sparql = str(response.content).strip()
        # Strip markdown fences if the model adds them despite the instruction
        sparql = _strip_fences(sparql)
        return sparql

    def _generate_answer(self, question: str, result: QueryResult) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        results_text = _format_results(result)
        messages = [
            SystemMessage(content=answer_generation_prompt()),
            HumanMessage(
                content=(
                    f"Question: {question}\n\n"
                    f"Query results:\n{results_text}"
                )
            ),
        ]
        response = self._llm.invoke(messages)  # type: ignore[union-attr]
        return str(response.content).strip()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_fences(text: str) -> str:
    """Remove ```sparql ... ``` or ``` ... ``` wrappers if present."""
    import re
    return re.sub(r"^```[a-z]*\n?|```$", "", text.strip(), flags=re.MULTILINE).strip()


def _format_results(result: QueryResult) -> str:
    if result.is_empty():
        return "(no results)"
    lines = ["\t".join(result.columns)]
    for row in result.rows:
        lines.append("\t".join(str(row.get(c, "")) for c in result.columns))
    return "\n".join(lines)
