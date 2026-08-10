"""IED PDF ingester: extract compliance thresholds from Industrial Emissions Directive PDFs."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from rdflib import Graph, Literal, Namespace, RDF, XSD

from water_ontology.config import SourceConfig
from water_ontology.ingesters.base import BaseIngester
from water_ontology.models import ComplianceThreshold

logger = logging.getLogger(__name__)

WC = Namespace("https://w3id.org/water-contamination/")
WCD = Namespace("https://w3id.org/water-contamination/data/")

# Regex patterns tuned for IED / E-PRTR threshold tables.
# Matches lines like: "Arsenic and its compounds  5  kg/year  water"
_THRESHOLD_RE = re.compile(
    r"(?P<name>[A-Za-z][\w\s,()/-]{2,60}?)"     # pollutant name (lazy)
    r"\s{2,}"                                    # gap (table cell boundary)
    r"(?P<value>[\d,.]+)"                        # numeric threshold
    r"\s+"
    r"(?P<unit>kg/year|t/year|g/year|mg/year)"  # unit
    r"\s+"
    r"(?P<medium>air|water|land)",               # medium
    re.IGNORECASE,
)

# E-PRTR Regulation threshold table header text — used to locate the right pages.
_TABLE_ANCHOR = re.compile(r"pollutant.*threshold.*medium|threshold.*pollutant", re.IGNORECASE)


@dataclass
class RawThreshold:
    name: str
    value_kg: float
    medium: str
    page: int
    regulation: str


class PdfIngester(BaseIngester):
    """Extract ComplianceThreshold individuals from IED / E-PRTR PDF documents."""

    source_name = "IED-PDF"

    def __init__(
        self,
        graph: Graph,
        cfg: SourceConfig,
        raw_dir: Path = Path("data/raw"),
        regulation_label: str = "E-PRTR Regulation (EC) No 166/2006",
    ) -> None:
        super().__init__(graph, raw_dir)
        self.cfg = cfg
        self.local_path = Path(cfg.local_file) if cfg.local_file else raw_dir / "ied.pdf"
        self.regulation_label = regulation_label

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download(self) -> None:
        self._download_file(self.cfg.url, self.local_path)

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    def ingest(self) -> dict[str, int]:
        try:
            import pdfplumber
        except ImportError as exc:
            raise ImportError("Install pdfplumber to enable PDF ingestion") from exc

        logger.info("[PDF] Parsing %s", self.local_path.name)
        counts: dict[str, int] = {"thresholds": 0}

        with pdfplumber.open(str(self.local_path)) as pdf:
            for raw in self._extract_thresholds(pdf):
                self._add_threshold(raw)
                counts["thresholds"] += 1

        logger.info("[PDF] Extracted %d thresholds", counts["thresholds"])
        return counts

    # ------------------------------------------------------------------
    # Extraction logic
    # ------------------------------------------------------------------

    def _extract_thresholds(self, pdf: object) -> Iterator[RawThreshold]:
        """Yield RawThreshold objects parsed from threshold tables in the PDF."""
        in_table = False
        for page_num, page in enumerate(pdf.pages, start=1):  # type: ignore[attr-defined]
            text = page.extract_text() or ""

            # Activate table mode when we find the anchor header
            if _TABLE_ANCHOR.search(text):
                in_table = True

            if not in_table:
                continue

            for line in text.splitlines():
                m = _THRESHOLD_RE.search(line)
                if not m:
                    continue

                name = m.group("name").strip().rstrip(",")
                raw_val = m.group("value").replace(",", "")
                unit = m.group("unit").lower()
                medium = m.group("medium").lower()

                try:
                    value = float(raw_val)
                except ValueError:
                    continue

                value_kg = _to_kg_per_year(value, unit)
                yield RawThreshold(
                    name=name,
                    value_kg=value_kg,
                    medium=medium,
                    page=page_num,
                    regulation=self.regulation_label,
                )

    # ------------------------------------------------------------------
    # Triple builder
    # ------------------------------------------------------------------

    def _add_threshold(self, raw: RawThreshold) -> None:
        threshold_id = _safe(f"{raw.name}:{raw.medium}:{raw.regulation}")
        iri = WCD[f"threshold/{threshold_id}"]
        g = self.graph

        g.add((iri, RDF.type, WC.ComplianceThreshold))
        g.add((iri, WC.pollutantName, Literal(raw.name, datatype=XSD.string)))
        g.add((iri, WC.medium, Literal(raw.medium, datatype=XSD.string)))
        g.add((iri, WC.thresholdKgPerYear, Literal(raw.value_kg, datatype=XSD.decimal)))
        g.add((iri, WC.regulation, Literal(raw.regulation, datatype=XSD.string)))

        # Link to RegulationDocument individual
        reg_iri = WCD[f"regulation/{_safe(raw.regulation)}"]
        g.add((reg_iri, RDF.type, WC.RegulationDocument))
        g.add((reg_iri, WC.regulationTitle, Literal(raw.regulation, datatype=XSD.string)))
        g.add((iri, WC.regulatedBy, reg_iri))


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _to_kg_per_year(value: float, unit: str) -> float:
    factors = {"kg/year": 1.0, "t/year": 1_000.0, "g/year": 0.001, "mg/year": 1e-6}
    return value * factors.get(unit, 1.0)


def _safe(fragment: str) -> str:
    return re.sub(r"[^\w]", "_", fragment)[:120]
