#ifndef ETP_ECDSA_HPP
#define ETP_ECDSA_HPP

#include <string>

namespace etp {

/**
 * Verify ECDSA (secp256r1/P-256 with SHA-256) signature.
 * @param message_hash_hex 64-character hex SHA-256 hash of the message payload.
 * @param signature_b64 Base64-encoded DER or raw R+S ECDSA signature.
 * @param public_key_pem PEM-formatted EC public key (-----BEGIN PUBLIC KEY----- ...).
 * @return true if valid, false otherwise.
 */
bool verify_ecdsa_signature(
    const std::string& message_hash_hex,
    const std::string& signature_b64,
    const std::string& public_key_pem
);

} // namespace etp

#endif // ETP_ECDSA_HPP
