#ifndef ETP_PROOF_PACK_HPP
#define ETP_PROOF_PACK_HPP

#include <string>
#include <vector>
#include <utility>
#include <cstdint>

namespace etp {

struct ProofPack {
    std::string mpan;
    double reading_kwh = 0.0;
    std::string timestamp;
    std::string prev_hash;
    int64_t nonce = 0;
    std::string crypto_suite_id;
    std::string key_id;
    std::string signature;
    std::string public_key_pem;
    std::string leaf_hash;
    std::vector<std::pair<std::string, bool>> proof; // (hash, is_left)
    std::string merkle_root;
    int64_t first_nonce = 0;
    int64_t last_nonce = 0;
    int64_t leaf_count = 0;
    int64_t prev_day_last_nonce = -1;
    int64_t eod_gap = 0;
    std::string anchor_digest;
    std::string timestamp_token;
};

struct ProofPackVerifyResult {
    bool verified = false;
    std::string error_message;
    bool merkle_verified = false;
    bool ecdsa_verified = false;
    bool anchor_verified = false;
    bool timestamp_verified = false;
    bool key_registry_verified = false;
};

/**
 * Perform fail-closed verification of an EnergyTrust Protocol (ETP) ProofPack.
 * 
 * FAIL-CLOSED SECURITY GUARANTEES:
 * 1. An empty or incomplete proof pack is STRICTLY REJECTED (verified = false).
 * 2. Meter ECDSA signature must be valid against public_key_pem (or trusted_public_key_pem).
 * 3. If trusted_public_key_pem is provided, pack's public_key_pem MUST match it.
 * 4. Merkle proof path must reconstruct merkle_root from leaf_hash.
 * 5. Anchor digest must match SHA-256 of anchor metadata payload.
 * 6. RFC 3161 timestamp token signature must be cryptographically verified against anchor digest.
 * 7. Simulated TSA tokens are REJECTED unless allow_simulated_tsa = true is explicitly passed.
 */
ProofPackVerifyResult verify_proof_pack(
    const ProofPack& pack,
    const std::string& trusted_public_key_pem = "",
    bool allow_simulated_tsa = false,
    const std::string& trusted_tsa_ca_pem = ""
);

/**
 * Helper to parse ProofPack JSON string with proper unescaping of PEM newlines.
 */
ProofPack parse_proof_pack_json(const std::string& json_str);

} // namespace etp

#endif // ETP_PROOF_PACK_HPP
