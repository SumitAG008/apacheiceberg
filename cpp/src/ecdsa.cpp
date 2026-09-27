#include "etp/ecdsa.hpp"
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/bio.h>
#include <openssl/err.h>
#include <openssl/ec.h>
#include <openssl/param_build.h>
#include <vector>
#include <sstream>
#include <iomanip>
#include <algorithm>

namespace etp {

static std::vector<uint8_t> base64_decode(const std::string& b64) {
    if (b64.empty()) return {};
    
    // Clean up whitespace or newline characters
    std::string clean_b64;
    clean_b64.reserve(b64.size());
    for (char c : b64) {
        if (!isspace(static_cast<unsigned char>(c))) {
            clean_b64.push_back(c);
        }
    }

    BIO* bio = BIO_new_mem_buf(clean_b64.data(), static_cast<int>(clean_b64.size()));
    BIO* b64_bio = BIO_new(BIO_f_base64());
    BIO_set_flags(b64_bio, BIO_FLAGS_BASE64_NO_NL);
    bio = BIO_push(b64_bio, bio);

    std::vector<uint8_t> buffer(clean_b64.size());
    int decoded_size = BIO_read(bio, buffer.data(), static_cast<int>(buffer.size()));
    BIO_free_all(bio);

    if (decoded_size <= 0) return {};
    buffer.resize(static_cast<size_t>(decoded_size));
    return buffer;
}

static std::vector<uint8_t> hex_to_bytes(const std::string& hex) {
    std::vector<uint8_t> bytes;
    bytes.reserve(hex.size() / 2);
    for (size_t i = 0; i < hex.length(); i += 2) {
        std::string byteString = hex.substr(i, 2);
        uint8_t byte = static_cast<uint8_t>(strtol(byteString.c_str(), nullptr, 16));
        bytes.push_back(byte);
    }
    return bytes;
}

// Convert raw IEEE P1363 (r || s) signature (64 bytes for P-256) to DER format if needed
static std::vector<uint8_t> raw_rs_to_der(const std::vector<uint8_t>& raw_sig) {
    if (raw_sig.size() != 64) return raw_sig; // Already DER or unknown format

    const uint8_t* r_ptr = raw_sig.data();
    const uint8_t* s_ptr = raw_sig.data() + 32;

    ECDSA_SIG* sig = ECDSA_SIG_new();
    if (!sig) return raw_sig;

    BIGNUM* r = BN_bin2bn(r_ptr, 32, nullptr);
    BIGNUM* s = BN_bin2bn(s_ptr, 32, nullptr);


    if (!r || !s || !ECDSA_SIG_set0(sig, r, s)) {
        if (r) BN_free(r);
        if (s) BN_free(s);
        ECDSA_SIG_free(sig);
        return raw_sig;
    }

    int der_len = i2d_ECDSA_SIG(sig, nullptr);
    if (der_len <= 0) {
        ECDSA_SIG_free(sig);
        return raw_sig;
    }

    std::vector<uint8_t> der(der_len);
    unsigned char* p = der.data();
    i2d_ECDSA_SIG(sig, &p);
    ECDSA_SIG_free(sig);

    return der;
}

bool verify_ecdsa_signature(
    const std::string& message_hash_hex,
    const std::string& signature_b64,
    const std::string& public_key_pem
) {
    if (message_hash_hex.empty() || signature_b64.empty() || public_key_pem.empty()) {
        return false;
    }

    // Decode signature
    std::vector<uint8_t> sig_bytes = base64_decode(signature_b64);
    if (sig_bytes.empty()) {
        return false;
    }

    // Convert raw R+S (64 bytes) to DER if necessary
    if (sig_bytes.size() == 64) {
        sig_bytes = raw_rs_to_der(sig_bytes);
    }

    // Format PEM key if it lacks newlines (e.g. escaped \n)
    std::string formatted_pem = public_key_pem;
    size_t pos = 0;
    while ((pos = formatted_pem.find("\\n", pos)) != std::string::npos) {
        formatted_pem.replace(pos, 2, "\n");
        pos += 1;
    }

    // Load Public Key from PEM
    BIO* key_bio = BIO_new_mem_buf(formatted_pem.data(), static_cast<int>(formatted_pem.size()));
    if (!key_bio) return false;

    EVP_PKEY* pkey = PEM_read_bio_PUBKEY(key_bio, nullptr, nullptr, nullptr);
    BIO_free(key_bio);

    if (!pkey) {
        ERR_clear_error();
        return false;
    }

    // Convert message hash hex to raw bytes
    std::vector<uint8_t> hash_bytes;
    if (message_hash_hex.length() == 64) {
        hash_bytes = hex_to_bytes(message_hash_hex);
    } else {
        hash_bytes = std::vector<uint8_t>(message_hash_hex.begin(), message_hash_hex.end());
    }

    // Verify Signature using EVP_DigestVerify
    EVP_MD_CTX* ctx = EVP_MD_CTX_new();
    if (!ctx) {
        EVP_PKEY_free(pkey);
        return false;
    }

    bool success = false;
    if (EVP_DigestVerifyInit(ctx, nullptr, nullptr, nullptr, pkey) == 1) {
        int res = EVP_DigestVerify(ctx, sig_bytes.data(), sig_bytes.size(), hash_bytes.data(), hash_bytes.size());
        if (res == 1) {
            success = true;
        }
    }

    EVP_MD_CTX_free(ctx);
    EVP_PKEY_free(pkey);
    ERR_clear_error();

    return success;
}

} // namespace etp
