"""Abstract base class for all data-source ingesters."""

from __future__ import annotations

import abc
import hashlib
import logging
import time
from pathlib import Path

import requests
from rdflib import Graph
from tqdm import tqdm

logger = logging.getLogger(__name__)


class BaseIngester(abc.ABC):
    """Download, parse, and populate the knowledge graph for one data source."""

    source_name: str = "base"

    def __init__(self, graph: Graph, raw_dir: Path = Path("data/raw")) -> None:
        self.graph = graph
        self.raw_dir = raw_dir
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> dict[str, int]:
        """Full pipeline: download → parse → map → return counts."""
        start = time.perf_counter()
        logger.info("[%s] Starting ingestion", self.source_name)

        self.download()
        counts = self.ingest()

        elapsed = time.perf_counter() - start
        logger.info("[%s] Done in %.1fs — triples added: %s", self.source_name, elapsed, counts)
        return counts

    # ------------------------------------------------------------------
    # Subclass interface
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def download(self) -> None:
        """Fetch raw data to disk; skip if already present and valid."""

    @abc.abstractmethod
    def ingest(self) -> dict[str, int]:
        """Parse raw data, map to ontology, populate self.graph. Return counts."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _download_file(
        self,
        url: str,
        dest: Path,
        chunk_size: int = 1 << 20,  # 1 MiB
        force: bool = False,
    ) -> None:
        """Stream-download url → dest with progress bar. Skip if dest exists."""
        if dest.exists() and not force:
            logger.info("[%s] Already downloaded: %s", self.source_name, dest.name)
            return

        logger.info("[%s] Downloading %s", self.source_name, url)
        response = requests.get(url, stream=True, timeout=120)
        response.raise_for_status()

        total = int(response.headers.get("content-length", 0))
        dest.parent.mkdir(parents=True, exist_ok=True)

        with (
            dest.open("wb") as fh,
            tqdm(total=total, unit="B", unit_scale=True, desc=dest.name) as bar,
        ):
            for chunk in response.iter_content(chunk_size=chunk_size):
                fh.write(chunk)
                bar.update(len(chunk))

    def _file_sha256(self, path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()
