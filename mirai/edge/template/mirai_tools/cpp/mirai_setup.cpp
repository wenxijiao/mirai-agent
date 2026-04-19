/**
 * Mirai Edge — C++ tool registration
 *
 * Register your functions with agent.registerTool() and call initMirai()
 * from your main program entry point.
 *
 * Build: add the MiraiSDK directory via CMake add_subdirectory(), then
 * link with target_link_libraries(your_app PRIVATE mirai_sdk).
 *
 * See README.md for full setup instructions.
 */

#include <mirai/mirai_agent.hpp>
#include <string>

// ── Connection (edit here, or set in .env) ──

static const char* MIRAI_CONNECTION_CODE = "mirai-lan_...";  // from `mirai --server`, or mirai_... for relay
static const char* MIRAI_EDGE_NAME = "My C++ App";

mirai::MiraiAgent* initMirai() {
    auto* agent = new mirai::MiraiAgent(MIRAI_CONNECTION_CODE, MIRAI_EDGE_NAME);

    // ── Register tools: name + description + parameters + handler ──

    // agent->registerTool({
    //     .name = "jump",
    //     .description = "Make the character jump",
    //     .parameters = {
    //         {"height", "number", "Jump height in meters"},
    //     },
    //     .handler = [](const mirai::ToolArguments& args) -> std::string {
    //         double h = args.number("height").value_or(1.0);
    //         return "Jumped " + std::to_string(h) + " meters";
    //     },
    // });

    // Dangerous tools: user confirms in the Mirai web UI or `mirai --chat` (not on device):
    // agent->registerTool({
    //     .name = "delete_all",
    //     .description = "Delete all data",
    //     .requireConfirmation = true,
    //     .handler = [](const mirai::ToolArguments&) -> std::string {
    //         return "Deleted everything";
    //     },
    // });

    agent->runInBackground();
    return agent;
}

// Example main (remove or replace with your own):
// int main() {
//     auto* agent = initMirai();
//     // ... your main loop ...
//     // agent->stop();
//     // delete agent;
//     return 0;
// }
