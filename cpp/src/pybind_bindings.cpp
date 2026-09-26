#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "etp/route_mutator.hpp"
#include "etp/gateway.hpp"
#include "etp/merkle.hpp"
#include "etp/ecdsa.hpp"
#include "etp/timestamp.hpp"
#include "etp/proof_pack.hpp"

namespace py = pybind11;

PYBIND11_MODULE(etp_core_cpp, m) {
    m.doc() = "EnergyTrust Protocol (ETP) Native C++20 Core Security & Provenance Engine";

    // --- Standalone ECDSA Verification ---
    m.def("verify_ecdsa_signature", &etp::verify_ecdsa_signature,
          py::arg("block_hash_hex"),
          py::arg("signature_hex"),
          py::arg("public_key_pem"),
          "Verifies ECDSA P-256 signature against block hash hex and public key PEM.");

    // --- Standalone RFC 3161 Timestamp Verification ---
    py::class_<etp::TimestampVerificationResult>(m, "TimestampVerificationResult")
        .def_readwrite("valid", &etp::TimestampVerificationResult::valid)
        .def_readwrite("is_simulated", &etp::TimestampVerificationResult::is_simulated)
        .def_readwrite("hashed_message", &etp::TimestampVerificationResult::hashed_message)
        .def_readwrite("gen_time", &etp::TimestampVerificationResult::gen_time)
        .def_readwrite("status_message", &etp::TimestampVerificationResult::status_message);

    m.def("verify_rfc3161_timestamp", &etp::verify_rfc3161_timestamp,
          py::arg("token_str"),
          py::arg("expected_digest_hex") = "",
          "Verifies RFC 3161 timestamp token (real DER or simulated) against expected digest.");

    // --- RouteMutator Bindings ---
    py::class_<etp::RouteWindow>(m, "RouteWindow")
        .def_readwrite("prev_route", &etp::RouteWindow::prev_route)
        .def_readwrite("current_route", &etp::RouteWindow::current_route)
        .def_readwrite("next_route", &etp::RouteWindow::next_route);

    py::class_<etp::RouteMutator>(m, "RouteMutator")
        .def(py::init<std::string_view, uint64_t, std::string_view>(),
             py::arg("secret_key"),
             py::arg("window_seconds") = 60,
             py::arg("base_uri") = "/api/v1/telemetry")
        .def("get_routes", &etp::RouteMutator::get_routes, py::arg("timestamp_sec"))
        .def("validate_route", &etp::RouteMutator::validate_route, py::arg("route"), py::arg("timestamp_sec"));

    // --- VerificationStatus Enum ---
    py::enum_<etp::VerificationStatus>(m, "VerificationStatus")
        .value("VERIFIED", etp::VerificationStatus::VERIFIED)
        .value("CHAIN_GAP", etp::VerificationStatus::CHAIN_GAP)
        .value("REPLAY_REJECTED", etp::VerificationStatus::REPLAY_REJECTED)
        .value("EXPIRED_NONCE_REJECTED", etp::VerificationStatus::EXPIRED_NONCE_REJECTED)
        .value("SIGNATURE_FAILED", etp::VerificationStatus::SIGNATURE_FAILED)
        .value("TAMPER_REJECTED", etp::VerificationStatus::TAMPER_REJECTED)
        .value("INVALID_ROUTE", etp::VerificationStatus::INVALID_ROUTE);

    // --- TelemetryBlock Binding ---
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

    // --- VerificationResult Binding ---
    py::class_<etp::VerificationResult>(m, "VerificationResult")
        .def_readwrite("status", &etp::VerificationResult::status)
        .def_readwrite("block_hash", &etp::VerificationResult::block_hash)
        .def_readwrite("error_message", &etp::VerificationResult::error_message)
        .def_readwrite("divert_to_honeypot", &etp::VerificationResult::divert_to_honeypot);

    // --- GatewayEngine Binding ---
    py::class_<etp::GatewayEngine>(m, "GatewayEngine")
        .def(py::init<std::string_view, uint64_t>(), py::arg("secret_key"), py::arg("route_window_seconds") = 60)
        .def("register_meter_public_key", &etp::GatewayEngine::register_meter_public_key, py::arg("mpan"), py::arg("public_key_pem"))
        .def("verify_telemetry_block", &etp::GatewayEngine::verify_telemetry_block, py::arg("route"), py::arg("block"), py::arg("now_epoch_s"))
        .def_static("compute_canonical_hash", &etp::GatewayEngine::compute_canonical_hash, py::arg("block"));

    // --- MerkleProofStep Binding ---
    py::class_<etp::MerkleProofStep>(m, "MerkleProofStep")
        .def(py::init<>())
        .def_readwrite("hash", &etp::MerkleProofStep::hash)
        .def_readwrite("is_left", &etp::MerkleProofStep::is_left);

    // --- MerkleTree Binding ---
    py::class_<etp::MerkleTree>(m, "MerkleTree")
        .def(py::init<>())
        .def("add_leaf", [](etp::MerkleTree& tree, py::bytes data) {
            std::string s = data;
            tree.add_leaf(std::span<const uint8_t>(reinterpret_cast<const uint8_t*>(s.data()), s.size()));
        }, py::arg("data"))
        .def("add_leaf_hex", &etp::MerkleTree::add_leaf_hex, py::arg("hex_hash"))
        .def("compute_root", &etp::MerkleTree::compute_root)
        .def("get_proof", &etp::MerkleTree::get_proof, py::arg("leaf_index"))
        .def_static("verify_proof", &etp::MerkleTree::verify_proof, py::arg("leaf_hash_hex"), py::arg("proof"), py::arg("root_hex"))
        .def("leaf_count", &etp::MerkleTree::leaf_count)
        .def("clear", &etp::MerkleTree::clear);

    // --- ProofPack & ProofPackResult Bindings ---
    py::class_<etp::ProofPack>(m, "ProofPack")
        .def(py::init<>())
        .def_readwrite("leaf_hash", &etp::ProofPack::leaf_hash)
        .def_readwrite("mpan", &etp::ProofPack::mpan)
        .def_readwrite("reading_kwh", &etp::ProofPack::reading_kwh)
        .def_readwrite("timestamp", &etp::ProofPack::timestamp)
        .def_readwrite("prev_hash", &etp::ProofPack::prev_hash)
        .def_readwrite("nonce", &etp::ProofPack::nonce)
        .def_readwrite("crypto_suite_id", &etp::ProofPack::crypto_suite_id)
        .def_readwrite("key_id", &etp::ProofPack::key_id)
        .def_readwrite("signature", &etp::ProofPack::signature)
        .def_readwrite("public_key_pem", &etp::ProofPack::public_key_pem)
        .def_readwrite("proof", &etp::ProofPack::proof)
        .def_readwrite("merkle_root", &etp::ProofPack::merkle_root)
        .def_readwrite("first_nonce", &etp::ProofPack::first_nonce)
        .def_readwrite("last_nonce", &etp::ProofPack::last_nonce)
        .def_readwrite("leaf_count", &etp::ProofPack::leaf_count)
        .def_readwrite("prev_day_last_nonce", &etp::ProofPack::prev_day_last_nonce)
        .def_readwrite("eod_gap", &etp::ProofPack::eod_gap)
        .def_readwrite("anchor_digest", &etp::ProofPack::anchor_digest)
        .def_readwrite("timestamp_token", &etp::ProofPack::timestamp_token);

    py::class_<etp::ProofPackResult>(m, "ProofPackResult")
        .def_readwrite("valid", &etp::ProofPackResult::valid)
        .def_readwrite("overall_status", &etp::ProofPackResult::overall_status)
        .def_readwrite("ecdsa_verified", &etp::ProofPackResult::ecdsa_verified)
        .def_readwrite("merkle_verified", &etp::ProofPackResult::merkle_verified)
        .def_readwrite("anchor_digest_verified", &etp::ProofPackResult::anchor_digest_verified)
        .def_readwrite("timestamp_verified", &etp::ProofPackResult::timestamp_verified)
        .def_readwrite("checks_passed", &etp::ProofPackResult::checks_passed)
        .def_readwrite("errors", &etp::ProofPackResult::errors);

    m.def("compute_anchor_digest", &etp::compute_anchor_digest,
          py::arg("merkle_root"),
          py::arg("first_nonce"),
          py::arg("last_nonce"),
          py::arg("leaf_count"),
          py::arg("prev_day_last_nonce"),
          py::arg("eod_gap"),
          "Computes metadata anchor commitment digest SHA-256.");

    m.def("verify_proof_pack", &etp::verify_proof_pack,
          py::arg("pack"),
          "Verifies complete ProofPack covering Merkle proof, ECDSA signature, anchor commitment, and RFC 3161 timestamp.");

    m.def("parse_proof_pack_json", &etp::parse_proof_pack_json,
          py::arg("json_str"),
          "Parses JSON string into a ProofPack object.");

    m.def("proof_pack_result_to_json", &etp::proof_pack_result_to_json,
          py::arg("res"),
          "Serializes ProofPackResult to a JSON string.");
}
