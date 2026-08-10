"""YAML-based configuration loader with Pydantic validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, field_validator


class SourceConfig(BaseModel):
    name: str
    url: str
    format: str
    local_file: str | None = None
    local_zip: str | None = None
    extract_to: str | None = None
    releases_file: str | None = None
    facilities_file: str | None = None
    encoding: str = "utf-8"
    chunksize: int = 100_000
    sheet_name: int | str = 0


class SourcesConfig(BaseModel):
    sources: dict[str, SourceConfig]


class NamespacesConfig(BaseModel):
    base_iri: str
    namespaces: dict[str, str]
    ontology_file: str
    shacl_file: str


def load_sources(path: Path | str = "config/sources.yaml") -> SourcesConfig:
    """Load and validate data-source configuration."""
    raw: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return SourcesConfig(**raw)


def load_ontology_config(path: Path | str = "config/ontology.yaml") -> NamespacesConfig:
    """Load and validate ontology/namespace configuration."""
    raw: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return NamespacesConfig(**raw)
