#pragma once
#include <cerrno>
#include <cstdint>
#include <fcntl.h>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>

namespace gridguard {
class File {
    int fd_;

  public:
    explicit File(int fd) : fd_(fd) {
        if (fd < 0)
            throw std::runtime_error("WAL open failed");
    }
    ~File() { ::close(fd_); }
    File(const File &) = delete;
    File &operator=(const File &) = delete;
    int get() const { return fd_; }
};

inline std::uint32_t crc32(const std::string &value) {
    std::uint32_t crc = 0xffffffffU;
    for (const unsigned char byte : value) {
        crc ^= byte;
        for (int bit = 0; bit < 8; ++bit)
            crc = (crc >> 1U) ^ (0xedb88320U & (0U - (crc & 1U)));
    }
    return ~crc;
}

// Linux/POSIX laboratory WAL. One locked writer, immutable completed records.
class Wal {
    File file_;
    static constexpr off_t capacity = 128 * 1024 * 1024;

  public:
    explicit Wal(const std::string &path)
        : file_(::open(path.c_str(), O_RDWR | O_CREAT | O_APPEND | O_CLOEXEC | O_NOFOLLOW, 0600)) {
        if (::flock(file_.get(), LOCK_EX | LOCK_NB) != 0)
            throw std::runtime_error("WAL already has a writer");
        struct stat status {};
        if (::fstat(file_.get(), &status) != 0 || !S_ISREG(status.st_mode) ||
            status.st_size > capacity)
            throw std::runtime_error("WAL is invalid or exceeds capacity");
        off_t end = status.st_size;
        char byte = 0;
        while (end > 0) {
            if (::pread(file_.get(), &byte, 1, end - 1) != 1)
                throw std::runtime_error("WAL recovery read failed");
            if (byte == '\n')
                break;
            --end;
        }
        if (end != status.st_size && ::ftruncate(file_.get(), end) != 0)
            throw std::runtime_error("WAL torn-tail recovery failed");
        if (::fsync(file_.get()) != 0)
            throw std::runtime_error("WAL recovery sync failed");
        const auto separator = path.find_last_of('/');
        const auto directory = separator == std::string::npos ? "." : path.substr(0, separator);
        File parent(::open(directory.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC));
        if (::fsync(parent.get()) != 0)
            throw std::runtime_error("WAL directory sync failed");
    }

    void append(const std::string &json) {
        if (json.find('\n') != std::string::npos || json.size() > 4096)
            throw std::runtime_error("WAL invalid record");
        std::ostringstream encoded;
        encoded << std::hex << std::setfill('0') << std::setw(8) << crc32(json) << '\t' << json
                << '\n';
        const auto record = encoded.str();
        struct stat status {};
        if (::fstat(file_.get(), &status) != 0 ||
            status.st_size + static_cast<off_t>(record.size()) > capacity)
            throw std::runtime_error("WAL capacity reached");
        std::size_t offset = 0;
        while (offset < record.size()) {
            const auto written =
                ::write(file_.get(), record.data() + offset, record.size() - offset);
            if (written < 0 && errno == EINTR)
                continue;
            if (written <= 0)
                throw std::runtime_error("WAL write failed");
            offset += static_cast<std::size_t>(written);
        }
        if (::fdatasync(file_.get()) != 0)
            throw std::runtime_error("WAL durability sync failed");
    }
};
} // namespace gridguard
