#include <mirai/mirai_agent.h>
#include <mirai/mirai_agent.hpp>

#include <memory>
#include <string>
#include <vector>

extern "C" {

MiraiAgentHandle mirai_agent_create(
    const char* connection_code,
    const char* edge_name,
    const char* env_path
) {
    auto* agent = new mirai::MiraiAgent(
        connection_code ? connection_code : "",
        edge_name ? edge_name : "",
        env_path ? env_path : "",
        std::make_shared<mirai::DefaultTransport>()
    );
    return static_cast<MiraiAgentHandle>(agent);
}

struct CHandlerContext {
    mirai_tool_handler_t handler;
    void* userData;
};

void mirai_agent_register(
    MiraiAgentHandle handle,
    const char* name,
    const char* description,
    const MiraiToolParam* params,
    int param_count,
    mirai_tool_handler_t handler,
    void* user_data
) {
    auto* agent = static_cast<mirai::MiraiAgent*>(handle);

    std::vector<mirai::ToolParameter> parameters;
    for (int i = 0; i < param_count; ++i) {
        parameters.push_back({
            params[i].name ? params[i].name : "",
            params[i].type ? params[i].type : "string",
            params[i].description ? params[i].description : "",
            params[i].required != 0
        });
    }

    // Capture handler + user_data in a shared context
    auto ctx = std::make_shared<CHandlerContext>();
    ctx->handler = handler;
    ctx->userData = user_data;

    agent->registerTool({
        .name = name ? name : "",
        .description = description ? description : "",
        .parameters = std::move(parameters),
        .handler = [ctx](const mirai::ToolArguments& args) -> std::string {
            std::string argsJson = args.rawData().dump();
            const char* result = ctx->handler(argsJson.c_str(), ctx->userData);
            return result ? std::string(result) : "";
        },
    });
}

void mirai_agent_run_in_background(MiraiAgentHandle handle) {
    auto* agent = static_cast<mirai::MiraiAgent*>(handle);
    agent->runInBackground();
}

void mirai_agent_stop(MiraiAgentHandle handle) {
    auto* agent = static_cast<mirai::MiraiAgent*>(handle);
    agent->stop();
}

void mirai_agent_destroy(MiraiAgentHandle handle) {
    auto* agent = static_cast<mirai::MiraiAgent*>(handle);
    delete agent;
}

} // extern "C"
