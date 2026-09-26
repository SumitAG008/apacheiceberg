#include "etp/route_mutator.hpp"
#include "etp/merkle.hpp"
#include "etp/gateway.hpp"
#include "etp/ecdsa.hpp"
#include "etp/timestamp.hpp"
#include "etp/proof_pack.hpp"
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

std::string compute_sha256_str(std::string_view input) {
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

std::string base64_encode(const std::string& input) {
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

std::string create_simulated_token_for_digest(std::string_view digest_hex, std::string_view timestamp_iso) {
    std::string nonce_hex = "8ae27362aa48ec5f";
    std::string policy = "1.3.6.1.4.1.58432.1.1.simulated";
    std::string sig_payload = "SIMULATED_TSA_V1|policy:" + policy +
        "|digest:sha256:" + std::string(digest_hex) +
        "|nonce:" + nonce_hex +
        "|ts:" + std::string(timestamp_iso);

    std::string sig = compute_sha256_str(sig_payload);
    std::ostringstream json;
    json << "{\"algorithm\":\"sha256\",\"gen_time\":\"" << timestamp_iso << "\","
         << "\"hashed_message\":\"" << digest_hex << "\","
         << "\"nonce\":\"" << nonce_hex << "\","
         << "\"policy\":\"" << policy << "\","
         << "\"signature\":\"" << sig << "\"}";

    return "urn:meldra:simulated-tsa:" + base64_encode(json.str());
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

    // --- 1. Test Standalone ECDSA Signature Verification ---
    auto [pub_pem, priv_pem] = generate_test_keypair_pem();
    std::string sig = sign_block_hash(golden_hash, priv_pem);
    ETP_CHECK(etp::verify_ecdsa_signature(golden_hash, sig, pub_pem), "Valid ECDSA signature failed verification");
    ETP_CHECK(!etp::verify_ecdsa_signature("0000000000000000000000000000000000000000000000000000000000000000", sig, pub_pem), "Bad block hash accepted");
    std::cout << "  ✓ Standalone ECDSA verification passed.\n";

    // --- 2. Test RFC 3161 Timestamp Verification ---
    std::string sim_token = create_simulated_token_for_digest(golden_hash, "2026-09-20T23:00:00.000Z");
    auto ts_res = etp::verify_rfc3161_timestamp(sim_token, golden_hash);
    ETP_CHECK(ts_res.valid, "Simulated RFC 3161 timestamp verification failed");
    ETP_CHECK(ts_res.is_simulated, "Expected is_simulated = true");
    std::cout << "  ✓ RFC 3161 timestamp verification passed.\n";

    // --- 3. Test Unified verify_proof_pack (M2 Offline Verifier) ---
    etp::MerkleTree merkle_3;
    std::string l1 = golden_hash;
    std::string l2 = "0000000000000000000000000000000000000000000000000000000000000002";
    merkle_3.add_leaf_hex(l1);
    merkle_3.add_leaf_hex(l2);
    std::string root_3 = merkle_3.compute_root();
    auto proof0 = merkle_3.get_proof(0);

    std::string anchor_digest = etp::compute_anchor_digest(root_3, 100, 101, 2, -1, 0);
    std::string anchor_sim_token = create_simulated_token_for_digest(anchor_digest, "2026-09-20T23:00:00.000Z");

    etp::ProofPack pack{
        .leaf_hash = l1,
        .mpan = golden_block.mpan,
        .reading_kwh = golden_block.reading_kwh,
        .timestamp = golden_block.timestamp,
        .prev_hash = golden_block.prev_hash,
        .nonce = golden_block.nonce,
        .crypto_suite_id = golden_block.crypto_suite_id,
        .key_id = golden_block.key_id,
        .signature = sig,
        .public_key_pem = pub_pem,
        .proof = proof0,
        .merkle_root = root_3,
        .first_nonce = 100,
        .last_nonce = 101,
        .leaf_count = 2,
        .prev_day_last_nonce = -1,
        .eod_gap = 0,
        .anchor_digest = anchor_digest,
        .timestamp_token = anchor_sim_token
    };

    auto pack_res = etp::verify_proof_pack(pack);
    ETP_CHECK(pack_res.valid, "ProofPack unified verification failed");
    ETP_CHECK(pack_res.overall_status == "VERIFIED", "Status must be VERIFIED");
    ETP_CHECK(pack_res.ecdsa_verified, "ECDSA check failed in proof pack");
    ETP_CHECK(pack_res.merkle_verified, "Merkle check failed in proof pack");
    ETP_CHECK(pack_res.anchor_digest_verified, "Anchor digest check failed in proof pack");
    ETP_CHECK(pack_res.timestamp_verified, "Timestamp check failed in proof pack");
    std::cout << "  ✓ Unified verify_proof_pack (M2) offline check passed.\n";

    std::cout << "\n[SUCCESS] All etp_core C++20 tests passed cleanly!\n";
    OPENSSL_cleanup();
    return 0;
}
