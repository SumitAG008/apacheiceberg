# CPP-ARC-001 — EnergyTrust Protocol: Native C++20 Core Architecture Specification

**Document ID:** CPP-ARC-001  
**Version:** 1.0  
**Issued:** 2026-09-18  
**Status:** Approved Specification  
**Authority:** ETP Core Systems Engineering & Performance Architecture  
**Target Performance:** 35,000+ verifications/sec per core · Sub-25 μs Gateway Verification Latency · Zero Memory Leaks  

---

## 1. Architectural Motivation & System Boundary

The **EnergyTrust Protocol (ETP)** processes high-frequency telemetry across smart meter fleets (scaling to 52+ billion rows/year per 3-million-meter estate). To eliminate Python GIL bottlenecks, achieve deterministic microsecond response times, and guarantee zero memory leaks under DoS stress, ETP implements its hot-path cryptographic and ingestion core in **Modern C++20** (`libetp_core`).

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                            C++20 NATIVE SECURITY ENGINE (`etp-core`)                        │
│                                                                                             │
│   ┌───────────────────────────┐  ┌───────────────────────────┐  ┌───────────────────────┐   │
│   │ etp::RouteMutator         │  │ etp::GatewayEngine        │  │ etp::MerkleTree       │   │
│   │ • HMAC-SHA256 MTD Window  │  │ • Atomic Nonce Lock       │  │ • Domain Separated    │   │
│   │ • std::string_view        │  │ • OpenSSL 3.0 ECDSA-P256  │  │ • Ultra-fast SHA-256  │   │
│   └───────────────────────────┘  └───────────────────────────┘  └───────────────────────┘   │
│                                                │                                            │
│                                                ▼                                            │
│                                 ┌─────────────────────────────┐                             │
│                                 │ Arrow / Parquet Writer Core │                             │
│                                 │ (Apache Arrow C++ SDK)      │                             │
│                                 └─────────────────────────────┘                             │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
                                                 ▲
                                                 │ pybind11 Zero-Copy
┌────────────────────────────────────────────────┴────────────────────────────────────────────┐
│                        Python Management & Orchestration Layer                              │
│                        • FastAPI Endpoints & OIDC/SAML Auth                                 │
│                        • DuckDB Analytics & Data Studio Dashboard                           │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Modern C++20 Memory Safety & Zero-Leak Guarantees

To ensure complete memory safety and prevent memory leaks or security fuzz crashes:

1. **RAII Ownership (Resource Acquisition Is Initialization):**
   - No raw pointers (`T*`), `malloc`, `free`, `new`, or `delete`.
   - Dynamic allocations strictly managed by `std::unique_ptr` and `std::vector`.
   - String and buffer parameters passed via non-owning, zero-copy `std::string_view` and `std::span<const uint8_t>`.

2. **Automated Sanitizers in Build Pipeline:**
   - Debug & CI builds run with GCC/Clang sanitizers:
     - `-fsanitize=address` (AddressSanitizer: out-of-bounds & use-after-free check)
     - `-fsanitize=leak` (LeakSanitizer: hard failure on any memory leak)
     - `-fsanitize=undefined` (UBSan: unaligned accesses & integer overflow checks)

3. **Security Fuzzing with `libFuzzer`:**
   - `cpp/fuzz/fuzz_gateway.cpp` exposes an LLVM `libFuzzer` entry point to validate that corrupt or adversarial HTTP payloads are rejected without memory leaks or segmentation faults.

---

## 3. Native C++ Component Specifications

### 3.1 `etp::RouteMutator` — Moving Target Defense (MTD)
* **Header:** `cpp/include/etp/route_mutator.hpp`
* **Algorithm:** Computes rotating ingress route hashes using HMAC-SHA256 over 60-second time windows ($W = \lfloor t / 60 \rfloor$).
* **Implementation:** Employs OpenSSL 3.0 `EVP_MAC` primitives with zero heap allocation per invocation.

```cpp
namespace etp {

struct RouteWindow {
    std::string prev_route;
    std::string current_route;
    std::string next_route;
};

class RouteMutator {
public:
    explicit RouteMutator(std::string_view secret_key, uint64_t window_seconds = 60);
    
    [[nodiscard]] RouteWindow get_routes(uint64_t timestamp_sec) const;
    [[nodiscard]] bool validate_route(std::string_view route, uint64_t timestamp_sec) const;

private:
    std::string secret_key_;
    uint64_t window_seconds_;
};

} // namespace etp
```

---

### 3.2 `etp::GatewayEngine` — DoS-Resistant Ingestion Boundary
* **Header:** `cpp/include/etp/gateway.hpp`
* **Pipeline Sequence:**
  1. **Fast Route Match:** Checks request path against `RouteMutator::get_routes()`. If invalid, flags for Phantom Grid deception.
  2. **Atomic Monotonic Nonce Check:** Validates $N_{\text{meter}} > N_{\text{last}}$ using thread-safe std::atomic memory or Redis CAS.
  3. **Canonical Byte Hashing:** Recomputes $H_{\text{block}} = \text{SHA256}(\text{mpan} \,||\, \text{ts} \,||\, \text{kwh} \,||\, \text{nonce})$.
  4. **OpenSSL 3.0 ECDSA Signature Verification:** Validates signature using `EVP_PKEY_verify_digest`.

```cpp
namespace etp {

enum class VerificationStatus {
    VERIFIED,
    CHAIN_GAP,
    REPLAY_REJECTED,
    SIGNATURE_FAILED,
    INVALID_ROUTE
};

struct VerificationResult {
    VerificationStatus status;
    std::string block_hash;
    std::string error_message;
    bool divert_to_honeypot{false};
};

class GatewayEngine {
public:
    explicit GatewayEngine(std::string_view secret_key);

    VerificationResult verify_telemetry_block(
        std::string_view route,
        const TelemetryBlock& block,
        std::string_view public_key_pem
    );
};

} // namespace etp
```

---

### 3.3 `etp::MerkleTree` — Domain-Separated Cryptographic Checkpointer
* **Header:** `cpp/include/etp/merkle.hpp`
* **Domain Separation:** Prevents second-preimage attacks:
  - Leaf Hash: $\text{SHA256}(0x00 \,||\, \text{leaf\_data})$
  - Interior Hash: $\text{SHA256}(0x01 \,||\, \text{left\_hash} \,||\, \text{right\_hash})$

```cpp
namespace etp {

class MerkleTree {
public:
    MerkleTree() = default;
    
    void add_leaf(std::span<const uint8_t> leaf_data);
    [[nodiscard]] std::string compute_root();
    [[nodiscard]] std::vector<std::string> get_proof(size_t leaf_index) const;

private:
    std::vector<std::vector<uint8_t>> leaves_;
};

} // namespace etp
```

---

## 4. `pybind11` Zero-Copy Python Interface

The `cpp/src/pybind_bindings.cpp` file exports the native C++ library directly into Python as `etp_core_cpp`:

```cpp
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "etp/route_mutator.hpp"
#include "etp/gateway.hpp"
#include "etp/merkle.hpp"

namespace py = pybind11;

PYBIND11_MODULE(etp_core_cpp, m) {
    m.doc() = "EnergyTrust Protocol Native C++20 Core Security Engine";

    py::class_<etp::RouteWindow>(m, "RouteWindow")
        .def_readwrite("prev_route", &etp::RouteWindow::prev_route)
        .def_readwrite("current_route", &etp::RouteWindow::current_route)
        .def_readwrite("next_route", &etp::RouteWindow::next_route);

    py::class_<etp::RouteMutator>(m, "RouteMutator")
        .def(py::init<std::string_view, uint64_t>(), py::arg("secret_key"), py::arg("window_seconds") = 60)
        .def("get_routes", &etp::RouteMutator::get_routes)
        .def("validate_route", &etp::RouteMutator::validate_route);

    py::enum_<etp::VerificationStatus>(m, "VerificationStatus")
        .value("VERIFIED", etp::VerificationStatus::VERIFIED)
        .value("CHAIN_GAP", etp::VerificationStatus::CHAIN_GAP)
        .value("REPLAY_REJECTED", etp::VerificationStatus::REPLAY_REJECTED)
        .value("SIGNATURE_FAILED", etp::VerificationStatus::SIGNATURE_FAILED)
        .value("INVALID_ROUTE", etp::VerificationStatus::INVALID_ROUTE);

    py::class_<etp::VerificationResult>(m, "VerificationResult")
        .def_readwrite("status", &etp::VerificationResult::status)
        .def_readwrite("block_hash", &etp::VerificationResult::block_hash)
        .def_readwrite("error_message", &etp::VerificationResult::error_message)
        .def_readwrite("divert_to_honeypot", &etp::VerificationResult::divert_to_honeypot);

    py::class_<etp::GatewayEngine>(m, "GatewayEngine")
        .def(py::init<std::string_view>(), py::arg("secret_key"))
        .def("verify_telemetry_block", &etp::GatewayEngine::verify_telemetry_block);

    py::class_<etp::MerkleTree>(m, "MerkleTree")
        .def(py::init<>())
        .def("add_leaf", [](etp::MerkleTree& tree, py::bytes data) {
            std::string s = data;
            tree.add_leaf(std::span<const uint8_t>(reinterpret_cast<const uint8_t*>(s.data()), s.size()));
        })
        .def("compute_root", &etp::MerkleTree::compute_root)
        .def("get_proof", &etp::MerkleTree::get_proof);
}
```

---

## 5. CMake Build Configuration (`cpp/CMakeLists.txt`)

```cmake
cmake_minimum_required(VERSION 3.20)
project(etp_core VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# Find OpenSSL 3.0
find_package(OpenSSL 3.0 REQUIRED)

# Find pybind11
find_package(pybind11 REQUIRED)

# Include directories
include_directories(include ${OPENSSL_INCLUDE_DIR})

# Source files
set(SOURCES
    src/route_mutator.cpp
    src/gateway.cpp
    src/merkle.cpp
)

# Native shared library
add_library(etp_core SHARED ${SOURCES})
target_link_libraries(etp_core PRIVATE OpenSSL::Crypto OpenSSL::SSL)

# Sanitizers in Debug mode
if(CMAKE_BUILD_TYPE STREQUAL "Debug")
    target_compile_options(etp_core PRIVATE -fsanitize=address,leak,undefined -g)
    target_link_options(etp_core PRIVATE -fsanitize=address,leak,undefined)
endif()

# pybind11 module target
pybind11_add_module(etp_core_cpp src/pybind_bindings.cpp ${SOURCES})
target_link_libraries(etp_core_cpp PRIVATE OpenSSL::Crypto OpenSSL::SSL)
```

---

## 6. Document Control

| Version | Date | Author | Summary of Changes |
|---|---|---|---|
| 1.0 | 2026-09-18 | ETP Core Engineering | Initial C++20 Native Core Architecture Specification |
