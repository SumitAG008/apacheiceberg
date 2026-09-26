// Copyright (c) 2026 Meldra AI Ltd. All rights reserved.
// Standalone Performance & Throughput Harness for ETP Native C++ Core Engine (CLM-006 Benchmark)

#include "etp/gateway.hpp"
#include "etp/route_mutator.hpp"
#include "etp/merkle.hpp"
#include "etp/ecdsa.hpp"
#include "etp/timestamp.hpp"
#include "etp/proof_pack.hpp"
#include <chrono>
#include <iostream>
#include <vector>
#include <numeric>
#include <iomanip>
#include <openssl/ec.h>
#include <openssl/evp.h>
#include <openssl/pem.h>

using EVP_PKEY_ptr = std::unique_ptr<EVP_PKEY, decltype(&EVP_PKEY_free)>;
using EVP_MD_CTX_ptr = std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)>;
using BIO_ptr = std::unique_ptr<BIO, decltype(&BIO_free)>;

std::pair<std::string, std::string> generate_bench_keypair() {
    EVP_PKEY_CTX* pctx = EVP_PKEY_CTX_new_id(EVP_PKEY_EC, nullptr);
    EVP_PKEY_keygen_init(pctx);
    EVP_PKEY_CTX_set_ec_paramgen_curve_nid(pctx, NID_X9_62_prime256v1);
    EVP_PKEY* raw_key = nullptr;
    EVP_PKEY_keygen(pctx, &raw_key);
    EVP_PKEY_CTX_free(pctx);
    EVP_PKEY_ptr pkey(raw_key, EVP_PKEY_free);

    BIO_ptr pub_bio(BIO_new(BIO_s_mem()), BIO_free);
    PEM_write_bio_PUBKEY(pub_bio.get(), pkey.get());
    char* pub_data = nullptr;
    long pub_len = BIO_get_mem_data(pub_bio.get(), &pub_data);
    std::string pub_pem(pub_data, pub_len);

    BIO_ptr priv_bio(BIO_new(BIO_s_mem()), BIO_free);
    PEM_write_bio_PKCS8PrivateKey(priv_bio.get(), pkey.get(), nullptr, nullptr, 0, nullptr, nullptr);
    char* priv_data = nullptr;
    long priv_len = BIO_get_mem_data(priv_bio.get(), &priv_data);
    std::string priv_pem(priv_data, priv_len);

    return {pub_pem, priv_pem};
}

std::string sign_bench_hash(std::string_view block_hash_hex, std::string_view priv_key_pem) {
    BIO_ptr bio(BIO_new_mem_buf(priv_key_pem.data(), static_cast<int>(priv_key_pem.size())), BIO_free);
    EVP_PKEY_ptr pkey(PEM_read_bio_PrivateKey(bio.get(), nullptr, nullptr, nullptr), EVP_PKEY_free);

    std::vector<uint8_t> hash_bytes;
    for (size_t i = 0; i < block_hash_hex.size(); i += 2) {
        std::string byte_str(block_hash_hex.substr(i, 2));
        hash_bytes.push_back(static_cast<uint8_t>(std::stoul(byte_str, nullptr, 16)));
    }

    EVP_MD_CTX_ptr ctx(EVP_MD_CTX_new(), EVP_MD_CTX_free);
    EVP_DigestSignInit(ctx.get(), nullptr, EVP_sha256(), nullptr, pkey.get());
    EVP_DigestSignUpdate(ctx.get(), hash_bytes.data(), hash_bytes.size());

    size_t sig_len = 0;
    EVP_DigestSignFinal(ctx.get(), nullptr, &sig_len);
    std::vector<uint8_t> sig_bytes(sig_len);
    EVP_DigestSignFinal(ctx.get(), sig_bytes.data(), &sig_len);
    sig_bytes.resize(sig_len);

    std::ostringstream oss;
    oss.imbue(std::locale::classic());
    for (uint8_t b : sig_bytes) {
        oss << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(b);
    }
    return oss.str();
}

std::string compute_sha256_str_bench(std::string_view input) {
    std::vector<uint8_t> hash(32);
    unsigned int out_len = 0;
    EVP_MD_CTX_ptr ctx(EVP_MD_CTX_new(), EVP_MD_CTX_free);
    EVP_DigestInit_ex(ctx.get(), EVP_sha256(), nullptr);
    EVP_DigestUpdate(ctx.get(), input.data(), input.size());
    EVP_DigestFinal_ex(ctx.get(), hash.data(), &out_len);

    std::ostringstream oss;
    oss.imbue(std::locale::classic());
    for (uint8_t b : hash) {
        oss << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(b);
    }
    return oss.str();
}

std::string base64_encode_bench(const std::string& input) {
    BIO_ptr bio(BIO_new(BIO_f_base64()), BIO_free);
    BIO_set_flags(bio.get(), BIO_FLAGS_BASE64_NO_NL);
    BIO* mem = BIO_new(BIO_s_mem());
    bio.reset(BIO_push(bio.release(), mem));
    BIO_write(bio.get(), input.data(), static_cast<int>(input.size()));
    BIO_flush(bio.get());
    char* buffer = nullptr;
    long length = BIO_get_mem_data(bio.get(), &buffer);
    return std::string(buffer, length);
}

std::string create_simulated_bench_token(std::string_view digest_hex, std::string_view timestamp_iso) {
    std::string nonce_hex = "8ae27362aa48ec5f";
    std::string policy = "1.3.6.1.4.1.58432.1.1.simulated";
    std::string sig_payload = "SIMULATED_TSA_V1|policy:" + policy +
        "|digest:sha256:" + std::string(digest_hex) +
        "|nonce:" + nonce_hex +
        "|ts:" + std::string(timestamp_iso);

    std::string sig = compute_sha256_str_bench(sig_payload);
    std::ostringstream json;
    json << "{\"algorithm\":\"sha256\",\"gen_time\":\"" << timestamp_iso << "\","
         << "\"hashed_message\":\"" << digest_hex << "\","
         << "\"nonce\":\"" << nonce_hex << "\","
         << "\"policy\":\"" << policy << "\","
         << "\"signature\":\"" << sig << "\"}";

    return "urn:meldra:simulated-tsa:" + base64_encode_bench(json.str());
}

int main() {
    std::cout << "========================================================\n";
    std::cout << " ETP Native C++ Core Performance Benchmark (CLM-006)\n";
    std::cout << "========================================================\n\n";

    constexpr size_t ITERATIONS = 50000;

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
    std::cout << "  Throughput: " << std::fixed << std::setprecision(2) << ops_sec_hash << " ops/sec\n";
    std::cout << "  Latency:    " << std::fixed << std::setprecision(3) << us_per_op_hash << " us/op\n\n";

    // 2. Benchmark ECDSA Signature Verification
    auto [pub_pem, priv_pem] = generate_bench_keypair();
    std::string bench_sig = sign_bench_hash(dummy_hash, priv_pem);

    constexpr size_t ECDSA_ITERATIONS = 10000;
    auto start_ecdsa = std::chrono::high_resolution_clock::now();
    bool ecdsa_ok = true;
    for (size_t i = 0; i < ECDSA_ITERATIONS; ++i) {
        ecdsa_ok &= etp::verify_ecdsa_signature(dummy_hash, bench_sig, pub_pem);
    }
    auto end_ecdsa = std::chrono::high_resolution_clock::now();
    double elapsed_ecdsa_s = std::chrono::duration<double>(end_ecdsa - start_ecdsa).count();
    double ops_sec_ecdsa = static_cast<double>(ECDSA_ITERATIONS) / elapsed_ecdsa_s;
    double us_per_op_ecdsa = (elapsed_ecdsa_s * 1e6) / static_cast<double>(ECDSA_ITERATIONS);

    std::cout << "[Benchmark 2] Standalone verify_ecdsa_signature (OpenSSL ECDSA P-256)\n";
    std::cout << "  Iterations: " << ECDSA_ITERATIONS << " (Verified: " << (ecdsa_ok ? "YES" : "NO") << ")\n";
    std::cout << "  Throughput: " << std::fixed << std::setprecision(2) << ops_sec_ecdsa << " verifications/sec\n";
    std::cout << "  Latency:    " << std::fixed << std::setprecision(3) << us_per_op_ecdsa << " us/op\n\n";

    // 3. Benchmark Merkle Tree Proof Verification
    etp::MerkleTree tree;
    for (size_t i = 0; i < 48; ++i) {
        tree.add_leaf_hex(dummy_hash);
    }
    std::string root = tree.compute_root();
    auto proof = tree.get_proof(0);

    constexpr size_t MERKLE_ITERATIONS = 50000;
    auto start_merkle = std::chrono::high_resolution_clock::now();
    bool merkle_ok = true;
    for (size_t i = 0; i < MERKLE_ITERATIONS; ++i) {
        merkle_ok &= etp::MerkleTree::verify_proof(dummy_hash, proof, root);
    }
    auto end_merkle = std::chrono::high_resolution_clock::now();
    double elapsed_merkle_s = std::chrono::duration<double>(end_merkle - start_merkle).count();
    double ops_sec_merkle = static_cast<double>(MERKLE_ITERATIONS) / elapsed_merkle_s;
    double us_per_op_merkle = (elapsed_merkle_s * 1e6) / static_cast<double>(MERKLE_ITERATIONS);

    std::cout << "[Benchmark 3] MerkleTree::verify_proof (48-leaf tree path verification)\n";
    std::cout << "  Iterations: " << MERKLE_ITERATIONS << " (Verified: " << (merkle_ok ? "YES" : "NO") << ")\n";
    std::cout << "  Throughput: " << std::fixed << std::setprecision(2) << ops_sec_merkle << " proof_verifications/sec\n";
    std::cout << "  Latency:    " << std::fixed << std::setprecision(3) << us_per_op_merkle << " us/op\n\n";

    // 4. Benchmark RFC 3161 Timestamp Verification
    std::string sim_token = create_simulated_bench_token(dummy_hash, "2026-09-22T12:00:00.000Z");

    constexpr size_t TS_ITERATIONS = 50000;
    auto start_ts = std::chrono::high_resolution_clock::now();
    bool ts_ok = true;
    for (size_t i = 0; i < TS_ITERATIONS; ++i) {
        auto ts_res = etp::verify_rfc3161_timestamp(sim_token, dummy_hash);
        ts_ok &= ts_res.valid;
    }
    auto end_ts = std::chrono::high_resolution_clock::now();
    double elapsed_ts_s = std::chrono::duration<double>(end_ts - start_ts).count();
    double ops_sec_ts = static_cast<double>(TS_ITERATIONS) / elapsed_ts_s;
    double us_per_op_ts = (elapsed_ts_s * 1e6) / static_cast<double>(TS_ITERATIONS);

    std::cout << "[Benchmark 4] verify_rfc3161_timestamp (Timestamp Token Check)\n";
    std::cout << "  Iterations: " << TS_ITERATIONS << " (Verified: " << (ts_ok ? "YES" : "NO") << ")\n";
    std::cout << "  Throughput: " << std::fixed << std::setprecision(2) << ops_sec_ts << " tokens/sec\n";
    std::cout << "  Latency:    " << std::fixed << std::setprecision(3) << us_per_op_ts << " us/op\n\n";

    // 5. Benchmark Unified verify_proof_pack Execution (Full Proof Verification Engine)
    std::string anchor_digest = etp::compute_anchor_digest(root, 100, 147, 48, -1, 0);
    std::string anchor_token = create_simulated_bench_token(anchor_digest, "2026-09-22T12:00:00.000Z");

    etp::ProofPack pack{
        .leaf_hash = dummy_hash,
        .mpan = block.mpan,
        .reading_kwh = block.reading_kwh,
        .timestamp = block.timestamp,
        .prev_hash = block.prev_hash,
        .nonce = block.nonce,
        .crypto_suite_id = block.crypto_suite_id,
        .key_id = block.key_id,
        .signature = bench_sig,
        .public_key_pem = pub_pem,
        .proof = proof,
        .merkle_root = root,
        .first_nonce = 100,
        .last_nonce = 147,
        .leaf_count = 48,
        .prev_day_last_nonce = -1,
        .eod_gap = 0,
        .anchor_digest = anchor_digest,
        .timestamp_token = anchor_token
    };

    constexpr size_t PACK_ITERATIONS = 10000;
    auto start_pack = std::chrono::high_resolution_clock::now();
    bool pack_ok = true;
    for (size_t i = 0; i < PACK_ITERATIONS; ++i) {
        auto pack_res = etp::verify_proof_pack(pack);
        pack_ok &= pack_res.valid;
    }
    auto end_pack = std::chrono::high_resolution_clock::now();
    double elapsed_pack_s = std::chrono::duration<double>(end_pack - start_pack).count();
    double ops_sec_pack = static_cast<double>(PACK_ITERATIONS) / elapsed_pack_s;
    double us_per_op_pack = (elapsed_pack_s * 1e6) / static_cast<double>(PACK_ITERATIONS);

    std::cout << "[Benchmark 5] Unified verify_proof_pack (Merkle + ECDSA + Anchor + Timestamp)\n";
    std::cout << "  Iterations: " << PACK_ITERATIONS << " (Verified: " << (pack_ok ? "YES" : "NO") << ")\n";
    std::cout << "  Throughput: " << std::fixed << std::setprecision(2) << ops_sec_pack << " proof_packs/sec per core\n";
    std::cout << "  Latency:    " << std::fixed << std::setprecision(3) << us_per_op_pack << " us/pack\n\n";

    std::cout << "========================================================\n";
    std::cout << " CLM-006 Empirical Throughput Summary:\n";
    std::cout << "   Merkle Proof Verification: " << std::fixed << std::setprecision(0) << ops_sec_merkle << " ops/sec\n";
    std::cout << "   Timestamp Verification:    " << std::fixed << std::setprecision(0) << ops_sec_ts << " ops/sec\n";
    std::cout << "   ECDSA P-256 Sign Check:    " << std::fixed << std::setprecision(0) << ops_sec_ecdsa << " ops/sec\n";
    std::cout << "   Full Proof Pack Verifier:  " << std::fixed << std::setprecision(0) << ops_sec_pack << " packs/sec per core\n";
    std::cout << "========================================================\n";

    return 0;
}
