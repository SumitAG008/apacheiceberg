#ifndef ETP_MERKLE_HPP
#define ETP_MERKLE_HPP

#include <vector>
#include <string>
#include <string_view>
#include <span>
#include <cstdint>

namespace etp {

class MerkleTree {
public:
    MerkleTree() = default;

    void add_leaf(std::span<const uint8_t> leaf_data);
    void add_leaf_hex(std::string_view hex_hash);

    [[nodiscard]] std::string compute_root();
    [[nodiscard]] std::vector<std::string> get_proof(size_t leaf_index);
    [[nodiscard]] size_t leaf_count() const noexcept { return leaves_.size(); }
    void clear() noexcept { leaves_.clear(); }

private:
    [[nodiscard]] static std::vector<uint8_t> hash_leaf(std::span<const uint8_t> leaf_data);
    [[nodiscard]] static std::vector<uint8_t> hash_internal(
        std::span<const uint8_t> left,
        std::span<const uint8_t> right
    );

    std::vector<std::vector<uint8_t>> leaves_;
};

} // namespace etp

#endif // ETP_MERKLE_HPP
