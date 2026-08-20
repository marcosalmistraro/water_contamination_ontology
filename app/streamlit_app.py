"""
Water Contamination Ontology — Streamlit frontend.

Imports NLChain and QueryEngine directly (no FastAPI hop needed).
Set GROQ_API_KEY in .env or in the sidebar to enable the chat tab.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

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

def _download_store_from_hf(ox_path: Path) -> None:
    """Download and extract the Oxigraph store from Hugging Face Hub."""
    import zipfile
    repo_id = os.getenv("HF_REPO_ID") or st.secrets.get("HF_REPO_ID", "")
    if not repo_id:
        return
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        logger.warning("huggingface_hub not installed — cannot download store")
        return
    token = os.getenv("HF_TOKEN") or st.secrets.get("HF_TOKEN", "") or None
    with st.status("Downloading knowledge graph from Hugging Face…", expanded=True) as s:
        try:
            s.write("Fetching oxigraph_store.zip …")
            zip_path = hf_hub_download(
                repo_id=repo_id,
                filename="oxigraph_store.zip",
                repo_type="dataset",
                token=token,
            )
            s.write("Extracting …")
            ox_path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(ox_path.parent)
            s.update(label="Knowledge graph ready.", state="complete")
        except Exception as exc:
            logger.error("HF download failed: %s", exc)
            s.update(label=f"Download failed: {exc}", state="error")


@st.cache_resource(show_spinner="Loading knowledge graph…")
def load_graph():  # type: ignore[return]
    from water_ontology.graph import build_graph, load_graph as _load, load_graph_oxigraph

    ox_path = _ROOT / "data" / "ontology" / "oxigraph_store"

    # If store is missing and we have an HF repo configured, fetch it
    if not ox_path.exists():
        _download_store_from_hf(ox_path)

    # Oxigraph store: opens in milliseconds
    if ox_path.exists():
        return load_graph_oxigraph(ox_path)

    # Fallback: parse NT / OWL file
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
    groq_key = os.getenv("GROQ_API_KEY", "")

    st.markdown("**Knowledge Graph**")
    st.caption(
        "Six EU open-data sources ingested and linked into an OWL ontology. "
        "Stored in an Oxigraph persistent store — millisecond startup, full SPARQL 1.1."
    )

    graph = load_graph()
    _WC = "https://w3id.org/water-contamination/"
    from rdflib import RDF, URIRef

    with st.container(border=True):
        st.markdown("**Oxigraph persistent store**")
        counts = {
            cls: sum(1 for _ in graph.subjects(RDF.type, URIRef(f"{_WC}{cls}")))
            for cls in ["IndustrialFacility", "EmissionEvent", "WaterBody", "MonitoringStation"]
        }
        st.caption(f"{len(graph):,} triples · 8 OWL classes")
        for cls, n in counts.items():
            st.markdown(f"&nbsp;&nbsp;`{cls}` — **{n:,}**", unsafe_allow_html=True)

# ── Page header (always visible above tabs) ───────────────────────────────────

st.markdown("## Water Contamination Intelligence")
st.caption(
    "Natural-language intelligence over the EU industrial emissions "
    "and water quality knowledge graph — 3.1M RDF triples across 8 OWL classes."
)

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_chat, tab_map, tab_explore, tab_sources, tab_arch, tab_sparql = st.tabs(
    ["Ask", "Visualize", "Explore", "Data Sources", "Architecture", "Raw SPARQL"]
)

# ── Chat tab ──────────────────────────────────────────────────────────────────

with tab_chat:
    if not groq_key:
        st.info("Add a Groq API key to `.env` to enable the chat.")
    else:
        if "messages" not in st.session_state:
            st.session_state.messages = []

        # New question (chat_input always renders at page bottom)
        if prompt := st.chat_input("Ask about facilities, emissions, or water quality…"):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.spinner("Querying knowledge graph…"):
                try:
                    chain = load_chain(groq_key)
                    result = chain.ask(prompt)
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": result.answer,
                        "sparql": result.sparql,
                        "rows": result.query_result.rows,
                        "row_count": result.query_result.row_count,
                    })
                except Exception as exc:
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": "Something went wrong. Please try again.",
                    })
                    logger.error("[UI] Unexpected chain error: %s", exc)

        # Group into (user, assistant) exchange pairs
        _msgs = st.session_state.messages
        _exchanges: list[tuple[int, dict, dict | None]] = []
        _i = 0
        while _i < len(_msgs):
            if _msgs[_i]["role"] == "user":
                _asst = _msgs[_i + 1] if _i + 1 < len(_msgs) and _msgs[_i + 1]["role"] == "assistant" else None
                _exchanges.append((_i, _msgs[_i], _asst))
                _i += 2 if _asst else 1
            else:
                _i += 1

        if _exchanges:
            _hcol, _bcol = st.columns([6, 1])
            with _hcol:
                st.caption(f"{len(_exchanges)} exchange(s) — newest first")
            with _bcol:
                if st.button("Clear all", type="secondary", use_container_width=True):
                    st.session_state.messages = []
                    st.rerun()

            import pandas as pd
            for _rev_idx, (_msg_idx, _user, _asst) in enumerate(reversed(_exchanges)):
                with st.container(border=True):
                    _qcol, _dcol = st.columns([20, 1])
                    with _qcol:
                        st.markdown(f"**{_user['content']}**")
                    with _dcol:
                        if st.button("✕", key=f"del_{_rev_idx}", help="Remove"):
                            _end = _msg_idx + (2 if _asst else 1)
                            del st.session_state.messages[_msg_idx:_end]
                            st.rerun()
                    if _asst:
                        st.markdown(_asst["content"])
                        if _asst.get("sparql"):
                            with st.expander("Generated SPARQL"):
                                st.code(_asst["sparql"], language="sparql")

# ── Map tab ───────────────────────────────────────────────────────────────────

with tab_map:
    try:
        from streamlit_folium import st_folium
        from components.map_view import build_map
        fmap = build_map(graph)
        st_folium(fmap, use_container_width=True, height=600, returned_objects=[])
        st.markdown(
            "🔴 &nbsp;Industrial facility &nbsp;&nbsp;&nbsp; 🔵 &nbsp;Monitoring station",
            unsafe_allow_html=True,
        )
    except Exception as _map_exc:
        import traceback
        st.error(f"Map error: {_map_exc}")
        st.code(traceback.format_exc())

# ── Explore tab ──────────────────────────────────────────────────────────────

with tab_explore:
    st.markdown("#### Ontology Structure")
    st.caption(
        "Eight OWL classes connected by seven object properties. "
        "Hover over a node to inspect its data properties and instance count. "
        "Drag nodes to rearrange — use the filters above the graph to focus on a domain."
    )
    import streamlit.components.v1 as _components
    _explorer_html = (_ROOT / "app" / "components" / "ontology_explorer.html").read_text(encoding="utf-8")
    _components.html(_explorer_html, height=620)

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
        "provider": "European Environment Agency (EEA)",
        "format": "CSV / ZIP · ~148 MB",
        "local_key": "local_zip",
        "desc": (
            "The European Pollutant Release and Transfer Register is the EU's primary registry "
            "of industrial pollutant emissions. It covers 65 pollutants reported annually by "
            "facilities across all EU member states and several reporting countries."
        ),
        "usage": (
            "7,615 industrial facilities and 254,156 emission events (2007–2024) are ingested "
            "as `IndustrialFacility` and `EmissionEvent` individuals. Facility coordinates are "
            "used for the map and spatial linking to River Basin Districts."
        ),
    },
    "waterbase": {
        "label": "EEA Waterbase WISE6 (Part 1)",
        "provider": "European Environment Agency (EEA)",
        "format": "CSV / ZIP · ~733 MB",
        "local_key": "local_zip",
        "desc": (
            "Waterbase WISE6 contains water quality observations from EU monitoring stations "
            "following the WISE6 ICM schema. The full dataset is 14 GB / 51M rows; ingestion "
            "is capped at 500K rows by default to keep graph size manageable."
        ),
        "usage": (
            "2,168 monitoring stations and their associated water bodies are created as "
            "`MonitoringStation` and `WaterBody` individuals. Up to 500K observations link "
            "stations to measured pollutant concentrations over time."
        ),
    },
    "eea_geojson": {
        "label": "EEA River Basin Districts",
        "provider": "European Environment Agency (EEA) / ArcGIS REST",
        "format": "GeoJSON · ~291 MB",
        "local_key": "local_file",
        "desc": (
            "Polygon geometry for all 209 EU River Basin Districts (WISE_SoE). RBDs are the "
            "fundamental spatial unit of the EU Water Framework Directive, each covering one "
            "or more river basins managed as a single hydrological unit."
        ),
        "usage": (
            "RBD polygons are loaded as `Catchment` individuals and used in a point-in-polygon "
            "spatial join to link 7,431 facilities and 1,559 monitoring station water bodies "
            "to their enclosing river basin via `locatedInCatchment` / `drainsToCatchment`."
        ),
    },
    "wise_monitoring_sites": {
        "label": "WISE Monitoring Sites",
        "provider": "European Environment Agency (EEA) / ArcGIS REST",
        "format": "GeoJSON · ~2 MB",
        "local_key": "local_file",
        "desc": (
            "Coordinates for ~15,000 EU water quality monitoring stations maintained under the "
            "WISE reporting framework. Fetched via a two-pass crosswalk: first the EIONET "
            "service, then a WFD2022 batch lookup for any remaining unmatched sites."
        ),
        "usage": (
            "Lat/lon coordinates are patched onto the 2,168 `MonitoringStation` individuals "
            "already in the graph (1,560 successfully patched). These coordinates power "
            "the station layer on the Visualize map."
        ),
    },
    "ied_pdf": {
        "label": "IED BREF — Large Combustion Plants (2017)",
        "provider": "European Commission / EIPPCB",
        "format": "PDF · ~34 MB",
        "local_key": "local_file",
        "desc": (
            "The EU Industrial Emissions Directive Best Available Techniques Reference Document "
            "for Large Combustion Plants defines emission limit values for major pollutants "
            "under BAT (Best Available Techniques) conclusions."
        ),
        "usage": (
            "90 pollutant compliance thresholds are extracted from the Annex II table and "
            "stored as `ComplianceThreshold` individuals linked to `Pollutant` via `hasThreshold` "
            "and to `RegulationDocument` via `regulatedBy`."
        ),
    },
    "inspire_envthes": {
        "label": "EnvThes Environmental Thesaurus",
        "provider": "LTER Europe / INSPIRE",
        "format": "Turtle (RDF) · ~3 MB",
        "local_key": "local_file",
        "desc": (
            "EnvThes is a SKOS multilingual thesaurus for environmental and ecological terminology "
            "maintained by LTER Europe. It aligns concepts across INSPIRE, GEMET, and other "
            "EU environmental vocabularies."
        ),
        "usage": (
            "Three `owl:sameAs` links are added to the graph, connecting ontology pollutant "
            "and water body concepts to their INSPIRE-compliant EnvThes URIs. This enables "
            "interoperability with other INSPIRE-aligned datasets."
        ),
    },
}

with tab_sources:
    st.subheader("Data Sources")
    st.markdown(
        "All data is open and publicly available. "
        "Click any dataset link to download or explore the original source."
    )

    from water_ontology.config import load_sources
    src_cfg = load_sources(_ROOT / "config" / "sources.yaml")

    for key, meta in _SOURCES_META.items():
        cfg = src_cfg.sources.get(key)
        local_path = None
        if cfg:
            raw = getattr(cfg, meta["local_key"], None)
            local_path = Path(raw) if raw else None

        with st.container(border=True):
            hcol, bcol = st.columns([8, 1])
            with hcol:
                st.markdown(f"**{meta['label']}**")
                st.caption(f"Provider: {meta['provider']} · Format: {meta['format']}")
            with bcol:
                if cfg:
                    st.link_button("Download ↗", url=cfg.url, use_container_width=True)

            st.markdown(meta["desc"])
            st.markdown(f"**How it is used:** {meta['usage']}")

# ── Architecture tab ──────────────────────────────────────────────────────────

with tab_arch:
    st.subheader("System Architecture")
    st.markdown(
        "The pipeline is split into two phases: an **offline ingestion pipeline** that builds "
        "the knowledge graph, and an **online query pipeline** that answers questions in real time."
    )

    st.divider()

    col_off, col_on = st.columns(2)

    with col_off:
        st.markdown("#### Offline — ingestion")
        for step, detail in [
            ("E-PRTR CSV", "European Pollutant Release and Transfer Register v16. Yields 7,615 industrial facilities and 254K emission events across 65 pollutants (2007–2024)."),
            ("Waterbase WISE6 CSV", "EEA water quality observations from 2,168 EU monitoring stations. The full file is 14 GB; ingestion is capped at 500K rows by default."),
            ("EEA River Basins GeoJSON", "209 EU River Basin District polygons fetched from the EEA ArcGIS REST service. Used as spatial containers for linking facilities and stations."),
            ("IED BREF PDF", "EU Industrial Emissions Directive reference document for Large Combustion Plants. 90 pollutant compliance thresholds are extracted from the Annex II table."),
            ("EnvThes Turtle", "SKOS vocabulary from LTER Europe. Three owl:sameAs links align ontology pollutant concepts to INSPIRE-compliant URIs."),
            ("WISE Monitoring Sites GeoJSON", "Lat/lon coordinates for ~15K EU monitoring stations. A two-pass crosswalk (EIONET + WFD2022 batch lookup) patches 1,560 stations with coordinates."),
            ("Spatial joiner", "Point-in-polygon test using Shapely STRtree. Links 7,431 facilities and 1,559 station water bodies to their enclosing River Basin District."),
            ("rdflib Graph → N-Triples", "All ingesters write into a single in-memory rdflib Graph (~3.1M triples). Serialised to N-Triples format (~1.2 GB) for portability."),
            ("Oxigraph bulk_load", "The NT file is bulk-loaded into a pyoxigraph persistent B-tree store (~400 MB on disk). The store opens read-only in ~0.15 s on subsequent runs."),
        ]:
            with st.container(border=True):
                st.markdown(f"**{step}**")
                st.caption(detail)

    with col_on:
        st.markdown("#### Online — query")
        for step, detail in [
            ("Streamlit UI", "Opens the Oxigraph store in read-only mode on startup. Multiple concurrent readers are supported. The store is cached in memory for the session lifetime."),
            ("Ask — NLChain", "A LangChain chain backed by the Groq API. The user's question is combined with the ontology schema and sent to the LLM to generate a SPARQL SELECT query."),
            ("Groq API", "Hosted LLM inference (openai/gpt-oss-120b). Receives the schema context and question, returns a valid SPARQL query. Latency is typically under 2 s."),
            ("Oxigraph SPARQL engine", "Rust-native SPARQL 1.1 execution over the full 3.1M-triple graph. Accessed via a thin OxigraphAdapter that provides the rdflib Graph interface."),
            ("QueryEngine", "Validates the generated SPARQL against guardrails (SELECT-only, no DROP/INSERT). Executes the query and formats rows into a structured result object."),
            ("Visualize — pyoxigraph", "Two SPARQL queries retrieve facility and station coordinates. Results are passed to FastMarkerCluster, keeping the Folium HTML payload small at any scale."),
            ("SPARQL tab", "Raw query editor for direct SPARQL access. The same guardrails apply. Results are shown as an interactive dataframe."),
        ]:
            with st.container(border=True):
                st.markdown(f"**{step}**")
                st.caption(detail)

    st.divider()
    st.markdown("#### Components")

    for title, body in [
        (
            "Data ingestion",
            "Six ingesters pull from EU open-data APIs and files. Each implements a common "
            "`BaseIngester` interface (`run()` → counts dict). The CLI (`water-ontology ingest all`) "
            "runs all ingesters sequentially, then applies the spatial joiner to link facilities "
            "and monitoring stations to river basin districts via point-in-polygon."
        ),
        (
            "OWL ontology",
            "Eight core classes: `IndustrialFacility`, `EmissionEvent`, `Pollutant`, `WaterBody`, "
            "`MonitoringStation`, `ComplianceThreshold`, `Catchment`, `RegulationDocument`. "
            "Object properties link the graph (e.g. `hasEmissionEvent`, `monitors`, `drainsToCatchment`). "
            "SHACL shapes are available for validation (`make validate-graph`) but excluded from the "
            "default pipeline due to cost at 3M+ triples."
        ),
        (
            "Oxigraph persistent store",
            "After ingestion, the rdflib graph is serialised to N-Triples (~1.2 GB) and then "
            "bulk-loaded into a pyoxigraph persistent store (B-tree, ~400 MB on disk). "
            "Streamlit opens the store read-only in ~0.15 s. Multiple concurrent readers are supported. "
            "A thin `OxigraphAdapter` bridges pyoxigraph's query API to the rdflib `Graph` interface "
            "used throughout the codebase."
        ),
        (
            "NL query chain",
            "User questions are passed to a LangChain SPARQL-generation chain backed by Groq. "
            "The chain receives the ontology schema as context, generates a SPARQL SELECT query, "
            "executes it against the Oxigraph store, and formats the results into a natural-language answer."
        ),
        (
            "Map",
            "Facility and station coordinates are retrieved via two SPARQL queries (LIMIT 10K / 5K). "
            "`FastMarkerCluster` serialises only `[lat, lon, tooltip]` arrays — keeping the Folium "
            "HTML payload small regardless of marker count."
        ),
    ]:
        with st.expander(title):
            st.markdown(body)
