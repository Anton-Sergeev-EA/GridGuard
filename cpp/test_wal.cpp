#include "wal.hpp"
#include <chrono>
#include <fstream>
#include <iostream>

void require(bool value) {
    if (!value)
        throw std::runtime_error("WAL contract failed");
}
int main(int argc, char **argv) {
    try {
        require(argc == 2);
        require(gridguard::crc32("123456789") == 0xcbf43926U);
        const auto unique = std::chrono::steady_clock::now().time_since_epoch().count();
        const auto path = std::string(argv[1]) + "." + std::to_string(unique);
        {
            gridguard::Wal wal(path);
            wal.append("{\"value\":123}");
            bool locked = false;
            try {
                gridguard::Wal duplicate(path);
            } catch (const std::exception &) {
                locked = true;
            }
            require(locked);
        }
        struct stat before {};
        require(::stat(path.c_str(), &before) == 0);
        {
            gridguard::File torn(::open(path.c_str(), O_WRONLY | O_APPEND));
            require(::write(torn.get(), "torn", 4) == 4);
        }
        {
            gridguard::Wal recovered(path);
            struct stat after {};
            require(::stat(path.c_str(), &after) == 0 && after.st_size == before.st_size);
            recovered.append("{\"value\":456}");
        }
        std::ifstream records(path);
        std::string first, second;
        std::getline(records, first);
        std::getline(records, second);
        require(first.find("123") != std::string::npos && second.find("456") != std::string::npos);
        std::cout << "WAL reference CRC, exclusive writer and torn-tail recovery passed\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
