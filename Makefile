.PHONY: install lint test ingest ingest-eprtr ingest-waterbase ingest-geojson ingest-pdf ingest-rdf validate validate-graph ui api clean

install:
	pip install -e ".[dev]"

lint:
	ruff check src tests
	mypy src

test:
	pytest tests/ -v

# Full pipeline (all sources)
ingest:
	water-ontology ingest all --no-validate

# Validate a previously saved graph (slow on large graphs — run separately)
validate-graph:
	water-ontology validate-only data/ontology/water_contamination.nt

# Individual sources
ingest-eprtr:
	water-ontology ingest eprtr --validate

ingest-waterbase:
	water-ontology ingest waterbase --validate

ingest-geojson:
	water-ontology ingest geojson --validate

ingest-pdf:
	water-ontology ingest pdf --validate

ingest-rdf:
	water-ontology ingest rdf --validate

# Launch Streamlit UI
ui:
	streamlit run app/streamlit_app.py

# Launch FastAPI (dev)
api:
	uvicorn water_ontology.api.app:app --reload

# Validate an existing OWL file
validate:
	water-ontology validate-only data/ontology/water_contamination.nt

clean:
	rm -rf data/raw/ data/processed/ mlruns/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -name "*.pyc" -delete
