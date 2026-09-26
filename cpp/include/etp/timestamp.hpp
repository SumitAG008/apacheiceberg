#ifndef ETP_TIMESTAMP_HPP
#define ETP_TIMESTAMP_HPP

#include <string>
#include <string_view>

namespace etp {

struct TimestampVerificationResult {
    bool valid{false};
    bool is_simulated{false};
    std::string hashed_message;
    std::string gen_time;
    std::string status_message;
};

// Verifies RFC 3161 timestamp token (real OpenSSL DER token or simulated token) against expected digest
TimestampVerificationResult verify_rfc3161_timestamp(
    std::string_view token_str,
    std::string_view expected_digest_hex
);

} // namespace etp

#endif // ETP_TIMESTAMP_HPP
