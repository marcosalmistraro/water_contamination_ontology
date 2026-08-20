"""MLflow run logger for pipeline auditability."""

from __future__ import annotations

import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "mlruns")
_EXPERIMENT = os.getenv("MLFLOW_EXPERIMENT", "water_contamination_pipeline")


@contextmanager
def pipeline_run(
    run_name: str,
    tags: dict[str, str] | None = None,
) -> Generator[Any, None, None]:
    """Context manager that wraps a pipeline execution in an MLflow run."""
    try:
        import mlflow
    except ImportError as exc:
        raise ImportError("Install mlflow to enable run tracking") from exc

    mlflow.set_tracking_uri(_TRACKING_URI)
    mlflow.set_experiment(_EXPERIMENT)

    with mlflow.start_run(run_name=run_name, tags=tags or {}) as run:
        logger.info("[MLflow] Run started: %s (id=%s)", run_name, run.info.run_id)
        yield run
        logger.info("[MLflow] Run finished: %s", run.info.run_id)


def log_ingestion_counts(counts: dict[str, int]) -> None:
    """Log entity counts as MLflow metrics."""
    try:
        import mlflow
        for key, value in counts.items():
            mlflow.log_metric(key, value)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[MLflow] Could not log metrics: %s", exc)


def log_validation_result(conforms: bool, violation_count: int) -> None:
    """Log SHACL validation outcome."""
    try:
        import mlflow
        mlflow.log_metric("shacl_conforms", int(conforms))
        mlflow.log_metric("shacl_violations", violation_count)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[MLflow] Could not log validation: %s", exc)
