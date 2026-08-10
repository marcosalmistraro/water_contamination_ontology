"""E-PRTR ingester: download ZIP, parse facility + release CSVs, populate graph."""

from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path
from typing import Iterator

import pandas as pd
from rdflib import Graph

from water_ontology.config import SourceConfig
from water_ontology.ingesters.base import BaseIngester
from water_ontology.mapping.eprtr_mapper import EprtrMapper
from water_ontology.models import EmissionEvent, IndustrialFacility, Pollutant

logger = logging.getLogger(__name__)

# E-PRTR v18 column names (may differ across versions — centralised here)
_FACILITY_COLS = {
    "FacilityID": "facility_id",
    "FacilityName": "name",
    "CountryCode": "country_code",
    "NUTSRegionSourceCode": "nuts_region",
    "Lat": "lat",
    "Long": "lon",
    "NACEMainEconomicActivityCode": "nace_code",
    "CompetentAuthorityName": "competent_authority",
    "StreetName": "street_address",
    "City": "city",
    "PostalCode": "postcode",
}

_RELEASE_COLS = {
    "FacilityID": "facility_id",
    "PollutantCode": "pollutant_code",
    "PollutantName": "pollutant_name",
    "ReportingYear": "reporting_year",
    "TotalQuantity": "quantity_kg",
    "Medium": "medium",
    "AccidentalQuantity": "accidental_quantity",
    "CASNumber": "cas_number",
}


class EprtrIngester(BaseIngester):
    """Ingest E-PRTR pollutant-release and facility data into the knowledge graph."""

    source_name = "E-PRTR"

    def __init__(
        self,
        graph: Graph,
        cfg: SourceConfig,
        raw_dir: Path = Path("data/raw"),
        chunksize: int | None = None,
    ) -> None:
        super().__init__(graph, raw_dir)
        self.cfg = cfg
        self.chunksize = chunksize or cfg.chunksize
        self.zip_path = Path(cfg.local_zip) if cfg.local_zip else raw_dir / "eprtr.zip"
        self.extract_dir = Path(cfg.extract_to) if cfg.extract_to else raw_dir / "eprtr"
        self.mapper = EprtrMapper(graph)

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download(self) -> None:
        """Download the E-PRTR ZIP archive unless already present."""
        self._download_file(self.cfg.url, self.zip_path)
        self._extract()

    def _extract(self) -> None:
        """Extract ZIP contents to extract_dir, skipping if already done."""
        releases_path = self.extract_dir / self.cfg.releases_file  # type: ignore[arg-type]
        if releases_path.exists():
            logger.info("[E-PRTR] Already extracted to %s", self.extract_dir)
            return

        logger.info("[E-PRTR] Extracting %s → %s", self.zip_path.name, self.extract_dir)
        self.extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(self.zip_path) as zf:
            zf.extractall(self.extract_dir)

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    def ingest(self) -> dict[str, int]:
        """Parse CSVs, map to ontology individuals, add triples to graph."""
        facilities = self._load_facilities()
        counts = {"facilities": 0, "pollutants": 0, "emission_events": 0}

        # Index facilities for reuse when building EmissionEvents
        facility_index: dict[str, IndustrialFacility] = {}
        for fac in facilities:
            self.mapper.add_facility(fac)
            facility_index[fac.facility_id] = fac
            counts["facilities"] += 1

        logger.info("[E-PRTR] Mapped %d facilities", counts["facilities"])

        pollutant_index: dict[str, Pollutant] = {}

        for chunk in self._iter_releases():
            for _, row in chunk.iterrows():
                pollutant_id = _pollutant_id(row["pollutant_code"], row["cas_number"])

                # Deduplicated pollutant individuals
                if pollutant_id not in pollutant_index:
                    pol = Pollutant(
                        pollutant_id=pollutant_id,
                        name=_str(row["pollutant_name"]),
                        cas_number=_str(row["cas_number"]) or None,
                        medium=_normalise_medium(row["medium"]),
                    )
                    self.mapper.add_pollutant(pol)
                    pollutant_index[pollutant_id] = pol
                    counts["pollutants"] += 1

                event = EmissionEvent(
                    event_id=_event_id(row),
                    facility_id=str(row["facility_id"]),
                    pollutant_id=pollutant_id,
                    reporting_year=int(row["reporting_year"]),
                    quantity_kg=_float(row["quantity_kg"]),
                    medium=_normalise_medium(row["medium"]),
                    accidental=_float(row["accidental_quantity"]) is not None
                    and _float(row["accidental_quantity"]) > 0,
                    data_source="E-PRTR",
                )
                self.mapper.add_emission_event(event)
                counts["emission_events"] += 1

        logger.info("[E-PRTR] Mapped %d pollutant types, %d emission events",
                    counts["pollutants"], counts["emission_events"])
        return counts

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_facilities(self) -> list[IndustrialFacility]:
        path = self.extract_dir / self.cfg.facilities_file  # type: ignore[arg-type]
        logger.info("[E-PRTR] Reading facilities from %s", path.name)
        df = pd.read_csv(path, encoding=self.cfg.encoding, low_memory=False)
        df = _rename_and_filter(df, _FACILITY_COLS)
        df = df.dropna(subset=["facility_id"])
        df["facility_id"] = df["facility_id"].astype(str)
        return [IndustrialFacility(**row) for row in df.to_dict(orient="records")]

    def _iter_releases(self) -> Iterator[pd.DataFrame]:
        """Yield chunked DataFrames of the releases CSV."""
        path = self.extract_dir / self.cfg.releases_file  # type: ignore[arg-type]
        logger.info("[E-PRTR] Streaming releases from %s (chunk=%d)", path.name, self.chunksize)

        reader = pd.read_csv(
            path,
            encoding=self.cfg.encoding,
            chunksize=self.chunksize,
            low_memory=False,
        )
        for chunk in reader:
            chunk = _rename_and_filter(chunk, _RELEASE_COLS)
            chunk = chunk.dropna(subset=["facility_id", "pollutant_code", "reporting_year"])
            chunk["facility_id"] = chunk["facility_id"].astype(str)
            yield chunk


# ---------------------------------------------------------------------------
# Module-level utilities
# ---------------------------------------------------------------------------

def _rename_and_filter(df: pd.DataFrame, col_map: dict[str, str]) -> pd.DataFrame:
    """Keep only mapped columns and rename them; tolerate missing columns."""
    present = {k: v for k, v in col_map.items() if k in df.columns}
    return df[list(present.keys())].rename(columns=present)


def _normalise_medium(raw: str | float) -> str:
    """Map E-PRTR medium codes to canonical values: air | water | land."""
    mapping = {"AIR": "air", "WATER": "water", "LAND": "land"}
    return mapping.get(str(raw).upper().strip(), "water")


def _str(val: object) -> str:
    return "" if pd.isna(val) else str(val).strip()  # type: ignore[arg-type]


def _float(val: object) -> float | None:
    try:
        f = float(val)  # type: ignore[arg-type]
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None


def _pollutant_id(code: object, cas: object) -> str:
    """Prefer CAS number; fall back to E-PRTR pollutant code."""
    cas_str = _str(cas)
    return f"CAS:{cas_str}" if cas_str else f"EPRTR:{_str(code)}"


def _event_id(row: pd.Series) -> str:  # type: ignore[type-arg]
    return f"EPRTR:{row['facility_id']}:{row['pollutant_code']}:{row['reporting_year']}"
