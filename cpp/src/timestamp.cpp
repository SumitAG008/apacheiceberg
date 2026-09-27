#include "etp/timestamp.hpp"
#include <openssl/ts.h>
#include <openssl/bio.h>
#include <openssl/pem.h>
#include <openssl/err.h>
#include <openssl/evp.h>
#include <openssl/x509.h>
#include <openssl/x509v3.h>
#include <vector>
#include <sstream>
#include <iomanip>
#include <algorithm>
#include <iostream>

namespace etp {

static std::vector<uint8_t> base64_decode_ts(const std::string& b64) {
    if (b64.empty()) return {};

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

static std::vector<uint8_t> hex_to_bytes_ts(const std::string& hex) {
    std::vector<uint8_t> bytes;
    bytes.reserve(hex.size() / 2);
    for (size_t i = 0; i < hex.length(); i += 2) {
        std::string byteString = hex.substr(i, 2);
        uint8_t byte = static_cast<uint8_t>(strtol(byteString.c_str(), nullptr, 16));
        bytes.push_back(byte);
    }
    return bytes;
}

TimestampVerifyResult verify_rfc3161_timestamp(
    const std::string& token_str,
    const std::string& expected_message_hash_hex,
    bool allow_simulated,
    const std::string& trusted_ca_pem
) {
    TimestampVerifyResult res;

    if (token_str.empty()) {
        res.error = "Empty timestamp token";
        return res;
    }

    // Check if token is a simulated TSA token
    if (token_str.rfind("urn:meldra:simulated-tsa:", 0) == 0 || token_str.find("is_simulated") != std::string::npos) {
        if (!allow_simulated) {
            res.error = "Simulated TSA tokens are rejected in strict mode (allow_simulated = false). Cryptographic RFC 3161 token required.";
            return res;
        }

        // Handle simulated token (demo mode only)
        // Extract base64 portion after prefix if present
        std::string payload_b64 = token_str;
        size_t prefix_pos = token_str.find("urn:meldra:simulated-tsa:");
        if (prefix_pos != std::string::npos) {
            payload_b64 = token_str.substr(prefix_pos + strlen("urn:meldra:simulated-tsa:"));
        }

        std::vector<uint8_t> decoded = base64_decode_ts(payload_b64);
        std::string decoded_str(decoded.begin(), decoded.end());

        if (decoded_str.find(expected_message_hash_hex) == std::string::npos) {
            res.error = "Simulated timestamp message hash mismatch";
            return res;
        }

        res.valid = true;
        res.is_simulated = true;
        res.gen_time = "2026-09-20T23:00:00.000Z";
        res.policy_oid = "1.3.6.1.4.1.58432.1.1.simulated";
        return res;
    }

    // Decode ASN.1 DER TS_RESP token
    std::vector<uint8_t> der_bytes = base64_decode_ts(token_str);
    if (der_bytes.empty()) {
        res.error = "Failed to base64 decode RFC 3161 timestamp token";
        return res;
    }

    BIO* der_bio = BIO_new_mem_buf(der_bytes.data(), static_cast<int>(der_bytes.size()));
    if (!der_bio) {
        res.error = "Memory BIO allocation failed";
        return res;
    }

    TS_RESP* response = d2i_TS_RESP_bio(der_bio, nullptr);
    BIO_free(der_bio);

    if (!response) {
        ERR_clear_error();
        res.error = "Failed to parse RFC 3161 TS_RESP ASN.1 structure";
        return res;
    }

    // Verify response status
    TS_STATUS_INFO* status_info = TS_RESP_get_status_info(response);
    if (status_info) {
        const ASN1_INTEGER* status = TS_STATUS_INFO_get0_status(status_info);
        long status_val = ASN1_INTEGER_get(status);
        if (status_val != 0) { // TS_STATUS_GRANTED = 0
            TS_RESP_free(response);
            res.error = "TSA response status rejected: " + std::to_string(status_val);
            return res;
        }
    }

    TS_TST_INFO* tst_info = TS_RESP_get_tst_info(response);
    if (!tst_info) {
        TS_RESP_free(response);
        res.error = "Missing TS_TST_INFO structure in RFC 3161 response";
        return res;
    }

    // Verify Message Imprint (Digest)
    TS_MSG_IMPRINT* msg_imprint = TS_TST_INFO_get_msg_imprint(tst_info);
    if (!msg_imprint) {
        TS_RESP_free(response);
        res.error = "Missing message imprint in RFC 3161 TST_INFO";
        return res;
    }

    ASN1_STRING* hashed_msg = TS_MSG_IMPRINT_get_msg(msg_imprint);
    if (!hashed_msg) {
        TS_RESP_free(response);
        res.error = "Missing hashed message in imprint";
        return res;
    }

    const uint8_t* msg_bytes = ASN1_STRING_get0_data(hashed_msg);
    int msg_len = ASN1_STRING_length(hashed_msg);

    std::vector<uint8_t> expected_bytes = hex_to_bytes_ts(expected_message_hash_hex);
    if (msg_len != static_cast<int>(expected_bytes.size()) ||
        memcmp(msg_bytes, expected_bytes.data(), expected_bytes.size()) != 0) {
        TS_RESP_free(response);
        res.error = "RFC 3161 timestamp message digest mismatch with anchor digest";
        return res;
    }

    // Cryptographic Signature Verification of PKCS#7 / CMS Timestamp Token
    PKCS7* token = TS_RESP_get_token(response);
    if (!token) {
        TS_RESP_free(response);
        res.error = "Missing PKCS#7 token in RFC 3161 response";
        return res;
    }

    // Build trusted CA store
    X509_STORE* store = X509_STORE_new();
    if (!trusted_ca_pem.empty()) {
        BIO* ca_bio = BIO_new_mem_buf(trusted_ca_pem.data(), static_cast<int>(trusted_ca_pem.size()));
        if (ca_bio) {
            STACK_OF(X509_INFO)* inf = PEM_X509_INFO_read_bio(ca_bio, nullptr, nullptr, nullptr);
            if (inf) {
                for (int i = 0; i < sk_X509_INFO_num(inf); i++) {
                    X509_INFO* it = sk_X509_INFO_value(inf, i);
                    if (it->x509) {
                        X509_STORE_add_cert(store, it->x509);
                    }
                }
                sk_X509_INFO_pop_free(inf, X509_INFO_free);
            }
            BIO_free(ca_bio);
        }
    } else {
        // Load default system trusted CA roots
        X509_STORE_set_default_paths(store);
    }

    TS_VERIFY_CTX* ctx = TS_VERIFY_CTX_new();
    if (!ctx) {
        X509_STORE_free(store);
        TS_RESP_free(response);
        res.error = "Failed to allocate TS_VERIFY_CTX";
        return res;
    }

    TS_VERIFY_CTX_init(ctx);
    TS_VERIFY_CTX_set_flags(ctx, TS_VERIFY_DATA | TS_VERIFY_SIGNER);
    TS_VERIFY_CTX_set_store(ctx, store);

    int verify_status = TS_RESP_verify_token(ctx, token);

    TS_VERIFY_CTX_free(ctx);
    X509_STORE_free(store);
    TS_RESP_free(response);

    if (verify_status != 1) {
        ERR_clear_error();
        res.error = "RFC 3161 cryptographic signature verification failed against trusted CA store";
        return res;
    }

    res.valid = true;
    res.is_simulated = false;
    return res;
}

} // namespace etp
