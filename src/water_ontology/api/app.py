"""FastAPI application factory with lifespan graph loading."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from water_ontology.api import deps
from water_ontology.api.routes import ask, graph, query

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Load the OWL graph and initialise the NLChain once at startup."""
    owl_path = Path(os.getenv("ONTOLOGY_FILE", "data/ontology/water_contamination.owl"))

    if owl_path.exists():
        from water_ontology.graph import load_graph
        g = load_graph(owl_path)
        logger.info("Graph loaded from %s (%d triples)", owl_path, len(g))
    else:
        from rdflib import Graph
        from water_ontology.config import load_ontology_config
        from water_ontology.graph import build_graph
        logger.warning("OWL file not found at %s — starting with empty graph", owl_path)
        g = build_graph()

    deps.set_graph(g)

    api_key = os.getenv("GROQ_API_KEY", "")
    if api_key:
        from water_ontology.query.nl_chain import NLChain
        chain = NLChain(g, api_key=api_key)
        deps.set_chain(chain)
        logger.info("NLChain initialised (model=%s)", chain.model)
    else:
        logger.warning("GROQ_API_KEY not set — /ask endpoint will be unavailable")

    yield
    # Nothing to teardown for an in-memory graph


def create_app() -> FastAPI:
    app = FastAPI(
        title="Water Contamination Ontology API",
        description=(
            "Query the EU water contamination knowledge graph via natural language or raw SPARQL."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],      # tighten in production
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.include_router(ask.router, tags=["NL Query"])
    app.include_router(query.router, tags=["SPARQL"])
    app.include_router(graph.router, tags=["Graph"])

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {"docs": "/docs", "health": "/health", "stats": "/graph/stats"}

    return app


app = create_app()
