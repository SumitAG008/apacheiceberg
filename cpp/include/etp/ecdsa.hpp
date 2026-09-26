#ifndef ETP_ECDSA_HPP
#define ETP_ECDSA_HPP

#include <string_view>
#include <string>

namespace etp {

// Verifies an ECDSA P-256 signature against a SHA-256 block hash hex and public key PEM string
bool verify_ecdsa_signature(
    std::string_view block_hash_hex,
    std::string_view signature_hex,
    std::string_view public_key_pem
);

} // namespace etp

#endif // ETP_ECDSA_HPP
