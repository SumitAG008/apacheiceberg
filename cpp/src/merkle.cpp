#include "etp/merkle.hpp"
#include <openssl/evp.h>
#include <memory>
#include <stdexcept>
#include <iomanip>
#include <sstream>
#include <algorithm>

namespace etp {

namespace {

using EVP_MD_CTX_ptr = std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)>;

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

std::string bytes_to_hex(std::span<const uint8_t> data) {
    std::ostringstream oss;
    oss.imbue(std::locale::classic());
    for (uint8_t b : data) {
        oss << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(b);
    }
    return oss.str();
}

std::vector<uint8_t> sha256_two_inputs(
    uint8_t prefix,
    std::span<const uint8_t> input1,
    std::span<const uint8_t> input2 = {}
) {
    std::vector<uint8_t> digest(32);
    unsigned int out_len = 0;

    EVP_MD_CTX_ptr ctx(EVP_MD_CTX_new(), EVP_MD_CTX_free);
    if (!ctx) {
        throw std::runtime_error("Failed to allocate OpenSSL EVP_MD_CTX");
    }

    if (EVP_DigestInit_ex(ctx.get(), EVP_sha256(), nullptr) != 1 ||
        EVP_DigestUpdate(ctx.get(), &prefix, 1) != 1 ||
        EVP_DigestUpdate(ctx.get(), input1.data(), input1.size()) != 1) {
        throw std::runtime_error("OpenSSL digest update failed");
    }

    if (!input2.empty()) {
        if (EVP_DigestUpdate(ctx.get(), input2.data(), input2.size()) != 1) {
            throw std::runtime_error("OpenSSL digest update failed");
        }
    }

    if (EVP_DigestFinal_ex(ctx.get(), digest.data(), &out_len) != 1 || out_len != 32) {
        throw std::runtime_error("OpenSSL digest final failed");
    }

    return digest;
}

} // namespace

std::vector<uint8_t> MerkleTree::hash_leaf(std::span<const uint8_t> leaf_data) {
    // Leaf Domain Separation: SHA256(0x00 || leaf_data)
    return sha256_two_inputs(0x00, leaf_data);
}

std::vector<uint8_t> MerkleTree::hash_internal(
    std::span<const uint8_t> left,
    std::span<const uint8_t> right
) {
    // Interior Domain Separation: SHA256(0x01 || left || right)
    return sha256_two_inputs(0x01, left, right);
}

void MerkleTree::add_leaf(std::span<const uint8_t> leaf_data) {
    leaves_.push_back(hash_leaf(leaf_data));
}

void MerkleTree::add_leaf_hex(std::string_view hex_hash) {
    std::vector<uint8_t> raw_bytes;
    if (hex_to_bytes(hex_hash, raw_bytes)) {
        add_leaf(raw_bytes);
    }
}

std::string MerkleTree::compute_root() {
    if (leaves_.empty()) {
        return std::string(64, '0');
    }

    std::vector<std::vector<uint8_t>> current_level = leaves_;

    while (current_level.size() > 1) {
        std::vector<std::vector<uint8_t>> next_level;
        next_level.reserve((current_level.size() + 1) / 2);

        for (size_t i = 0; i < current_level.size(); i += 2) {
            if (i + 1 < current_level.size()) {
                next_level.push_back(hash_internal(current_level[i], current_level[i + 1]));
            } else {
                // Duplicate odd leaf/node
                next_level.push_back(hash_internal(current_level[i], current_level[i]));
            }
        }
        current_level = std::move(next_level);
    }

    return bytes_to_hex(current_level[0]);
}

std::vector<std::string> MerkleTree::get_proof(size_t leaf_index) {
    if (leaf_index >= leaves_.size()) {
        throw std::out_of_range("Leaf index out of bounds");
    }

    std::vector<std::string> proof;
    std::vector<std::vector<uint8_t>> current_level = leaves_;
    size_t idx = leaf_index;

    while (current_level.size() > 1) {
        size_t sibling_idx = (idx % 2 == 0) ? (idx + 1) : (idx - 1);

        if (sibling_idx < current_level.size()) {
            proof.push_back(bytes_to_hex(current_level[sibling_idx]));
        } else {
            // Sibling is itself when odd length
            proof.push_back(bytes_to_hex(current_level[idx]));
        }

        std::vector<std::vector<uint8_t>> next_level;
        next_level.reserve((current_level.size() + 1) / 2);

        for (size_t i = 0; i < current_level.size(); i += 2) {
            if (i + 1 < current_level.size()) {
                next_level.push_back(hash_internal(current_level[i], current_level[i + 1]));
            } else {
                next_level.push_back(hash_internal(current_level[i], current_level[i]));
            }
        }

        current_level = std::move(next_level);
        idx /= 2;
    }

    return proof;
}

} // namespace etp
