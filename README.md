# Water Contamination Ontology

An ontology-driven pipeline that ingests EU industrial emissions and water quality data into an OWL/RDF knowledge graph, validates it with SHACL, and exposes it through a FastAPI backend and a Streamlit UI with natural-language querying.

## Architecture

```
Data sources (6)
    │
    ▼
Ingesters → RDF triples → OWL graph (rdflib)
                               │
                    ┌──────────┴──────────┐
                    ▼                     ▼
              FastAPI /ask          Streamlit UI
              /query /graph         Chat / Map / SPARQL
              (SPARQL + NL)
```

**Ontology classes:** `IndustrialFacility` · `EmissionEvent` · `Pollutant` · `WaterBody` · `MonitoringStation` · `ComplianceThreshold` · `Catchment` · `RegulationDocument`

**Data sources:**

| Source | What it provides |
|--------|-----------------|
| E-PRTR v16 (CSV/ZIP) | Industrial facilities, pollutant releases 2007–2024 |
| EEA Waterbase WISE6 (CSV/ZIP) | Water quality observations, monitoring stations |
| EEA River Basin Districts (ArcGIS GeoJSON) | EU catchment polygons, spatial join for facilities |
| WISE Monitoring Sites (ArcGIS GeoJSON) | Lat/lon coordinates for monitoring stations |
| IED BREF (static Annex II table) | E-PRTR compliance thresholds (91 substances, kg/year) |
| EnvThes (Turtle) | Environmental thesaurus vocabulary |

## Prerequisites

- Python ≥ 3.11
- `GROQ_API_KEY` — required for the `/ask` natural-language endpoint (Llama 3.3-70B via Groq). Without it, the API starts but `/ask` returns 503.

Copy `.env.example` to `.env` and fill in the key:

```
GROQ_API_KEY=your_key_here
```

## Installation

```bash
pip install -e ".[dev]"
```

## Running the pipeline

Run all sources end-to-end (downloads data if not already present, ingests, runs SHACL validation):

```bash
make ingest
# or
water-ontology ingest all --validate
```

Run a single source:

```bash
make ingest-eprtr
make ingest-waterbase
make ingest-geojson
make ingest-pdf
make ingest-rdf
# or
water-ontology ingest <source>
```

Validate an existing OWL file without re-ingesting:

```bash
make validate
```

The output graph is written to `data/ontology/water_contamination.owl`.

> **Note:** The Waterbase ZIP is ~733 MB; the extracted CSV is ~14 GB. Ingestion is capped at 500 000 rows by default (`max_rows` in `config/sources.yaml`). The full pipeline takes 10–30 minutes depending on network speed.

## Running the API

```bash
make api
# or
uvicorn water_ontology.api.app:app --reload
```

Endpoints:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/ask` | Natural-language question → SPARQL → answer |
| `POST` | `/query` | Raw SPARQL SELECT query |
| `GET` | `/graph/stats` | Triple counts per class |
| `GET` | `/health` | Liveness check |

## Running the UI

```bash
make ui
# or
streamlit run app/streamlit_app.py
```

Three tabs: **Chat** (NL queries), **Map** (Folium choropleth), **SPARQL** (raw editor).

## Testing

```bash
make test
# or
pytest tests/ -v
```

## Example SPARQL queries

Top 10 facilities by water release quantity:

```sparql
PREFIX wc: <https://w3id.org/water-contamination/>
PREFIX wcd: <https://w3id.org/water-contamination/data/>

SELECT ?name ?kg WHERE {
    ?fac a wc:IndustrialFacility ; wc:facilityName ?name .
    ?fac wc:hasEmissionEvent ?ev .
    ?ev wc:medium "water" ; wc:quantityKg ?kg .
}
ORDER BY DESC(?kg) LIMIT 10
```

Compliance thresholds for water pollutants:

```sparql
PREFIX wc: <https://w3id.org/water-contamination/>

SELECT ?name ?kg WHERE {
    ?t a wc:ComplianceThreshold ;
       wc:pollutantName ?name ;
       wc:medium "water" ;
       wc:thresholdKgPerYear ?kg .
}
ORDER BY ?kg
```

## Project layout

```
src/water_ontology/
├── api/            FastAPI app and route handlers
├── ingesters/      One ingester per data source
├── linkers/        Spatial join (facilities → river basin districts)
├── mapping/        Pydantic models → RDF triples (E-PRTR mapper)
├── query/          SPARQL engine, NL-to-SPARQL chain, guardrails
├── tracking/       MLflow integration (opt-in via --track)
├── validation/     SHACL validator
├── cli.py          Typer CLI entry point
├── config.py       Config loaders
├── graph.py        OWL graph builder
└── models.py       Pydantic domain models

app/                Streamlit frontend
config/             ontology.yaml, sources.yaml
data/
├── ontology/       water_contamination.owl, shacl_shapes.ttl
└── raw/            Downloaded source files (git-ignored)
tests/              One test module per source/component
```
