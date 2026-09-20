#ifndef ETP_ROUTE_MUTATOR_HPP
#define ETP_ROUTE_MUTATOR_HPP

#include <string>
#include <string_view>
#include <cstdint>

namespace etp {

struct RouteWindow {
    std::string prev_route;
    std::string current_route;
    std::string next_route;
};

class RouteMutator {
public:
    explicit RouteMutator(
        std::string_view secret_key,
        uint64_t window_seconds = 60,
        std::string_view base_uri = "/api/v1/telemetry"
    );

    [[nodiscard]] RouteWindow get_routes(uint64_t timestamp_sec) const;
    [[nodiscard]] bool validate_route(std::string_view route, uint64_t timestamp_sec) const;

private:
    [[nodiscard]] std::string scramble_hex(uint64_t window) const;

    std::string secret_key_;
    uint64_t window_seconds_;
    std::string base_uri_;
};

} // namespace etp

#endif // ETP_ROUTE_MUTATOR_HPP
