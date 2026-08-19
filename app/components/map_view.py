"""Folium map builder: queries the graph for geolocated entities and renders them."""

from __future__ import annotations

from typing import Any

import folium
from folium.plugins import FastMarkerCluster

_WC = "https://w3id.org/water-contamination/"
_GEO = "http://www.w3.org/2003/01/geo/wgs84_pos#"

_FACILITY_SPARQL = f"""
PREFIX wc:  <{_WC}>
PREFIX geo: <{_GEO}>
SELECT ?name ?country ?lat ?lon WHERE {{
    ?iri a wc:IndustrialFacility ;
         wc:facilityName ?name ;
         wc:countryCode  ?country .
    OPTIONAL {{ ?iri geo:lat ?lat ; geo:long ?lon . }}
}}
LIMIT 10000
"""

_STATION_SPARQL = f"""
PREFIX wc:  <{_WC}>
PREFIX geo: <{_GEO}>
SELECT ?name ?lat ?lon WHERE {{
    ?iri a wc:MonitoringStation .
    OPTIONAL {{ ?iri wc:stationName ?name . }}
    OPTIONAL {{ ?iri geo:lat ?lat ; geo:long ?lon . }}
}}
LIMIT 5000
"""

_FACILITY_CB = """
function(row) {
    return L.circleMarker([row[0], row[1]], {
        radius: 5, color: '#e74c3c',
        fill: true, fillColor: '#e74c3c', fillOpacity: 0.7
    }).bindTooltip('<b>' + row[2] + '</b><br>' + row[3]);
}
"""

_STATION_CB = """
function(row) {
    return L.circleMarker([row[0], row[1]], {
        radius: 4, color: '#2980b9',
        fill: true, fillColor: '#2980b9', fillOpacity: 0.7
    }).bindTooltip('<b>' + (row[2] || 'Station') + '</b>');
}
"""


def build_map(graph: Any) -> folium.Map:
    m = folium.Map(location=[52.0, 10.0], zoom_start=4, tiles="CartoDB positron")
    _add_facilities(m, graph)
    _add_stations(m, graph)
    _add_legend(m)
    return m


def _add_facilities(m: folium.Map, graph: Any) -> None:
    data = []
    for row in graph.query(_FACILITY_SPARQL):
        lat = _float(row.get("lat"))
        lon = _float(row.get("lon"))
        if lat is None or lon is None:
            continue
        data.append([lat, lon,
                      str(row.get("name") or "Unknown"),
                      str(row.get("country") or "")])
    if data:
        FastMarkerCluster(data=data, callback=_FACILITY_CB,
                          name="Industrial Facilities").add_to(m)


def _add_stations(m: folium.Map, graph: Any) -> None:
    data = []
    for row in graph.query(_STATION_SPARQL):
        lat = _float(row.get("lat"))
        lon = _float(row.get("lon"))
        if lat is None or lon is None:
            continue
        data.append([lat, lon, str(row.get("name") or "")])
    if data:
        FastMarkerCluster(data=data, callback=_STATION_CB,
                          name="Monitoring Stations").add_to(m)
    folium.LayerControl().add_to(m)


def _add_legend(m: folium.Map) -> None:
    legend_html = """
    <div style="
        position: fixed; bottom: 36px; left: 36px; z-index: 1000;
        background: rgba(255,255,255,0.95); padding: 12px 16px;
        border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.18);
        font-family: sans-serif; font-size: 13px; line-height: 2;
        min-width: 180px;
    ">
        <div style="font-weight:700; margin-bottom:4px;">Legend</div>
        <div>
            <svg width="14" height="14" style="vertical-align:middle;margin-right:6px">
                <circle cx="7" cy="7" r="6" fill="#e74c3c" fill-opacity="0.85"/>
            </svg>Industrial Facility
        </div>
        <div>
            <svg width="14" height="14" style="vertical-align:middle;margin-right:6px">
                <circle cx="7" cy="7" r="6" fill="#2980b9" fill-opacity="0.85"/>
            </svg>Monitoring Station
        </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))


def _float(val: Any) -> float | None:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
