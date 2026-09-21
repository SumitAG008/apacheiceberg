# Energy Traceability Protocol (ETP) — Defect & Resolution Log

This document records all defects, security regressions, and build failures identified and resolved during the ETP Native C++ Engine migration and CI/CD pipeline stabilization.

---

## Logged Defects Summary

| ID | Category | Component | Root Cause | Impact | Status |
|---|---|---|---|---|---|
| **DEF-001** | Build | `cpp/src/` | OpenSSL `EVP_Q_mac` API misuse | Compilation failure on Linux OpenSSL 3.0 toolchain | **RESOLVED** |
| **DEF-002** | Build | `cpp/src/gateway.cpp` | Missing `#include <array>` header | Incomplete type error for `std::array<uint8_t, 32>` | **RESOLVED** |
| **DEF-003** | API | `cpp/tests/test_etp_core.cpp` | Called nonexistent `EVP_PKEY_CTX_set_ec_paramgen_curve_name` | OpenSSL compilation error (needed `..._curve_nid`) | **RESOLVED** |
| **DEF-004** | Vulnerability | `cpp/src/merkle.cpp` | Duplication of odd nodes during tree construction | Re-introduced CVE-2012-2459 duplicate leaf vulnerability | **RESOLVED** |
| **DEF-005** | Flakiness | `cpp/tests/test_etp_core.cpp` | Missing `sig_bytes.resize(sig_len)` after `EVP_DigestSignFinal` | DER signature length mismatch (70-72 bytes) caused 75% test failure rate | **RESOLVED** |
| **DEF-006** | Parity | `cpp/src/merkle.cpp` | `compute_root()` on 0 leaves returned `64 * '0'` instead of `""` | Divergence from Python reference implementation on empty leaf set | **RESOLVED** |
| **DEF-007** | Security | `backend/rbac_utils.py` | Broad `except Exception: return []` in policy fetchers | Fail-open regression: DB errors silently disabled row-level security | **RESOLVED** |
| **DEF-008** | Race Condition | `backend/etp/nonce_store.py` | Read-compute-write window in `RedisNonceStore` | Non-atomic check/commit enabled concurrent replay attacks across pods | **RESOLVED** |
| **DEF-009** | Security | `backend/etp/nonce_store.py` | Fail-open fallback to `MemoryNonceStore` during Redis outage | Disconnected Redis degraded multi-replica cluster to isolated in-memory stores | **RESOLVED** |

---

## Defect Details & Root Cause Analysis

### DEF-001: OpenSSL `EVP_Q_mac` API Misuse
- **Symptom**: CMake target `etp_core_cpp` failed to compile under OpenSSL 3.0 toolchain.
- **Root Cause**: `EVP_Q_mac` parameter format was incorrect for SHA-256 HMAC calculation.
- **Resolution**: Refactored HMAC calculation to `EVP_MAC` / `EVP_MAC_CTX` OpenSSL 3.0 standard API.

### DEF-002: Missing `<array>` Header Inclusion
- **Symptom**: `cpp/src/gateway.cpp:208: error: variable 'std::array<unsigned char, 32> hash' has initializer but incomplete type`.
- **Root Cause**: Forward declaration of `std::array` was pulled in by transitive headers, but full definition was missing.
- **Resolution**: Explicitly added `#include <array>` to `cpp/src/gateway.cpp`.

### DEF-003: Incorrect OpenSSL EC Parameter Function Name
- **Symptom**: `test_etp_core.cpp:30: error: 'EVP_PKEY_CTX_set_ec_paramgen_curve_name' was not declared in this scope`.
- **Root Cause**: OpenSSL API function name takes NID (`EVP_PKEY_CTX_set_ec_paramgen_curve_nid`).
- **Resolution**: Renamed function call to `EVP_PKEY_CTX_set_ec_paramgen_curve_nid(pctx, NID_X9_62_prime256v1)`.

### DEF-004: Odd-Node Duplication (CVE-2012-2459 Vulnerability)
- **Symptom**: Merkle tree calculation duplicated odd nodes when building parent levels.
- **Root Cause**: Standard naive Merkle trees duplicate the final node in odd-count levels, enabling malicious actors to inject duplicate transaction leaves with identical roots (CVE-2012-2459).
- **Resolution**: Updated `cpp/src/merkle.cpp` to promote odd nodes directly without duplication (`next_level.push_back(current_level[i])`).

### DEF-005: Flaky Signature Verification Buffer (~25% Pass Rate)
- **Symptom**: `Execute C++ Native Core Verification Suite` passed in run #1 but failed in run #2 without code changes.
- **Root Cause**: `EVP_DigestSignFinal(ctx.get(), nullptr, &sig_len)` sets `sig_len` to maximum size (72 bytes). ECDSA P-256 DER signatures vary between 70 and 72 bytes depending on integer padding of $r$ and $s$. Vector was allocated with size 72 but never resized to actual signature length, causing trailing zeroes to be hex-encoded.
- **Resolution**: Added `sig_bytes.resize(sig_len)` after `EVP_DigestSignFinal` in `cpp/tests/test_etp_core.cpp`.

### DEF-006: Empty-Tree Merkle Root Differential Divergence
- **Symptom**: `test_cpp_bindings.py` failed with `Merkle root mismatch for 0 leaves: cpp = '0000...0000', py = ''`.
- **Root Cause**: C++ `MerkleTree::compute_root()` returned `std::string(64, '0')` when `leaves_.empty()`, whereas Python reference returned `""`.
- **Resolution**: Updated `cpp/src/merkle.cpp` to `return std::string()` when `leaves_.empty()`.

### DEF-007: Fail-Open RBAC Policy Swallowing Exception
- **Symptom**: `backend/rbac_utils.py` returned `[]` on any exception in `get_role_policies` and `get_row_filters`.
- **Root Cause**: Swallowing DB errors caused missing tables or dropped DB connections to silently strip all restrictions, elevating users to unrestricted view.
- **Resolution**: Updated `rbac_utils.py` to catch `psycopg2.errors.UndefinedTable` explicitly and raise `RuntimeError` (refusing to serve data) when `ENVIRONMENT` is outside `("development", "dev", "local", "test")`.

### DEF-008: Non-Atomic Redis Nonce Store Read-Compute-Write Race
- **Symptom**: `RedisNonceStore` called plain `hgetall` followed by `hset` without transaction or Lua evaluation.
- **Root Cause**: Un-serialised read-compute-write window allowed concurrent requests hitting different pods for the same MPAN to read identical nonces and pass replay verification.
- **Resolution**: Converted `check_only` and `commit` in `backend/etp/nonce_store.py` to execute server-side atomic Redis Lua scripts (`LUA_CHECK_ONLY` and `LUA_COMMIT`).

### DEF-009: Fail-Open Fallback in Non-Development Environments
- **Symptom**: `RedisNonceStore` silently degraded to `MemoryNonceStore` whenever Redis connection failed.
- **Root Cause**: In multi-replica production environments (`replicas: 2` to `10`), falling back to process-local memory stores breaks distributed replay protection.
- **Resolution**: Restricted `MemoryNonceStore` fallback to `ENVIRONMENT` in `("development", "dev", "local", "test")`. In production/staging, connection or command failures raise `RuntimeError`, failing closed and halting un-protected ingestion.
