# Mirai SDKs

This directory holds the **canonical source** for every Mirai edge SDK. `mirai --edge` copies SDK code out of this directory into a self-contained `mirai_tools/` workspace inside the user's project.

> Looking for usage examples? See [`docs/EDGE_TOOLS.md`](../../docs/EDGE_TOOLS.md) for full code samples in each language. This file is the **maintainer-facing** layout overview.

## Who This Is For

- **Mirai users** integrating edge tools: start from `mirai --edge` and then open `mirai_tools/<lang>/README.md`, or read [`docs/EDGE_TOOLS.md`](../../docs/EDGE_TOOLS.md).
- **SDK maintainers**: this directory is the canonical implementation — update SDK logic here first, then let `mirai --edge` copy it into user projects.

## Layout

```text
sdk/
├── README.md
├── __init__.py
├── python/
├── swift/
├── typescript/
├── cpp/
├── ue5/
├── go/
├── java/
├── csharp/
├── rust/
├── kotlin/
└── dart/
```

## Language Overview

| Language | Runtime / build | Main entry | Notes |
|---|---|---|---|
| Python | `pip`, `websockets` | `mirai.sdk.MiraiAgent` | self-contained single-file runtime |
| Swift | SwiftPM / Xcode | `MiraiAgent` | full package copied into edge workspace |
| TypeScript / JavaScript | npm | `MiraiAgent` | isomorphic: browser + Node |
| C / C++ | CMake | `mirai::MiraiAgent` | header-only C++ core + optional C ABI |
| UE5 | UE module | `FMiraiAgent` | native UE5 implementation; **CI does not compile UE5** (requires a local Unreal toolchain) |
| Go | Go modules | `mirai_sdk.NewAgent` | local-module workflow via `replace` |
| Java | Maven | `new MiraiAgent(...)` | JDK 11+ native WebSocket; only external dep is Gson |
| C# | .NET 6+ | `new MiraiAgent(...)` | native `System.Net.WebSockets`, zero external deps |
| Rust | Cargo, Tokio | `MiraiAgent::new` | `tokio-tungstenite`, relay bootstrap via `reqwest` |
| Kotlin | JVM, Gradle | `MiraiAgent(...)` | OkHttp WebSocket + Gson |
| Dart | `dart pub`, VM / Flutter | `MiraiAgent(...)` | `web_socket_channel` + `http` |

## Edge Workspace Targets

When `mirai --edge` runs, code from this tree is copied into the user's project as follows:

| SDK | Edge workspace target |
|---|---|
| Python | `mirai_tools/python/mirai_sdk/` |
| TypeScript | `mirai_tools/typescript/mirai_sdk/` |
| C++ | `mirai_tools/cpp/MiraiSDK/` |
| Swift | `mirai_tools/swift/MiraiSDK/` |
| Go | `mirai_tools/go/mirai_sdk/` (consumed via `replace` in `go.mod`) |
| Java | `mirai_tools/java/mirai_sdk/` |
| C# | `mirai_tools/csharp/mirai_sdk/` |
| Rust | `mirai_tools/rust/mirai_sdk/` |
| Kotlin | `mirai_tools/kotlin/mirai_sdk/` |
| Dart | `mirai_tools/dart/mirai_sdk/` |
| UE5 | `mirai_tools/ue5/MiraiSDK/` |

## Connection Resolution (Cross-SDK Contract)

Every SDK resolves the connection in the same order:

1. `MIRAI_RELAY_URL` + `MIRAI_ACCESS_TOKEN`
2. Explicit connection code passed to the SDK
3. `MIRAI_CONNECTION_CODE`
4. Legacy `BRAIN_URL` (where supported)
5. Local fallback such as `ws://127.0.0.1:8000/ws/edge`

Accepted connection-code shapes: `mirai-lan_…` (LAN), `mirai_…` (relay pairing), `ws://…` / `wss://…`, `http://…` / `https://…`.

Tool confirmation policy is persisted to local disk where the host platform allows it; browser-based TypeScript keeps it in memory.

## Where To Go Next

- End-user docs: [`docs/EDGE_TOOLS.md`](../../docs/EDGE_TOOLS.md), [`docs/TOOL_REGISTRATION.md`](../../docs/TOOL_REGISTRATION.md)
- Edge workspace template: [`mirai/edge/template/mirai_tools/README.md`](../edge/template/mirai_tools/README.md)
