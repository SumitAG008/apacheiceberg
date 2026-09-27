#ifndef ETP_TIMESTAMP_HPP
#define ETP_TIMESTAMP_HPP

#include <string>

namespace etp {

struct TimestampVerifyResult {
    bool valid = false;
    std::string error;
    std::string gen_time;
    std::string policy_oid;
    bool is_simulated = false;
};

/**
 * Verify an RFC 3161 timestamp token or simulated token.
 * @param token_str Base64-encoded DER TS_RESP token or simulated TSA string.
 * @param expected_message_hash_hex 64-char hex expected anchor digest.
 * @param allow_simulated If false (default), simulated tokens are strictly rejected.
 * @param trusted_ca_pem Optional PEM of trusted TSA CA certificates for OpenSSL verification.
 */
TimestampVerifyResult verify_rfc3161_timestamp(
    const std::string& token_str,
    const std::string& expected_message_hash_hex,
    bool allow_simulated = false,
    const std::string& trusted_ca_pem = ""
);

} // namespace etp

#endif // ETP_TIMESTAMP_HPP
