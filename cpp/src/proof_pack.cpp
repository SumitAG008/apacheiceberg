#include "etp/proof_pack.hpp"
#include "etp/gateway.hpp"
#include <openssl/evp.h>
#include <array>
#include <memory>
#include <sstream>
#include <iomanip>
#include <iostream>
#include <algorithm>
#include <cstdint>

namespace etp {

namespace {

using EVP_MD_CTX_ptr = std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)>;

std::string bytes_to_hex(const uint8_t* data, size_t len) {
    std::ostringstream oss;
    oss.imbue(std::locale::classic());
    for (size_t i = 0; i < len; ++i) {
        oss << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(data[i]);
    }
    return oss.str();
}

inline bool is_ws(char c) {
    return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == ':';
}

std::string json_extract_string(std::string_view json, std::string_view key) {
    std::string search = "\"" + std::string(key) + "\"";
    size_t pos = json.find(search);
    if (pos == std::string_view::npos) return "";

    pos += search.length();
    while (pos < json.length() && is_ws(json[pos])) pos++;
    if (pos >= json.length() || json[pos] != '"') return "";
    pos++;

    size_t end_pos = json.find('"', pos);
    if (end_pos == std::string_view::npos) return "";

    return std::string(json.substr(pos, end_pos - pos));
}

int64_t json_extract_int(std::string_view json, std::string_view key, int64_t default_val = 0) {
    std::string search = "\"" + std::string(key) + "\"";
    size_t pos = json.find(search);
    if (pos == std::string_view::npos) return default_val;

    pos += search.length();
    while (pos < json.length() && is_ws(json[pos])) pos++;
    if (pos >= json.length()) return default_val;

    size_t start = pos;
    if (json[pos] == '-') pos++;
    while (pos < json.length() && json[pos] >= '0' && json[pos] <= '9') pos++;

    if (pos > start) {
        try {
            return std::stoll(std::string(json.substr(start, pos - start)));
        } catch (...) {
            return default_val;
        }
    }
    return default_val;
}

double json_extract_double(std::string_view json, std::string_view key, double default_val = 0.0) {
    std::string search = "\"" + std::string(key) + "\"";
    size_t pos = json.find(search);
    if (pos == std::string_view::npos) return default_val;

    pos += search.length();
    while (pos < json.length() && is_ws(json[pos])) pos++;
    if (pos >= json.length()) return default_val;

    size_t start = pos;
    if (json[pos] == '-') pos++;
    while (pos < json.length() && ((json[pos] >= '0' && json[pos] <= '9') || json[pos] == '.')) pos++;

    if (pos > start) {
        try {
            return std::stod(std::string(json.substr(start, pos - start)));
        } catch (...) {
            return default_val;
        }
    }
    return default_val;
}

} // namespace

std::string compute_anchor_digest(
    std::string_view merkle_root,
    uint64_t first_nonce,
    uint64_t last_nonce,
    size_t leaf_count,
    int prev_day_last_nonce,
    size_t eod_gap
) {
    std::ostringstream oss;
    oss.imbue(std::locale::classic());
    oss << merkle_root << "|"
        << first_nonce << "|"
        << last_nonce << "|"
        << leaf_count << "|";
    
    if (prev_day_last_nonce < 0) {
        oss << "None";
    } else {
        oss << prev_day_last_nonce;
    }
    oss << "|" << eod_gap;

    std::string payload = oss.str();
    std::array<uint8_t, 32> hash{};
    unsigned int out_len = 0;

    EVP_MD_CTX_ptr ctx(EVP_MD_CTX_new(), EVP_MD_CTX_free);
    if (!ctx) return "";

    if (EVP_DigestInit_ex(ctx.get(), EVP_sha256(), nullptr) == 1 &&
        EVP_DigestUpdate(ctx.get(), payload.data(), payload.size()) == 1 &&
        EVP_DigestFinal_ex(ctx.get(), hash.data(), &out_len) == 1) {
        return bytes_to_hex(hash.data(), out_len);
    }
    return "";
}

ProofPackResult verify_proof_pack(const ProofPack& pack) {
    ProofPackResult res;

    // 1. Canonical Block Hash & ECDSA Signature Verification
    if (!pack.mpan.empty() && !pack.signature.empty() && !pack.public_key_pem.empty()) {
        TelemetryBlock block{
            .mpan = pack.mpan,
            .reading_kwh = pack.reading_kwh,
            .timestamp = pack.timestamp,
            .prev_hash = pack.prev_hash,
            .nonce = pack.nonce,
            .crypto_suite_id = pack.crypto_suite_id.empty() ? "ECDSA-P256-SHA256-v1" : pack.crypto_suite_id,
            .key_id = pack.key_id
        };

        std::string computed_hash = GatewayEngine::compute_canonical_hash(block);
        if (!pack.leaf_hash.empty() && computed_hash != pack.leaf_hash) {
            res.valid = false;
            res.overall_status = "TAMPER_REJECTED";
            res.errors.push_back("Canonical block hash mismatch: computed=" + computed_hash + " != expected=" + pack.leaf_hash);
            return res;
        }

        std::string target_hash = pack.leaf_hash.empty() ? computed_hash : pack.leaf_hash;
        if (verify_ecdsa_signature(target_hash, pack.signature, pack.public_key_pem)) {
            res.ecdsa_verified = true;
            res.checks_passed.push_back("ECDSA signature verified");
        } else {
            res.valid = false;
            res.overall_status = "SIGNATURE_FAILED";
            res.errors.push_back("ECDSA signature verification failed");
            return res;
        }
    } else if (!pack.signature.empty() && !pack.public_key_pem.empty() && !pack.leaf_hash.empty()) {
        if (verify_ecdsa_signature(pack.leaf_hash, pack.signature, pack.public_key_pem)) {
            res.ecdsa_verified = true;
            res.checks_passed.push_back("ECDSA signature verified");
        } else {
            res.valid = false;
            res.overall_status = "SIGNATURE_FAILED";
            res.errors.push_back("ECDSA signature verification failed");
            return res;
        }
    }

    // 2. Merkle Proof Verification
    if (!pack.merkle_root.empty() && !pack.leaf_hash.empty()) {
        if (MerkleTree::verify_proof(pack.leaf_hash, pack.proof, pack.merkle_root)) {
            res.merkle_verified = true;
            res.checks_passed.push_back("Merkle proof path verified");
        } else {
            res.valid = false;
            res.overall_status = "MERKLE_FAILED";
            res.errors.push_back("Merkle proof verification failed for leaf " + pack.leaf_hash + " against root " + pack.merkle_root);
            return res;
        }
    }

    // 3. Anchor Digest Commitment Verification
    if (!pack.anchor_digest.empty() && !pack.merkle_root.empty()) {
        std::string recomputed_anchor = compute_anchor_digest(
            pack.merkle_root,
            pack.first_nonce,
            pack.last_nonce,
            pack.leaf_count,
            pack.prev_day_last_nonce,
            pack.eod_gap
        );

        if (recomputed_anchor == pack.anchor_digest) {
            res.anchor_digest_verified = true;
            res.checks_passed.push_back("Anchor metadata commitment verified");
        } else {
            res.valid = false;
            res.overall_status = "ANCHOR_FAILED";
            res.errors.push_back("Anchor digest mismatch: computed=" + recomputed_anchor + " != expected=" + pack.anchor_digest);
            return res;
        }
    }

    // 4. RFC 3161 Timestamp Token Verification
    if (!pack.timestamp_token.empty()) {
        std::string target_digest = !pack.anchor_digest.empty() ? pack.anchor_digest : pack.merkle_root;
        auto ts_res = verify_rfc3161_timestamp(pack.timestamp_token, target_digest);

        if (ts_res.valid) {
            res.timestamp_verified = true;
            res.checks_passed.push_back("RFC 3161 timestamp token verified (" + ts_res.status_message + ")");
        } else {
            res.valid = false;
            res.overall_status = "TIMESTAMP_FAILED";
            res.errors.push_back("RFC 3161 timestamp token verification failed: " + ts_res.status_message);
            return res;
        }
    }

    if (res.errors.empty()) {
        res.valid = true;
        res.overall_status = "VERIFIED";
    }

    return res;
}

ProofPack parse_proof_pack_json(std::string_view json_str) {
    ProofPack pack;
    pack.leaf_hash = json_extract_string(json_str, "leaf_hash");
    if (pack.leaf_hash.empty()) pack.leaf_hash = json_extract_string(json_str, "block_hash");

    pack.mpan = json_extract_string(json_str, "mpan");
    pack.reading_kwh = json_extract_double(json_str, "reading_kwh", 0.0);
    pack.timestamp = json_extract_string(json_str, "timestamp");
    pack.prev_hash = json_extract_string(json_str, "prev_hash");
    pack.nonce = static_cast<uint64_t>(json_extract_int(json_str, "nonce", 0));
    pack.crypto_suite_id = json_extract_string(json_str, "crypto_suite_id");
    pack.key_id = json_extract_string(json_str, "key_id");
    pack.signature = json_extract_string(json_str, "signature");
    pack.public_key_pem = json_extract_string(json_str, "public_key_pem");

    pack.merkle_root = json_extract_string(json_str, "merkle_root");
    pack.first_nonce = static_cast<uint64_t>(json_extract_int(json_str, "first_nonce", 0));
    pack.last_nonce = static_cast<uint64_t>(json_extract_int(json_str, "last_nonce", 0));
    pack.leaf_count = static_cast<size_t>(json_extract_int(json_str, "leaf_count", 0));
    pack.prev_day_last_nonce = static_cast<int>(json_extract_int(json_str, "prev_day_last_nonce", -1));
    pack.eod_gap = static_cast<size_t>(json_extract_int(json_str, "eod_gap", 0));
    pack.anchor_digest = json_extract_string(json_str, "anchor_digest");
    pack.timestamp_token = json_extract_string(json_str, "timestamp_token");

    // Parse proof steps array: "proof": [ {"hash": "...", "is_left": true/false}, ... ]
    size_t proof_pos = json_str.find("\"proof\"");
    if (proof_pos != std::string_view::npos) {
        size_t arr_start = json_str.find('[', proof_pos);
        size_t arr_end = json_str.find(']', arr_start);
        if (arr_start != std::string_view::npos && arr_end != std::string_view::npos) {
            std::string_view arr_str = json_str.substr(arr_start + 1, arr_end - arr_start - 1);
            size_t step_pos = 0;
            while ((step_pos = arr_str.find('{', step_pos)) != std::string_view::npos) {
                size_t step_end = arr_str.find('}', step_pos);
                if (step_end == std::string_view::npos) break;

                std::string_view step_obj = arr_str.substr(step_pos, step_end - step_pos + 1);
                std::string step_hash = json_extract_string(step_obj, "hash");
                bool is_left = (step_obj.find("\"is_left\": true") != std::string_view::npos ||
                                step_obj.find("\"is_left\":true") != std::string_view::npos);

                if (!step_hash.empty()) {
                    pack.proof.push_back(MerkleProofStep{.hash = step_hash, .is_left = is_left});
                }
                step_pos = step_end + 1;
            }
        }
    }

    return pack;
}

std::string proof_pack_result_to_json(const ProofPackResult& res) {
    std::ostringstream oss;
    oss.imbue(std::locale::classic());
    oss << "{\n";
    oss << "  \"valid\": " << (res.valid ? "true" : "false") << ",\n";
    oss << "  \"overall_status\": \"" << res.overall_status << "\",\n";
    oss << "  \"ecdsa_verified\": " << (res.ecdsa_verified ? "true" : "false") << ",\n";
    oss << "  \"merkle_verified\": " << (res.merkle_verified ? "true" : "false") << ",\n";
    oss << "  \"anchor_digest_verified\": " << (res.anchor_digest_verified ? "true" : "false") << ",\n";
    oss << "  \"timestamp_verified\": " << (res.timestamp_verified ? "true" : "false") << ",\n";
    oss << "  \"checks_passed\": [";
    for (size_t i = 0; i < res.checks_passed.size(); ++i) {
        oss << "\"" << res.checks_passed[i] << "\"" << (i + 1 < res.checks_passed.size() ? ", " : "");
    }
    oss << "],\n";
    oss << "  \"errors\": [";
    for (size_t i = 0; i < res.errors.size(); ++i) {
        oss << "\"" << res.errors[i] << "\"" << (i + 1 < res.errors.size() ? ", " : "");
    }
    oss << "]\n";
    oss << "}";
    return oss.str();
}

} // namespace etp
