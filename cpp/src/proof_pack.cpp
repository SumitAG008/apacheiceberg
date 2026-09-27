#include "etp/proof_pack.hpp"
#include "etp/ecdsa.hpp"
#include "etp/timestamp.hpp"
#include <openssl/evp.h>
#include <openssl/sha.h>
#include <sstream>
#include <iomanip>
#include <algorithm>
#include <cmath>
#include <locale>
#include <iostream>


namespace etp {

static std::string sha256_hex(const std::string& input) {
    uint8_t hash[32];
    EVP_MD_CTX* ctx = EVP_MD_CTX_new();
    if (!ctx) return "";
    EVP_DigestInit_ex(ctx, EVP_sha256(), nullptr);
    EVP_DigestUpdate(ctx, input.data(), input.size());
    EVP_DigestFinal_ex(ctx, hash, nullptr);
    EVP_MD_CTX_free(ctx);

    std::stringstream ss;
    for (int i = 0; i < 32; ++i) {
        ss << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(hash[i]);
    }
    return ss.str();
}

static std::string format_reading_kwh(double reading) {
    std::stringstream ss;
    ss.imbue(std::locale::classic());
    ss << std::fixed << std::setprecision(3) << reading;
    return ss.str();
}


static std::string unescape_json_string(const std::string& input) {
    std::string result;
    result.reserve(input.size());
    for (size_t i = 0; i < input.size(); ++i) {
        if (input[i] == '\\' && i + 1 < input.size()) {
            char next = input[i + 1];
            if (next == 'n') {
                result.push_back('\n');
                i++;
            } else if (next == 'r') {
                result.push_back('\r');
                i++;
            } else if (next == 't') {
                result.push_back('\t');
                i++;
            } else if (next == '"') {
                result.push_back('"');
                i++;
            } else if (next == '\\') {
                result.push_back('\\');
                i++;
            } else {
                result.push_back(input[i]);
            }
        } else {
            result.push_back(input[i]);
        }
    }
    return result;
}

static std::string extract_json_field(const std::string& json, const std::string& key) {
    std::string search_key = "\"" + key + "\"";
    size_t pos = json.find(search_key);
    if (pos == std::string::npos) return "";

    size_t colon_pos = json.find(':', pos + search_key.length());
    if (colon_pos == std::string::npos) return "";

    size_t val_start = json.find_first_not_of(" \t\r\n", colon_pos + 1);
    if (val_start == std::string::npos) return "";

    if (json[val_start] == '"') {
        size_t end_quote = val_start + 1;
        while (end_quote < json.length()) {
            if (json[end_quote] == '"' && json[end_quote - 1] != '\\') {
                break;
            }
            end_quote++;
        }
        if (end_quote >= json.length()) return "";
        std::string raw_val = json.substr(val_start + 1, end_quote - val_start - 1);
        return unescape_json_string(raw_val);
    } else {
        size_t end_val = json.find_first_of(",}\r\n", val_start);
        if (end_val == std::string::npos) end_val = json.length();
        std::string val = json.substr(val_start, end_val - val_start);
        val.erase(val.find_last_not_of(" \t\r\n") + 1);
        return val;
    }
}

ProofPack parse_proof_pack_json(const std::string& json_str) {
    ProofPack pack;
    pack.mpan = extract_json_field(json_str, "mpan");
    std::string reading_str = extract_json_field(json_str, "reading_kwh");
    if (!reading_str.empty()) pack.reading_kwh = std::stod(reading_str);
    
    pack.timestamp = extract_json_field(json_str, "timestamp");
    pack.prev_hash = extract_json_field(json_str, "prev_hash");
    std::string nonce_str = extract_json_field(json_str, "nonce");
    if (!nonce_str.empty()) pack.nonce = std::stoll(nonce_str);

    pack.crypto_suite_id = extract_json_field(json_str, "crypto_suite_id");
    pack.key_id = extract_json_field(json_str, "key_id");
    pack.signature = extract_json_field(json_str, "signature");
    pack.public_key_pem = extract_json_field(json_str, "public_key_pem");
    pack.leaf_hash = extract_json_field(json_str, "leaf_hash");
    pack.merkle_root = extract_json_field(json_str, "merkle_root");

    std::string fn_str = extract_json_field(json_str, "first_nonce");
    if (!fn_str.empty()) pack.first_nonce = std::stoll(fn_str);

    std::string ln_str = extract_json_field(json_str, "last_nonce");
    if (!ln_str.empty()) pack.last_nonce = std::stoll(ln_str);

    std::string lc_str = extract_json_field(json_str, "leaf_count");
    if (!lc_str.empty()) pack.leaf_count = std::stoll(lc_str);

    std::string pd_str = extract_json_field(json_str, "prev_day_last_nonce");
    if (!pd_str.empty()) pack.prev_day_last_nonce = std::stoll(pd_str);

    std::string eod_str = extract_json_field(json_str, "eod_gap");
    if (!eod_str.empty()) pack.eod_gap = std::stoll(eod_str);

    pack.anchor_digest = extract_json_field(json_str, "anchor_digest");
    pack.timestamp_token = extract_json_field(json_str, "timestamp_token");

    // Parse proof array
    size_t proof_pos = json_str.find("\"proof\"");
    if (proof_pos != std::string::npos) {
        size_t arr_start = json_str.find('[', proof_pos);
        size_t arr_end = json_str.find(']', arr_start);
        if (arr_start != std::string::npos && arr_end != std::string::npos) {
            std::string arr_str = json_str.substr(arr_start, arr_end - arr_start + 1);
            size_t step_pos = 0;
            while ((step_pos = arr_str.find('{', step_pos)) != std::string::npos) {
                size_t step_end = arr_str.find('}', step_pos);
                if (step_end == std::string::npos) break;
                std::string step_obj = arr_str.substr(step_pos, step_end - step_pos + 1);
                std::string hash = extract_json_field(step_obj, "hash");
                std::string is_left_str = extract_json_field(step_obj, "is_left");
                bool is_left = (is_left_str == "true");
                if (!hash.empty()) {
                    pack.proof.push_back({hash, is_left});
                }
                step_pos = step_end + 1;
            }
        }
    }

    return pack;
}

ProofPackVerifyResult verify_proof_pack(
    const ProofPack& pack,
    const std::string& trusted_public_key_pem,
    bool allow_simulated_tsa,
    const std::string& trusted_tsa_ca_pem
) {
    ProofPackVerifyResult res;
    res.verified = false;

    // FAIL-CLOSED: Strict Mandatory Field Validation
    if (pack.leaf_hash.empty() || pack.leaf_hash.length() != 64) {
        res.error_message = "Missing or invalid leaf_hash (must be 64-char hex SHA-256)";
        return res;
    }
    if (pack.merkle_root.empty() || pack.merkle_root.length() != 64) {
        res.error_message = "Missing or invalid merkle_root (must be 64-char hex SHA-256)";
        return res;
    }
    if (pack.proof.empty()) {
        res.error_message = "Missing Merkle proof path array";
        return res;
    }
    if (pack.signature.empty()) {
        res.error_message = "Missing meter ECDSA signature";
        return res;
    }
    if (pack.anchor_digest.empty() || pack.anchor_digest.length() != 64) {
        res.error_message = "Missing or invalid anchor_digest";
        return res;
    }
    if (pack.timestamp_token.empty()) {
        res.error_message = "Missing RFC 3161 timestamp token";
        return res;
    }

    // Key Registry Verification
    std::string key_to_use = trusted_public_key_pem;
    if (!key_to_use.empty()) {
        if (!pack.public_key_pem.empty() && pack.public_key_pem != key_to_use) {
            res.error_message = "Meter public key in proof pack does not match trusted key registry";
            return res;
        }
        res.key_registry_verified = true;
    } else {
        if (pack.public_key_pem.empty()) {
            res.error_message = "Missing meter public_key_pem and no trusted_public_key_pem provided";
            return res;
        }
        key_to_use = pack.public_key_pem;
        res.key_registry_verified = false; // Self-asserted key, not registry validated
    }

    // 1. Merkle Proof Verification
    std::string current = pack.leaf_hash;
    for (const auto& step : pack.proof) {
        if (step.second) { // is_left
            current = sha256_hex(step.first + current);
        } else {
            current = sha256_hex(current + step.first);
        }
    }
    if (current != pack.merkle_root) {
        res.error_message = "Merkle proof verification failed: computed root " + current + " != " + pack.merkle_root;
        return res;
    }
    res.merkle_verified = true;

    // 2. Meter ECDSA Signature Verification
    std::string reading_str = format_reading_kwh(pack.reading_kwh);
    std::string msg = pack.mpan + "|" + reading_str + "|" + pack.timestamp + "|" + pack.prev_hash + "|" + std::to_string(pack.nonce) + "|" + pack.leaf_hash;
    std::string msg_hash = sha256_hex(msg);

    if (!verify_ecdsa_signature(msg_hash, pack.signature, key_to_use)) {
        res.error_message = "ECDSA meter signature verification failed";
        return res;
    }
    res.ecdsa_verified = true;

    // 3. Anchor Digest Verification
    std::string anchor_payload = pack.merkle_root + "|" + std::to_string(pack.first_nonce) + "|" + std::to_string(pack.last_nonce) + "|" + std::to_string(pack.leaf_count) + "|" + std::to_string(pack.prev_day_last_nonce) + "|" + std::to_string(pack.eod_gap);
    std::string computed_anchor_digest = sha256_hex(anchor_payload);
    if (computed_anchor_digest != pack.anchor_digest) {
        res.error_message = "Anchor digest mismatch: computed " + computed_anchor_digest + " vs pack " + pack.anchor_digest;
        return res;
    }
    res.anchor_verified = true;

    // 4. RFC 3161 Timestamp Token Verification
    auto ts_res = verify_rfc3161_timestamp(pack.timestamp_token, pack.anchor_digest, allow_simulated_tsa, trusted_tsa_ca_pem);
    if (!ts_res.valid) {
        res.error_message = "RFC 3161 timestamp token verification failed: " + ts_res.error;
        return res;
    }
    res.timestamp_verified = true;

    // All verification checks passed
    res.verified = true;
    return res;
}

} // namespace etp
