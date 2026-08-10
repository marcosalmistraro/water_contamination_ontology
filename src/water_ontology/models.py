"""Pydantic domain models that mirror the core ontology classes."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class IndustrialFacility(BaseModel):
    facility_id: str
    name: str
    country_code: str
    nuts_region: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    nace_code: Optional[str] = None
    competent_authority: Optional[str] = None
    street_address: Optional[str] = None
    city: Optional[str] = None
    postcode: Optional[str] = None


class Pollutant(BaseModel):
    pollutant_id: str      # e.g. "CAS:7440-38-2" or E-PRTR pollutant code
    name: str
    cas_number: Optional[str] = None
    medium: str = Field(pattern="^(air|water|land)$")


class EmissionEvent(BaseModel):
    event_id: str
    facility_id: str
    pollutant_id: str
    reporting_year: int
    quantity_kg: Optional[float] = None
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
    name: Optional[str] = None
    water_body_type: Optional[str] = None   # river, lake, coastal, transitional
    country_code: Optional[str] = None
    rbd_code: Optional[str] = None          # River Basin District code


class MonitoringStation(BaseModel):
    station_id: str
    name: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    water_body_id: Optional[str] = None
    country_code: Optional[str] = None


class ComplianceThreshold(BaseModel):
    threshold_id: str
    pollutant_id: str
    medium: str
    value_kg_per_year: float
    regulation: str    # e.g. "E-PRTR Regulation (EC) No 166/2006"
