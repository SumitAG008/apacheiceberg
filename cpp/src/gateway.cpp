#include "etp/gateway.hpp"
#include <array>
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/crypto.h>

#include <charconv>
#include <memory>
#include <sstream>
#include <iomanip>
#include <locale>
#include <system_error>
#include <stdexcept>
#include <algorithm>
#include <cstring>

namespace etp {

namespace {

// RAII Smart Pointer Aliases for OpenSSL handles (CPP-ARC-001 §2 compliance)
using EVP_PKEY_ptr = std::unique_ptr<EVP_PKEY, decltype(&EVP_PKEY_free)>;
using EVP_MD_CTX_ptr = std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)>;
using BIO_ptr = std::unique_ptr<BIO, decltype(&BIO_free)>;

inline bool hex_char_val(char c, uint8_t& val) {
    if (c >= '0' && c <= '9') { val = static_cast<uint8_t>(c - '0'); return true; }
    if (c >= 'a' && c <= 'f') { val = static_cast<uint8_t>(c - 'a' + 10); return true; }
    if (c >= 'A' && c <= 'F') { val = static_cast<uint8_t>(c - 'A' + 10); return true; }
    return false;
}

// Zero-throw, zero-allocation hex parser preventing memory leaks or exceptions on corrupt inputs
inline bool hex_to_bytes(std::string_view hex, std::vector<uint8_t>& out) {
    if (hex.size() % 2 != 0) return false;
    out.clear();
    out.reserve(hex.size() / 2);
    for (size_t i = 0; i < hex.size(); i += 2) {
        uint8_t hi = 0, lo = 0;
        if (!hex_char_val(hex[i], hi) || !hex_char_val(hex[i + 1], lo)) {
            out.clear();
            return false;
        }
        out.push_back(static_cast<uint8_t>((hi << 4) | lo));
    }
    return true;
}

std::string bytes_to_hex(const uint8_t* data, size_t len) {
    std::ostringstream oss;
    oss.imbue(std::locale::classic());
    for (size_t i = 0; i < len; ++i) {
        oss << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(data[i]);
    }
    return oss.str();
}

bool constant_time_equal(std::string_view a, std::string_view b) {
    if (a.size() != b.size()) {
        return false;
    }
    return CRYPTO_memcmp(a.data(), b.data(), a.size()) == 0;
}

} // namespace

// --- SlidingWindowNonceStore ---

SlidingWindowNonceStore::SlidingWindowNonceStore(size_t window_size) : window_size_(window_size) {
    if (window_size_ == 0 || window_size_ > 64) {
        // Bitmap optimization uses uint64_t for fast zero-alloc bitmap operations up to 64 nonces
        window_size_ = 64;
    }
}

SlidingWindowNonceStore::CheckResult SlidingWindowNonceStore::check_only(
    std::string_view mpan,
    uint64_t incoming_nonce
) {
    std::lock_guard<std::mutex> lock(mutex_);
    std::string key(mpan);
    auto it = store_.find(key);
    if (it == store_.end()) {
        return {true, 0, "OK"};
    }

    const auto& rec = it->second;
    if (incoming_nonce > rec.last_nonce) {
        return {true, rec.last_nonce, "OK"};
    }

    uint64_t diff = rec.last_nonce - incoming_nonce;
    if (diff < window_size_) {
        bool is_seen = (rec.seen_bitmap >> diff) & 1ULL;
        if (is_seen) {
            return {false, rec.last_nonce, "REPLAY_REJECTED"};
        }
        return {true, rec.last_nonce, "OK_BACKFILL"};
    }

    return {false, rec.last_nonce, "EXPIRED_NONCE_REJECTED"};
}

SlidingWindowNonceStore::CommitResult SlidingWindowNonceStore::commit(
    std::string_view mpan,
    uint64_t incoming_nonce,
    std::string_view incoming_hash,
    std::string_view timestamp
) {
    std::lock_guard<std::mutex> lock(mutex_);
    std::string key(mpan);
    auto it = store_.find(key);

    if (it == store_.end()) {
        store_[key] = MeterRecord{
            .last_nonce = incoming_nonce,
            .seen_bitmap = 1ULL,
            .last_hash = std::string(incoming_hash),
            .updated_at = std::string(timestamp)
        };
        return {true, incoming_nonce, "ACCEPT"};
    }

    auto& rec = it->second;
    if (incoming_nonce > rec.last_nonce) {
        uint64_t shift = incoming_nonce - rec.last_nonce;
        uint64_t new_bitmap = 0;
        if (shift >= window_size_) {
            new_bitmap = 1ULL;
        } else {
            uint64_t mask = (window_size_ == 64) ? ~0ULL : ((1ULL << window_size_) - 1ULL);
            new_bitmap = ((rec.seen_bitmap << shift) | 1ULL) & mask;
        }

        rec.last_nonce = incoming_nonce;
        rec.seen_bitmap = new_bitmap;
        rec.last_hash = std::string(incoming_hash);
        rec.updated_at = std::string(timestamp);
        return {true, incoming_nonce, "ACCEPT"};
    }

    uint64_t diff = rec.last_nonce - incoming_nonce;
    if (diff < window_size_) {
        if ((rec.seen_bitmap >> diff) & 1ULL) {
            return {false, rec.last_nonce, "REPLAY_REJECTED"};
        }

        rec.seen_bitmap |= (1ULL << diff);
        rec.updated_at = std::string(timestamp);
        // Crucial fix: Do NOT update last_hash on backfill! Chain head remains last_nonce block.
        return {true, incoming_nonce, "ACCEPT_BACKFILL"};
    }

    return {false, rec.last_nonce, "EXPIRED_NONCE_REJECTED"};
}

std::optional<std::string> SlidingWindowNonceStore::get_last_hash(std::string_view mpan) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = store_.find(std::string(mpan));
    if (it != store_.end()) {
        return it->second.last_hash;
    }
    return std::nullopt;
}

// --- GatewayEngine ---

GatewayEngine::GatewayEngine(std::string_view secret_key, uint64_t route_window_seconds)
    : route_mutator_(secret_key, route_window_seconds), nonce_store_(64) {}

void GatewayEngine::register_meter_public_key(std::string_view mpan, std::string_view public_key_pem) {
    std::lock_guard<std::mutex> lock(key_registry_mutex_);
    public_key_registry_pem_[std::string(mpan)] = std::string(public_key_pem);
}

std::string GatewayEngine::compute_canonical_hash(const TelemetryBlock& block) {
    // Locale-independent float formatting using std::to_chars (prevents LC_NUMERIC European comma bug)
    char formatted_kwh_buf[64];
    auto [ptr, ec] = std::to_chars(
        formatted_kwh_buf,
        formatted_kwh_buf + sizeof(formatted_kwh_buf),
        block.reading_kwh,
        std::chars_format::fixed,
        3
    );
    std::string_view formatted_kwh(formatted_kwh_buf, (ec == std::errc{}) ? (ptr - formatted_kwh_buf) : 0);

    std::string nonce_str = std::to_string(block.nonce);
    const uint8_t sep = 0x1F; // ASCII Unit Separator

    std::vector<uint8_t> payload;
    auto append_part = [&](std::string_view str) {
        payload.insert(payload.end(), str.begin(), str.end());
    };

    append_part(block.mpan);
    payload.push_back(sep);
    append_part(formatted_kwh);
    payload.push_back(sep);
    append_part(block.timestamp);
    payload.push_back(sep);
    append_part(block.prev_hash);
    payload.push_back(sep);
    append_part(nonce_str);
    payload.push_back(sep);
    append_part(block.crypto_suite_id);
    payload.push_back(sep);
    append_part(block.key_id);

    std::array<uint8_t, 32> hash{};
    unsigned int out_len = 0;

    EVP_MD_CTX_ptr ctx(EVP_MD_CTX_new(), EVP_MD_CTX_free);
    if (!ctx) {
        throw std::runtime_error("Failed to allocate EVP_MD_CTX");
    }

    if (EVP_DigestInit_ex(ctx.get(), EVP_sha256(), nullptr) != 1 ||
        EVP_DigestUpdate(ctx.get(), payload.data(), payload.size()) != 1 ||
        EVP_DigestFinal_ex(ctx.get(), hash.data(), &out_len) != 1) {
        throw std::runtime_error("OpenSSL SHA256 canonical hash failed");
    }

    return bytes_to_hex(hash.data(), hash.size());
}

bool GatewayEngine::verify_ecdsa_signature(
    std::string_view mpan,
    std::string_view block_hash_hex,
    std::string_view signature_hex
) const {
    std::string pem;
    {
        std::lock_guard<std::mutex> lock(key_registry_mutex_);
        auto it = public_key_registry_pem_.find(std::string(mpan));
        if (it == public_key_registry_pem_.end()) {
            return false;
        }
        pem = it->second;
    }

    // Convert hex inputs safely before allocating OpenSSL handles (zero throw, zero leak)
    std::vector<uint8_t> hash_bytes;
    std::vector<uint8_t> sig_bytes;
    if (!hex_to_bytes(block_hash_hex, hash_bytes) || !hex_to_bytes(signature_hex, sig_bytes)) {
        return false;
    }

    // Load Public Key from PEM string using OpenSSL 3.0 BIO with RAII auto-cleanup
    BIO_ptr bio(BIO_new_mem_buf(pem.data(), static_cast<int>(pem.size())), BIO_free);
    if (!bio) {
        return false;
    }

    EVP_PKEY_ptr pkey(PEM_read_bio_PUBKEY(bio.get(), nullptr, nullptr, nullptr), EVP_PKEY_free);
    if (!pkey) {
        return false;
    }

    EVP_MD_CTX_ptr ctx(EVP_MD_CTX_new(), EVP_MD_CTX_free);
    if (!ctx) {
        return false;
    }

    if (EVP_DigestVerifyInit(ctx.get(), nullptr, EVP_sha256(), nullptr, pkey.get()) == 1) {
        if (EVP_DigestVerifyUpdate(ctx.get(), hash_bytes.data(), hash_bytes.size()) == 1) {
            if (EVP_DigestVerifyFinal(ctx.get(), sig_bytes.data(), sig_bytes.size()) == 1) {
                return true;
            }
        }
    }

    return false;
}

VerificationResult GatewayEngine::verify_telemetry_block(
    std::string_view route,
    const TelemetryBlock& block,
    uint64_t now_epoch_s
) {
    // 1. MTD Ingress Route Validation
    if (!route_mutator_.validate_route(route, now_epoch_s)) {
        return {
            VerificationStatus::INVALID_ROUTE,
            block.block_hash,
            "Invalid ingress route - divert to Phantom Grid honeypot",
            true // divert_to_honeypot = true
        };
    }

    // 2. Nonce Check Only (Peek before expensive ECDSA math)
    auto check_res = nonce_store_.check_only(block.mpan, block.nonce);
    if (!check_res.ok) {
        VerificationStatus status = (check_res.reason == "EXPIRED_NONCE_REJECTED")
            ? VerificationStatus::EXPIRED_NONCE_REJECTED
            : VerificationStatus::REPLAY_REJECTED;
        return {
            status,
            block.block_hash,
            check_res.reason,
            false
        };
    }

    // 3. Canonical Block Hash Verification
    std::string recomputed_hash = compute_canonical_hash(block);
    if (!constant_time_equal(recomputed_hash, block.block_hash)) {
        return {
            VerificationStatus::TAMPER_REJECTED,
            block.block_hash,
            "Canonical hash mismatch: payload tampered in transit",
            false
        };
    }

    // 4. ECDSA Signature Verification
    if (!verify_ecdsa_signature(block.mpan, block.block_hash, block.signature)) {
        return {
            VerificationStatus::SIGNATURE_FAILED,
            block.block_hash,
            "ECDSA signature verification failed",
            false
        };
    }

    // 5. Chain Link Check (VERIFIED vs CHAIN_GAP)
    auto expected_prev_hash = nonce_store_.get_last_hash(block.mpan);
    VerificationStatus verify_status = VerificationStatus::VERIFIED;
    if (expected_prev_hash.has_value() && block.prev_hash != *expected_prev_hash) {
        verify_status = VerificationStatus::CHAIN_GAP;
    }

    // 6. Commit State (After all cryptographic checks pass)
    auto commit_res = nonce_store_.commit(block.mpan, block.nonce, block.block_hash, block.timestamp);
    if (!commit_res.ok) {
        return {
            VerificationStatus::REPLAY_REJECTED,
            block.block_hash,
            commit_res.reason,
            false
        };
    }

    return {
        verify_status,
        block.block_hash,
        "Telemetry block verified successfully",
        false
    };
}

} // namespace etp
