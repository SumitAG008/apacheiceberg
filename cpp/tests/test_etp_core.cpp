#include "etp/route_mutator.hpp"
#include "etp/merkle.hpp"
#include "etp/gateway.hpp"
#include <iostream>
#include <cassert>
#include <openssl/ec.h>
#include <openssl/evp.h>
#include <openssl/pem.h>

std::pair<std::string, std::string> generate_test_keypair_pem() {
    EVP_PKEY_CTX* pctx = EVP_PKEY_CTX_new_id(EVP_PKEY_EC, nullptr);
    EVP_PKEY_keygen_init(pctx);
    EVP_PKEY_CTX_set_ec_paramgen_curve_name(pctx, NID_X9_62_prime256v1);

    EVP_PKEY* pkey = nullptr;
    EVP_PKEY_keygen(pctx, &pkey);
    EVP_PKEY_CTX_free(pctx);

    // Export Public Key to PEM
    BIO* pub_bio = BIO_new(BIO_s_mem());
    PEM_write_bio_PUBKEY(pub_bio, pkey);
    char* pub_data = nullptr;
    long pub_len = BIO_get_mem_data(pub_bio, &pub_data);
    std::string pub_pem(pub_data, pub_len);
    BIO_free(pub_bio);

    // Export Private Key to PEM
    BIO* priv_bio = BIO_new(BIO_s_mem());
    PEM_write_bio_PKCS8PrivateKey(priv_bio, pkey, nullptr, nullptr, 0, nullptr, nullptr);
    char* priv_data = nullptr;
    long priv_len = BIO_get_mem_data(priv_bio, &priv_data);
    std::string priv_pem(priv_data, priv_len);
    BIO_free(priv_bio);

    EVP_PKEY_free(pkey);
    return {pub_pem, priv_pem};
}

std::string sign_block_hash(std::string_view block_hash_hex, std::string_view priv_key_pem) {
    BIO* bio = BIO_new_mem_buf(priv_key_pem.data(), static_cast<int>(priv_key_pem.size()));
    EVP_PKEY* pkey = PEM_read_bio_PrivateKey(bio, nullptr, nullptr, nullptr);
    BIO_free(bio);

    // Convert hex to bytes
    std::vector<uint8_t> hash_bytes;
    for (size_t i = 0; i < block_hash_hex.size(); i += 2) {
        std::string byte_str(block_hash_hex.substr(i, 2));
        hash_bytes.push_back(static_cast<uint8_t>(std::stoul(byte_str, nullptr, 16)));
    }

    EVP_MD_CTX* ctx = EVP_MD_CTX_new();
    EVP_DigestSignInit(ctx, nullptr, EVP_sha256(), nullptr, pkey);
    EVP_DigestSignUpdate(ctx, hash_bytes.data(), hash_bytes.size());

    size_t sig_len = 0;
    EVP_DigestSignFinal(ctx, nullptr, &sig_len);
    std::vector<uint8_t> sig_bytes(sig_len);
    EVP_DigestSignFinal(ctx, sig_bytes.data(), &sig_len);

    EVP_MD_CTX_free(ctx);
    EVP_PKEY_free(pkey);

    std::ostringstream oss;
    for (uint8_t b : sig_bytes) {
        oss << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(b);
    }
    return oss.str();
}

int main() {
    std::cout << "[TEST] Starting etp_core Native C++20 Verification Suite...\n";

    // --- 1. Test RouteMutator ---
    std::string secret = "0123456789abcdef0123456789abcdef"; // 32 bytes
    etp::RouteMutator mutator(secret, 60, "/api/v1/telemetry");
    uint64_t now = 1700000000;
    auto routes = mutator.get_routes(now);
    std::cout << "  [RouteMutator] Current route: " << routes.current_route << "\n";
    assert(mutator.validate_route(routes.current_route, now));
    assert(mutator.validate_route(routes.prev_route, now));
    assert(mutator.validate_route(routes.next_route, now));
    assert(!mutator.validate_route("/api/v1/telemetry/rotated_invalidhex", now));
    std::cout << "  ✓ RouteMutator MTD tests passed.\n";

    // --- 2. Test MerkleTree ---
    etp::MerkleTree merkle;
    std::string leaf1 = "leaf_1_telemetry_data";
    std::string leaf2 = "leaf_2_telemetry_data";
    merkle.add_leaf(std::span<const uint8_t>(reinterpret_cast<const uint8_t*>(leaf1.data()), leaf1.size()));
    merkle.add_leaf(std::span<const uint8_t>(reinterpret_cast<const uint8_t*>(leaf2.data()), leaf2.size()));
    std::string root = merkle.compute_root();
    std::cout << "  [MerkleTree] Root: " << root << "\n";
    assert(root.size() == 64);
    assert(merkle.leaf_count() == 2);
    std::cout << "  ✓ MerkleTree domain separation tests passed.\n";

    // --- 3. Test GatewayEngine ---
    auto [pub_pem, priv_pem] = generate_test_keypair_pem();
    etp::GatewayEngine gateway(secret, 60);
    std::string mpan = "1012345678901";
    gateway.register_meter_public_key(mpan, pub_pem);

    etp::TelemetryBlock block{
        .mpan = mpan,
        .reading_kwh = 12.345,
        .timestamp = "2026-09-20T23:00:00.000Z",
        .prev_hash = "0000000000000000000000000000000000000000000000000000000000000000",
        .nonce = 100,
        .crypto_suite_id = "ECDSA-P256-SHA256-v1",
        .key_id = "k-test"
    };

    block.block_hash = etp::GatewayEngine::compute_canonical_hash(block);
    block.signature = sign_block_hash(block.block_hash, priv_pem);

    // Verify valid block
    auto res = gateway.verify_telemetry_block(routes.current_route, block, now);
    assert(res.status == etp::VerificationStatus::VERIFIED);
    assert(!res.divert_to_honeypot);
    std::cout << "  ✓ GatewayEngine valid block verification passed.\n";

    // Verify replay rejection
    auto res_replay = gateway.verify_telemetry_block(routes.current_route, block, now);
    assert(res_replay.status == etp::VerificationStatus::REPLAY_REJECTED);
    std::cout << "  ✓ GatewayEngine anti-replay check passed.\n";

    // Verify MTD route failure -> honeypot diversion
    auto res_invalid_route = gateway.verify_telemetry_block("/api/v1/telemetry/bad_route", block, now);
    assert(res_invalid_route.status == etp::VerificationStatus::INVALID_ROUTE);
    assert(res_invalid_route.divert_to_honeypot);
    std::cout << "  ✓ GatewayEngine MTD honeypot diversion passed.\n";

    std::cout << "\n[SUCCESS] All etp_core C++20 tests passed cleanly!\n";
    return 0;
}
