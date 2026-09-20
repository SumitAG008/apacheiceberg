#ifndef ETP_GATEWAY_HPP
#define ETP_GATEWAY_HPP

#include "etp/route_mutator.hpp"
#include <string>
#include <string_view>
#include <vector>
#include <unordered_map>
#include <mutex>
#include <memory>
#include <cstdint>
#include <optional>

namespace etp {

enum class VerificationStatus {
    VERIFIED,
    CHAIN_GAP,
    REPLAY_REJECTED,
    EXPIRED_NONCE_REJECTED,
    SIGNATURE_FAILED,
    TAMPER_REJECTED,
    INVALID_ROUTE
};

struct TelemetryBlock {
    std::string mpan;
    double reading_kwh{0.0};
    std::string timestamp;
    std::string prev_hash;
    uint64_t nonce{0};
    std::string crypto_suite_id;
    std::string key_id;
    std::string block_hash;
    std::string signature;
};

struct VerificationResult {
    VerificationStatus status;
    std::string block_hash;
    std::string error_message;
    bool divert_to_honeypot{false};
};

class SlidingWindowNonceStore {
public:
    explicit SlidingWindowNonceStore(size_t window_size = 1024);

    // Non-committal peek check before expensive ECDSA signature math
    struct CheckResult {
        bool ok{false};
        uint64_t last_nonce{0};
        std::string reason;
    };

    struct CommitResult {
        bool ok{false};
        uint64_t last_nonce{0};
        std::string reason;
    };

    CheckResult check_only(std::string_view mpan, uint64_t incoming_nonce);
    CommitResult commit(
        std::string_view mpan,
        uint64_t incoming_nonce,
        std::string_view incoming_hash,
        std::string_view timestamp
    );

    std::optional<std::string> get_last_hash(std::string_view mpan);

private:
    struct MeterRecord {
        uint64_t last_nonce{0};
        uint64_t seen_bitmap{0}; // 64-bit fast bitmask window
        std::string last_hash;
        std::string updated_at;
    };

    size_t window_size_;
    std::unordered_map<std::string, MeterRecord> store_;
    mutable std::mutex mutex_;
};

class GatewayEngine {
public:
    explicit GatewayEngine(std::string_view secret_key, uint64_t route_window_seconds = 60);

    void register_meter_public_key(std::string_view mpan, std::string_view public_key_pem);
    
    VerificationResult verify_telemetry_block(
        std::string_view route,
        const TelemetryBlock& block,
        uint64_t now_epoch_s
    );

    [[nodiscard]] static std::string compute_canonical_hash(const TelemetryBlock& block);

private:
    [[nodiscard]] bool verify_ecdsa_signature(
        std::string_view mpan,
        std::string_view block_hash_hex,
        std::string_view signature_hex
    ) const;

    RouteMutator route_mutator_;
    SlidingWindowNonceStore nonce_store_;
    std::unordered_map<std::string, std::string> public_key_registry_pem_;
    mutable std::mutex key_registry_mutex_;
};

} // namespace etp

#endif // ETP_GATEWAY_HPP
