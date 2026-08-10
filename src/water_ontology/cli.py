"""Typer CLI entry point for the water-ontology ingestion pipeline."""

from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

app = typer.Typer(
    name="water-ontology",
    help="Automated ingestion pipeline for the water contamination ontology.",
    add_completion=False,
)
console = Console()


class LogLevel(str, Enum):
    debug = "DEBUG"
    info = "INFO"
    warning = "WARNING"
    error = "ERROR"


def _setup_logging(level: LogLevel) -> None:
    logging.basicConfig(
        level=level.value,
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True, console=Console(stderr=True))],
    )


@app.command()
def ingest(
    source: str = typer.Argument(
        "all", help="Data source to ingest: eprtr | waterbase | geojson | pdf | rdf | all"
    ),
    raw_dir: Path = typer.Option(Path("data/raw"), help="Directory for raw downloads"),
    output: Path = typer.Option(
        Path("data/ontology/water_contamination.owl"), help="Output OWL file"
    ),
    sources_cfg: Path = typer.Option(Path("config/sources.yaml"), help="Sources config"),
    ontology_cfg: Path = typer.Option(Path("config/ontology.yaml"), help="Ontology config"),
    validate: bool = typer.Option(True, help="Run SHACL validation after ingestion"),
    shacl_shapes: Path = typer.Option(
        Path("data/ontology/shacl_shapes.ttl"), help="SHACL shapes file"
    ),
    log_level: LogLevel = typer.Option(LogLevel.info, help="Logging verbosity"),
    track: bool = typer.Option(False, help="Log run to MLflow"),
) -> None:
    """Download, parse, and populate the knowledge graph."""
    _setup_logging(log_level)

    from water_ontology.config import load_ontology_config, load_sources
    from water_ontology.graph import build_graph, save_graph
    from water_ontology.ingesters.eprtr import EprtrIngester
    from water_ontology.ingesters.waterbase import WaterbaseIngester
    from water_ontology.ingesters.geojson_ingester import GeoJsonIngester
    from water_ontology.ingesters.pdf_ingester import PdfIngester
    from water_ontology.ingesters.rdf_ingester import RdfIngester

    src_cfg = load_sources(sources_cfg)
    ont_cfg = load_ontology_config(ontology_cfg)
    graph = build_graph(ont_cfg)

    all_counts: dict[str, int] = {}

    ctx_manager = _maybe_mlflow(track, source)

    with ctx_manager:
        if source in ("eprtr", "all"):
            ingester = EprtrIngester(graph, src_cfg.sources["eprtr"], raw_dir=raw_dir)
            counts = ingester.run()
            all_counts.update({f"eprtr_{k}": v for k, v in counts.items()})
            if track:
                from water_ontology.tracking.mlflow_logger import log_ingestion_counts
                log_ingestion_counts(counts)

        if source in ("waterbase", "all") and "waterbase" in src_cfg.sources:
            ingester_wb = WaterbaseIngester(graph, src_cfg.sources["waterbase"], raw_dir=raw_dir)
            counts = ingester_wb.run()
            all_counts.update({f"waterbase_{k}": v for k, v in counts.items()})
            if track:
                from water_ontology.tracking.mlflow_logger import log_ingestion_counts
                log_ingestion_counts(counts)

        if source in ("geojson", "all") and "eea_geojson" in src_cfg.sources:
            ingester_geo = GeoJsonIngester(
                graph, src_cfg.sources["eea_geojson"], raw_dir=raw_dir, mode="both"
            )
            counts = ingester_geo.run()
            all_counts.update({f"geojson_{k}": v for k, v in counts.items()})
            if track:
                from water_ontology.tracking.mlflow_logger import log_ingestion_counts
                log_ingestion_counts(counts)

        if source in ("pdf", "all") and "ied_pdf" in src_cfg.sources:
            ingester_pdf = PdfIngester(graph, src_cfg.sources["ied_pdf"], raw_dir=raw_dir)
            counts = ingester_pdf.run()
            all_counts.update({f"pdf_{k}": v for k, v in counts.items()})
            if track:
                from water_ontology.tracking.mlflow_logger import log_ingestion_counts
                log_ingestion_counts(counts)

        if source in ("rdf", "all") and "inspire_envthes" in src_cfg.sources:
            ingester_rdf = RdfIngester(graph, src_cfg.sources["inspire_envthes"], raw_dir=raw_dir)
            counts = ingester_rdf.run()
            all_counts.update({f"rdf_{k}": v for k, v in counts.items()})
            if track:
                from water_ontology.tracking.mlflow_logger import log_ingestion_counts
                log_ingestion_counts(counts)

        if validate and shacl_shapes.exists():
            from water_ontology.validation.shacl_validator import validate as shacl_validate
            from water_ontology.tracking.mlflow_logger import log_validation_result
            result = shacl_validate(graph, shacl_shapes)
            if track:
                log_validation_result(result.conforms, result.violation_count)
            if not result.conforms:
                console.print(f"[bold red]SHACL: {result.violation_count} violation(s)[/bold red]")
            else:
                console.print("[bold green]SHACL: graph conforms[/bold green]")

    save_graph(graph, output, fmt="xml")
    console.print(f"[bold green]Graph saved → {output}[/bold green]")
    _print_counts(all_counts)


@app.command()
def validate_only(
    owl_file: Path = typer.Argument(..., help="OWL file to validate"),
    shacl_shapes: Path = typer.Option(
        Path("data/ontology/shacl_shapes.ttl"), help="SHACL shapes file"
    ),
    log_level: LogLevel = typer.Option(LogLevel.info),
) -> None:
    """Run SHACL validation on an existing OWL file."""
    _setup_logging(log_level)
    from water_ontology.graph import load_graph
    from water_ontology.validation.shacl_validator import validate

    graph = load_graph(owl_file)
    result = validate(graph, shacl_shapes)
    console.print(result.report_text)
    raise typer.Exit(code=0 if result.conforms else 1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_counts(counts: dict[str, int]) -> None:
    table = Table(title="Ingestion summary", show_header=True)
    table.add_column("Entity", style="cyan")
    table.add_column("Count", justify="right", style="green")
    for key, val in counts.items():
        table.add_row(key, str(val))
    console.print(table)


def _maybe_mlflow(track: bool, run_name: str) -> object:
    if not track:
        from contextlib import nullcontext
        return nullcontext()
    from water_ontology.tracking.mlflow_logger import pipeline_run
    return pipeline_run(run_name)


if __name__ == "__main__":
    app()
