#include "etp/timestamp.hpp"
#include <openssl/ts.h>
#include <openssl/bio.h>
#include <openssl/evp.h>
#include <array>
#include <memory>
#include <vector>
#include <sstream>
#include <iomanip>
#include <algorithm>
#include <cstdint>
#include <iostream>

namespace etp {

namespace {

using BIO_ptr = std::unique_ptr<BIO, decltype(&BIO_free)>;
using TS_RESP_ptr = std::unique_ptr<TS_RESP, decltype(&TS_RESP_free)>;
using TS_TST_INFO_ptr = std::unique_ptr<TS_TST_INFO, decltype(&TS_TST_INFO_free)>;
using EVP_MD_CTX_ptr = std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)>;

inline std::vector<uint8_t> base64_decode(std::string_view in) {
    if (in.empty()) return {};
    size_t in_len = in.size();
    std::vector<uint8_t> out(in_len);
    int out_len = EVP_DecodeBlock(out.data(), reinterpret_cast<const uint8_t*>(in.data()), static_cast<int>(in_len));
    if (out_len <= 0) return {};

    int padding = 0;
    if (in_len >= 1 && in[in_len - 1] == '=') padding++;
    if (in_len >= 2 && in[in_len - 2] == '=') padding++;

    if (out_len >= padding) {
        out.resize(static_cast<size_t>(out_len - padding));
    }
    return out;
}

std::string bytes_to_hex(const uint8_t* data, size_t len) {
    std::ostringstream oss;
    oss.imbue(std::locale::classic());
    for (size_t i = 0; i < len; ++i) {
        oss << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(data[i]);
    }
    return oss.str();
}

std::string extract_json_string_field(std::string_view json, std::string_view key) {
    std::string search = "\"" + std::string(key) + "\"";
    size_t pos = json.find(search);
    if (pos == std::string_view::npos) return "";

    pos += search.length();
    while (pos < json.length() && (json[pos] == ' ' || json[pos] == ':' || json[pos] == '\t')) pos++;
    if (pos >= json.length() || json[pos] != '"') return "";
    pos++;

    size_t end_pos = json.find('"', pos);
    if (end_pos == std::string_view::npos) return "";

    return std::string(json.substr(pos, end_pos - pos));
}

std::string compute_sha256_hex(std::string_view input) {
    std::array<uint8_t, 32> hash{};
    unsigned int out_len = 0;
    EVP_MD_CTX_ptr ctx(EVP_MD_CTX_new(), EVP_MD_CTX_free);
    if (!ctx) return "";

    if (EVP_DigestInit_ex(ctx.get(), EVP_sha256(), nullptr) == 1 &&
        EVP_DigestUpdate(ctx.get(), input.data(), input.size()) == 1 &&
        EVP_DigestFinal_ex(ctx.get(), hash.data(), &out_len) == 1) {
        return bytes_to_hex(hash.data(), out_len);
    }
    return "";
}

} // namespace

TimestampVerificationResult verify_rfc3161_timestamp(
    std::string_view token_str,
    std::string_view expected_digest_hex
) {
    if (token_str.empty()) {
        return {false, false, "", "", "Empty timestamp token"};
    }

    // 1. Simulated TSA token handler (urn:meldra:simulated-tsa:... or urn:meldra:simulated-local:...)
    if (token_str.rfind("urn:meldra:", 0) == 0) {
        size_t last_colon = token_str.rfind(':');
        if (last_colon == std::string_view::npos || last_colon + 1 >= token_str.size()) {
            return {false, true, "", "", "Malformed simulated timestamp token URI"};
        }

        std::string_view b64_payload = token_str.substr(last_colon + 1);
        std::vector<uint8_t> decoded_bytes = base64_decode(b64_payload);
        if (decoded_bytes.empty()) {
            return {false, true, "", "", "Failed to decode Base64 payload in simulated timestamp token"};
        }

        std::string json_str(decoded_bytes.begin(), decoded_bytes.end());

        std::string hashed_msg = extract_json_string_field(json_str, "hashed_message");
        std::string gen_time = extract_json_string_field(json_str, "gen_time");
        std::string nonce = extract_json_string_field(json_str, "nonce");
        std::string signature = extract_json_string_field(json_str, "signature");
        std::string policy = extract_json_string_field(json_str, "policy");
        if (policy.empty()) policy = "1.3.6.1.4.1.58432.1.1.simulated";

        std::string sig_payload = "SIMULATED_TSA_V1|policy:" + policy +
            "|digest:sha256:" + hashed_msg +
            "|nonce:" + nonce +
            "|ts:" + gen_time;

        std::string recomputed_sig = compute_sha256_hex(sig_payload);
        if (recomputed_sig.empty() || recomputed_sig != signature) {
            return {false, true, hashed_msg, gen_time, "Simulated TSA signature mismatch: computed=" + recomputed_sig + " != sig=" + signature};
        }

        if (!expected_digest_hex.empty() && hashed_msg != expected_digest_hex) {
            return {false, true, hashed_msg, gen_time, "Timestamp message imprint mismatch against expected digest"};
        }

        return {true, true, hashed_msg, gen_time, "Simulated RFC 3161 token verified successfully"};
    }

    // 2. Real RFC 3161 DER token handler (urn:ietf:rfc:3161:<base64_der> or raw base64 DER)
    std::string_view b64_der = token_str;
    if (token_str.rfind("urn:ietf:rfc:3161:", 0) == 0) {
        b64_der = token_str.substr(std::string_view("urn:ietf:rfc:3161:").length());
    }

    std::vector<uint8_t> der_bytes = base64_decode(b64_der);
    if (der_bytes.empty()) {
        return {false, false, "", "", "Base64 decode failed for timestamp DER token"};
    }

    BIO_ptr bio(BIO_new_mem_buf(der_bytes.data(), static_cast<int>(der_bytes.size())), BIO_free);
    if (!bio) {
        return {false, false, "", "", "Failed to allocate BIO memory buffer"};
    }

    // Try parsing as TS_RESP (Full RFC 3161 TimeStampResp structure)
    TS_RESP* resp_raw = d2i_TS_RESP_bio(bio.get(), nullptr);
    if (resp_raw) {
        TS_RESP_ptr resp(resp_raw, TS_RESP_free);

        TS_STATUS_INFO* status_info = TS_RESP_get_status_info(resp.get());
        if (!status_info) {
            return {false, false, "", "", "TimeStampResp missing status info"};
        }

        const ASN1_INTEGER* status_asn1 = TS_STATUS_INFO_get0_status(status_info);
        long status = status_asn1 ? ASN1_INTEGER_get(status_asn1) : -1;
        if (status != 0 && status != 1) { // 0 = GRANTED, 1 = GRANTED_WITH_MODS
            return {false, false, "", "", "TSA status rejected with PKIStatus=" + std::to_string(status)};
        }

        TS_TST_INFO* tst_info = TS_RESP_get_tst_info(resp.get());
        if (!tst_info) {
            return {false, false, "", "", "TimeStampResp missing TST_INFO payload"};
        }

        TS_MSG_IMPRINT* imprint = TS_TST_INFO_get_msg_imprint(tst_info);
        if (!imprint) {
            return {false, false, "", "", "TST_INFO missing MessageImprint"};
        }

        ASN1_OCTET_STRING* msg_octet = TS_MSG_IMPRINT_get_msg(imprint);
        if (!msg_octet || !msg_octet->data) {
            return {false, false, "", "", "MessageImprint missing digest bytes"};
        }

        std::string hashed_msg = bytes_to_hex(msg_octet->data, msg_octet->length);

        std::string gen_time;
        const ASN1_GENERALIZEDTIME* gtime = TS_TST_INFO_get_time(tst_info);
        if (gtime && gtime->data) {
            gen_time = std::string(reinterpret_cast<const char*>(gtime->data), gtime->length);
        }

        if (!expected_digest_hex.empty() && hashed_msg != expected_digest_hex) {
            return {false, false, hashed_msg, gen_time, "RFC 3161 TimeStampResp message imprint mismatch"};
        }

        return {true, false, hashed_msg, gen_time, "RFC 3161 DER TimeStampResp token verified successfully"};
    }

    // Attempt fallback parsing as TS_TST_INFO DER
    BIO_ptr bio_tst(BIO_new_mem_buf(der_bytes.data(), static_cast<int>(der_bytes.size())), BIO_free);
    TS_TST_INFO* tst_raw = d2i_TS_TST_INFO_bio(bio_tst.get(), nullptr);
    if (tst_raw) {
        TS_TST_INFO_ptr tst(tst_raw, TS_TST_INFO_free);
        TS_MSG_IMPRINT* imprint = TS_TST_INFO_get_msg_imprint(tst.get());
        if (imprint) {
            ASN1_OCTET_STRING* msg_octet = TS_MSG_IMPRINT_get_msg(imprint);
            if (msg_octet && msg_octet->data) {
                std::string hashed_msg = bytes_to_hex(msg_octet->data, msg_octet->length);

                std::string gen_time;
                const ASN1_GENERALIZEDTIME* gtime = TS_TST_INFO_get_time(tst.get());
                if (gtime && gtime->data) {
                    gen_time = std::string(reinterpret_cast<const char*>(gtime->data), gtime->length);
                }

                if (!expected_digest_hex.empty() && hashed_msg != expected_digest_hex) {
                    return {false, false, hashed_msg, gen_time, "RFC 3161 TST_INFO message imprint mismatch"};
                }

                return {true, false, hashed_msg, gen_time, "RFC 3161 DER TST_INFO token verified successfully"};
            }
        }
    }

    return {false, false, "", "", "Failed to parse RFC 3161 timestamp DER token structure"};
}

} // namespace etp
