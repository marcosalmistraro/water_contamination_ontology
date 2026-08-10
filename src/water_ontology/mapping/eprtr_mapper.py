"""Maps validated Pydantic models to OWL individuals in the rdflib graph."""

from __future__ import annotations

from rdflib import Graph, Literal, RDF, XSD
from rdflib.namespace import Namespace

from water_ontology.models import EmissionEvent, IndustrialFacility, Pollutant

WC = Namespace("https://w3id.org/water-contamination/")
WCD = Namespace("https://w3id.org/water-contamination/data/")
GEO = Namespace("http://www.w3.org/2003/01/geo/wgs84_pos#")
SCHEMA = Namespace("https://schema.org/")


def _safe_iri(fragment: str) -> str:
    """Percent-encode characters that break IRI syntax."""
    return fragment.replace(" ", "_").replace("/", "-").replace(":", "_")


class EprtrMapper:
    """Converts E-PRTR domain objects to RDF triples and adds them to the graph."""

    def __init__(self, graph: Graph) -> None:
        self.graph = graph

    # ------------------------------------------------------------------
    # Public methods — one per ontology class
    # ------------------------------------------------------------------

    def add_facility(self, fac: IndustrialFacility) -> None:
        """Assert IndustrialFacility individual with datatype properties."""
        iri = WCD[f"facility/{_safe_iri(fac.facility_id)}"]
        g = self.graph

        g.add((iri, RDF.type, WC.IndustrialFacility))
        g.add((iri, WC.facilityId, Literal(fac.facility_id, datatype=XSD.string)))
        g.add((iri, WC.facilityName, Literal(fac.name, datatype=XSD.string)))
        g.add((iri, WC.countryCode, Literal(fac.country_code, datatype=XSD.string)))

        if fac.nuts_region:
            g.add((iri, WC.nutsRegion, Literal(fac.nuts_region, datatype=XSD.string)))
        if fac.nace_code:
            g.add((iri, WC.naceCode, Literal(fac.nace_code, datatype=XSD.string)))
        if fac.competent_authority:
            g.add((iri, WC.competentAuthority, Literal(fac.competent_authority, datatype=XSD.string)))
        if fac.street_address:
            g.add((iri, SCHEMA.streetAddress, Literal(fac.street_address, datatype=XSD.string)))
        if fac.city:
            g.add((iri, SCHEMA.addressLocality, Literal(fac.city, datatype=XSD.string)))
        if fac.postcode:
            g.add((iri, SCHEMA.postalCode, Literal(fac.postcode, datatype=XSD.string)))
        if fac.lat is not None:
            g.add((iri, GEO.lat, Literal(fac.lat, datatype=XSD.decimal)))
        if fac.lon is not None:
            g.add((iri, GEO.long, Literal(fac.lon, datatype=XSD.decimal)))

    def add_pollutant(self, pol: Pollutant) -> None:
        """Assert Pollutant individual."""
        iri = WCD[f"pollutant/{_safe_iri(pol.pollutant_id)}"]
        g = self.graph

        g.add((iri, RDF.type, WC.Pollutant))
        g.add((iri, WC.pollutantName, Literal(pol.name, datatype=XSD.string)))
        g.add((iri, WC.medium, Literal(pol.medium, datatype=XSD.string)))
        if pol.cas_number:
            g.add((iri, WC.casNumber, Literal(pol.cas_number, datatype=XSD.string)))

    def add_emission_event(self, event: EmissionEvent) -> None:
        """Assert EmissionEvent individual linked to facility and pollutant."""
        iri = WCD[f"emission/{_safe_iri(event.event_id)}"]
        facility_iri = WCD[f"facility/{_safe_iri(event.facility_id)}"]
        pollutant_iri = WCD[f"pollutant/{_safe_iri(event.pollutant_id)}"]
        g = self.graph

        g.add((iri, RDF.type, WC.EmissionEvent))
        g.add((iri, WC.reportingYear, Literal(event.reporting_year, datatype=XSD.integer)))
        g.add((iri, WC.medium, Literal(event.medium, datatype=XSD.string)))
        g.add((iri, WC.dataSource, Literal(event.data_source, datatype=XSD.string)))
        g.add((iri, WC.accidental, Literal(event.accidental, datatype=XSD.boolean)))

        if event.quantity_kg is not None:
            g.add((iri, WC.quantityKg, Literal(event.quantity_kg, datatype=XSD.decimal)))

        # Object property links
        g.add((facility_iri, WC.hasEmissionEvent, iri))
        g.add((iri, WC.involvesPollutant, pollutant_iri))
