#include "common.hpp"
#include "hal_thread.h"
#include "iec61850_server.h"
#include "physics.hpp"
#include <array>
#include <chrono>
#include <cmath>
#include <iostream>
#include <thread>

int main(int argc, char **argv) {
    try {
        const int tcp_port = argc > 1 ? port(argv[1]) : 8102;
        gridguard::Physics physics(argc > 2 ? argv[2] : "normal");
        std::signal(SIGINT, stop);
        std::signal(SIGTERM, stop);
        std::unique_ptr<IedModel, Deleter<IedModel_destroy>> model(IedModel_create("GridGuard"));
        auto *device = LogicalDevice_create("LAB", model.get());
        auto *lln0 = LogicalNode_create("LLN0", device);
        auto *ggio = LogicalNode_create("GGIO1", device);
        CDC_ENS_create("Mod", reinterpret_cast<ModelNode *>(lln0), 0);
        CDC_ENS_create("Beh", reinterpret_cast<ModelNode *>(lln0), 0);
        std::array<DataAttribute *, 3> values{}, qualities{}, timestamps{};
        auto *dataset = DataSet_create("Measurements", lln0);
        for (std::size_t i = 0; i < values.size(); ++i) {
            const auto name = "AnIn" + std::to_string(i + 1);
            auto *obj = CDC_MV_create(name.c_str(), reinterpret_cast<ModelNode *>(ggio), 0, false);
            values[i] = reinterpret_cast<DataAttribute *>(
                ModelNode_getChild(reinterpret_cast<ModelNode *>(obj), "mag.f"));
            qualities[i] = reinterpret_cast<DataAttribute *>(
                ModelNode_getChild(reinterpret_cast<ModelNode *>(obj), "q"));
            timestamps[i] = reinterpret_cast<DataAttribute *>(
                ModelNode_getChild(reinterpret_cast<ModelNode *>(obj), "t"));
            const auto reference = "GGIO1$MX$" + name;
            DataSetEntry_create(dataset, reference.c_str(), -1, nullptr);
        }
        ReportControlBlock_create(
            "Measurements01", lln0, "GridGuardSynthetic", false, "Measurements", 1,
            TRG_OPT_DATA_CHANGED | TRG_OPT_GI,
            RPT_OPT_SEQ_NUM | RPT_OPT_TIME_STAMP | RPT_OPT_REASON_FOR_INCLUSION, 20, 0);
        std::unique_ptr<sIedServerConfig, Deleter<IedServerConfig_destroy>> config(
            IedServerConfig_create());
        IedServerConfig_enableFileService(config.get(), false);
        IedServerConfig_enableDynamicDataSetService(config.get(), false);
        IedServerConfig_enableLogService(config.get(), false);
        std::unique_ptr<sIedServer, Deleter<IedServer_destroy>> server(
            IedServer_createWithConfig(model.get(), nullptr, config.get()));
        IedServer_setLocalIpAddress(server.get(), "0.0.0.0");
        IedServer_start(server.get(), tcp_port);
        if (!IedServer_isRunning(server.get()))
            throw std::runtime_error("IED listen failed");
        std::cerr << "{\"event\":\"ied_started\",\"source\":\"synthetic\"}\n";
        while (running) {
            const auto reading = physics.step();
            IedServer_lockDataModel(server.get());
            for (std::size_t i = 0; i < values.size(); ++i) {
                IedServer_updateFloatAttributeValue(server.get(), values[i], reading[i]);
                IedServer_updateQuality(
                    server.get(), qualities[i],
                    QUALITY_TEST |
                        (physics.invalid_sensor() && i == 0 ? QUALITY_VALIDITY_INVALID : 0));
                IedServer_updateUTCTimeAttributeValue(server.get(), timestamps[i],
                                                      Hal_getTimeInMs());
            }
            IedServer_unlockDataModel(server.get());
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
        IedServer_stop(server.get());
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
