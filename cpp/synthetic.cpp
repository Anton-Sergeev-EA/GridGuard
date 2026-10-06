#include "physics.hpp"
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <string>

int main(int argc, char **argv) {
    try {
        if (argc != 3)
            throw std::invalid_argument("usage: gridguard_synthetic SCENARIO STEPS");
        std::size_t parsed = 0;
        const int steps = std::stoi(argv[2], &parsed);
        if (parsed != std::string(argv[2]).size() || steps < 2 || steps > 100000)
            throw std::invalid_argument("steps must be between 2 and 100000");
        gridguard::Physics physics(argv[1]);
        std::cout << std::setprecision(9);
        for (int i = 0; i < steps; ++i) {
            const auto values = physics.step();
            // Deterministic replay clock: same 10x model/wall-time ratio as the IED.
            const std::int64_t stamp = 1700000000000LL + static_cast<std::int64_t>(i) * 100;
            std::cout << "{\"asset\":\"transformer-lab-1\",\"source\":\"synthetic\","
                         "\"protocol\":\"synthetic-replay\","
                         "\"quality_basis\":\"gateway-normalized\","
                         "\"temperature_c\":"
                      << values[0] << ",\"load_pu\":" << values[1]
                      << ",\"vibration_g\":" << values[2] << ",\"sample_ms\":" << stamp
                      << ",\"channel_ms\":[" << stamp << ',' << stamp << ',' << stamp
                      << "],\"quality\":[" << (physics.invalid_sensor() ? 2049 : 2048)
                      << ",2048,2048]}\n";
        }
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
