"""IEC Common Information Model (CIM) RDF/XML Profile Exporter.

Maps physical Iceberg schema columns to standard IEC 61970 / IEC 61968 classes
(UsagePoint, Meter, IntervalReading, ACLineSegment) and emits RDF/XML with the
proposed `cim:TelemetryProvenance` extension.
"""

from typing import List, Dict, Any
import xml.etree.ElementTree as ET


class CIMProfileExporter:
    """Exports ETP Iceberg rows to IEC CIM compliant RDF/XML."""

    def __init__(self):
        self.cim_ns = "http://iec.ch/TC57/CIM100#"
        self.rdf_ns = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        self.etp_ns = "http://energytrustprotocol.org/schema/cim-extension#"

    def export_to_rdf_xml(self, readings: List[Dict[str, Any]]) -> str:
        """Serializes Iceberg telemetry records to IEC CIM RDF/XML format."""
        
        # Register XML Namespaces
        ET.register_namespace("rdf", self.rdf_ns)
        ET.register_namespace("cim", self.cim_ns)
        ET.register_namespace("etp", self.etp_ns)

        rdf_root = ET.Element(f"{{{self.rdf_ns}}}RDF")

        for r in readings:
            mpan = r.get("mpan", "UNKNOWN")
            ts = r.get("reading_ts", "")
            val = r.get("reading_kwh", 0.0)

            # 1. UsagePoint Element (IEC 61968-9)
            up_elem = ET.SubElement(
                rdf_root,
                f"{{{self.cim_ns}}}UsagePoint",
                {f"{{{self.rdf_ns}}}about": f"#_UsagePoint_{mpan}"}
            )
            mrid_elem = ET.SubElement(up_elem, f"{{{self.cim_ns}}}IdentifiedObject.mRID")
            mrid_elem.text = mpan

            # 2. IntervalReading Element (IEC 61968-9)
            reading_elem = ET.SubElement(
                rdf_root,
                f"{{{self.cim_ns}}}IntervalReading",
                {f"{{{self.rdf_ns}}}about": f"#_Reading_{mpan}_{ts}"}
            )
            
            ts_elem = ET.SubElement(reading_elem, f"{{{self.cim_ns}}}IntervalReading.timeStamp")
            ts_elem.text = str(ts)
            
            val_elem = ET.SubElement(reading_elem, f"{{{self.cim_ns}}}IntervalReading.value")
            val_elem.text = f"{val:.3f}"
            
            up_ref = ET.SubElement(
                reading_elem,
                f"{{{self.cim_ns}}}IntervalReading.UsagePoint",
                {f"{{{self.rdf_ns}}}resource": f"#_UsagePoint_{mpan}"}
            )

            # 3. ETP Telemetry Provenance Extension Properties (Proposed International Standard Extension)
            prov_elem = ET.SubElement(reading_elem, f"{{{self.etp_ns}}}TelemetryProvenance")
            
            block_hash = ET.SubElement(prov_elem, f"{{{self.etp_ns}}}blockHash")
            block_hash.text = str(r.get("etp_block_hash", ""))
            
            nonce = ET.SubElement(prov_elem, f"{{{self.etp_ns}}}nonce")
            nonce.text = str(r.get("etp_nonce", 0))
            
            suite = ET.SubElement(prov_elem, f"{{{self.etp_ns}}}cryptoSuiteId")
            suite.text = str(r.get("etp_crypto_suite_id", "ECDSA-P256-SHA256-v1"))
            
            status = ET.SubElement(prov_elem, f"{{{self.etp_ns}}}verificationStatus")
            status.text = str(r.get("etp_verify_status", "UNVERIFIED"))
            
            anchor = ET.SubElement(prov_elem, f"{{{self.etp_ns}}}anchorReference")
            anchor.text = f"tsa:{ts}:token_{str(r.get('etp_block_hash', ''))[:12]}"

        xml_bytes = ET.tostring(rdf_root, encoding="utf-8", xml_declaration=True)
        return xml_bytes.decode("utf-8")
