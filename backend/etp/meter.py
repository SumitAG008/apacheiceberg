"""Block 1 — Smart Meter Simulator & Firmware Cryptography Engine.

Owns monotonic nonces, hardware key pair, canonical block hashing, and ECDSA signing.
"""

import hashlib
import datetime
from dataclasses import dataclass, asdict
from typing import Dict, Any, Tuple
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption


UNIT_SEPARATOR = b"\x1f"  # ASCII 0x1F unit separator for byte canonicalization


@dataclass(frozen=True)
class TelemetryBlock:
    """Canonical telemetry block schema."""
    mpan: str
    reading_kwh: float
    timestamp: str
    prev_hash: str
    nonce: int
    crypto_suite_id: str
    key_id: str
    block_hash: str
    signature: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SmartMeterSimulator:
    """Simulates a physical smart meter edge device with a hardware Secure Element."""

    def __init__(self, mpan: str, key_id: str = "k-7f31a2", initial_nonce: int = 184290):
        self.mpan = mpan
        self.key_id = key_id
        self.nonce = initial_nonce
        self.prev_hash = "0000000000000000000000000000000000000000000000000000000000000000"
        self.crypto_suite_id = "ECDSA-P256-SHA256-v1"

        # Generate hardware ECDSA P-256 keypair inside Secure Element
        self._private_key = ec.generate_private_key(ec.SECP256R1())
        self.public_key = self._private_key.public_key()

    def export_public_key_pem(self) -> str:
        """Exports the public key in PEM format for gateway registry."""
        pem_bytes = self.public_key.public_bytes(
            encoding=Encoding.PEM,
            format=PublicFormat.SubjectPublicKeyInfo
        )
        return pem_bytes.decode('utf-8')

    def compute_canonical_hash(
        self,
        mpan: str,
        reading_kwh: float,
        timestamp: str,
        prev_hash: str,
        nonce: int,
        crypto_suite_id: str,
        key_id: str
    ) -> str:
        """Calculates canonical SHA-256 block hash using ASCII 0x1F unit separators.
        
        PayloadBytes = mpan || 0x1F || reading_kwh (3dp) || 0x1F || timestamp || 0x1F ||
                       prev_hash || 0x1F || nonce || 0x1F || crypto_suite_id || 0x1F || key_id
        """
        formatted_kwh = f"{reading_kwh:.3f}"
        
        parts = [
            mpan.encode('utf-8'),
            formatted_kwh.encode('utf-8'),
            timestamp.encode('utf-8'),
            prev_hash.encode('utf-8'),
            str(nonce).encode('utf-8'),
            crypto_suite_id.encode('utf-8'),
            key_id.encode('utf-8')
        ]
        
        payload_bytes = UNIT_SEPARATOR.join(parts)
        return hashlib.sha256(payload_bytes).hexdigest()

    def generate_block(self, reading_kwh: float, timestamp_iso: str = None) -> TelemetryBlock:
        """Increments monotonic nonce, computes canonical hash, and signs in Secure Element."""
        # 1. Increment monotonic nonce exactly once per block
        self.nonce += 1
        
        if timestamp_iso is None:
            now = datetime.datetime.now(datetime.timezone.utc)
            timestamp_iso = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        # 2. Compute canonical SHA-256 block hash
        block_hash = self.compute_canonical_hash(
            mpan=self.mpan,
            reading_kwh=reading_kwh,
            timestamp=timestamp_iso,
            prev_hash=self.prev_hash,
            nonce=self.nonce,
            crypto_suite_id=self.crypto_suite_id,
            key_id=self.key_id
        )

        # 3. Sign canonical block hash inside Secure Element using ECDSA P-256
        hash_bytes = bytes.fromhex(block_hash)
        signature_bytes = self._private_key.sign(
            hash_bytes,
            ec.ECDSA(hashes.SHA256())
        )
        signature_hex = signature_bytes.hex()

        # 4. Construct block
        block = TelemetryBlock(
            mpan=self.mpan,
            reading_kwh=reading_kwh,
            timestamp=timestamp_iso,
            prev_hash=self.prev_hash,
            nonce=self.nonce,
            crypto_suite_id=self.crypto_suite_id,
            key_id=self.key_id,
            block_hash=block_hash,
            signature=signature_hex
        )

        # Update local previous hash chain
        self.prev_hash = block_hash
        return block
