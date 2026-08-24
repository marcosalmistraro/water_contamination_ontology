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
    """Stream the Oxigraph store zip from HF Hub with live progress, then extract."""
    import tempfile
    import zipfile

    import requests

    repo_id = os.getenv("HF_REPO_ID") or st.secrets.get("HF_REPO_ID", "")
    if not repo_id:
        return

    token = os.getenv("HF_TOKEN") or st.secrets.get("HF_TOKEN", "") or None
    url = f"https://huggingface.co/datasets/{repo_id}/resolve/main/oxigraph_store.zip"
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    with st.status("Downloading knowledge graph…", expanded=True) as s:
        try:
            s.write("Connecting to Hugging Face…")
            resp = requests.get(url, headers=headers, stream=True, timeout=30)
            resp.raise_for_status()

            total = int(resp.headers.get("content-length", 0))
            total_mb = total / 1_048_576

            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                tmp_path = Path(tmp.name)
                downloaded = 0
                chunk_size = 4 * 1024 * 1024  # 4 MB chunks
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if chunk:
                        tmp.write(chunk)
                        downloaded += len(chunk)
                        done_mb = downloaded / 1_048_576
                        pct = int(downloaded / total * 100) if total else 0
                        s.write(f"Downloading… {done_mb:.0f} / {total_mb:.0f} MB ({pct}%)")

            s.write("Extracting store…")
            ox_path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(tmp_path) as zf:
                zf.extractall(ox_path.parent)
            tmp_path.unlink(missing_ok=True)

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
            for cls in [
                "IndustrialFacility", "EmissionEvent", "WaterBody", "MonitoringStation",
                "Pollutant", "ComplianceThreshold", "Catchment", "RegulationDocument",
            ]
        }
        st.caption(f"{len(graph):,} triples · 8 OWL classes")
        for cls, n in counts.items():
            st.markdown(f"&nbsp;&nbsp;`{cls}` — **{n:,}**", unsafe_allow_html=True)

# ── Page header (always visible above tabs) ───────────────────────────────────

st.markdown("## 💧 Water Contamination Intelligence")
st.caption(
    "Natural-language intelligence over the EU industrial emissions "
    "and water quality knowledge graph — 3.1M RDF triples across 8 OWL classes."
)

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_chat, tab_map, tab_explore, tab_sources, tab_arch, tab_sparql = st.tabs(
    ["Ask", "Visualize", "Explore", "Data Sources", "Architecture", "Raw SPARQL"]
)

# ── Chat tab ──────────────────────────────────────────────────────────────────

_EXAMPLE_QUESTIONS = [
    "Which facilities in Germany emitted the most nitrogen in 2022?",
    "How many industrial facilities are located in the Rhine river basin?",
    "What are the top 5 pollutants by total emission quantity across all countries?",
    "List monitoring stations in France with their water body names.",
    "Which country reported the highest total emissions in 2023?",
    "How many emission events involved mercury across all years?",
]

_COUNTRIES = [
    "Germany", "France", "Italy", "Poland", "Spain", "Netherlands",
    "Belgium", "Czech Republic", "Romania", "Hungary", "Austria", "Sweden",
]


def _on_change_example() -> None:
    val = st.session_state.get("_example_q")
    if val is not None:
        st.session_state["_input_mode"] = "example"
        st.session_state["_manual_q"] = val
    elif st.session_state.get("_input_mode") == "example":
        st.session_state["_input_mode"] = None
        st.session_state["_manual_q"] = ""


def _clear_example() -> None:
    st.session_state["_input_mode"] = None
    st.session_state["_example_q"] = None
    st.session_state["_manual_q"] = ""


def _on_change_country() -> None:
    val = st.session_state.get("_country_q")
    if val is not None:
        st.session_state["_input_mode"] = "country"
        st.session_state["_manual_q"] = (
            f"Which industrial facilities in {val} emitted the most pollutants? "
            "Show the top 10 with their total emission quantities."
        )
    elif st.session_state.get("_input_mode") == "country":
        st.session_state["_input_mode"] = None
        st.session_state["_manual_q"] = ""


def _clear_country() -> None:
    st.session_state["_input_mode"] = None
    st.session_state["_country_q"] = None
    st.session_state["_manual_q"] = ""


def _on_change_manual() -> None:
    if st.session_state.get("_manual_q", "").strip():
        st.session_state["_input_mode"] = "manual"
    else:
        st.session_state["_input_mode"] = None


def _clear_manual() -> None:
    st.session_state["_input_mode"] = None
    st.session_state["_manual_q"] = ""


with tab_chat:
    if not groq_key:
        st.info("Add a Groq API key to `.env` to enable the chat.")
    else:
        import pandas as pd

        for _k, _v in [
            ("messages", []),
            ("_input_mode", None),
            ("_example_q", None),
            ("_country_q", None),
            ("_manual_q", ""),
        ]:
            if _k not in st.session_state:
                st.session_state[_k] = _v

        st.markdown("#### Ask a question")

        with st.container(border=True):
            st.caption(
                "❓ Ready-made — pick from a curated list of questions.\n\n"
                "🗺️ By country — generate a country-specific query.\n\n"
                "✏️ Your own — type any question about the knowledge graph.\n\n"
                "Choosing one locks the other two. Hit ✕ next to the label to clear it."
            )

            _mode = st.session_state["_input_mode"]

            # Row 1 — Ready-made
            _r1, _x1 = st.columns([11, 1])
            with _r1:
                st.selectbox(
                    "❓ Ready-made",
                    options=[None] + _EXAMPLE_QUESTIONS,
                    format_func=lambda x: "— pick an example question —" if x is None else x,
                    disabled=_mode not in (None, "example"),
                    on_change=_on_change_example,
                    key="_example_q",
                )
            with _x1:
                st.markdown('<div style="height:28px"></div>', unsafe_allow_html=True)
                if _mode == "example":
                    st.button("✕", key="_clr_ex", on_click=_clear_example)

            # Row 2 — By country
            _r2, _x2 = st.columns([11, 1])
            with _r2:
                st.selectbox(
                    "🗺️ By country",
                    options=[None] + _COUNTRIES,
                    format_func=lambda x: "— pick a country —" if x is None else x,
                    disabled=_mode not in (None, "country"),
                    on_change=_on_change_country,
                    key="_country_q",
                )
            with _x2:
                st.markdown('<div style="height:28px"></div>', unsafe_allow_html=True)
                if _mode == "country":
                    st.button("✕", key="_clr_co", on_click=_clear_country)

            st.divider()

            # Shared question box — pickers populate it; typing directly activates manual mode
            st.markdown("**✏️ Write your own**")
            st.text_area(
                "Write your own",
                label_visibility="collapsed",
                disabled=_mode in ("example", "country"),
                on_change=_on_change_manual,
                key="_manual_q",
                height=100,
                placeholder="Select a picker above, or type your question here.",
            )

        # Active question is always whatever is in the shared box
        _question: str | None = st.session_state.get("_manual_q", "").strip() or None

        # Action row
        _act_c, _exp_c = st.columns([3, 1])
        with _act_c:
            _ask_clicked = st.button("Ask", type="primary", use_container_width=True, disabled=not _question)
        with _exp_c:
            _all_rows: list[dict] = [
                row
                for _m in st.session_state.messages
                if _m["role"] == "assistant"
                for row in (_m.get("rows") or [])
            ]
            if _all_rows:
                _df_export = pd.DataFrame(_all_rows)
                st.download_button(
                    "Export CSV",
                    data=_df_export.to_csv(index=False).encode(),
                    file_name="water_results.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

        if _ask_clicked and _question:
            from datetime import datetime
            st.session_state.messages.append({
                "role": "user",
                "content": _question,
                "ts": datetime.now().strftime("%H:%M · %d %b %Y"),
            })
            with st.spinner("Querying knowledge graph…"):
                try:
                    chain = load_chain(groq_key)
                    result = chain.ask(_question)
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
            st.rerun()

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
            st.divider()
            _hcol, _bcol = st.columns([6, 1])
            with _hcol:
                st.markdown(f"#### Conversation history")
                st.caption(f"{len(_exchanges)} exchange(s) — newest first")
            with _bcol:
                st.markdown('<div style="height:32px"></div>', unsafe_allow_html=True)
                if st.button("Clear all", type="secondary", use_container_width=True):
                    st.session_state.messages = []
                    st.rerun()

            for _rev_idx, (_msg_idx, _user, _asst) in enumerate(reversed(_exchanges)):
                with st.container(border=True):
                    _qcol, _dcol = st.columns([20, 1])
                    with _qcol:
                        st.markdown(f"**{_user['content']}**")
                        if _user.get("ts"):
                            st.caption(_user["ts"])
                    with _dcol:
                        st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
                        if st.button("✕", key=f"del_{_rev_idx}", help="Remove this exchange"):
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

_CLASS_COLORS = {
    "industrial": "#1a6fa8",
    "water":      "#0f6e56",
    "pollution":  "#854F0B",
    "spatial":    "#993C1D",
    "regulatory": "#534AB7",
}

_OWL_CLASSES = [
    {
        "name": "IndustrialFacility",
        "group": "industrial",
        "count": "7,615 individuals",
        "description": (
            "An EU industrial site that is legally required to report its pollutant releases under the "
            "E-PRTR regulation. Each facility has a unique identifier, a name, a country code, a NUTS "
            "region, a NACE economic activity code, and geographic coordinates."
        ),
        "links_out": [
            ("hasEmissionEvent", "EmissionEvent",
             "Each facility generates one emission record per pollutant per year. "
             "A facility with many active years and many pollutants accumulates hundreds of records."),
            ("locatedInCatchment", "Catchment",
             "The facility's coordinates are matched to a River Basin District via point-in-polygon. "
             "This allows spatial queries such as 'all facilities in the Rhine basin'."),
        ],
        "links_in": [],
    },
    {
        "name": "EmissionEvent",
        "group": "industrial",
        "count": "254,156 individuals",
        "description": (
            "A single annual emission record: one facility released a specific quantity of one pollutant "
            "in one year via one medium (air, water, or land). Quantities are in kilograms per year. "
            "The record also flags whether the release was accidental."
        ),
        "links_out": [
            ("involvesPollutant", "Pollutant",
             "Each emission event is linked to the specific chemical substance that was released, "
             "allowing queries like 'all events involving mercury' or 'total nitrogen emitted per country'."),
        ],
        "links_in": [
            ("hasEmissionEvent", "IndustrialFacility",
             "The facility that reported this release. Every emission event belongs to exactly one facility."),
        ],
    },
    {
        "name": "MonitoringStation",
        "group": "water",
        "count": "2,168 individuals",
        "description": (
            "A fixed measurement point operated by an EU member state to track water quality. "
            "Stations are identified by a WISE6 station ID and name. Geographic coordinates were "
            "patched from the WISE monitoring sites service via a two-pass crosswalk "
            "(EIONET first, then WFD2022 batch lookup for unresolved stations)."
        ),
        "links_out": [
            ("monitors", "WaterBody",
             "The water body that this station is measuring. "
             "One station monitors exactly one water body."),
        ],
        "links_in": [],
    },
    {
        "name": "WaterBody",
        "group": "water",
        "count": "",
        "description": (
            "A river, lake, transitional water, or coastal water body identified by its WISE6 code "
            "and name. Water bodies are the unit of assessment under the EU Water Framework Directive."
        ),
        "links_out": [
            ("drainsToCatchment", "Catchment",
             "The River Basin District that this water body drains into. "
             "Used to spatially connect monitoring data to the broader basin."),
        ],
        "links_in": [
            ("monitors", "MonitoringStation",
             "The monitoring station that measures this water body. "
             "One water body may be monitored by one or more stations."),
        ],
    },
    {
        "name": "Pollutant",
        "group": "pollution",
        "count": "65 substances",
        "description": (
            "A chemical substance that is either emitted by industrial facilities or monitored at "
            "water quality stations. Identified by a standard name and, where available, a CAS registry "
            "number (e.g. CAS 7440-38-2 for arsenic)."
        ),
        "links_out": [
            ("hasThreshold", "ComplianceThreshold",
             "The regulatory emission limit that applies to this pollutant under EU law. "
             "Thresholds are drawn from the IED BREF Annex II table."),
        ],
        "links_in": [
            ("involvesPollutant", "EmissionEvent",
             "Every emission event that involves this substance. "
             "Allows aggregating total releases across all facilities and years."),
        ],
    },
    {
        "name": "ComplianceThreshold",
        "group": "pollution",
        "count": "90 thresholds",
        "description": (
            "A legally binding emission limit value from E-PRTR Regulation (EC) No 166/2006 Annex II. "
            "Specifies the maximum quantity (kg/year) that a facility may release for a given pollutant "
            "before the release must be publicly reported."
        ),
        "links_out": [
            ("regulatedBy", "RegulationDocument",
             "The legal instrument that defines this threshold. "
             "Provides the document title, year, and publisher for full traceability."),
        ],
        "links_in": [
            ("hasThreshold", "Pollutant",
             "The pollutant this threshold governs. "
             "Each threshold applies to exactly one substance."),
        ],
    },
    {
        "name": "Catchment",
        "group": "spatial",
        "count": "209 River Basin Districts",
        "description": (
            "An EU River Basin District (RBD) — the fundamental spatial management unit under the "
            "Water Framework Directive. RBDs are large hydrological areas defined by polygon geometry "
            "fetched from the EEA ArcGIS REST service. They serve as spatial containers linking "
            "industrial activity to water bodies."
        ),
        "links_out": [],
        "links_in": [
            ("locatedInCatchment", "IndustrialFacility",
             "All industrial facilities whose coordinates fall inside this RBD polygon. "
             "7,431 facilities were successfully matched."),
            ("drainsToCatchment", "WaterBody",
             "All water bodies that drain into this basin. "
             "1,559 water bodies were linked via this property."),
        ],
    },
    {
        "name": "RegulationDocument",
        "group": "regulatory",
        "count": "",
        "description": (
            "A regulatory source document that defines emission standards. Currently one individual: "
            "the IED Best Available Techniques Reference Document (BREF) for Large Combustion Plants, "
            "European Commission, 2017. It provides the legal authority behind the 90 compliance thresholds."
        ),
        "links_out": [],
        "links_in": [
            ("regulatedBy", "ComplianceThreshold",
             "All compliance thresholds that cite this document as their legal source."),
        ],
    },
]

with tab_explore:
    st.markdown("#### Ontology Entities")
    st.caption("Eight OWL classes. For each entity: what it represents, what it links to, and what links to it.")

    for _cls_meta in _OWL_CLASSES:
        _color = _CLASS_COLORS[_cls_meta["group"]]
        _badge = (
            f'<span style="background:{_color};color:#fff;padding:2px 10px;'
            f'border-radius:99px;font-size:12px;font-weight:500">{_cls_meta["name"]}</span>'
        )
        _count_str = f" &nbsp;·&nbsp; {_cls_meta['count']}" if _cls_meta["count"] else ""
        st.markdown(f"{_badge}{_count_str}", unsafe_allow_html=True)
        st.markdown(_cls_meta["description"])

        _lo, _li = _cls_meta["links_out"], _cls_meta["links_in"]
        if _lo or _li:
            _c1, _c2 = st.columns(2)
            with _c1:
                if _lo:
                    st.markdown("**Links to**")
                    for _prop, _target, _why in _lo:
                        st.markdown(f"→ **{_target}** via `{_prop}`")
                        st.caption(_why)
            with _c2:
                if _li:
                    st.markdown("**Linked from**")
                    for _prop, _src, _why in _li:
                        st.markdown(f"← **{_src}** via `{_prop}`")
                        st.caption(_why)
        st.divider()

    st.markdown("#### Ontology Graph")
    st.caption(
        "Hover over a node to inspect its data properties and instance count. "
        "Drag nodes to rearrange — use the filters to focus on a domain."
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

        st.divider()
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
