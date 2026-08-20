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

_FACILITY_CLUSTER_FN = """
function(cluster) {
    var n = cluster.getChildCount();
    var d = n < 100 ? 34 : n < 1000 ? 42 : 52;
    return L.divIcon({
        html: '<div style="width:'+d+'px;height:'+d+'px;border-radius:50%;background:rgba(231,76,60,0.88);border:2px solid rgba(255,255,255,0.55);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:11px;box-sizing:border-box">'+n+'</div>',
        className: '', iconSize: L.point(d, d)
    });
}
"""

_STATION_CLUSTER_FN = """
function(cluster) {
    var n = cluster.getChildCount();
    var d = n < 100 ? 34 : n < 1000 ? 42 : 52;
    return L.divIcon({
        html: '<div style="width:'+d+'px;height:'+d+'px;border-radius:50%;background:rgba(41,128,185,0.88);border:2px solid rgba(255,255,255,0.55);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:11px;box-sizing:border-box">'+n+'</div>',
        className: '', iconSize: L.point(d, d)
    });
}
"""


def build_map(graph: Any) -> folium.Map:
    m = folium.Map(location=[52.0, 10.0], zoom_start=4, tiles="CartoDB positron")
    _add_facilities(m, graph)
    _add_stations(m, graph)
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
                          icon_create_function=_FACILITY_CLUSTER_FN,
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
                          icon_create_function=_STATION_CLUSTER_FN,
                          name="Monitoring Stations").add_to(m)




def _float(val: Any) -> float | None:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
