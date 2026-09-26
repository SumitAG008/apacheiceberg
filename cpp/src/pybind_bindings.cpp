#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "etp/route_mutator.hpp"
#include "etp/gateway.hpp"
#include "etp/merkle.hpp"

namespace py = pybind11;

PYBIND11_MODULE(etp_core_cpp, m) {
    m.doc() = "EnergyTrust Protocol (ETP) Native C++20 Core Security & Provenance Engine";

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
}
