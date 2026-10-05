#include "common.hpp"
#include "iec61850_client.h"
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <iostream>
#include <mutex>
#include <random>
#include <thread>

namespace {
struct State {
    std::mutex mutex;
    std::array<double, 3> value{};
    std::array<unsigned, 3> quality{};
    std::array<std::uint64_t, 3> timestamp{};
    std::array<bool, 3> seen{};
    std::atomic<unsigned> reports{0};
    std::atomic<bool> malformed{false};
    std::atomic<std::int64_t> last_report_ms{0};
};
void on_report(void *parameter, ClientReport report) {
    auto &state = *static_cast<State *>(parameter);
    std::lock_guard lock(state.mutex);
    const auto *data = ClientReport_getDataSetValues(report);
    if (!data || MmsValue_getType(data) != MMS_ARRAY || MmsValue_getArraySize(data) != 3) {
        state.malformed = true;
        return;
    }
    for (int i = 0; i < 3; ++i) {
        if (ClientReport_getReasonForInclusion(report, i) == IEC61850_REASON_NOT_INCLUDED)
            continue;
        const auto *object = MmsValue_getElement(data, i);
        if (!object || MmsValue_getType(object) != MMS_STRUCTURE ||
            MmsValue_getArraySize(object) != 3) {
            state.malformed = true;
            return;
        }
        const auto *mag = MmsValue_getElement(object, 0);
        const auto *q = MmsValue_getElement(object, 1);
        const auto *t = MmsValue_getElement(object, 2);
        if (!mag || MmsValue_getType(mag) != MMS_STRUCTURE || MmsValue_getArraySize(mag) != 1 ||
            !q || MmsValue_getType(q) != MMS_BIT_STRING || !t ||
            MmsValue_getType(t) != MMS_UTC_TIME) {
            state.malformed = true;
            return;
        }
        const auto *v = MmsValue_getElement(mag, 0);
        if (!v || MmsValue_getType(v) != MMS_FLOAT || !std::isfinite(MmsValue_toFloat(v))) {
            state.malformed = true;
            return;
        }
        const auto index = static_cast<std::size_t>(i);
        state.value[index] = MmsValue_toFloat(v);
        state.quality[index] = MmsValue_getBitStringAsInteger(q);
        state.timestamp[index] = MmsValue_getUtcTimeInMs(t);
        state.seen[index] = true;
    }
    if (!std::all_of(state.seen.begin(), state.seen.end(), [](bool seen) { return seen; }))
        return;
    std::cout << "{\"asset\":\"transformer-lab-1\",\"source\":\"synthetic\","
                 "\"protocol\":\"iec61850-mms-report\",\"temperature_c\":"
              << state.value[0] << ",\"load_pu\":" << state.value[1]
              << ",\"vibration_g\":" << state.value[2] << ",\"sample_ms\":"
              << *std::max_element(state.timestamp.begin(), state.timestamp.end())
              << ",\"channel_ms\":[" << state.timestamp[0] << ',' << state.timestamp[1] << ','
              << state.timestamp[2] << "],\"quality\":[" << state.quality[0] << ','
              << state.quality[1] << ',' << state.quality[2] << "]}" << std::endl;
    state.last_report_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                               std::chrono::steady_clock::now().time_since_epoch())
                               .count();
    state.reports.fetch_add(1);
}
} // namespace
int main(int argc, char **argv) {
    try {
        if (argc < 3)
            throw std::invalid_argument("usage: gridguard_edge HOST PORT [once]");
        const int tcp_port = port(argv[2]);
        const bool once = argc > 3 && std::string(argv[3]) == "once";
        std::signal(SIGTERM, stop);
        std::signal(SIGINT, stop);
        unsigned backoff = 100;
        std::mt19937 random(std::random_device{}());
        while (running) {
            State state;
            std::unique_ptr<sIedConnection, Deleter<IedConnection_destroy>> connection(
                IedConnection_create());
            IedConnection_setConnectTimeout(connection.get(), 1000);
            IedConnection_setRequestTimeout(connection.get(), 1000);
            IedClientError error;
            IedConnection_connect(connection.get(), &error, argv[1], tcp_port);
            bool subscribed = false;
            if (error == IED_ERROR_OK) {
                const char *reference = "GridGuardLAB/LLN0.RP.Measurements01";
                std::unique_ptr<sClientReportControlBlock,
                                Deleter<ClientReportControlBlock_destroy>>
                    rcb(IedConnection_getRCBValues(connection.get(), &error, reference, nullptr));
                if (error == IED_ERROR_OK && rcb &&
                    ClientReportControlBlock_getConfRev(rcb.get()) == 1) {
                    IedConnection_installReportHandler(connection.get(), reference,
                                                       ClientReportControlBlock_getRptId(rcb.get()),
                                                       on_report, &state);
                    ClientReportControlBlock_setResv(rcb.get(), true);
                    ClientReportControlBlock_setDataSetReference(rcb.get(),
                                                                 "GridGuardLAB/LLN0$Measurements");
                    ClientReportControlBlock_setTrgOps(rcb.get(),
                                                       TRG_OPT_DATA_CHANGED | TRG_OPT_GI);
                    ClientReportControlBlock_setRptEna(rcb.get(), true);
                    ClientReportControlBlock_setGI(rcb.get(), true);
                    IedConnection_setRCBValues(connection.get(), &error, rcb.get(),
                                               RCB_ELEMENT_RESV | RCB_ELEMENT_DATSET |
                                                   RCB_ELEMENT_TRG_OPS | RCB_ELEMENT_RPT_ENA |
                                                   RCB_ELEMENT_GI,
                                               true);
                    subscribed = error == IED_ERROR_OK;
                }
                if (subscribed) {
                    const auto began = std::chrono::steady_clock::now();
                    while (running &&
                           IedConnection_getState(connection.get()) == IED_STATE_CONNECTED &&
                           !state.malformed) {
                        const auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                                                std::chrono::steady_clock::now().time_since_epoch())
                                                .count();
                        if (state.last_report_ms > 0 && now_ms - state.last_report_ms > 5000)
                            break;
                        if (once && state.reports > 0)
                            break;
                        if (std::chrono::steady_clock::now() - began > std::chrono::seconds(5) &&
                            state.reports == 0)
                            break;
                        std::this_thread::sleep_for(std::chrono::milliseconds(20));
                    }
                }
                IedConnection_close(connection.get());
            }
            connection.reset(); // Join receiver before callback state leaves scope.
            if (once)
                return subscribed && state.reports > 0 && !state.malformed ? 0 : 1;
            if (state.reports > 0)
                backoff = 100;
            std::cerr << "{\"event\":\"reconnect\",\"delay_ms\":" << backoff << "}\n";
            const unsigned delay =
                std::uniform_int_distribution<unsigned>(backoff / 2, backoff)(random);
            for (unsigned elapsed = 0; running && elapsed < delay; elapsed += 20)
                std::this_thread::sleep_for(std::chrono::milliseconds(20));
            backoff = std::min(backoff * 2, 5000U);
        }
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
