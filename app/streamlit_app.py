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
    from water_ontology.graph import build_graph, load_graph as _load, load_graph_oxigraph

    # Oxigraph store: opens in milliseconds (no NT parsing)
    ox_path = _ROOT / "data" / "ontology" / "oxigraph_store"
    if ox_path.exists():
        return load_graph_oxigraph(ox_path)

    # Fallback: parse NT / OWL file (slow on large graphs)
    for fname, fmt in [("water_contamination.nt", "nt"), ("water_contamination.owl", "xml")]:
        p = _ROOT / "data" / "ontology" / fname
        if p.exists():
            return _load(p, fmt=fmt)

    st.warning("No graph file found — using empty graph. Run `make ingest` first.")
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

    # API key — loaded from .env via load_dotenv() at startup
    groq_key = os.getenv("GROQ_API_KEY", "")

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

tab_chat, tab_map, tab_sparql, tab_sources = st.tabs(["💬 Chat", "🗺️ Map", "🔍 SPARQL", "📦 Data Sources"])

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
    st.subheader("Facility & Monitoring Station Map")
    st.caption("Red = industrial facilities · Blue = monitoring stations")
    try:
        from streamlit_folium import st_folium
        from components.map_view import build_map
        fmap = build_map(graph)
        st_folium(fmap, use_container_width=True, height=600, returned_objects=[])
    except Exception as _map_exc:
        import traceback
        st.error(f"Map error: {_map_exc}")
        st.code(traceback.format_exc())

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

# ── Data Sources tab ──────────────────────────────────────────────────────────

_SOURCES_META = {
    "eprtr": {
        "label": "E-PRTR v16 (2007–2024)",
        "desc": (
            "European Pollutant Release and Transfer Register. "
            "Industrial facility emissions across 65 pollutants, covering 4,000+ facilities "
            "in EU member states and reporting countries."
        ),
        "format": "CSV / ZIP",
        "approx_size": "~148 MB",
        "local_key": "local_zip",
    },
    "waterbase": {
        "label": "EEA Waterbase WISE6 (Part 1)",
        "desc": (
            "Water quality observations from EU monitoring stations (WISE6 ICM schema). "
            "Full file is 14 GB / 51M rows — ingestion is capped at 500K rows by default."
        ),
        "format": "CSV / ZIP",
        "approx_size": "~733 MB",
        "local_key": "local_zip",
    },
    "eea_geojson": {
        "label": "EEA River Basin Districts",
        "desc": (
            "Polygon geometry for 209 EU River Basin Districts (WISE_SoE). "
            "Used to spatially link facilities and monitoring stations to their catchments."
        ),
        "format": "GeoJSON (ArcGIS REST)",
        "approx_size": "~291 MB",
        "local_key": "local_file",
    },
    "wise_monitoring_sites": {
        "label": "WISE Monitoring Sites",
        "desc": (
            "Lat/lon coordinates for ~15,000 EU water quality monitoring stations. "
            "Two-pass fetch: EIONET service + WFD2022 batch lookup for remaining sites."
        ),
        "format": "GeoJSON (ArcGIS REST)",
        "approx_size": "~2 MB",
        "local_key": "local_file",
    },
    "ied_pdf": {
        "label": "IED BREF — Large Combustion Plants (2017)",
        "desc": (
            "EU Industrial Emissions Directive Best Available Techniques Reference Document. "
            "Downloaded for provenance; compliance thresholds come from the hardcoded E-PRTR Annex II table."
        ),
        "format": "PDF",
        "approx_size": "~34 MB",
        "local_key": "local_file",
    },
    "inspire_envthes": {
        "label": "EnvThes Environmental Thesaurus",
        "desc": (
            "SKOS vocabulary from LTER Europe aligning pollutant and water body terminology "
            "to INSPIRE standards. Imported as owl:sameAs links into the knowledge graph."
        ),
        "format": "Turtle (RDF)",
        "approx_size": "~3 MB",
        "local_key": "local_file",
    },
}

with tab_sources:
    st.subheader("Data Sources")
    st.caption(
        "Six sources are ingested into the knowledge graph. "
        "Run `make ingest` to download and process all of them, "
        "or `water-ontology ingest <source>` for a single source."
    )

    from water_ontology.config import load_sources
    src_cfg = load_sources(_ROOT / "config" / "sources.yaml")

    for key, meta in _SOURCES_META.items():
        cfg = src_cfg.sources.get(key)
        with st.container(border=True):
            col_info, col_status, col_btn = st.columns([5, 2, 2])

            with col_info:
                st.markdown(f"**{meta['label']}**")
                st.caption(meta["desc"])
                st.markdown(
                    f"`{meta['format']}` &nbsp;·&nbsp; {meta['approx_size']}",
                    unsafe_allow_html=True,
                )

            with col_status:
                local_path = None
                if cfg:
                    raw = getattr(cfg, meta["local_key"], None)
                    local_path = Path(raw) if raw else None
                if local_path and local_path.exists():
                    size_mb = local_path.stat().st_size / 1_048_576
                    st.success(f"Downloaded ({size_mb:.0f} MB)")
                else:
                    st.warning("Not downloaded")

            with col_btn:
                if cfg:
                    st.link_button(
                        "Source ↗",
                        url=cfg.url,
                        use_container_width=True,
                    )
