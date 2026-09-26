#ifndef ETP_PROOF_PACK_HPP
#define ETP_PROOF_PACK_HPP

#include "etp/merkle.hpp"
#include "etp/ecdsa.hpp"
#include "etp/timestamp.hpp"
#include <string>
#include <string_view>
#include <vector>
#include <cstdint>

namespace etp {

struct ProofPack {
    std::string leaf_hash;               // Leaf/block hash (64 hex characters)
    std::string mpan;                    // Smart meter MPAN
    double reading_kwh{0.0};             // Meter reading kWh
    std::string timestamp;               // ISO timestamp
    std::string prev_hash;               // Chain previous hash
    uint64_t nonce{0};                   // Monotonic nonce
    std::string crypto_suite_id;         // Crypto suite ID (default "ECDSA-P256-SHA256-v1")
    std::string key_id;                  // Key ID
    std::string signature;               // ECDSA signature hex
    std::string public_key_pem;          // Meter public key PEM
    
    std::vector<MerkleProofStep> proof;  // Merkle proof path to root
    std::string merkle_root;             // Expected Merkle tree root hex
    
    uint64_t first_nonce{0};             // Day first nonce
    uint64_t last_nonce{0};              // Day last nonce
    size_t leaf_count{0};                // Day leaf count
    int prev_day_last_nonce{-1};         // Boundary previous day last nonce (-1 if none)
    size_t eod_gap{0};                   // End of day gap count
    std::string anchor_digest;           // Metadata commitment digest
    
    std::string timestamp_token;         // RFC 3161 timestamp token string
};

struct ProofPackResult {
    bool valid{false};
    std::string overall_status;          // VERIFIED | SIGNATURE_FAILED | MERKLE_FAILED | ANCHOR_FAILED | TIMESTAMP_FAILED | TAMPER_REJECTED
    bool ecdsa_verified{false};
    bool merkle_verified{false};
    bool anchor_digest_verified{false};
    bool timestamp_verified{false};
    std::vector<std::string> checks_passed;
    std::vector<std::string> errors;
};

// Computes the metadata commitment digest: SHA256(merkle_root|first_nonce|last_nonce|leaf_count|prev_day_last_nonce|eod_gap)
std::string compute_anchor_digest(
    std::string_view merkle_root,
    uint64_t first_nonce,
    uint64_t last_nonce,
    size_t leaf_count,
    int prev_day_last_nonce,
    size_t eod_gap
);

// Unified single-entry verification function covering Merkle proof, signature, metadata anchor and timestamp together
ProofPackResult verify_proof_pack(const ProofPack& pack);

// Parse JSON string into ProofPack
ProofPack parse_proof_pack_json(std::string_view json_str);

// Serialize ProofPackResult to JSON
std::string proof_pack_result_to_json(const ProofPackResult& res);

} // namespace etp

#endif // ETP_PROOF_PACK_HPP
