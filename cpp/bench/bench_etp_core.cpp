// Copyright (c) 2026 Meldra AI Ltd. All rights reserved.
// Google Microbenchmarks / Standalone Performance Harness for ETP Native C++ Core

#include "etp/gateway.hpp"
#include "etp/route_mutator.hpp"
#include "etp/merkle.hpp"
#include <chrono>
#include <iostream>
#include <vector>
#include <numeric>
#include <iomanip>

int main() {
    std::cout << "========================================================\n";
    std::cout << " ETP Native C++ Core Performance Benchmark Harness\n";
    std::cout << "========================================================\n\n";

    constexpr size_t ITERATIONS = 100000;

    // 1. Benchmark Canonical Hash Computation
    etp::TelemetryBlock block{
        "MPAN-1200098765432",
        14.205,
        "2026-09-22T12:00:00.000Z",
        "0000000000000000000000000000000000000000000000000000000000000000",
        1024,
        "ECDSA-P256-SHA256-v1",
        "k-bench"
    };

    auto start_hash = std::chrono::high_resolution_clock::now();
    std::string dummy_hash;
    for (size_t i = 0; i < ITERATIONS; ++i) {
        dummy_hash = etp::GatewayEngine::compute_canonical_hash(block);
    }
    auto end_hash = std::chrono::high_resolution_clock::now();
    double elapsed_hash_s = std::chrono::duration<double>(end_hash - start_hash).count();
    double ops_sec_hash = static_cast<double>(ITERATIONS) / elapsed_hash_s;
    double us_per_op_hash = (elapsed_hash_s * 1e6) / static_cast<double>(ITERATIONS);

    std::cout << "[Benchmark 1] GatewayEngine::compute_canonical_hash\n";
    std::cout << "  Iterations: " << ITERATIONS << "\n";
    std::cout << "  Total Time: " << std::fixed << std::setprecision(4) << elapsed_hash_s << " s\n";
    std::cout << "  Throughput: " << std::fixed << std::setprecision(2) << ops_sec_hash << " ops/sec\n";
    std::cout << "  Latency:    " << std::fixed << std::setprecision(3) << us_per_op_hash << " us/op\n\n";

    // 2. Benchmark Route Mutator (HMAC-SHA256)
    etp::RouteMutator mutator("super-secret-etp-key-32-bytes-long", 60);
    auto start_route = std::chrono::high_resolution_clock::now();
    for (size_t i = 0; i < ITERATIONS; ++i) {
        auto routes = mutator.get_routes(1787400000 + i);
        (void)routes;
    }
    auto end_route = std::chrono::high_resolution_clock::now();
    double elapsed_route_s = std::chrono::duration<double>(end_route - start_route).count();
    double ops_sec_route = static_cast<double>(ITERATIONS) / elapsed_route_s;
    double us_per_op_route = (elapsed_route_s * 1e6) / static_cast<double>(ITERATIONS);

    std::cout << "[Benchmark 2] RouteMutator::get_routes (HMAC-SHA256)\n";
    std::cout << "  Iterations: " << ITERATIONS << "\n";
    std::cout << "  Total Time: " << std::fixed << std::setprecision(4) << elapsed_route_s << " s\n";
    std::cout << "  Throughput: " << std::fixed << std::setprecision(2) << ops_sec_route << " ops/sec\n";
    std::cout << "  Latency:    " << std::fixed << std::setprecision(3) << us_per_op_route << " us/op\n\n";

    // 3. Benchmark Merkle Tree Computation (48 readings = 1 daily meter dataset)
    std::vector<std::string> leaf_hashes(48, dummy_hash);
    constexpr size_t MERKLE_ITERATIONS = 10000;
    auto start_merkle = std::chrono::high_resolution_clock::now();
    for (size_t i = 0; i < MERKLE_ITERATIONS; ++i) {
        etp::MerkleTree tree;
        for (const auto& h : leaf_hashes) {
            tree.add_leaf_hex(h);
        }
        std::string root = tree.compute_root();
        (void)root;
    }
    auto end_merkle = std::chrono::high_resolution_clock::now();
    double elapsed_merkle_s = std::chrono::duration<double>(end_merkle - start_merkle).count();
    double ops_sec_merkle = static_cast<double>(MERKLE_ITERATIONS) / elapsed_merkle_s;
    double us_per_op_merkle = (elapsed_merkle_s * 1e6) / static_cast<double>(MERKLE_ITERATIONS);

    std::cout << "[Benchmark 3] MerkleTree::get_root (48 Leaves = Daily Meter Dataset)\n";
    std::cout << "  Iterations: " << MERKLE_ITERATIONS << "\n";
    std::cout << "  Total Time: " << std::fixed << std::setprecision(4) << elapsed_merkle_s << " s\n";
    std::cout << "  Throughput: " << std::fixed << std::setprecision(2) << ops_sec_merkle << " daily trees/sec\n";
    std::cout << "  Latency:    " << std::fixed << std::setprecision(3) << us_per_op_merkle << " us/tree\n\n";

    std::cout << "Benchmark run completed successfully.\n";
    return 0;
}
