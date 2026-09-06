# LLD-001 — EnergyTrust Protocol: Low-Level Design & Code Contracts

**Document ID:** LLD-001  
**Version:** 2.0  
**Issued:** 2026-09-06T17:38:00Z  
**Status:** Approved Specification · **Audience:** Implementers & Software Engineers  

---

## 1. Cryptographic Formulations & Mathematical Specifications

### 1.1 Moving Target Defense Ingress Route Scrambling
For secret key $K_{secret} \in \{0,1\}^{256}$, current epoch timestamp $t \in \mathbb{N}$ (seconds since Unix epoch), and window duration $T_{window} = 60 \text{ s}$:

$$\text{EpochWindow}(t) = \left\lfloor \frac{t}{T_{window}} \right\rfloor$$

$$\text{ScrambleHex}(W) = \text{HexEncode}\left( \text{HMAC-SHA256}\left(K_{secret}, \text{uint64\_be}(W)\right) \right)[0 \dots 12]$$

$$\text{ActiveRoute}(W) = \text{BaseURI} \mathbin{\Vert} \text{"/rotated\_"} \mathbin{\Vert} \text{ScrambleHex}(W)$$

To compensate for network jitter and edge clock drift, the gateway accepts the route set:
$$\mathcal{R}_{valid}(t) = \left\{ \text{ActiveRoute}(W-1), \text{ActiveRoute}(W), \text{ActiveRoute}(W+1) \right\}$$

### 1.2 Telemetry Block Canonicalization Protocol
To guarantee identical hash computation across Python, C, and Rust implementations, fields must be concatenated in fixed order using UTF-8 encoding separated by the ASCII Unit Separator byte $0x1F$:

$$\text{PayloadBytes} = \text{mpan} \mathbin{\Vert} 0x1F \mathbin{\Vert} \text{reading\_kwh} \mathbin{\Vert} 0x1F \mathbin{\Vert} \text{timestamp} \mathbin{\Vert} 0x1F \mathbin{\Vert} \text{prev\_hash} \mathbin{\Vert} 0x1F \mathbin{\Vert} \text{nonce} \mathbin{\Vert} 0x1F \mathbin{\Vert} \text{crypto\_suite\_id} \mathbin{\Vert} 0x1F \mathbin{\Vert} \text{key\_id}$$

$$H_{block} = \text{SHA256}(\text{PayloadBytes})$$

- `reading_kwh` MUST be formatted as a 3-decimal fixed point string (e.g., `"0.412"`).
- `timestamp` MUST follow ISO-8601 millisecond UTC format ending with `Z` (e.g., `"2026-09-06T17:38:00.000Z"`).
- `nonce` MUST be formatted as an unsigned 64-bit decimal string.

### 1.3 Merkle Tree Generation with Domain Separation
To prevent second-preimage attacks where interior nodes are presented as leaves, node hashes enforce domain separation prefixes:

$$\text{LeafHash}(H_{block}) = \text{SHA256}(0x00 \mathbin{\Vert} \text{HexDecode}(H_{block}))$$

$$\text{ParentHash}(L, R) = \text{SHA256}(0x01 \mathbin{\Vert} L \mathbin{\Vert} R)$$

**Odd Leaf Count Handling (CVE-2012-2459 Prevention):** If a level contains an odd number of nodes, the final node $N_{last}$ is promoted to the next level **without duplication**:
$$\text{Parent}(N_{last}) = N_{last}$$

---

## 2. Low-Level Component Contracts & Implementation Code

### 2.1 Block 2 — Ingress Route Mutator Contract

```python
import hmac
import hashlib
import struct
import math
from typing import Dict, Set

class RouteMutator:
    """Pure mathematical function implementing Moving Target Defense route scrambling.
    Zero internal state, zero network/disk I/O.
    """
    def __init__(self, secret_key: bytes, window_s: int = 60, base_uri: str = "/api/v1/telemetry"):
        if len(secret_key) < 32:
            raise ValueError("Secret key must be at least 32 bytes")
        self.secret_key = secret_key
        self.window_s = window_s
        self.base_uri = base_uri.rstrip('/')

    def _scramble_hex(self, window: int) -> str:
        # Encode window as 64-bit big-endian integer to prevent string boundary ambiguity
        msg = struct.pack(">Q", window)
        digest = hmac.new(self.secret_key, msg, hashlib.sha256).hexdigest()
        return digest[:12]

    def active_routes(self, now_epoch_s: int) -> Dict[str, str]:
        """Returns valid routes for windows W-1, W, W+1."""
        w = math.floor(now_epoch_s / self.window_s)
        return {
            "prev": f"{self.base_uri}/rotated_{self._scramble_hex(w - 1)}",
            "current": f"{self.base_uri}/rotated_{self._scramble_hex(w)}",
            "next": f"{self.base_uri}/rotated_{self._scramble_hex(w + 1)}"
        }

    def validate_route(self, requested_path: str, now_epoch_s: int) -> bool:
        """Constant-time route validation to prevent timing side-channel attacks."""
        valid_map = self.active_routes(now_epoch_s)
        for valid_route in valid_map.values():
            if hmac.compare_digest(requested_path.encode('utf-8'), valid_route.encode('utf-8')):
                return True
        return False
```

---

### 2.2 Block 3 — Gateway Nonce Storage Lua Script (Redis / Valkey)

To eliminate race conditions and achieve sub-millisecond DoS resistance, the gateway uses a Redis Lua script executing atomic Compare-And-Swap (CAS):

```lua
-- Keys: KEYS[1] = meter_id
-- ARGV: ARGV[1] = incoming_nonce, ARGV[2] = incoming_hash, ARGV[3] = updated_at_ts

local current_data = redis.call('HMGET', KEYS[1], 'last_nonce', 'last_hash')
local last_nonce = tonumber(current_data[1])

if last_nonce ~= nil then
    if tonumber(ARGV[1]) <= last_nonce then
        -- Replay attack detected
        return {0, last_nonce, "REPLAY_REJECTED"}
    end
end

-- Update atomic state
redis.call('HMSET', KEYS[1], 'last_nonce', ARGV[1], 'last_hash', ARGV[2], 'updated_at', ARGV[3])
return {1, ARGV[1], "ACCEPT"}
```

---

### 2.3 Block 3 — Gateway Ingestion Endpoint Contract

```python
from dataclasses import dataclass
from typing import Optional, Tuple
import datetime

@dataclass(frozen=True)
class TelemetryBlock:
    mpan: str
    reading_kwh: float
    timestamp: str
    prev_hash: str
    nonce: int
    crypto_suite_id: str
    key_id: str
    block_hash: str
    signature: str

class ETPGateway:
    def __init__(self, route_mutator: RouteMutator, nonce_store, public_key_registry):
        self.mutator = route_mutator
        self.nonce_store = nonce_store
        self.key_registry = public_key_registry

    def process_request(self, path: str, payload: dict, now_s: int) -> Tuple[int, dict]:
        # 1. Route Check (Constant Time)
        if not self.mutator.validate_route(path, now_s):
            # Divert to Phantom Grid honeypot without signaling error
            return 200, self.trigger_phantom_grid(path, payload)

        # 2. Schema Validation
        try:
            block = TelemetryBlock(**payload)
        except Exception:
            return 400, {"error": "Invalid schema"}

        # 3. Fast Atomic Nonce Check (Redis CAS)
        status, last_nonce, msg = self.nonce_store.atomic_cas(
            block.mpan, block.nonce, block.block_hash, block.timestamp
        )
        if status == 0:
            self.log_audit("telemetry.replay_rejected", block.mpan, block.nonce)
            return 401, {"error": "Replay rejected"}

        # 4. Hash & Signature Recomputation
        computed_hash = self.canonical_hash(block)
        if not hmac.compare_digest(computed_hash, block.block_hash):
            self.log_audit("telemetry.tamper_rejected", block.mpan, block.nonce)
            return 401, {"error": "Tamper detected"}

        if not self.verify_signature(block):
            self.log_audit("telemetry.signature_invalid", block.mpan, block.nonce)
            return 401, {"error": "Invalid signature"}

        # 5. Buffer for Micro-Batch Writer
        verify_status = "VERIFIED"
        if block.prev_hash != self.nonce_store.get_last_hash(block.mpan):
            verify_status = "CHAIN_GAP"

        self.buffer_writer(block, verify_status)
        return 200, {"status": "accepted", "verify_status": verify_status}
```

---

### 2.4 Block 6 — Merkle Tree Checkpointer Contract

```python
import hashlib
from typing import List

def canonical_merkle_root(leaf_hashes_hex: List[str]) -> str:
    """Builds a binary Merkle tree with domain separation.
    Leaves prefixed with 0x00; Interior nodes prefixed with 0x01.
    Prevents CVE-2012-2459 duplicate node vulnerability.
    """
    if not leaf_hashes_hex:
        return ""

    # Level 0: Leaf Nodes with 0x00 domain separation
    current_level = [
        hashlib.sha256(b"\x00" + bytes.fromhex(h)).digest()
        for h in leaf_hashes_hex
    ]

    # Tree Construction
    while len(current_level) > 1:
        next_level = []
        for i in range(0, len(current_level), 2):
            left = current_level[i]
            if i + 1 < len(current_level):
                right = current_level[i + 1]
                parent = hashlib.sha256(b"\x01" + left + right).digest()
            else:
                # Odd node promotion without duplication
                parent = left
            next_level.append(parent)
        current_level = next_level

    return current_level[0].hex()
```

---

## 3. Comprehensive Audit Event Schema

Every system component writes structured audit logs to an append-only, high-performance audit bus:

```json
{
  "audit_id": "evt_9a8f3b12-4c5d-6e7f-8a9b-0c1d2e3f4a5b",
  "timestamp": "2026-09-06T17:38:00.104Z",
  "action": "telemetry.replay_rejected",
  "actor": "gw-uk-01",
  "target_mpan": "MPAN-1200012345678",
  "source_ip": "198.51.100.42",
  "outcome": "DENY",
  "details": {
    "submitted_nonce": 184290,
    "last_accepted_nonce": 184291,
    "route_attempted": "/api/v1/telemetry/rotated_7f3a9b1c2d4e"
  }
}
```

---

## 4. Exhaustive Test & Edge-Case Matrix (T1 to T25)

| Test ID | Test Scenario | Input Conditions | Expected Outcome | Verification Point |
|---|---|---|---|---|
| **T1** | Valid telemetry ingest | Valid block, current route $W$ | HTTP 200 OK, `VERIFIED` | Block written to Iceberg |
| **T2** | Clock drift tolerance | Valid block, route window $W-1$ | HTTP 200 OK, `VERIFIED` | Drift accepted cleanly |
| **T3** | Expired route hit | Valid block, route window $W-2$ | HTTP 200 OK (Synthetic) | Diverted to Phantom Grid |
| **T4** | Replay attack | Submitted nonce $N \le N_{last}$ | HTTP 401 Unauthorized | Nonce CAS fails; zero ECDSA run |
| **T5** | Single-byte payload tamper | Modified `reading_kwh` | HTTP 401 Unauthorized | Hash mismatch detected |
| **T6** | Invalid signature | Payload signed with wrong key | HTTP 401 Unauthorized | Signature check fails |
| **T7** | Non-linking prev_hash | `prev_hash` does not match | HTTP 200 OK, `CHAIN_GAP` | Recorded for audit |
| **T8** | Recon scanner hit | `POST /api/v1/telemetry` | HTTP 200 OK (Synthetic) | IP flagged in Threat Registry |
| **T9** | Phantom Grid isolation | Attack vector inside honeypot | Zero network route to S3 | Penetration test pass |
| **T10**| Deterministic Merkle Root| Fixed set of 48 reading hashes | Identical Merkle root | Bit-for-bit test pass |
| **T11**| Iceberg row tampering | Edit 1 byte in Parquet file | Verifier outputs `FAILED` | Merkle proof check flags row |
| **T12**| 3M meter daily batch | 144M rows processed | All roots built & anchored | Batch completes $<30 \text{ min}$ |
| **T13**| Timing side-channel | Compare valid vs invalid route | Equal execution time | Stopwatch test variance $<10 \ \mu\text{s}$ |
| **T14**| Redis Nonce Store failover| Primary Redis node failure | Automatic Sentinel failover | Zero lost nonce checks |
| **T15**| Graph topology query | 400 anomaly meters input | Returns upstream substation | Cypher query execution success |
| **T16**| Public key revocation | Meter key marked revoked | HTTP 401 for subsequent blocks | Ingestion blocked instantly |
| **T17**| Dual PQC signature verify| `ECDSA-P256 + Dilithium3` | HTTP 200 OK | Both signatures valid |
| **T18**| Consultant RBAC deny | Query unassigned namespace | Permission Denied | `rbac.check` deny logged |
| **T19**| Nonce gap detection | Nonce sequence 101, 102, 105 | Output `gap_count = 2` | Completeness check pass |
| **T20**| Peak tariff dispute proof| Aggregate peak query executed | Certified Merkle proof generated| Audit bundle exported |
| **T21**| Cross-DNO isolation | DNO B queries DNO A view | Boundary rows visible only | Row filter enforced |
| **T22**| Firmware OTA hash audit | Firmware status block emitted | `VERIFIED` in Iceberg | Audit trail complete |
| **T23**| STIX/TAXII SIEM export | Phantom Grid honeypot probe | STIX 2.1 JSON generated | TAXII push successful |
| **T24**| High concurrency burst | 10,000 blocks/sec burst | Micro-batch writer flushes | Zero buffer overflow |
| **T25**| Odd leaf Merkle tree | 47 leaf hashes (odd count) | Odd leaf promoted without dup | No CVE-2012-2459 flaw |

---

## 5. Document Control

| Version | Date | Author | Summary of Changes |
|---|---|---|---|
| 1.0 | 2026-09-06T09:30:00Z | Lead Architect | Initial Baseline |
| 2.0 | 2026-09-06T17:38:00Z | Lead Architect | Added mathematical equations, Python code contracts, Redis Lua script, and expanded T1–T25 test matrix |
