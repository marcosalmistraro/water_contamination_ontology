"""Pydantic domain models that mirror the core ontology classes."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class IndustrialFacility(BaseModel):
    facility_id: str
    name: str
    country_code: str
    nuts_region: str | None = None
    lat: float | None = None
    lon: float | None = None
    nace_code: str | None = None
    competent_authority: str | None = None
    street_address: str | None = None
    city: str | None = None
    postcode: str | None = None


class Pollutant(BaseModel):
    pollutant_id: str      # e.g. "CAS:7440-38-2" or E-PRTR pollutant code
    name: str
    cas_number: str | None = None
    medium: str = Field(pattern="^(air|water|land)$")


class EmissionEvent(BaseModel):
    event_id: str
    facility_id: str
    pollutant_id: str
    reporting_year: int
    quantity_kg: float | None = None
    medium: str = Field(pattern="^(air|water|land)$")
    accidental: bool = False
    data_source: str = "E-PRTR"

    @field_validator("reporting_year")
    @classmethod
    def valid_year(cls, v: int) -> int:
        if not (1990 <= v <= 2100):
            raise ValueError(f"Implausible reporting year: {v}")
        return v


class WaterBody(BaseModel):
    water_body_id: str
    name: str | None = None
    water_body_type: str | None = None   # river, lake, coastal, transitional
    country_code: str | None = None
    rbd_code: str | None = None          # River Basin District code


class MonitoringStation(BaseModel):
    station_id: str
    name: str | None = None
    lat: float | None = None
    lon: float | None = None
    water_body_id: str | None = None
    country_code: str | None = None


class ComplianceThreshold(BaseModel):
    threshold_id: str
    pollutant_id: str
    medium: str
    value_kg_per_year: float
    regulation: str    # e.g. "E-PRTR Regulation (EC) No 166/2006"
