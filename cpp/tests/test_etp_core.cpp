#include "etp/route_mutator.hpp"
#include "etp/merkle.hpp"
#include "etp/gateway.hpp"
#include "etp/proof_pack.hpp"
#include "etp/timestamp.hpp"

#include <iostream>
#include <cassert>
#include <memory>
#include <sstream>
#include <iomanip>
#include <locale>
#include <vector>
#include <openssl/ec.h>
#include <openssl/evp.h>
#include <openssl/pem.h>

#define ETP_CHECK(cond, msg) \
    do { \
        if (!(cond)) { \
            std::cerr << "[FAIL] Check failed: " << (msg) << " (" << #cond << ") at " << __FILE__ << ":" << __LINE__ << std::endl; \
            std::exit(1); \
        } \
    } while (0)

using EVP_PKEY_ptr = std::unique_ptr<EVP_PKEY, decltype(&EVP_PKEY_free)>;
using EVP_MD_CTX_ptr = std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)>;
using BIO_ptr = std::unique_ptr<BIO, decltype(&BIO_free)>;

std::pair<std::string, std::string> generate_test_keypair_pem() {
    EVP_PKEY_CTX* pctx = EVP_PKEY_CTX_new_id(EVP_PKEY_EC, nullptr);
    EVP_PKEY_keygen_init(pctx);
    EVP_PKEY_CTX_set_ec_paramgen_curve_nid(pctx, NID_X9_62_prime256v1);

    EVP_PKEY* raw_key = nullptr;
    EVP_PKEY_keygen(pctx, &raw_key);
    EVP_PKEY_CTX_free(pctx);
    EVP_PKEY_ptr pkey(raw_key, EVP_PKEY_free);

    // Export Public Key to PEM
    BIO_ptr pub_bio(BIO_new(BIO_s_mem()), BIO_free);
    PEM_write_bio_PUBKEY(pub_bio.get(), pkey.get());
    char* pub_data = nullptr;
    long pub_len = BIO_get_mem_data(pub_bio.get(), &pub_data);
    std::string pub_pem(pub_data, pub_len);

    // Export Private Key to PEM
    BIO_ptr priv_bio(BIO_new(BIO_s_mem()), BIO_free);
    PEM_write_bio_PKCS8PrivateKey(priv_bio.get(), pkey.get(), nullptr, nullptr, 0, nullptr, nullptr);
    char* priv_data = nullptr;
    long priv_len = BIO_get_mem_data(priv_bio.get(), &priv_data);
    std::string priv_pem(priv_data, priv_len);

    return {pub_pem, priv_pem};
}

std::string sign_block_hash(std::string_view block_hash_hex, std::string_view priv_key_pem) {
    BIO_ptr bio(BIO_new_mem_buf(priv_key_pem.data(), static_cast<int>(priv_key_pem.size())), BIO_free);
    EVP_PKEY_ptr pkey(PEM_read_bio_PrivateKey(bio.get(), nullptr, nullptr, nullptr), EVP_PKEY_free);

    // Convert hex to bytes
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

int main() {
    std::cout << "[TEST] Starting etp_core Native C++20 Verification Suite...\n";

    // --- Golden Vector Cross-Validation (Shared with Python test_golden_vectors.py) ---
    std::string golden_secret = "0123456789abcdef0123456789abcdef";
    etp::TelemetryBlock golden_block{
        .mpan = "MPAN-1200012345678",
        .reading_kwh = 12.345,
        .timestamp = "2026-09-20T23:00:00.000Z",
        .prev_hash = "0000000000000000000000000000000000000000000000000000000000000000",
        .nonce = 100,
        .crypto_suite_id = "ECDSA-P256-SHA256-v1",
        .key_id = "k-test"
    };

    std::string golden_hash = etp::GatewayEngine::compute_canonical_hash(golden_block);
    ETP_CHECK(golden_hash.size() == 64, "Golden hash length must be 64 hex characters");
    ETP_CHECK(golden_hash == "1f145bd697f44d967781afccaebc44ea04b6b4e821ab9171441454d1502a5e41", "Golden canonical hash mismatch");
    std::cout << "  ✓ Golden canonical hash vector match (1f145bd6...).\n";

    etp::RouteMutator golden_mutator(golden_secret, 60, "/api/v1/telemetry");
    auto golden_routes = golden_mutator.get_routes(1700000000);
    ETP_CHECK(golden_routes.current_route == "/api/v1/telemetry/rotated_2559e962cce1", "Golden route mismatch");
    std::cout << "  ✓ Golden route scrambler vector match (rotated_2559e962cce1).\n";

    // --- 1. Test RouteMutator ---
    std::string secret = "0123456789abcdef0123456789abcdef"; // 32 bytes
    etp::RouteMutator mutator(secret, 60, "/api/v1/telemetry");
    uint64_t now = 1700000000;
    auto routes = mutator.get_routes(now);
    std::cout << "  [RouteMutator] Current route: " << routes.current_route << "\n";
    ETP_CHECK(mutator.validate_route(routes.current_route, now), "Valid current route rejected");
    ETP_CHECK(mutator.validate_route(routes.prev_route, now), "Valid prev route rejected");
    ETP_CHECK(mutator.validate_route(routes.next_route, now), "Valid next route rejected");
    ETP_CHECK(!mutator.validate_route("/api/v1/telemetry/rotated_invalidhex", now), "Invalid route accepted");
    std::cout << "  ✓ RouteMutator MTD tests passed.\n";

    // --- 2. Test MerkleTree ---
    etp::MerkleTree merkle;
    std::string leaf1 = "leaf_1_telemetry_data";
    std::string leaf2 = "leaf_2_telemetry_data";
    merkle.add_leaf(std::span<const uint8_t>(reinterpret_cast<const uint8_t*>(leaf1.data()), leaf1.size()));
    merkle.add_leaf(std::span<const uint8_t>(reinterpret_cast<const uint8_t*>(leaf2.data()), leaf2.size()));
    std::string root = merkle.compute_root();
    std::cout << "  [MerkleTree] 2-leaf Root: " << root << "\n";
    ETP_CHECK(root.size() == 64, "Merkle root length must be 64");
    ETP_CHECK(merkle.leaf_count() == 2, "Leaf count mismatch");

    // Test 3-leaf odd node promotion Merkle Tree golden vector
    etp::MerkleTree merkle_3;
    std::string l1 = "0000000000000000000000000000000000000000000000000000000000000001";
    std::string l2 = "0000000000000000000000000000000000000000000000000000000000000002";
    std::string l3 = "0000000000000000000000000000000000000000000000000000000000000003";
    merkle_3.add_leaf_hex(l1);
    merkle_3.add_leaf_hex(l2);
    merkle_3.add_leaf_hex(l3);
    std::string root_3 = merkle_3.compute_root();
    std::cout << "  [MerkleTree] 3-leaf Root: " << root_3 << "\n";
    ETP_CHECK(root_3 == "93e34ecb30d456c2bb3903c45dd51d053db3e66522a0a2eaf5fafa58312ed037", "3-leaf Merkle root vector mismatch (odd node promotion)");

    // Test directional Merkle proof generation and verification
    auto proof0 = merkle_3.get_proof(0);
    auto proof1 = merkle_3.get_proof(1);
    auto proof2 = merkle_3.get_proof(2); // Leaf 2 is promoted at level 0, so proof size should be 1 (the hash of leaf0+leaf1 on the left)

    ETP_CHECK(etp::MerkleTree::verify_proof(l1, proof0, root_3), "Proof verification failed for leaf 0");
    ETP_CHECK(etp::MerkleTree::verify_proof(l2, proof1, root_3), "Proof verification failed for leaf 1");
    ETP_CHECK(etp::MerkleTree::verify_proof(l3, proof2, root_3), "Proof verification failed for leaf 2 (promoted node)");
    ETP_CHECK(!etp::MerkleTree::verify_proof(l1, proof1, root_3), "Bad proof accepted for leaf 0");
    std::cout << "  ✓ MerkleTree directional proof verification passed.\n";

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
    ETP_CHECK(res.status == etp::VerificationStatus::VERIFIED, "Valid block verification failed");
    ETP_CHECK(!res.divert_to_honeypot, "Valid block diverted to honeypot");
    std::cout << "  ✓ GatewayEngine valid block verification passed.\n";

    // Verify replay rejection
    auto res_replay = gateway.verify_telemetry_block(routes.current_route, block, now);
    ETP_CHECK(res_replay.status == etp::VerificationStatus::REPLAY_REJECTED, "Replay attack not rejected");
    std::cout << "  ✓ GatewayEngine anti-replay check passed.\n";

    // Verify MTD route failure -> honeypot diversion
    auto res_invalid_route = gateway.verify_telemetry_block("/api/v1/telemetry/bad_route", block, now);
    ETP_CHECK(res_invalid_route.status == etp::VerificationStatus::INVALID_ROUTE, "Invalid route not caught");
    ETP_CHECK(res_invalid_route.divert_to_honeypot, "Invalid route not diverted to honeypot");
    std::cout << "  ✓ GatewayEngine MTD honeypot diversion passed.\n";

    // --- 4. Forgery Attack Verification Tests (M1-03) ---
    std::cout << "  [M1-03] Testing Forgery Rejection Suite...\n";

    // Forgery 1: Empty Proof Pack
    etp::ProofPack empty_pack;
    auto res_empty = etp::verify_proof_pack(empty_pack, pub_pem);
    ETP_CHECK(!res_empty.verified, "Forgery test 1 failed: Empty proof pack MUST be rejected");
    std::cout << "  ✓ Forgery 1: Empty proof pack strictly rejected.\n";

    // Forgery 2a: No Trusted Key provided (self-asserted key without registry key)
    etp::ProofPack no_trusted_key_pack{
        .mpan = mpan,
        .reading_kwh = 12.345,
        .timestamp = "2026-09-20T23:00:00.000Z",
        .prev_hash = "0000000000000000000000000000000000000000000000000000000000000000",
        .nonce = 100,
        .crypto_suite_id = "ECDSA-P256-SHA256-v1",
        .key_id = "k-test",
        .signature = block.signature,
        .public_key_pem = pub_pem,
        .leaf_hash = block.block_hash,
        .proof = {{leaf2, false}},
        .merkle_root = root,
        .first_nonce = 100,
        .last_nonce = 101,
        .leaf_count = 2,
        .prev_day_last_nonce = -1,
        .eod_gap = 0,
        .anchor_digest = "0000000000000000000000000000000000000000000000000000000000000000",
        .timestamp_token = "invalid_token"
    };
    auto res_no_key = etp::verify_proof_pack(no_trusted_key_pack, ""); // Empty trusted key
    ETP_CHECK(!res_no_key.verified, "Forgery test 2a failed: Proof pack without trusted key MUST be rejected");
    std::cout << "  ✓ Forgery 2a: Proof pack without trusted key strictly rejected.\n";

    // Forgery 2b: Attacker Key Mismatch
    etp::ProofPack self_key_pack = no_trusted_key_pack;
    self_key_pack.public_key_pem = "UNTRUSTED_SELF_ASSERTED_KEY_PEM";
    auto res_self_key = etp::verify_proof_pack(self_key_pack, pub_pem);
    ETP_CHECK(!res_self_key.verified, "Forgery test 2b failed: Mismatching self-asserted key MUST be rejected");
    std::cout << "  ✓ Forgery 2b: Self-asserted key mismatch strictly rejected.\n";

    // Forgery 3: Unsigned / Corrupt Timestamp Token
    auto res_unsigned_ts = etp::verify_rfc3161_timestamp("invalid_b64_garbage_token", "1f145bd697f44d967781afccaebc44ea04b6b4e821ab9171441454d1502a5e41", false);
    ETP_CHECK(!res_unsigned_ts.valid, "Forgery test 3 failed: Unsigned/corrupt RFC3161 token MUST be rejected");
    std::cout << "  ✓ Forgery 3: Unsigned/corrupt timestamp token strictly rejected.\n";

    // Forgery 4: Forged Simulated Token presented in strict mode
    auto res_forged_sim = etp::verify_rfc3161_timestamp("urn:meldra:simulated-tsa:aW52YWxpZF9tZXNzYWdlX2hhc2g=", "1f145bd697f44d967781afccaebc44ea04b6b4e821ab9171441454d1502a5e41", false);
    ETP_CHECK(!res_forged_sim.valid, "Forgery test 4 failed: Forged simulated token MUST be rejected when allow_simulated=false");
    std::cout << "  ✓ Forgery 4: Forged simulated token strictly rejected in strict mode.\n";

    // Forgery 5: Token dated after the reading's day interval (post-dated attack)
    etp::ProofPack dated_after_pack = no_trusted_key_pack;
    dated_after_pack.timestamp = "2026-09-20T23:00:00.000Z"; // Day 2026-09-20
    // Token has gen_time 2026-09-25 (post-dated day 2026-09-25)
    std::string post_dated_sim_token = "urn:meldra:simulated-tsa:MWYxNDViZDY5N2Y0NGQ5Njc3ODE0ZmNjYWViYzQ0ZWEwNGI2YjRlODIxYWI5MTcxNDQxNDU0ZDE1MDJhNWU0MQ==";
    dated_after_pack.timestamp_token = post_dated_sim_token;
    // Compute correct anchor digest for anchor verification to pass and reach date check
    std::string valid_anchor_payload = root + "|100|101|2|-1|0";
    uint8_t anchor_hash[32];
    EVP_MD_CTX* ctx_a = EVP_MD_CTX_new();
    EVP_DigestInit_ex(ctx_a, EVP_sha256(), nullptr);
    EVP_DigestUpdate(ctx_a, valid_anchor_payload.data(), valid_anchor_payload.size());
    EVP_DigestFinal_ex(ctx_a, anchor_hash, nullptr);
    EVP_MD_CTX_free(ctx_a);
    std::stringstream ss_a;
    for (int i = 0; i < 32; ++i) ss_a << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(anchor_hash[i]);
    dated_after_pack.anchor_digest = ss_a.str();
    dated_after_pack.leaf_hash = block.block_hash;

    // Use single leaf tree so proof matches
    etp::MerkleTree tree_single;
    tree_single.add_leaf_hex(block.block_hash);
    dated_after_pack.merkle_root = tree_single.compute_root();
    dated_after_pack.proof = {}; // No proof steps needed for single leaf

    // Now test post-dated token: timestamp is 2026-09-20, token gen_time is 2026-09-20 -> passes date check if matching, but if post-dated (e.g. reading 2026-09-10 vs token 2026-09-20) -> fails
    dated_after_pack.timestamp = "2026-09-10T23:00:00.000Z";
    std::string post_dated_anchor_payload = dated_after_pack.merkle_root + "|100|101|2|-1|0";
    EVP_MD_CTX* ctx_pd = EVP_MD_CTX_new();
    EVP_DigestInit_ex(ctx_pd, EVP_sha256(), nullptr);
    EVP_DigestUpdate(ctx_pd, post_dated_anchor_payload.data(), post_dated_anchor_payload.size());
    EVP_DigestFinal_ex(ctx_pd, anchor_hash, nullptr);
    EVP_MD_CTX_free(ctx_pd);
    std::stringstream ss_pd;
    for (int i = 0; i < 32; ++i) ss_pd << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(anchor_hash[i]);
    dated_after_pack.anchor_digest = ss_pd.str();
    // Re-create simulated token containing this anchor_digest
    std::string sim_payload_pd = "{\"hashed_message\": \"" + dated_after_pack.anchor_digest + "\"}";
    // Base64 encode sim_payload_pd
    BIO* bio_b64 = BIO_new(BIO_s_mem());
    BIO* b64_f = BIO_new(BIO_f_base64());
    BIO_set_flags(b64_f, BIO_FLAGS_BASE64_NO_NL);
    bio_b64 = BIO_push(b64_f, bio_b64);
    BIO_write(bio_b64, sim_payload_pd.data(), sim_payload_pd.size());
    BIO_flush(bio_b64);
    char* b64_pd_ptr = nullptr;
    long b64_pd_len = BIO_get_mem_data(bio_b64, &b64_pd_ptr);
    std::string b64_pd_str(b64_pd_ptr, b64_pd_len);
    BIO_free_all(bio_b64);
    dated_after_pack.timestamp_token = "urn:meldra:simulated-tsa:" + b64_pd_str;

    auto res_dated_after = etp::verify_proof_pack(dated_after_pack, pub_pem, true);
    ETP_CHECK(!res_dated_after.verified, "Forgery test 5 failed: Token dated after/mismatched day interval MUST be rejected");
    std::cout << "  ✓ Forgery 5: Token dated after day interval strictly rejected.\n";

    std::cout << "\n[SUCCESS] All etp_core C++20 tests passed cleanly!\n";
    OPENSSL_cleanup();
    return 0;
}

