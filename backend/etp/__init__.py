"""EnergyTrust Protocol (ETP) Core Package.

Patented security and data provenance engine for smart meter telemetry ingestion
and Apache Iceberg lakehouses.
"""

from .route_mutator import RouteMutator
from .meter import SmartMeterSimulator, TelemetryBlock, compute_canonical_hash
from .gateway import ETPGateway, MemoryNonceStore
from .phantom_grid import PhantomGridHoneypot
from .writer import MicroBatchWriter
from .checkpointer import MerkleCheckpointer, canonical_merkle_root
from .verifier import ETPVerifier, VerificationReport, VerificationAwareQueryObject
from .security import ETPSecurityManager
from .cim_exporter import CIMProfileExporter

__all__ = [
    "RouteMutator",
    "SmartMeterSimulator",
    "TelemetryBlock",
    "compute_canonical_hash",
    "ETPGateway",
    "MemoryNonceStore",
    "PhantomGridHoneypot",
    "MicroBatchWriter",
    "MerkleCheckpointer",
    "canonical_merkle_root",
    "ETPVerifier",
    "VerificationReport",
    "VerificationAwareQueryObject",
    "ETPSecurityManager",
    "CIMProfileExporter",
]
