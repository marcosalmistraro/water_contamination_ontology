"""Typer CLI entry point for the water-ontology ingestion pipeline."""

from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from water_ontology.ingesters.base import BaseIngester

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
        "all", help="Data source to ingest: eprtr | waterbase | geojson | pdf | rdf | monitoring_sites | all"
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
    from water_ontology.ingesters.monitoring_sites_ingester import MonitoringSitesIngester
    from water_ontology.linkers.spatial_joiner import link_facilities_to_rbds

    src_cfg = load_sources(sources_cfg)
    ont_cfg = load_ontology_config(ontology_cfg)
    graph = build_graph(ont_cfg)

    all_counts: dict[str, int] = {}
    skipped: list[str] = []

    ctx_manager = _maybe_mlflow(track, source)

    with ctx_manager:
        if source in ("eprtr", "all"):
            _run_ingester(
                "eprtr", lambda: EprtrIngester(graph, src_cfg.sources["eprtr"], raw_dir=raw_dir),
                all_counts, skipped, track,
            )

        if source in ("waterbase", "all") and "waterbase" in src_cfg.sources:
            _run_ingester(
                "waterbase",
                lambda: WaterbaseIngester(graph, src_cfg.sources["waterbase"], raw_dir=raw_dir),
                all_counts, skipped, track,
            )

        if source in ("geojson", "all") and "eea_geojson" in src_cfg.sources:
            _run_ingester(
                "geojson",
                lambda: GeoJsonIngester(
                    graph, src_cfg.sources["eea_geojson"], raw_dir=raw_dir, mode="both"
                ),
                all_counts, skipped, track,
            )

        if source in ("pdf", "all") and "ied_pdf" in src_cfg.sources:
            _run_ingester(
                "pdf",
                lambda: PdfIngester(graph, src_cfg.sources["ied_pdf"], raw_dir=raw_dir),
                all_counts, skipped, track,
            )

        if source in ("rdf", "all") and "inspire_envthes" in src_cfg.sources:
            _run_ingester(
                "rdf",
                lambda: RdfIngester(graph, src_cfg.sources["inspire_envthes"], raw_dir=raw_dir),
                all_counts, skipped, track,
            )

        if source in ("monitoring_sites", "all") and "wise_monitoring_sites" in src_cfg.sources:
            _run_ingester(
                "monitoring_sites",
                lambda: MonitoringSitesIngester(
                    graph, src_cfg.sources["wise_monitoring_sites"], raw_dir=raw_dir
                ),
                all_counts, skipped, track,
            )

        # Spatial join: link E-PRTR facilities to river basin districts
        if source == "all":
            import logging as _logging
            from water_ontology.linkers.spatial_joiner import link_stations_to_rbds
            _sj_log = _logging.getLogger(__name__)
            rbd_path = raw_dir / "eu_river_basins.geojson"
            try:
                sj_counts = link_facilities_to_rbds(graph, rbd_path)
                all_counts.update({f"spatial_{k}": v for k, v in sj_counts.items()})
                _sj_log.info("[SpatialJoin] %s", sj_counts)
            except Exception as exc:
                _sj_log.error("[SpatialJoin] Failed — skipping: %s", exc)
            try:
                sj2_counts = link_stations_to_rbds(graph, rbd_path)
                all_counts.update({f"spatial_stations_{k}": v for k, v in sj2_counts.items()})
                _sj_log.info("[SpatialJoin-Stations] %s", sj2_counts)
            except Exception as exc:
                _sj_log.error("[SpatialJoin-Stations] Failed — skipping: %s", exc)

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
    if skipped:
        console.print(f"[bold yellow]Skipped (errors): {', '.join(skipped)}[/bold yellow]")
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

def _run_ingester(
    label: str,
    factory: "Callable[[], BaseIngester]",
    all_counts: dict,
    skipped: list,
    track: bool,
) -> None:
    """Run one ingester, catch any exception, and continue the pipeline."""
    import logging as _logging
    _log = _logging.getLogger(__name__)
    try:
        ingester = factory()
        counts = ingester.run()
        all_counts.update({f"{label}_{k}": v for k, v in counts.items()})
        if track:
            from water_ontology.tracking.mlflow_logger import log_ingestion_counts
            log_ingestion_counts(counts)
    except Exception as exc:
        _log.error("[%s] Ingester failed — skipping: %s", label.upper(), exc)
        skipped.append(label)


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
