#include "etp/proof_pack.hpp"
#include <iostream>
#include <fstream>
#include <sstream>

int main(int argc, char* argv[]) {
    if (argc < 2) {
        std::cerr << "Usage: etp_verifier <proof_pack.json> [--trusted-key <key.pem>] [--allow-simulated] [--trusted-ca <ca.pem>]\n";
        return 1;
    }

    std::string filename = argv[1];
    std::string trusted_key_pem;
    std::string trusted_ca_pem;
    bool allow_simulated = false;

    for (int i = 2; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--trusted-key" && i + 1 < argc) {
            std::ifstream kfile(argv[++i]);
            if (kfile) {
                std::stringstream kbuffer;
                kbuffer << kfile.rdbuf();
                trusted_key_pem = kbuffer.str();
            }
        } else if (arg == "--trusted-ca" && i + 1 < argc) {
            std::ifstream cafile(argv[++i]);
            if (cafile) {
                std::stringstream cabuffer;
                cabuffer << cafile.rdbuf();
                trusted_ca_pem = cabuffer.str();
            }
        } else if (arg == "--allow-simulated") {
            allow_simulated = true;
        }
    }

    std::ifstream file(filename);
    if (!file) {
        std::cerr << "Error: Could not open file " << filename << "\n";
        return 1;
    }

    std::stringstream buffer;
    buffer << file.rdbuf();
    std::string json_str = buffer.str();

    etp::ProofPack pack = etp::parse_proof_pack_json(json_str);
    auto res = etp::verify_proof_pack(pack, trusted_key_pem, allow_simulated, trusted_ca_pem);

    if (res.verified) {
        std::cout << "VERIFIED: Proof pack verification succeeded.\n";
        std::cout << "  Merkle Proof: " << (res.merkle_verified ? "PASSED" : "FAILED") << "\n";
        std::cout << "  Meter Signature: " << (res.ecdsa_verified ? "PASSED" : "FAILED") << "\n";
        std::cout << "  Anchor Digest: " << (res.anchor_verified ? "PASSED" : "FAILED") << "\n";
        std::cout << "  Timestamp Token: " << (res.timestamp_verified ? "PASSED" : "FAILED") << "\n";
        if (res.key_registry_verified) {
            std::cout << "  Key Registry Match: PASSED\n";
        }
        return 0;
    } else {
        std::cerr << "VERIFICATION FAILED: " << res.error_message << "\n";
        return 1;
    }
}
