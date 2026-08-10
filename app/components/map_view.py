"""Folium map builder: queries the graph for geolocated entities and renders them."""

from __future__ import annotations

from typing import Any

import folium
from rdflib import Graph

_WC = "https://w3id.org/water-contamination/"
_WCD = "https://w3id.org/water-contamination/data/"
_GEO = "http://www.w3.org/2003/01/geo/wgs84_pos#"

_FACILITY_SPARQL = f"""
PREFIX wc:  <{_WC}>
PREFIX geo: <{_GEO}>
SELECT ?iri ?name ?country ?lat ?lon WHERE {{
    ?iri a wc:IndustrialFacility ;
         wc:facilityName ?name ;
         wc:countryCode  ?country .
    OPTIONAL {{ ?iri geo:lat ?lat ; geo:long ?lon . }}
}}
LIMIT 2000
"""

_STATION_SPARQL = f"""
PREFIX wc:  <{_WC}>
PREFIX geo: <{_GEO}>
SELECT ?iri ?name ?lat ?lon WHERE {{
    ?iri a wc:MonitoringStation .
    OPTIONAL {{ ?iri wc:stationName ?name . }}
    OPTIONAL {{ ?iri geo:lat ?lat ; geo:long ?lon . }}
}}
LIMIT 2000
"""


def build_map(graph: Graph) -> folium.Map:
    """Return a Folium map populated with facilities and monitoring stations."""
    m = folium.Map(
        location=[52.0, 10.0],   # centred on central Europe
        zoom_start=4,
        tiles="CartoDB positron",
    )

    _add_facilities(m, graph)
    _add_stations(m, graph)
    _add_legend(m)
    return m


def _add_facilities(m: folium.Map, graph: Graph) -> None:
    results = graph.query(_FACILITY_SPARQL)
    fg = folium.FeatureGroup(name="Industrial Facilities", show=True)

    for row in results:
        lat = _float(row.get("lat"))
        lon = _float(row.get("lon"))
        if lat is None or lon is None:
            continue

        name = str(row.get("name") or "Unknown facility")
        country = str(row.get("country") or "")

        folium.CircleMarker(
            location=[lat, lon],
            radius=5,
            color="#e74c3c",
            fill=True,
            fill_color="#e74c3c",
            fill_opacity=0.7,
            tooltip=f"<b>{name}</b><br>{country}",
            popup=folium.Popup(
                f"<b>{name}</b><br>Country: {country}<br>"
                f"<small>{str(row.get('iri') or '')}</small>",
                max_width=300,
            ),
        ).add_to(fg)

    fg.add_to(m)


def _add_stations(m: folium.Map, graph: Graph) -> None:
    results = graph.query(_STATION_SPARQL)
    fg = folium.FeatureGroup(name="Monitoring Stations", show=True)

    for row in results:
        lat = _float(row.get("lat"))
        lon = _float(row.get("lon"))
        if lat is None or lon is None:
            continue

        name = str(row.get("name") or "Monitoring station")

        folium.CircleMarker(
            location=[lat, lon],
            radius=4,
            color="#2980b9",
            fill=True,
            fill_color="#2980b9",
            fill_opacity=0.7,
            tooltip=f"<b>{name}</b>",
        ).add_to(fg)

    fg.add_to(m)
    folium.LayerControl().add_to(m)


def _add_legend(m: folium.Map) -> None:
    legend_html = """
    <div style="
        position: fixed; bottom: 30px; left: 30px; z-index: 1000;
        background: white; padding: 10px 14px; border-radius: 6px;
        border: 1px solid #ccc; font-size: 13px; line-height: 1.8;
    ">
        <b>Legend</b><br>
        <span style="color:#e74c3c">●</span> Industrial Facility<br>
        <span style="color:#2980b9">●</span> Monitoring Station
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))


def _float(val: Any) -> float | None:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
