"""EEA Waterbase ingester: CSV-in-ZIP → MonitoringStation + WaterQualityObservation triples.

EEA retired the single-file Excel download (≤v2021). Data is now distributed as
CSV files inside a ZIP archive (WISE6 ICM schema). The ingester downloads the ZIP,
extracts it, finds the main measurement CSV by keyword, and streams it in chunks.
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

import pandas as pd
from rdflib import RDF, XSD, Graph, Literal, Namespace

from water_ontology.config import SourceConfig
from water_ontology.ingesters.base import BaseIngester

logger = logging.getLogger(__name__)

WC = Namespace("https://w3id.org/water-contamination/")
WCD = Namespace("https://w3id.org/water-contamination/data/")
SOSA = Namespace("http://www.w3.org/ns/sosa/")
GEO = Namespace("http://www.w3.org/2003/01/geo/wgs84_pos#")

# Waterbase ICM v2021 column mapping (tolerates minor header variations)
_STATION_COLS = {
    "monitoringSiteIdentifier": "station_id",
    "monitoringSiteName": "name",
    "lat": "lat",
    "lon": "lon",
    "waterBodyIdentifier": "water_body_id",
    "countryCode": "country_code",
}

_OBS_COLS = {
    "monitoringSiteIdentifier": "station_id",
    "observedPropertyDeterminandLabel": "parameter_name",
    "observedPropertyDeterminandCode": "parameter_code",
    "phenomenonTimeReferenceYear": "year",
    "resultMeanValue": "mean_value",
    "resultUom": "unit",
    "parameterWaterBodyCategory": "water_category",
}


def _safe(fragment: str) -> str:
    return str(fragment).replace(" ", "_").replace("/", "-").replace(":", "_")


class WaterbaseIngester(BaseIngester):
    """Ingest EEA Waterbase water quality measurements into the knowledge graph."""

    source_name = "EEA-Waterbase"

    def __init__(
        self,
        graph: Graph,
        cfg: SourceConfig,
        raw_dir: Path = Path("data/raw"),
    ) -> None:
        super().__init__(graph, raw_dir)
        self.cfg = cfg
        self.zip_path = Path(cfg.local_zip) if cfg.local_zip else raw_dir / "waterbase.zip"
        self.extract_dir = Path(cfg.extract_to) if cfg.extract_to else raw_dir / "waterbase"
        self.chunksize = cfg.chunksize

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download(self) -> None:
        self._download_file(self.cfg.url, self.zip_path)
        self._extract()

    def _extract(self) -> None:
        self.extract_dir.mkdir(parents=True, exist_ok=True)
        if list(self.extract_dir.rglob("*.csv")):
            logger.info("[Waterbase] Already extracted")
            return
        logger.info("[Waterbase] Extracting %s → %s", self.zip_path.name, self.extract_dir)
        with zipfile.ZipFile(self.zip_path) as zf:
            logger.info("[Waterbase] ZIP contents: %s", zf.namelist())
            zf.extractall(self.extract_dir)

    def _find_csv(self) -> Path:
        """Find the main measurement CSV — prefer files with 'Disaggregated' or 'ICM' in name."""
        all_csvs = list(self.extract_dir.rglob("*.csv"))
        for kw in ("Disaggregated", "ICM", "waterbase", "WISE"):
            matches = [f for f in all_csvs if kw.lower() in f.name.lower()]
            if matches:
                return matches[0]
        if all_csvs:
            return all_csvs[0]
        raise FileNotFoundError(f"No CSV found in {self.extract_dir}")

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    def ingest(self) -> dict[str, int]:
        csv_path = self._find_csv()
        logger.info("[Waterbase] Streaming %s (chunk=%d)", csv_path.name, self.chunksize)

        counts: dict[str, int] = {"stations": 0, "water_bodies": 0, "observations": 0}
        wb_seen: set[str] = set()
        station_seen: set[str] = set()
        rows_processed = 0
        max_rows = self.cfg.max_rows

        reader = pd.read_csv(
            csv_path,
            encoding=self.cfg.encoding,
            chunksize=self.chunksize,
            low_memory=False,
        )
        for chunk in reader:
            if max_rows and rows_processed >= max_rows:
                logger.info("[Waterbase] max_rows=%d reached — stopping early", max_rows)
                break
            if max_rows:
                chunk = chunk.iloc[: max_rows - rows_processed]
            rows_processed += len(chunk)
            for _, row in chunk.iterrows():
                sid = _str(row.get("monitoringSiteIdentifier", ""))
                # WISE6 disaggregated CSV omits waterBodyIdentifier; fall back to
                # site ID as a proxy (each monitoring site monitors one water body).
                wb_id = _str(row.get("waterBodyIdentifier", "")) or sid
                if wb_id and wb_id not in wb_seen:
                    self._add_water_body(wb_id, row)
                    wb_seen.add(wb_id)
                    counts["water_bodies"] += 1
                if sid and sid not in station_seen:
                    self._add_station(sid, row, wb_id)
                    station_seen.add(sid)
                    counts["stations"] += 1

                if sid:
                    self._add_observation(sid, row)
                    counts["observations"] += 1

        logger.info(
            "[Waterbase] %d stations, %d water bodies, %d observations",
            counts["stations"], counts["water_bodies"], counts["observations"],
        )
        return counts

    # ------------------------------------------------------------------
    # Private triple builders
    # ------------------------------------------------------------------

    def _add_water_body(self, wb_id: str, row: pd.Series) -> None:  # type: ignore[type-arg]
        iri = WCD[f"waterbody/{_safe(wb_id)}"]
        g = self.graph
        g.add((iri, RDF.type, WC.WaterBody))
        g.add((iri, WC.waterBodyId, Literal(wb_id, datatype=XSD.string)))
        name = _str(row.get("waterBodyName", ""))
        if name:
            g.add((iri, WC.waterBodyName, Literal(name, datatype=XSD.string)))
        category = _str(row.get("parameterWaterBodyCategory", ""))
        if category:
            g.add((iri, WC.waterBodyType, Literal(category, datatype=XSD.string)))
        cc = _str(row.get("countryCode", ""))
        if cc:
            g.add((iri, WC.countryCode, Literal(cc, datatype=XSD.string)))

    def _add_station(self, sid: str, row: pd.Series, wb_id: str) -> None:  # type: ignore[type-arg]
        iri = WCD[f"station/{_safe(sid)}"]
        g = self.graph
        g.add((iri, RDF.type, WC.MonitoringStation))
        g.add((iri, WC.stationId, Literal(sid, datatype=XSD.string)))

        name = _str(row.get("monitoringSiteName", ""))
        if name:
            g.add((iri, WC.stationName, Literal(name, datatype=XSD.string)))

        lat = _float(row.get("lat"))
        lon = _float(row.get("lon"))
        if lat is not None:
            g.add((iri, GEO.lat, Literal(lat, datatype=XSD.decimal)))
        if lon is not None:
            g.add((iri, GEO.long, Literal(lon, datatype=XSD.decimal)))

        if wb_id:
            wb_iri = WCD[f"waterbody/{_safe(wb_id)}"]
            g.add((iri, WC.monitors, wb_iri))

    def _add_observation(self, sid: str, row: pd.Series) -> None:  # type: ignore[type-arg]
        param_code = _str(row.get("observedPropertyDeterminandCode", ""))
        # WISE6 DisaggregatedData uses sampling date; extract year for grouping
        date_str = _str(row.get("phenomenonTimeSamplingDate", row.get("phenomenonTimeReferenceYear", "")))
        year = date_str[:4] if len(date_str) >= 4 else ""
        if not param_code or not year:
            return

        obs_id = f"{sid}:{param_code}:{year}"
        iri = WCD[f"observation/{_safe(obs_id)}"]
        station_iri = WCD[f"station/{_safe(sid)}"]
        g = self.graph

        g.add((iri, RDF.type, SOSA.Observation))
        g.add((iri, SOSA.madeBySensor, station_iri))

        param_name = _str(row.get("observedPropertyDeterminandLabel", ""))
        if param_name:
            g.add((iri, SOSA.observedProperty, Literal(param_name, datatype=XSD.string)))

        # WISE6 disaggregated has per-sample values; older aggregated had resultMeanValue
        value = _float(row.get("resultObservedValue", row.get("resultMeanValue")))
        if value is not None:
            g.add((iri, SOSA.hasSimpleResult, Literal(value, datatype=XSD.decimal)))

        unit = _str(row.get("resultUom", ""))
        if unit:
            g.add((iri, WC.unit, Literal(unit, datatype=XSD.string)))

        g.add((iri, WC.reportingYear, Literal(int(year), datatype=XSD.integer)))


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _str(val: object) -> str:
    return "" if pd.isna(val) else str(val).strip()  # type: ignore[arg-type]


def _float(val: object) -> float | None:
    try:
        f = float(val)  # type: ignore[arg-type]
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None
