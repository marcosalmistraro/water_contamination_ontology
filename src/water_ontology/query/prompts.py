"""
System prompt builder: injects the ontology schema so the LLM generates
valid SPARQL against our specific classes, properties, and namespaces.
"""

from __future__ import annotations

from water_ontology.query.guardrails import ANSWER_GROUNDING, GROUNDING_RULES

# ── Ontology schema (kept in sync with graph.py and models.py) ────────────────

_NAMESPACES = """
PREFIX wc:      <https://w3id.org/water-contamination/>
PREFIX wcd:     <https://w3id.org/water-contamination/data/>
PREFIX geo:     <http://www.w3.org/2003/01/geo/wgs84_pos#>
PREFIX sosa:    <http://www.w3.org/ns/sosa/>
PREFIX owl:     <http://www.w3.org/2002/07/owl#>
PREFIX xsd:     <http://www.w3.org/2001/XMLSchema#>
PREFIX rdfs:    <http://www.w3.org/2000/01/rdf-schema#>
"""

_CLASSES = """
Classes:
  wc:IndustrialFacility   — an industrial site that releases pollutants
  wc:EmissionEvent        — a single pollutant release recorded in a reporting year
  wc:Pollutant            — a chemical substance released
  wc:WaterBody            — a river, lake, or coastal water body
  wc:MonitoringStation    — a measurement point on a water body
  wc:ComplianceThreshold  — a regulatory emission limit for a pollutant
  wc:Catchment            — a river basin or drainage area
  wc:RegulationDocument   — a legal instrument defining thresholds
"""

_PROPERTIES = """
Datatype properties:
  wc:facilityId           xsd:string   on IndustrialFacility
  wc:facilityName         xsd:string   on IndustrialFacility
  wc:countryCode          xsd:string   on IndustrialFacility, WaterBody (NOT on MonitoringStation).
                           Values are full English country names, e.g. "Germany", "France", "Poland" — NOT ISO codes.
  wc:nutsRegion           xsd:string   on IndustrialFacility
  wc:naceCode             xsd:string   on IndustrialFacility
  geo:lat                 xsd:decimal  on IndustrialFacility, MonitoringStation
  geo:long                xsd:decimal  on IndustrialFacility, MonitoringStation
  wc:reportingYear        xsd:integer  on EmissionEvent
  wc:quantityKg           xsd:decimal  on EmissionEvent
  wc:medium               xsd:string   on EmissionEvent, Pollutant   ("air", "water", or "land")
  wc:accidental           xsd:boolean  on EmissionEvent
  wc:dataSource           xsd:string   on EmissionEvent
  wc:pollutantName        xsd:string   on Pollutant
  wc:casNumber            xsd:string   on Pollutant
  wc:waterBodyId          xsd:string   on WaterBody
  wc:waterBodyName        xsd:string   on WaterBody
  wc:waterBodyType        xsd:string   on WaterBody
  wc:stationId            xsd:string   on MonitoringStation
  wc:stationName          xsd:string   on MonitoringStation
  wc:thresholdKgPerYear   xsd:decimal  on ComplianceThreshold
  wc:regulation           xsd:string   on ComplianceThreshold
  wc:catchmentId          xsd:string   on Catchment
  wc:catchmentName        xsd:string   on Catchment

Object properties:
  wc:hasEmissionEvent     IndustrialFacility → EmissionEvent
  wc:involvesPollutant    EmissionEvent      → Pollutant
  wc:monitors             MonitoringStation  → WaterBody
  wc:drainsToCatchment    WaterBody          → Catchment
  wc:locatedInCatchment   IndustrialFacility → Catchment
  wc:hasThreshold         Pollutant          → ComplianceThreshold
  wc:regulatedBy          ComplianceThreshold → RegulationDocument
"""

_SPARQL_NOTES = """
SPARQL notes:
- You MUST generate a SELECT query. Never use CONSTRUCT, ASK, or DESCRIBE.
- Always declare the PREFIX lines above at the top of every query.
- Individual IRIs follow the pattern wcd:facility/<id>, wcd:emission/<id>, etc.
  Do NOT hard-code individual IRIs — use triple patterns to find them.
- Use OPTIONAL for properties that may be absent (e.g. geo:lat, wc:nutsRegion).
- Always include a LIMIT clause.
- For aggregations (average, count, sum) use SELECT with GROUP BY and aggregate functions like AVG(), COUNT(), SUM().
"""

_EXAMPLES = """
EXAMPLES — study these before writing a query.

Q: Which facilities in Germany emitted the most nitrogen in 2022?
A:
PREFIX wc: <https://w3id.org/water-contamination/>
SELECT ?name (SUM(?qty) AS ?total) WHERE {
    ?f a wc:IndustrialFacility ;
       wc:facilityName ?name ;
       wc:countryCode "Germany" ;
       wc:hasEmissionEvent ?e .
    ?e wc:reportingYear 2022 ;
       wc:quantityKg ?qty ;
       wc:involvesPollutant ?p .
    ?p wc:pollutantName ?pname .
    FILTER(CONTAINS(LCASE(STR(?pname)), "nitrogen"))
}
GROUP BY ?name
ORDER BY DESC(?total)
LIMIT 10

Q: How many industrial facilities are there per country?
A:
PREFIX wc: <https://w3id.org/water-contamination/>
SELECT ?country (COUNT(DISTINCT ?f) AS ?count) WHERE {
    ?f a wc:IndustrialFacility ;
       wc:countryCode ?country .
}
GROUP BY ?country
ORDER BY DESC(?count)
LIMIT 50

Q: What are the top 5 pollutants by total emission quantity across all years?
A:
PREFIX wc: <https://w3id.org/water-contamination/>
SELECT ?pname (SUM(?qty) AS ?total) WHERE {
    ?e a wc:EmissionEvent ;
       wc:quantityKg ?qty ;
       wc:involvesPollutant ?p .
    ?p wc:pollutantName ?pname .
}
GROUP BY ?pname
ORDER BY DESC(?total)
LIMIT 5

Q: How many emission events are recorded per reporting year?
A:
PREFIX wc: <https://w3id.org/water-contamination/>
SELECT ?year (COUNT(?e) AS ?events) WHERE {
    ?e a wc:EmissionEvent ;
       wc:reportingYear ?year .
}
GROUP BY ?year
ORDER BY ?year

Q: Which countries had the highest total water emissions in 2022?
A:
PREFIX wc: <https://w3id.org/water-contamination/>
SELECT ?country (SUM(?qty) AS ?total) WHERE {
    ?f a wc:IndustrialFacility ;
       wc:countryCode ?country ;
       wc:hasEmissionEvent ?e .
    ?e wc:reportingYear 2022 ;
       wc:quantityKg ?qty ;
       wc:medium "water" .
}
GROUP BY ?country
ORDER BY DESC(?total)
LIMIT 10
"""

# ── Public builders ───────────────────────────────────────────────────────────

def sparql_generation_prompt() -> str:
    """System prompt for the SPARQL generation step."""
    return (
        "You are a SPARQL query generator for a water contamination knowledge graph.\n"
        + GROUNDING_RULES
        + "\nONTOLOGY SCHEMA\n"
        + _NAMESPACES
        + _CLASSES
        + _PROPERTIES
        + _SPARQL_NOTES
        + _EXAMPLES
        + "\nReturn ONLY the SPARQL query — no explanation, no markdown fences."
    )


def answer_generation_prompt() -> str:
    """System prompt for the natural-language answer generation step."""
    return (
        "You are an assistant that explains water contamination data to environmental analysts.\n"
        + ANSWER_GROUNDING
    )
