# Edge Tools Guide

Edge tools let the LLM call functions inside your own app or device process. Your app connects to the Mirai server over WebSocket, registers functions as tools, and the AI invokes them as needed.

Mirai loads core server tools on every turn, but Edge tools are dynamically routed by default. All tools registered by connected Edge processes stay in the server registry; for each chat turn Mirai uses the configured embedding model to select the most relevant Edge tool schemas (default: 20) before calling the LLM.

## Quick Start

```bash
cd my_project
mirai --edge
```

Or scaffold a subset of languages (repeat `--lang` or use commas):

```bash
mirai --edge --lang python
mirai --edge --lang rust --lang python
mirai --edge --lang rust,python
mirai --edge --lang swift
mirai --edge --lang typescript
mirai --edge --lang cpp
mirai --edge --lang ue5
mirai --edge --lang go
mirai --edge --lang java
mirai --edge --lang csharp
mirai --edge --lang rust
mirai --edge --lang kotlin
mirai --edge --lang dart
```

This creates `mirai_tools/`, a `.env` file, and language-specific setup templates.

## Next Steps After `mirai --edge`

1. Open `mirai_tools/README.md`
2. Open the README for your language
3. Edit the generated setup file
4. Call the generated initialization function from your real app entry point

`mirai --edge` only scaffolds files. Your own app still needs to call the generated `init_*` / `Init*` function at runtime.

## Tool Routing

Use meaningful Edge names when possible. Names like `Bedroom`, `Memory App`, or `Game NPC` become part of each Edge tool's retrieval document, so a request like "turn on the bedroom light" will prefer light-related tools registered under the bedroom Edge. If the Edge name is generic (for example `device-001`), Mirai still falls back to the function name, description, and parameter descriptions, so good tool descriptions remain important.

When an Edge reconnects, updates, or removes tools, the next chat turn uses the current in-memory registry. There is no persistent per-tool routing file to clean up; embedding vectors are cached in memory only and old deleted tools are no longer referenced.

Configure the per-turn Edge tool budget with:

```bash
mirai --tool-routing --edge-tools-limit 30
```

Or via HTTP:

```bash
curl -X PUT "$MIRAI_SERVER_URL/config/model" \
  -H "Content-Type: application/json" \
  -d '{"edge_tools_enable_dynamic_routing":true,"edge_tools_retrieval_limit":30}'
```

## SDK Overview

Every SDK follows the same core model:

1. Create a `MiraiAgent`
2. Register tools
3. Start the agent in the background
4. Let your main app continue running normally

### Python

```python
from mirai.sdk import MiraiAgent

agent = MiraiAgent(edge_name="My Device")
agent.register(my_function, "What this function does")
agent.run_in_background()
```

Runtime dependency: `websockets`

### TypeScript

```typescript
import { MiraiAgent } from "mirai-sdk";

const agent = new MiraiAgent({ edgeName: "My Web App" });
agent.register({
  name: "my_function",
  description: "What this function does",
  handler: async (args) => myFunction(args),
});
agent.runInBackground();
```

Runtime dependency in Node: `ws`. Browser uses native `WebSocket`.

### C++

```cpp
#include <mirai/mirai_agent.hpp>

mirai::MiraiAgent agent("mirai-lan_...", "My Device");
agent.registerTool({
    .name = "my_function",
    .description = "What this function does",
    .handler = [](auto args) { return myFunction(args); }
});
agent.runInBackground();
```

Build with CMake. Uses IXWebSocket when available.

### Swift

```swift
import MiraiSDK

let agent = MiraiAgent(edgeName: "My iPhone")
agent.register(
    name: "my_function",
    description: "What this function does"
) { args in
    return myFunction(args)
}
agent.runInBackground()
```

Uses SwiftPM. Full package copied into edge workspace.

### Go

```go
agent := mirai_sdk.NewAgent(mirai_sdk.AgentOptions{
    EdgeName: "My Go Service",
})
agent.Register(mirai_sdk.RegisterOptions{
    Name:        "my_function",
    Description: "What this function does",
    Handler:     func(args mirai_sdk.ToolArguments) (string, error) {
        return myFunction(args)
    },
})
agent.RunInBackground()
```

Runtime dependency: `gorilla/websocket`

### Java

```java
var agent = new MiraiAgent("mirai-lan_...", "My Java App");
agent.register(new RegisterOptions()
    .name("my_function")
    .description("What this function does")
    .handler(args -> myFunction(args)));
agent.runInBackground();
```

JDK 11+ native WebSocket. Only external dependency: Gson.

### Rust

```rust
use mirai_sdk::{AgentOptions, MiraiAgent, RegisterOptions, ToolParameter};
use std::sync::Arc;

let agent = MiraiAgent::new(AgentOptions {
    connection_code: None,
    edge_name: Some("My Rust App".into()),
    env_path: None,
});
agent.register(RegisterOptions {
    name: "my_function".into(),
    description: "What this function does".into(),
    parameters: vec![],
    timeout: None,
    require_confirmation: false,
    handler: Arc::new(|args| args.string("q")),
});
agent.run_in_background();
```

Runtime: Tokio + `tokio-tungstenite`. Call `init_mirai()` from `#[tokio::main] async fn main()`.

### Kotlin (JVM)

```kotlin
val agent = MiraiAgent(AgentOptions(edgeName = "My Kotlin App"))
agent.register(
    RegisterOptions(
        name = "my_function",
        description = "What this function does",
        handler = ToolHandler { args -> "ok" },
    ),
)
agent.runInBackground()
```

OkHttp WebSocket + Gson. Sources live under `io.mirai.sdk` in the edge workspace.

### Dart (VM)

```dart
final agent = MiraiAgent(AgentOptions(edgeName: 'My Dart App'));
agent.register(RegisterOptions(
  name: 'my_function',
  description: 'What this function does',
  handler: (args) => 'ok',
));
agent.runInBackground();
```

`web_socket_channel` + `http`. Suitable for CLI/server; Flutter can use the same `mirai_sdk` package.

### UE5

Native Unreal Engine 5 module. See [`mirai/sdk/ue5/`](../mirai/sdk/ue5/) for source.

## Connection

### Connection Resolution

Connection resolution is the same across all SDKs:

1. `MIRAI_RELAY_URL` + `MIRAI_ACCESS_TOKEN` env vars
2. Explicit connection code passed to the SDK
3. `MIRAI_CONNECTION_CODE` env var
4. Legacy `BRAIN_URL` env var (where supported)
5. Local fallback: `ws://127.0.0.1:8000/ws/edge`

### Connection Code Formats

| Format | Example |
|---|---|
| LAN code | `mirai-lan_...` |
| Relay token | `mirai_...` |
| WebSocket URL | `ws://192.168.1.10:8000/ws/edge` |
| HTTP URL | `http://192.168.1.10:8000` |

## Tool Confirmation

Set `require_confirmation=True` (Python) or the equivalent flag in other SDKs for tools with irreversible side effects. The user must approve in the Mirai UI or terminal chat before the tool is invoked.

Tool confirmation policy is persisted to disk when the platform supports it. Browser-based TypeScript keeps it in memory.

## `mirai --edge` Mapping

| Command | Generated result |
|---|---|
| `mirai --edge` | All language templates + SDK copies |
| `mirai --edge --lang python` | Python template + Python SDK copy |
| `mirai --edge --lang swift` | Swift template + full Swift package |
| `mirai --edge --lang typescript` | TS template + SDK tree |
| `mirai --edge --lang cpp` | C/C++ template + CMake tree |
| `mirai --edge --lang ue5` | UE5 template + module source |
| `mirai --edge --lang go` | Go template + local module source |
| `mirai --edge --lang java` | Java template + Maven project |
| `mirai --edge --lang csharp` | C# template + .NET project |
| `mirai --edge --lang rust` | Rust template + `mirai_sdk` crate |
| `mirai --edge --lang kotlin` | Kotlin template + `io.mirai.sdk` sources |
| `mirai --edge --lang dart` | Dart template + `mirai_sdk` package |

## Further Reading

- SDK source and maintainer notes: [`mirai/sdk/README.md`](../mirai/sdk/README.md)
- Edge workspace template: [`mirai/edge/template/mirai_tools/README.md`](../mirai/edge/template/mirai_tools/README.md)
