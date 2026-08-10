"""SHACL validation wrapper using pyshacl."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from rdflib import Graph

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    conforms: bool
    violation_count: int
    report_text: str


def validate(data_graph: Graph, shapes_path: Path) -> ValidationResult:
    """Run SHACL validation and return a structured result."""
    try:
        import pyshacl  # optional dev dependency
    except ImportError as exc:
        raise ImportError("Install pyshacl to enable SHACL validation") from exc

    shapes_graph = Graph().parse(str(shapes_path), format="turtle")
    conforms, report_graph, report_text = pyshacl.validate(
        data_graph,
        shacl_graph=shapes_graph,
        inference="rdfs",
        abort_on_first=False,
    )

    violation_count = _count_violations(report_graph)
    if not conforms:
        logger.warning("[SHACL] %d violation(s) found", violation_count)
    else:
        logger.info("[SHACL] Graph conforms to all shapes")

    return ValidationResult(
        conforms=conforms,
        violation_count=violation_count,
        report_text=str(report_text),
    )


def _count_violations(report_graph: Graph) -> int:
    from rdflib.namespace import SH
    return sum(1 for _ in report_graph.subjects(predicate=None, object=SH.Violation))
