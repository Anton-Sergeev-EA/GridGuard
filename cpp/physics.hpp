#pragma once
#include <array>
#include <cmath>
#include <stdexcept>
#include <string>
#include <utility>

namespace gridguard {
class Physics {
    double temperature_ = 45.0;
    double simulation_s_ = 0.0;
    std::string scenario_;

  public:
    explicit Physics(std::string scenario) : scenario_(std::move(scenario)) {
        if (scenario_ != "normal" && scenario_ != "cooling-fault" && scenario_ != "bearing-fault" &&
            scenario_ != "sensor-fault")
            throw std::invalid_argument("unknown synthetic scenario");
    }
    std::array<float, 3> step() {
        const double load = 0.7 + 0.15 * std::sin(simulation_s_ / 60.0);
        const double target = 25.0 + 55.0 * load * load * (scenario_ == "cooling-fault" ? 2 : 1);
        temperature_ += (target - temperature_) * (1.0 - std::exp(-1.0 / 90.0));
        const double vibration = 0.02 + 0.01 * load + 0.002 * std::sin(simulation_s_) +
                                 (scenario_ == "bearing-fault" ? 0.15 : 0.0);
        simulation_s_ += 1.0;
        return {static_cast<float>(temperature_), static_cast<float>(load),
                static_cast<float>(vibration)};
    }
    bool invalid_sensor() const { return scenario_ == "sensor-fault"; }
};
} // namespace gridguard
