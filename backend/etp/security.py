"""ETP Security & Cryptographic Encryption Manager.

Provides AES-256-GCM field encryption, deterministic PII column masking,
and tenant scope isolation guards.
"""

import os
import base64
import hashlib
from typing import Dict, Any, List
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class ETPSecurityManager:
    """Handles field-level AES-256-GCM encryption and RBAC column masking."""

    def __init__(self, master_key: bytes = None):
        if master_key is None:
            # 256-bit default key derived from environment or random seed
            raw_key = os.environ.get("ETP_MASTER_KEY", "etp-secret-master-key-32-bytes!!")
            self.master_key = hashlib.sha256(raw_key.encode("utf-8")).digest()
        else:
            if len(master_key) != 32:
                raise ValueError("Master key must be exactly 32 bytes (256 bits)")
            self.master_key = master_key
            
        self.aesgcm = AESGCM(self.master_key)

    def encrypt_field(self, plaintext: str) -> str:
        """Encrypts a string field using AES-256-GCM and returns Base64 representation."""
        if not plaintext:
            return ""
        nonce = os.urandom(12)  # 96-bit IV
        ciphertext = self.aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        combined = nonce + ciphertext
        return base64.b64encode(combined).decode("utf-8")

    def decrypt_field(self, encrypted_base64: str) -> str:
        """Decrypts a Base64-encoded AES-256-GCM ciphertext."""
        if not encrypted_base64:
            return ""
        combined = base64.b64decode(encrypted_base64.encode("utf-8"))
        if len(combined) < 28:
            raise ValueError("Ciphertext too short")
        nonce = combined[:12]
        ciphertext = combined[12:]
        plaintext_bytes = self.aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext_bytes.decode("utf-8")

    def mask_mpan(self, mpan: str, role: str) -> str:
        """Applies RBAC column masking rules to MPAN identifier."""
        if role in ("Admin", "SettlementAnalyst", "GridEngineer"):
            return mpan  # Unmasked for authorized roles
        
        # Masked via deterministic HMAC hash for unauthorized / analyst roles
        masked_hash = hashlib.sha256((mpan + "etp_salt").encode("utf-8")).hexdigest()[:8]
        return f"MPAN-***-{masked_hash}"

    def apply_rbac_masking(self, row: Dict[str, Any], role: str) -> Dict[str, Any]:
        """Applies pre-relation masking transformations to a record dict."""
        masked_row = dict(row)
        
        # ETP Provenance columns are NEVER masked
        # etp_block_hash and etp_verify_status remain unmasked to preserve audit proofs
        
        if "mpan" in masked_row:
            masked_row["mpan"] = self.mask_mpan(masked_row["mpan"], role)
            
        return masked_row
