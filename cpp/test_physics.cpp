#include "physics.hpp"
#include <iostream>

int main() {
    try {
        gridguard::Physics normal("normal"), repeat("normal"), cooling("cooling-fault"),
            bearing("bearing-fault"), invalid("sensor-fault");
        for (int i = 0; i < 1000; ++i) {
            const auto n = normal.step(), r = repeat.step(), c = cooling.step(), b = bearing.step();
            if (n != r || n[0] < 25 || n[0] > 65 || n[1] < 0.55F || n[1] > 0.85F || c[0] <= n[0] ||
                b[2] < 0.1F || c[1] != n[1])
                throw std::runtime_error("synthetic physics invariant failed");
        }
        if (!invalid.invalid_sensor() || normal.invalid_sensor())
            throw std::runtime_error("sensor quality scenario failed");
        bool rejected = false;
        try {
            gridguard::Physics unsupported("unsupported");
        } catch (const std::invalid_argument &) {
            rejected = true;
        }
        if (!rejected)
            throw std::runtime_error("unknown scenario accepted");
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
