// Copyright (c) 2026 Meldra AI Ltd. All rights reserved.
// libFuzzer target for ETP Native C++ Gateway Engine & Hex Parser

#include "etp/gateway.hpp"
#include "etp/route_mutator.hpp"
#include "etp/merkle.hpp"
#include <cstdint>
#include <cstddef>
#include <string>
#include <string_view>
#include <vector>

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    if (size < 16) {
        return 0;
    }

    std::string_view raw(reinterpret_cast<const char*>(data), size);

    // 1. Fuzz RouteMutator with arbitrary epoch and secret
    std::string secret(raw.substr(0, 8));
    uint64_t epoch = *reinterpret_cast<const uint64_t*>(data);
    etp::RouteMutator mutator(secret, 60);
    auto routes = mutator.generate_route_set(epoch);

    // 2. Fuzz TelemetryBlock canonical hash computation
    etp::TelemetryBlock block;
    block.mpan = std::string(raw.substr(0, size / 4));
    block.reading_kwh = static_cast<double>(size % 1000) / 10.0;
    block.timestamp = std::string(raw.substr(size / 4, size / 4));
    block.prev_hash = std::string(raw.substr(size / 2, size / 4));
    block.nonce = static_cast<uint64_t>(size);
    block.crypto_suite_id = "ECDSA-P256-SHA256-v1";
    block.key_id = "k-fuzz";
    block.signature = std::string(raw.substr((3 * size) / 4));

    std::string hash = etp::GatewayEngine::compute_canonical_hash(block);

    // 3. Fuzz Nonce Store peek and commit
    etp::SlidingWindowNonceStore nonce_store(1024);
    nonce_store.check_only(block.mpan, block.nonce);
    nonce_store.commit(block.mpan, block.nonce, hash, block.timestamp);

    // 4. Fuzz Merkle Tree node hashing & root computation
    std::vector<std::string> leaf_hashes;
    size_t chunk_size = 32;
    for (size_t i = 0; i < size; i += chunk_size) {
        leaf_hashes.push_back(std::string(raw.substr(i, std::min(chunk_size, size - i))));
    }
    if (!leaf_hashes.empty()) {
        etp::MerkleTree tree(leaf_hashes);
        std::string root = tree.get_root();
        (void)root;
    }

    return 0;
}
