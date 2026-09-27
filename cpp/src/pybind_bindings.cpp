#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "etp/gateway.hpp"
#include "etp/route_mutator.hpp"
#include "etp/merkle.hpp"
#include "etp/ecdsa.hpp"
#include "etp/timestamp.hpp"
#include "etp/proof_pack.hpp"

namespace py = pybind11;

PYBIND11_MODULE(etp_core_cpp, m) {
    m.doc() = "ETP C++ Core Native Extension Module";

    // Gateway API
    py::class_<etp::GatewayEngine>(m, "GatewayEngine")
        .def(py::init<int>(), py::arg("batch_size") = 100)
        .def("process_reading", &etp::GatewayEngine::process_reading, py::arg("reading_json"))
        .def("verify_meter_signature", &etp::GatewayEngine::verify_meter_signature, py::arg("reading_json"), py::arg("public_key_pem"));

    // Route Mutator API
    py::class_<etp::RouteMutator>(m, "RouteMutator")
        .def(py::init<>())
        .def("add_route", &etp::RouteMutator::add_route)
        .def("remove_route", &etp::RouteMutator::remove_route)
        .def("mutate_headers", &etp::RouteMutator::mutate_headers);

    // Merkle Engine API
    m.def("compute_merkle_root", &etp::compute_merkle_root, py::arg("hashes"));
    m.def("generate_merkle_proof", &etp::generate_merkle_proof, py::arg("hashes"), py::arg("index"));
    m.def("verify_merkle_proof", &etp::verify_merkle_proof, py::arg("leaf_hash"), py::arg("proof"), py::arg("root"));

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
