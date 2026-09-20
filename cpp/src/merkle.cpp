#include "etp/merkle.hpp"
#include <openssl/evp.h>
#include <stdexcept>
#include <iomanip>
#include <sstream>
#include <algorithm>

namespace etp {

namespace {

std::vector<uint8_t> hex_to_bytes(std::string_view hex) {
    std::vector<uint8_t> bytes;
    bytes.reserve(hex.size() / 2);
    for (size_t i = 0; i < hex.size(); i += 2) {
        std::string byte_str(hex.substr(i, 2));
        uint8_t b = static_cast<uint8_t>(std::stoul(byte_str, nullptr, 16));
        bytes.push_back(b);
    }
    return bytes;
}

std::string bytes_to_hex(std::span<const uint8_t> data) {
    std::ostringstream oss;
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

    EVP_MD_CTX* ctx = EVP_MD_CTX_new();
    if (!ctx) {
        throw std::runtime_error("Failed to allocate OpenSSL EVP_MD_CTX");
    }

    if (EVP_DigestInit_ex(ctx, EVP_sha256(), nullptr) != 1 ||
        EVP_DigestUpdate(ctx, &prefix, 1) != 1 ||
        EVP_DigestUpdate(ctx, input1.data(), input1.size()) != 1) {
        EVP_MD_CTX_free(ctx);
        throw std::runtime_error("OpenSSL digest update failed");
    }

    if (!input2.empty()) {
        if (EVP_DigestUpdate(ctx, input2.data(), input2.size()) != 1) {
            EVP_MD_CTX_free(ctx);
            throw std::runtime_error("OpenSSL digest update failed");
        }
    }

    if (EVP_DigestFinal_ex(ctx, digest.data(), &out_len) != 1 || out_len != 32) {
        EVP_MD_CTX_free(ctx);
        throw std::runtime_error("OpenSSL digest final failed");
    }

    EVP_MD_CTX_free(ctx);
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
    auto raw_bytes = hex_to_bytes(hex_hash);
    add_leaf(raw_bytes);
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
