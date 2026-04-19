cmake_minimum_required(VERSION 3.14)
project(MiraiSDK VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

option(MIRAI_BUILD_EXAMPLES "Build example programs" OFF)
option(MIRAI_USE_TLS "Enable TLS (wss://) support via IXWebSocket" ON)

include(FetchContent)

# nlohmann/json — header-only JSON library
FetchContent_Declare(
    nlohmann_json
    GIT_REPOSITORY https://github.com/nlohmann/json.git
    GIT_TAG        v3.11.3
    GIT_SHALLOW    TRUE
)
FetchContent_MakeAvailable(nlohmann_json)

# IXWebSocket — used by DefaultTransport in mirai_agent.hpp (FetchContent exposes headers to consumers)
set(USE_TLS ${MIRAI_USE_TLS} CACHE BOOL "" FORCE)
FetchContent_Declare(
    ixwebsocket
    GIT_REPOSITORY https://github.com/machinezone/IXWebSocket.git
    GIT_TAG        v11.4.5
    GIT_SHALLOW    TRUE
)
FetchContent_MakeAvailable(ixwebsocket)

# C++ core is header-only (mirai_agent.hpp). This target links the C ABI shim only.
add_library(mirai_sdk STATIC src/c_api.cpp)

target_include_directories(mirai_sdk
    PUBLIC  ${CMAKE_CURRENT_SOURCE_DIR}/include
)

target_link_libraries(mirai_sdk
    PUBLIC  nlohmann_json::nlohmann_json
            ixwebsocket
)

if(MIRAI_BUILD_EXAMPLES AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/examples/basic_usage.cpp")
    add_executable(mirai_example examples/basic_usage.cpp)
    target_link_libraries(mirai_example PRIVATE mirai_sdk)
endif()
