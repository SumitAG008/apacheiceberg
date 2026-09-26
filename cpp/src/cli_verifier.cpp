// Copyright (c) 2026 Meldra AI Ltd. All rights reserved.
// Offline Command-Line Verifier for EnergyTrust Protocol (ETP) Proof Packs

#include "etp/proof_pack.hpp"
#include <iostream>
#include <fstream>
#include <sstream>
#include <string>

void print_usage(const char* prog_name) {
    std::cout << "EnergyTrust Protocol (ETP) Native C++20 Offline Verifier (M2)\n";
    std::cout << "Usage: " << prog_name << " [--proof-pack <json_file>] [json_file]\n";
    std::cout << "       If no file is provided, reads JSON proof pack from standard input (stdin).\n\n";
    std::cout << "Options:\n";
    std::cout << "  --proof-pack <file>   Path to JSON proof pack file\n";
    std::cout << "  --help                Display this help message\n";
}

int main(int argc, char* argv[]) {
    std::string filepath;

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--help" || arg == "-h") {
            print_usage(argv[0]);
            return 0;
        } else if (arg == "--proof-pack" && i + 1 < argc) {
            filepath = argv[++i];
        } else if (!arg.empty() && arg[0] != '-') {
            filepath = arg;
        }
    }

    std::string json_content;
    if (!filepath.empty()) {
        std::ifstream ifs(filepath, std::ios::in | std::ios::binary);
        if (!ifs.is_open()) {
            std::cerr << "[ERROR] Unable to open proof pack file: " << filepath << std::endl;
            return 1;
        }
        std::ostringstream oss;
        oss << ifs.rdbuf();
        json_content = oss.str();
    } else {
        // Read from stdin if no file given
        std::ostringstream oss;
        oss << std::cin.rdbuf();
        json_content = oss.str();
    }

    if (json_content.empty()) {
        std::cerr << "[ERROR] Empty input proof pack JSON." << std::endl;
        print_usage(argv[0]);
        return 1;
    }

    etp::ProofPack pack = etp::parse_proof_pack_json(json_content);
    etp::ProofPackResult result = etp::verify_proof_pack(pack);

    std::cout << "========================================================\n";
    std::cout << " ETP Native C++ Proof Pack Verification Result\n";
    std::cout << "========================================================\n";
    std::cout << "Status:                " << result.overall_status << "\n";
    std::cout << "Verified (Overall):    " << (result.valid ? "PASSED ✅" : "FAILED ❌") << "\n";
    std::cout << "ECDSA Signature:       " << (result.ecdsa_verified ? "PASSED" : "N/A or FAILED") << "\n";
    std::cout << "Merkle Proof Path:     " << (result.merkle_verified ? "PASSED" : "N/A or FAILED") << "\n";
    std::cout << "Anchor Commitment:     " << (result.anchor_digest_verified ? "PASSED" : "N/A or FAILED") << "\n";
    std::cout << "RFC 3161 Timestamp:    " << (result.timestamp_verified ? "PASSED" : "N/A or FAILED") << "\n";
    std::cout << "--------------------------------------------------------\n";
    
    if (!result.checks_passed.empty()) {
        std::cout << "Checks Passed:\n";
        for (const auto& c : result.checks_passed) {
            std::cout << "  ✓ " << c << "\n";
        }
    }

    if (!result.errors.empty()) {
        std::cout << "Errors / Failures:\n";
        for (const auto& err : result.errors) {
            std::cout << "  ❌ " << err << "\n";
        }
    }
    std::cout << "--------------------------------------------------------\n";
    std::cout << "JSON Result:\n" << etp::proof_pack_result_to_json(result) << "\n";
    std::cout << "========================================================\n";

    return result.valid ? 0 : 1;
}
