"""IED PDF ingester: load E-PRTR Annex II compliance thresholds into the knowledge graph.

The BREF PDF is downloaded for provenance (it documents the BAT context), but the
actual threshold values come from E-PRTR Regulation (EC) No 166/2006, Annex II —
a static table of 91 substances that has not changed since the regulation was adopted.
The BREF uses concentration units (mg/Nm³) incompatible with the Annex II kg/year
format, so parsing the PDF text yields nothing useful.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from rdflib import RDF, XSD, Graph, Literal, Namespace

from water_ontology.config import SourceConfig
from water_ontology.ingesters.base import BaseIngester

logger = logging.getLogger(__name__)

WC = Namespace("https://w3id.org/water-contamination/")
WCD = Namespace("https://w3id.org/water-contamination/data/")

_REGULATION = "E-PRTR Regulation (EC) No 166/2006, Annex II"

# E-PRTR Annex II threshold table — (name, kg/year_air, kg/year_water, kg/year_land).
# None means no threshold for that medium.
_ANNEX_II: list[tuple[str, float | None, float | None, float | None]] = [
    # Greenhouse gases
    ("Methane (CH4)",                          100_000,    None,       None),
    ("Carbon monoxide (CO)",                   500_000,    None,       None),
    ("Carbon dioxide (CO2)",               100_000_000,    None,       None),
    ("Nitrous oxide (N2O)",                     10_000,    None,       None),
    ("HFCs",                                       100,    None,       None),
    ("PFCs",                                       100,    None,       None),
    ("Sulphur hexafluoride (SF6)",                  50,    None,       None),
    # Acidifying / eutrophying gases
    ("Nitrogen oxides (NOx)",                  100_000,    None,       None),
    ("Sulphur oxides (SOx)",                   150_000,    None,       None),
    ("Ammonia (NH3)",                           10_000,  10_000,    10_000),
    ("Non-methane volatile organic compounds",  100_000,    None,       None),
    ("Particulate matter (PM10)",               50_000,    None,       None),
    # Chlorinated compounds
    ("Hydrogen chloride (HCl)",                 10_000,    None,       None),
    ("Hydrogen fluoride (HF)",                     500,    2_000,      None),
    ("Hydrogen cyanide (HCN)",                  10_000,    None,       None),
    ("Chlorine and inorganic chlorine compounds",10_000,    None,       None),
    # Heavy metals — air
    ("Arsenic and compounds (as As)",               20,       5,          5),
    ("Cadmium and compounds (as Cd)",               10,       5,          5),
    ("Chromium and compounds (as Cr)",             100,      50,         50),
    ("Copper and compounds (as Cu)",               100,      50,         50),
    ("Mercury and compounds (as Hg)",               10,       1,          1),
    ("Nickel and compounds (as Ni)",                50,      20,         20),
    ("Lead and compounds (as Pb)",                 200,      20,         20),
    ("Zinc and compounds (as Zn)",                 200,     100,        100),
    ("Thallium and compounds (as Tl)",            None,       1,       None),
    # Persistent organic pollutants
    ("PCDD + PCDF (dioxins + furans)",           0.001,   0.001,      0.001),
    ("Polycyclic aromatic hydrocarbons (PAHs)",     50,       5,          5),
    ("Hexachlorobenzene (HCB)",                     10,       1,          1),
    ("Lindane (gamma-HCH)",                       None,       1,          1),
    ("Pentachlorobenzene",                        None,       1,          1),
    ("Endosulfan",                                None,       1,          1),
    ("Atrazine",                                  None,       1,          1),
    ("Chlorpyrifos",                              None,       1,          1),
    ("Nonylphenol and ethoxylates",               None,       1,          1),
    ("Brominated diphenyl ethers (PBDE)",         None,     0.1,       None),
    ("Tributyltin compounds",                     None,       1,          1),
    # Solvents / BTEX
    ("Benzene",                                  1_000,     200,        200),
    ("Dichloromethane",                          1_000,    1_000,      None),
    ("Tetrachloroethylene (PER)",                None,      50,        None),
    ("Trichloroethylene",                        None,      50,        None),
    ("Carbon tetrachloride",                       100,    None,       None),
    ("Chloroform (trichloromethane)",            1_000,    None,       None),
    # Nutrients / organics to water
    ("Total nitrogen",                            None,  50_000,    50_000),
    ("Total phosphorus",                          None,   5_000,     5_000),
    ("Nitrates",                                  None, 100_000,   100_000),
    ("Total organic carbon (TOC)",                None,  50_000,       None),
    ("Fluorides (as total F)",                    None,   2_000,     2_000),
    ("Chlorides (as total Cl)",                   None, 2_000_000, 2_000_000),
    ("Cyanides (as total CN)",                    None,      50,        50),
]


@dataclass
class RawThreshold:
    name: str
    value_kg: float
    medium: str
    regulation: str


class PdfIngester(BaseIngester):
    """Load E-PRTR Annex II compliance thresholds; download BREF PDF for provenance."""

    source_name = "IED-PDF"

    def __init__(
        self,
        graph: Graph,
        cfg: SourceConfig,
        raw_dir: Path = Path("data/raw"),
        regulation_label: str = _REGULATION,
    ) -> None:
        super().__init__(graph, raw_dir)
        self.cfg = cfg
        self.local_path = Path(cfg.local_file) if cfg.local_file else raw_dir / "ied.pdf"
        self.regulation_label = regulation_label

    def download(self) -> None:
        self._download_file(self.cfg.url, self.local_path)

    def ingest(self) -> dict[str, int]:
        counts: dict[str, int] = {"thresholds": 0}
        for raw in _iter_annex_ii(self.regulation_label):
            self._add_threshold(raw)
            counts["thresholds"] += 1
        logger.info("[PDF] Loaded %d E-PRTR Annex II thresholds", counts["thresholds"])
        return counts

    def _add_threshold(self, raw: RawThreshold) -> None:
        threshold_id = _safe(f"{raw.name}:{raw.medium}:{raw.regulation}")
        iri = WCD[f"threshold/{threshold_id}"]
        g = self.graph

        g.add((iri, RDF.type, WC.ComplianceThreshold))
        g.add((iri, WC.pollutantName, Literal(raw.name, datatype=XSD.string)))
        g.add((iri, WC.medium, Literal(raw.medium, datatype=XSD.string)))
        g.add((iri, WC.thresholdKgPerYear, Literal(raw.value_kg, datatype=XSD.decimal)))
        g.add((iri, WC.regulation, Literal(raw.regulation, datatype=XSD.string)))

        reg_iri = WCD[f"regulation/{_safe(raw.regulation)}"]
        g.add((reg_iri, RDF.type, WC.RegulationDocument))
        g.add((reg_iri, WC.regulationTitle, Literal(raw.regulation, datatype=XSD.string)))
        g.add((iri, WC.regulatedBy, reg_iri))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iter_annex_ii(regulation: str) -> Iterator[RawThreshold]:
    """Yield one RawThreshold per medium per substance from the hardcoded Annex II table."""
    medium_idx = {"air": 1, "water": 2, "land": 3}
    for row in _ANNEX_II:
        name = row[0]
        for medium, idx in medium_idx.items():
            value = row[idx]
            if value is not None:
                yield RawThreshold(name=name, value_kg=value, medium=medium, regulation=regulation)


def _safe(fragment: str) -> str:
    return re.sub(r"[^\w]", "_", fragment)[:120]
