#include "etp/ecdsa.hpp"
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <memory>
#include <vector>
#include <cstdint>

namespace etp {

namespace {

using EVP_PKEY_ptr = std::unique_ptr<EVP_PKEY, decltype(&EVP_PKEY_free)>;
using EVP_MD_CTX_ptr = std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)>;
using BIO_ptr = std::unique_ptr<BIO, decltype(&BIO_free)>;

inline bool hex_char_val(char c, uint8_t& val) {
    if (c >= '0' && c <= '9') { val = static_cast<uint8_t>(c - '0'); return true; }
    if (c >= 'a' && c <= 'f') { val = static_cast<uint8_t>(c - 'a' + 10); return true; }
    if (c >= 'A' && c <= 'F') { val = static_cast<uint8_t>(c - 'A' + 10); return true; }
    return false;
}

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

} // namespace

bool verify_ecdsa_signature(
    std::string_view block_hash_hex,
    std::string_view signature_hex,
    std::string_view public_key_pem
) {
    if (block_hash_hex.empty() || signature_hex.empty() || public_key_pem.empty()) {
        return false;
    }

    std::vector<uint8_t> hash_bytes;
    std::vector<uint8_t> sig_bytes;
    if (!hex_to_bytes(block_hash_hex, hash_bytes) || !hex_to_bytes(signature_hex, sig_bytes)) {
        return false;
    }

    BIO_ptr bio(BIO_new_mem_buf(public_key_pem.data(), static_cast<int>(public_key_pem.size())), BIO_free);
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

} // namespace etp
