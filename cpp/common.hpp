#pragma once
#include <csignal>
#include <memory>
#include <stdexcept>
#include <string>

inline volatile std::sig_atomic_t running = 1;
inline void stop(int) { running = 0; }
inline int port(const char *value) {
    std::size_t end = 0;
    const int number = std::stoi(value, &end);
    if (end != std::string(value).size() || number < 1024 || number > 65535)
        throw std::invalid_argument("port must be 1024..65535");
    return number;
}
template <auto Destroy> struct Deleter {
    template <typename T> void operator()(T *object) const {
        if (object)
            Destroy(object);
    }
};
