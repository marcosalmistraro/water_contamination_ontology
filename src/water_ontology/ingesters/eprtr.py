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

# Column aliases across E-PRTR versions — all keys that map to the same canonical name.
# v16 ZIP uses F2_4_Water_Releases_Facilities.csv for both facilities (deduplicated)
# and releases; v18 had separate EPRTR_Facilities.csv / EPRTR_PollutantReleases.csv.
_FACILITY_COLS = {
    # v16 — F2_4_Water_Releases_Facilities.csv
    "FacilityInspireId": "facility_id",
    "facilityName": "name",
    "countryName": "country_code",
    "city": "city",
    "Longitude": "lon",
    "Latitude": "lat",
    "EPRTR_SectorCode": "nace_code",
    # v18 legacy
    "FacilityID": "facility_id",
    "FacilityName": "name",
    "CountryCode": "country_code",
    "City": "city",
    "Lat": "lat",
    "Long": "lon",
    "NACEMainEconomicActivityCode": "nace_code",
    "CompetentAuthorityName": "competent_authority",
    "StreetName": "street_address",
    "PostalCode": "postcode",
}

_RELEASE_COLS = {
    # v16 — F2_4_Water_Releases_Facilities.csv
    "FacilityInspireId": "facility_id",
    "Pollutant": "pollutant_name",
    "reportingYear": "reporting_year",
    "Releases": "quantity_kg",
    "TargetRelease": "medium",
    # v18 legacy
    "FacilityID": "facility_id",
    "PollutantCode": "pollutant_code",
    "PollutantName": "pollutant_name",
    "ReportingYear": "reporting_year",
    "TotalQuantity": "quantity_kg",
    "Medium": "medium",
    "AccidentalQuantity": "accidental_quantity",
    "CASNumber": "cas_number",
}

# Fallback keywords for _resolve_csv when configured filename isn't found
_FACILITY_KEYWORDS = ("Water_Releases_Facilities",)
_RELEASE_KEYWORDS = ("Water_Releases_Facilities",)


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
        self.extract_dir.mkdir(parents=True, exist_ok=True)
        existing_csvs = list(self.extract_dir.rglob("*.csv"))
        if existing_csvs:
            logger.info("[E-PRTR] Already extracted (%d CSVs found)", len(existing_csvs))
            return

        logger.info("[E-PRTR] Extracting %s → %s", self.zip_path.name, self.extract_dir)
        with zipfile.ZipFile(self.zip_path) as zf:
            logger.info("[E-PRTR] ZIP contents: %s", [n for n in zf.namelist() if n.endswith(".csv")])
            zf.extractall(self.extract_dir)

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    def ingest(self) -> dict[str, int]:
        """Parse CSVs, map to ontology individuals, add triples to graph."""
        facilities = self._load_facilities()
        counts = {"facilities": 0, "pollutants": 0, "emission_events": 0}

        facility_index: dict[str, IndustrialFacility] = {}
        for fac in facilities:
            self.mapper.add_facility(fac)
            facility_index[fac.facility_id] = fac
            counts["facilities"] += 1

        logger.info("[E-PRTR] Mapped %d facilities", counts["facilities"])

        pollutant_index: dict[str, Pollutant] = {}

        for chunk in self._iter_releases():
            for _, row in chunk.iterrows():
                # pollutant_code is absent in v16; derive from name
                pol_code = _str(row.get("pollutant_code", ""))
                pol_name = _str(row.get("pollutant_name", ""))
                cas = _str(row.get("cas_number", "")) or None
                medium = _normalise_medium(row.get("medium", "water"))

                pollutant_id = _pollutant_id(pol_code or pol_name, cas)

                if pollutant_id not in pollutant_index:
                    pol = Pollutant(
                        pollutant_id=pollutant_id,
                        name=pol_name or pol_code,
                        cas_number=cas,
                        medium=medium,
                    )
                    self.mapper.add_pollutant(pol)
                    pollutant_index[pollutant_id] = pol
                    counts["pollutants"] += 1

                accidental_qty = _float(row.get("accidental_quantity", None))
                event = EmissionEvent(
                    event_id=_event_id(row, pol_code or pol_name),
                    facility_id=str(row["facility_id"]),
                    pollutant_id=pollutant_id,
                    reporting_year=int(row["reporting_year"]),
                    quantity_kg=_float(row["quantity_kg"]),
                    medium=medium,
                    accidental=accidental_qty is not None and accidental_qty > 0,
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

    def _resolve_csv(self, configured_name: str, keywords: tuple[str, ...]) -> Path:
        """Return path to a CSV: use configured name if found, else match by keyword."""
        direct = self.extract_dir / configured_name
        if direct.exists():
            return direct
        # Search recursively — new ZIP versions may nest files in subdirectories
        all_csvs = list(self.extract_dir.rglob("*.csv"))
        logger.debug("[E-PRTR] CSVs available: %s", [f.name for f in all_csvs])
        for kw in keywords:
            matches = [f for f in all_csvs if kw.lower() in f.name.lower()]
            if matches:
                logger.info("[E-PRTR] Resolved '%s' → %s", configured_name, matches[0].name)
                return matches[0]
        raise FileNotFoundError(
            f"Cannot find a CSV matching '{configured_name}' or keywords {keywords} "
            f"in {self.extract_dir}. Available: {[f.name for f in all_csvs]}"
        )

    def _load_facilities(self) -> list[IndustrialFacility]:
        path = self._resolve_csv(self.cfg.facilities_file, _FACILITY_KEYWORDS)  # type: ignore[arg-type]
        logger.info("[E-PRTR] Reading facilities from %s", path.name)
        df = pd.read_csv(path, encoding=self.cfg.encoding, low_memory=False)
        df = _rename_and_filter(df, _FACILITY_COLS)
        df = df.dropna(subset=["facility_id"])
        # Releases file has one row per release; deduplicate to get unique facilities
        df = df.drop_duplicates(subset=["facility_id"])
        df["facility_id"] = df["facility_id"].astype(str)
        return [IndustrialFacility(**_coerce_facility_row(row)) for row in df.to_dict(orient="records")]

    def _iter_releases(self) -> Iterator[pd.DataFrame]:
        """Yield chunked DataFrames of the releases CSV."""
        path = self._resolve_csv(self.cfg.releases_file, _RELEASE_KEYWORDS)  # type: ignore[arg-type]
        logger.info("[E-PRTR] Streaming releases from %s (chunk=%d)", path.name, self.chunksize)

        reader = pd.read_csv(
            path,
            encoding=self.cfg.encoding,
            chunksize=self.chunksize,
            low_memory=False,
        )
        for chunk in reader:
            chunk = _rename_and_filter(chunk, _RELEASE_COLS)
            # v16 has pollutant_name but not pollutant_code; accept either
            name_col = "pollutant_name" if "pollutant_name" in chunk.columns else "pollutant_code"
            chunk = chunk.dropna(subset=["facility_id", name_col, "reporting_year"])
            chunk["facility_id"] = chunk["facility_id"].astype(str)
            yield chunk


# ---------------------------------------------------------------------------
# Module-level utilities
# ---------------------------------------------------------------------------

_FLOAT_FACILITY_COLS = {"lat", "lon"}


def _coerce_facility_row(row: dict) -> dict:
    """Convert pandas float scalars to str for Optional[str] Pydantic fields."""
    out: dict = {}
    for k, v in row.items():
        if k in _FLOAT_FACILITY_COLS:
            out[k] = None if (isinstance(v, float) and pd.isna(v)) else float(v)
        elif isinstance(v, float):
            out[k] = None if pd.isna(v) else str(int(v) if v == int(v) else v)
        else:
            out[k] = v
    return out


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


def _pollutant_id(code_or_name: object, cas: object) -> str:
    """Prefer CAS number; fall back to code; last resort use name slug."""
    cas_str = _str(cas)
    if cas_str:
        return f"CAS:{cas_str}"
    slug = _str(code_or_name).replace(" ", "_").replace(",", "").replace("(", "").replace(")", "")[:60]
    return f"EPRTR:{slug}"


def _event_id(row: pd.Series, pol_label: str) -> str:  # type: ignore[type-arg]
    slug = pol_label.replace(" ", "_")[:40]
    return f"EPRTR:{row['facility_id']}:{slug}:{row['reporting_year']}"
