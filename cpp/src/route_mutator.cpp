#include "etp/route_mutator.hpp"
#include <openssl/evp.h>
#include <openssl/params.h>
#include <openssl/crypto.h>
#include <stdexcept>
#include <array>
#include <cmath>
#include <cstring>
#include <iomanip>
#include <sstream>

namespace etp {

namespace {

// Pack uint64_t to 8 bytes big-endian (matching Python struct.pack(">Q", window))
std::array<uint8_t, 8> pack_uint64_be(uint64_t val) {
    std::array<uint8_t, 8> bytes{};
    for (int i = 7; i >= 0; --i) {
        bytes[i] = static_cast<uint8_t>(val & 0xFF);
        val >>= 8;
    }
    return bytes;
}

// Convert byte array to lower hex string
std::string bytes_to_hex(const uint8_t* data, size_t len) {
    std::ostringstream oss;
    for (size_t i = 0; i < len; ++i) {
        oss << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(data[i]);
    }
    return oss.str();
}

// Constant-time string comparison using OpenSSL CRYPTO_memcmp
bool constant_time_equal(std::string_view a, std::string_view b) {
    if (a.size() != b.size()) {
        return false;
    }
    return CRYPTO_memcmp(a.data(), b.data(), a.size()) == 0;
}

} // namespace

RouteMutator::RouteMutator(
    std::string_view secret_key,
    uint64_t window_seconds,
    std::string_view base_uri
) : secret_key_(secret_key), window_seconds_(window_seconds), base_uri_(base_uri) {
    if (secret_key_.size() < 32) {
        throw std::invalid_argument("Secret key must be at least 32 bytes (256 bits)");
    }
    if (window_seconds_ == 0) {
        throw std::invalid_argument("window_seconds must be > 0");
    }
    // Trim trailing slash from base_uri_
    while (!base_uri_.empty() && base_uri_.back() == '/') {
        base_uri_.pop_back();
    }
}

std::string RouteMutator::scramble_hex(uint64_t window) const {
    auto msg_bytes = pack_uint64_be(window);
    
    // Compute HMAC-SHA256 using OpenSSL 3.0 EVP_Q_mac
    std::array<uint8_t, 32> digest{};
    size_t out_len = 0;

    unsigned char* res = EVP_Q_mac(
        nullptr,                    // OSSL_LIB_CTX
        "HMAC",                     // Algorithm
        nullptr,                    // Property query
        "SHA256",                   // Digest algorithm
        nullptr,                    // Parameters
        secret_key_.data(), secret_key_.size(),
        msg_bytes.data(), msg_bytes.size(),
        digest.data(), digest.size(), &out_len
    );

    if (res == nullptr || out_len != 32) {
        throw std::runtime_error("OpenSSL EVP_Q_mac failed to compute HMAC-SHA256");
    }

    std::string hex_full = bytes_to_hex(digest.data(), digest.size());
    return hex_full.substr(0, 12);
}

RouteWindow RouteMutator::get_routes(uint64_t timestamp_sec) const {
    uint64_t w = timestamp_sec / window_seconds_;

    RouteWindow rw;
    rw.prev_route = base_uri_ + "/rotated_" + scramble_hex(w > 0 ? w - 1 : 0);
    rw.current_route = base_uri_ + "/rotated_" + scramble_hex(w);
    rw.next_route = base_uri_ + "/rotated_" + scramble_hex(w + 1);

    return rw;
}

bool RouteMutator::validate_route(std::string_view route, uint64_t timestamp_sec) const {
    RouteWindow rw = get_routes(timestamp_sec);

    // Constant-time check against all three valid route windows
    bool m1 = constant_time_equal(route, rw.prev_route);
    bool m2 = constant_time_equal(route, rw.current_route);
    bool m3 = constant_time_equal(route, rw.next_route);

    return m1 || m2 || m3;
}

} // namespace etp
