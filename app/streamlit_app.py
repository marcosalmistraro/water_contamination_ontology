"""
Water Contamination Ontology — Streamlit frontend.

Imports NLChain and QueryEngine directly (no FastAPI hop needed).
Set GROQ_API_KEY in .env or in the sidebar to enable the chat tab.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

# Ensure src/ and app/ are both importable regardless of CWD
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "app"))

load_dotenv(_ROOT / ".env")

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Water Contamination Intelligence",
    page_icon="💧",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Cached resources ──────────────────────────────────────────────────────────

@st.cache_resource(show_spinner="Loading knowledge graph…")
def load_graph():  # type: ignore[return]
    from water_ontology.graph import build_graph, load_graph as _load
    owl_path = _ROOT / "data" / "ontology" / "water_contamination.owl"
    if owl_path.exists():
        return _load(owl_path)
    st.warning("OWL file not found — using empty graph. Run `make ingest` first.")
    return build_graph()


@st.cache_resource(show_spinner="Initialising LLM…")
def load_chain(api_key: str):  # type: ignore[return]
    from rdflib import Graph
    from water_ontology.query.nl_chain import NLChain
    graph = load_graph()
    return NLChain(graph, api_key=api_key)


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("💧 Water Contamination")
    st.caption("EU industrial emissions × water quality knowledge graph")
    st.divider()

    # API key
    groq_key = os.getenv("GROQ_API_KEY", "")
    if not groq_key:
        groq_key = st.text_input(
            "Groq API key", type="password", placeholder="gsk_…",
            help="Required for the Chat tab. Get one at console.groq.com."
        )

    st.divider()

    # Graph stats
    graph = load_graph()
    st.metric("Total triples", f"{len(graph):,}")

    _WC = "https://w3id.org/water-contamination/"
    from rdflib import RDF, URIRef
    for cls in ["IndustrialFacility", "EmissionEvent", "WaterBody", "MonitoringStation"]:
        n = sum(1 for _ in graph.subjects(RDF.type, URIRef(f"{_WC}{cls}")))
        st.metric(cls, f"{n:,}")

    st.divider()
    st.caption("Built with rdflib · LangChain · Groq · Folium")

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_chat, tab_map, tab_sparql = st.tabs(["💬 Chat", "🗺️ Map", "🔍 SPARQL"])

# ── Chat tab ──────────────────────────────────────────────────────────────────

with tab_chat:
    if not groq_key:
        st.info("Enter your Groq API key in the sidebar to enable the chat.")
    else:
        if "messages" not in st.session_state:
            st.session_state.messages = []

        # Render history
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg.get("sparql"):
                    with st.expander("Generated SPARQL"):
                        st.code(msg["sparql"], language="sparql")
                if msg.get("rows"):
                    import pandas as pd
                    with st.expander(f"Raw results ({msg['row_count']} rows)"):
                        st.dataframe(pd.DataFrame(msg["rows"]), use_container_width=True)

        # Input
        if prompt := st.chat_input("Ask about facilities, emissions, or water quality…"):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                with st.spinner("Querying knowledge graph…"):
                    try:
                        chain = load_chain(groq_key)
                        result = chain.ask(prompt)
                        st.markdown(result.answer)
                        with st.expander("Generated SPARQL"):
                            st.code(result.sparql, language="sparql")
                        if result.query_result.rows:
                            import pandas as pd
                            with st.expander(f"Raw results ({result.query_result.row_count} rows)"):
                                st.dataframe(
                                    pd.DataFrame(result.query_result.rows),
                                    use_container_width=True,
                                )
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": result.answer,
                            "sparql": result.sparql,
                            "rows": result.query_result.rows,
                            "row_count": result.query_result.row_count,
                        })
                    except Exception as exc:
                        st.error(f"Error: {exc}")

# ── Map tab ───────────────────────────────────────────────────────────────────

with tab_map:
    from streamlit_folium import st_folium
    from components.map_view import build_map

    st.subheader("Facility & Monitoring Station Map")
    st.caption("Red = industrial facilities · Blue = monitoring stations")

    fmap = build_map(graph)
    st_folium(fmap, use_container_width=True, height=600, returned_objects=[])

# ── SPARQL tab ────────────────────────────────────────────────────────────────

with tab_sparql:
    st.subheader("Raw SPARQL Query")

    default_query = """\
PREFIX wc:  <https://w3id.org/water-contamination/>
PREFIX geo: <http://www.w3.org/2003/01/geo/wgs84_pos#>

SELECT ?name ?country ?lat ?lon WHERE {
    ?f a wc:IndustrialFacility ;
       wc:facilityName  ?name ;
       wc:countryCode   ?country .
    OPTIONAL { ?f geo:lat ?lat ; geo:long ?lon . }
}
LIMIT 25"""

    sparql_input = st.text_area("SPARQL", value=default_query, height=220)

    if st.button("Run query", type="primary"):
        from water_ontology.query.engine import QueryEngine
        from water_ontology.query.guardrails import GuardrailError
        import pandas as pd

        engine = QueryEngine(graph)
        try:
            result = engine.run(sparql_input)
            if result.is_empty():
                st.info("Query returned no results.")
            else:
                st.success(f"{result.row_count} row(s)")
                st.dataframe(pd.DataFrame(result.rows), use_container_width=True)
        except GuardrailError as exc:
            st.error(f"Guardrail: {exc}")
        except Exception as exc:
            st.error(f"SPARQL error: {exc}")
