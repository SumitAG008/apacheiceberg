#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "etp/gateway.hpp"
#include "etp/route_mutator.hpp"
#include "etp/merkle.hpp"
#include "etp/ecdsa.hpp"
#include "etp/timestamp.hpp"
#include "etp/proof_pack.hpp"
#include <openssl/evp.h>
#include <sstream>
#include <iomanip>

namespace py = pybind11;

PYBIND11_MODULE(etp_core_cpp, m) {
    m.doc() = "ETP C++ Core Native Extension Module";

    // TelemetryBlock struct
    py::class_<etp::TelemetryBlock>(m, "TelemetryBlock")
        .def(py::init<>())
        .def_readwrite("mpan", &etp::TelemetryBlock::mpan)
        .def_readwrite("reading_kwh", &etp::TelemetryBlock::reading_kwh)
        .def_readwrite("timestamp", &etp::TelemetryBlock::timestamp)
        .def_readwrite("prev_hash", &etp::TelemetryBlock::prev_hash)
        .def_readwrite("nonce", &etp::TelemetryBlock::nonce)
        .def_readwrite("crypto_suite_id", &etp::TelemetryBlock::crypto_suite_id)
        .def_readwrite("key_id", &etp::TelemetryBlock::key_id)
        .def_readwrite("block_hash", &etp::TelemetryBlock::block_hash)
        .def_readwrite("signature", &etp::TelemetryBlock::signature);

    // VerificationStatus Enum
    py::enum_<etp::VerificationStatus>(m, "VerificationStatus")
        .value("VERIFIED", etp::VerificationStatus::VERIFIED)
        .value("CHAIN_GAP", etp::VerificationStatus::CHAIN_GAP)
        .value("REPLAY_REJECTED", etp::VerificationStatus::REPLAY_REJECTED)
        .value("EXPIRED_NONCE_REJECTED", etp::VerificationStatus::EXPIRED_NONCE_REJECTED)
        .value("SIGNATURE_FAILED", etp::VerificationStatus::SIGNATURE_FAILED)
        .value("TAMPER_REJECTED", etp::VerificationStatus::TAMPER_REJECTED)
        .value("INVALID_ROUTE", etp::VerificationStatus::INVALID_ROUTE);

    // VerificationResult Struct
    py::class_<etp::VerificationResult>(m, "VerificationResult")
        .def_readwrite("status", &etp::VerificationResult::status)
        .def_readwrite("block_hash", &etp::VerificationResult::block_hash)
        .def_readwrite("error_message", &etp::VerificationResult::error_message)
        .def_readwrite("divert_to_honeypot", &etp::VerificationResult::divert_to_honeypot);

    // Gateway API
    py::class_<etp::GatewayEngine>(m, "GatewayEngine")
        .def(py::init<std::string_view, uint64_t>(), py::arg("secret_key") = "0123456789abcdef0123456789abcdef", py::arg("route_window_seconds") = 60)
        .def_static("compute_canonical_hash", &etp::GatewayEngine::compute_canonical_hash)
        .def("register_meter_public_key", &etp::GatewayEngine::register_meter_public_key, py::arg("mpan"), py::arg("public_key_pem"))
        .def("verify_telemetry_block", &etp::GatewayEngine::verify_telemetry_block, py::arg("route"), py::arg("block"), py::arg("now_epoch_s"));

    // Route Mutator API
    py::class_<etp::RouteMutator>(m, "RouteMutator")
        .def(py::init<std::string_view, uint64_t, std::string_view>(), py::arg("secret_key"), py::arg("window_seconds") = 60, py::arg("base_uri") = "/api/v1/telemetry")
        .def("get_routes", &etp::RouteMutator::get_routes, py::arg("timestamp_sec"))
        .def("validate_route", &etp::RouteMutator::validate_route, py::arg("route"), py::arg("timestamp_sec"));

    // MerkleProofStep struct
    py::class_<etp::MerkleProofStep>(m, "MerkleProofStep")
        .def(py::init<>())
        .def_readwrite("hash", &etp::MerkleProofStep::hash)
        .def_readwrite("is_left", &etp::MerkleProofStep::is_left);

    // MerkleTree class
    py::class_<etp::MerkleTree>(m, "MerkleTree")
        .def(py::init<>())
        .def("add_leaf_hex", &etp::MerkleTree::add_leaf_hex)
        .def("compute_root", &etp::MerkleTree::compute_root)
        .def("get_proof", &etp::MerkleTree::get_proof)
        .def_static("verify_proof", &etp::MerkleTree::verify_proof)
        .def("leaf_count", &etp::MerkleTree::leaf_count)
        .def("clear", &etp::MerkleTree::clear);
    m.def("compute_anchor_digest", [](const std::string& merkle_root, int64_t first_nonce, int64_t last_nonce, int64_t leaf_count, int64_t prev_day_last_nonce, int64_t eod_gap) {
        std::string anchor_payload = merkle_root + "|" + std::to_string(first_nonce) + "|" + std::to_string(last_nonce) + "|" + std::to_string(leaf_count) + "|" + std::to_string(prev_day_last_nonce) + "|" + std::to_string(eod_gap);
        uint8_t hash[32];
        EVP_MD_CTX* ctx = EVP_MD_CTX_new();
        EVP_DigestInit_ex(ctx, EVP_sha256(), nullptr);
        EVP_DigestUpdate(ctx, anchor_payload.data(), anchor_payload.size());
        EVP_DigestFinal_ex(ctx, hash, nullptr);
        EVP_MD_CTX_free(ctx);
        std::stringstream ss;
        for (int i = 0; i < 32; ++i) {
            ss << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(hash[i]);
        }
        return ss.str();
    });


    // ECDSA Signature Verification API
    m.def("verify_ecdsa_signature", &etp::verify_ecdsa_signature,
          py::arg("message_hash_hex"), py::arg("signature_b64"), py::arg("public_key_pem"),
          "Verify secp256r1 ECDSA signature against message hash");

    // RFC 3161 Timestamp Token Verification API
    m.def("verify_rfc3161_timestamp", [](const std::string& token_str, const std::string& expected_hash, bool allow_simulated, const std::string& trusted_ca) {
        auto res = etp::verify_rfc3161_timestamp(token_str, expected_hash, allow_simulated, trusted_ca);
        py::dict d;
        d["valid"] = res.valid;
        d["error"] = res.error;
        d["gen_time"] = res.gen_time;
        d["policy_oid"] = res.policy_oid;
        d["is_simulated"] = res.is_simulated;
        return d;
    }, py::arg("token_str"), py::arg("expected_message_hash_hex"), py::arg("allow_simulated") = false, py::arg("trusted_ca_pem") = "",
       "Verify RFC 3161 timestamp token against expected message digest");

    // Unified ProofPack Verification API
    m.def("verify_proof_pack", [](const py::dict& pack_dict, const std::string& trusted_public_key, bool allow_simulated_tsa, const std::string& trusted_tsa_ca) {
        etp::ProofPack pack;
        if (pack_dict.contains("mpan")) pack.mpan = pack_dict["mpan"].cast<std::string>();
        if (pack_dict.contains("reading_kwh")) pack.reading_kwh = pack_dict["reading_kwh"].cast<double>();
        if (pack_dict.contains("timestamp")) pack.timestamp = pack_dict["timestamp"].cast<std::string>();
        if (pack_dict.contains("prev_hash")) pack.prev_hash = pack_dict["prev_hash"].cast<std::string>();
        if (pack_dict.contains("nonce")) pack.nonce = pack_dict["nonce"].cast<int64_t>();
        if (pack_dict.contains("crypto_suite_id")) pack.crypto_suite_id = pack_dict["crypto_suite_id"].cast<std::string>();
        if (pack_dict.contains("key_id")) pack.key_id = pack_dict["key_id"].cast<std::string>();
        if (pack_dict.contains("signature")) pack.signature = pack_dict["signature"].cast<std::string>();
        if (pack_dict.contains("public_key_pem")) pack.public_key_pem = pack_dict["public_key_pem"].cast<std::string>();
        if (pack_dict.contains("leaf_hash")) pack.leaf_hash = pack_dict["leaf_hash"].cast<std::string>();
        if (pack_dict.contains("merkle_root")) pack.merkle_root = pack_dict["merkle_root"].cast<std::string>();
        if (pack_dict.contains("first_nonce")) pack.first_nonce = pack_dict["first_nonce"].cast<int64_t>();
        if (pack_dict.contains("last_nonce")) pack.last_nonce = pack_dict["last_nonce"].cast<int64_t>();
        if (pack_dict.contains("leaf_count")) pack.leaf_count = pack_dict["leaf_count"].cast<int64_t>();
        if (pack_dict.contains("prev_day_last_nonce")) pack.prev_day_last_nonce = pack_dict["prev_day_last_nonce"].cast<int64_t>();
        if (pack_dict.contains("eod_gap")) pack.eod_gap = pack_dict["eod_gap"].cast<int64_t>();
        if (pack_dict.contains("anchor_digest")) pack.anchor_digest = pack_dict["anchor_digest"].cast<std::string>();
        if (pack_dict.contains("timestamp_token")) pack.timestamp_token = pack_dict["timestamp_token"].cast<std::string>();

        if (pack_dict.contains("proof")) {
            auto proof_list = pack_dict["proof"].cast<py::list>();
            for (auto item : proof_list) {
                auto step_dict = item.cast<py::dict>();
                std::string hash = step_dict["hash"].cast<std::string>();
                bool is_left = step_dict["is_left"].cast<bool>();
                pack.proof.push_back({hash, is_left});
            }
        }

        auto res = etp::verify_proof_pack(pack, trusted_public_key, allow_simulated_tsa, trusted_tsa_ca);

        py::dict out;
        out["verified"] = res.verified;
        out["error_message"] = res.error_message;
        out["merkle_verified"] = res.merkle_verified;
        out["ecdsa_verified"] = res.ecdsa_verified;
        out["anchor_verified"] = res.anchor_verified;
        out["timestamp_verified"] = res.timestamp_verified;
        out["key_registry_verified"] = res.key_registry_verified;
        return out;
    }, py::arg("pack_dict"), py::arg("trusted_public_key_pem") = "", py::arg("allow_simulated_tsa") = false, py::arg("trusted_tsa_ca_pem") = "",
       "Fail-closed verification of proof pack dictionary");
}
