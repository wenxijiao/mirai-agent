# Mirai SDKs

This directory contains the source of truth for all Mirai edge SDKs.

Every SDK follows the same core model:

1. Create a `MiraiAgent`
2. Register tools
3. Start the agent in the background
4. Let your main app continue running normally

`mirai --edge` copies SDK code out of this directory into a self-contained `mirai_tools/` workspace inside the user's project.

## Who This Is For

- **Mirai users integrating edge tools**: start from `mirai --edge` and then open `mirai_tools/<lang>/README.md`
- **SDK maintainers**: this directory is the canonical implementation

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
| UE5 | UE module | `FMiraiAgent` | native UE5 implementation |
| Go | Go modules | `mirai_sdk.NewAgent` | local-module workflow via `replace` |
| Java | Maven | `new MiraiAgent(...)` | JDK 11+ native WebSocket |
| C# | .NET 6+ | `new MiraiAgent(...)` | native `System.Net.WebSockets`, zero external deps |
| Rust | Cargo, Tokio | `MiraiAgent::new` | `tokio-tungstenite`, relay bootstrap via `reqwest` |
| Kotlin | JVM, Gradle | `MiraiAgent(...)` | OkHttp WebSocket + Gson |
| Dart | `dart pub`, VM / Flutter | `MiraiAgent(...)` | `web_socket_channel` + `http` |

## Quick Start by Language

### Python

```python
from mirai.sdk import MiraiAgent

agent = MiraiAgent(edge_name="My Device")

def greet(name: str) -> str:
    """Greet someone by name.

    Args:
        name: The person to greet.
    """
    return f"Hello, {name}!"

agent.register(greet, "Greet someone by name")
agent.run_in_background()

# ... your main app continues here ...
```

- Runtime dependency: `websockets`
- Edge workspace target: `mirai_tools/python/mirai_sdk/`

Or use the shorthand top-level API:

```python
import mirai

mirai.register(greet, "Greet someone by name")
mirai.run()
```

### TypeScript

```typescript
import { MiraiAgent } from "mirai-sdk";

const agent = new MiraiAgent({ edgeName: "My Web App" });

agent.register({
  name: "greet",
  description: "Greet someone by name",
  parameters: [{ name: "name", type: "string", description: "Person to greet" }],
  handler: async (args) => `Hello, ${args.name}!`,
});

agent.runInBackground();
```

- Runtime dependency in Node: `ws`. Browser uses native `WebSocket`.
- Edge workspace target: `mirai_tools/typescript/mirai_sdk/`

### C++

```cpp
#include <mirai/mirai_agent.hpp>

int main() {
    mirai::MiraiAgent agent("mirai-lan_...", "My Device");

    agent.registerTool({
        .name = "greet",
        .description = "Greet someone by name",
        .parameters = {{"name", "string", "Person to greet"}},
        .handler = [](mirai::ToolArguments args) -> std::string {
            return "Hello, " + args.getString("name", "World") + "!";
        }
    });

    agent.runInBackground();

    // ... your main loop ...
}
```

- Header-only C++ core (`mirai_agent.hpp`) + optional C ABI (`mirai_agent.h`)
- `IMiraiTransport` allows custom transports; `DefaultTransport` uses IXWebSocket
- Edge workspace target: `mirai_tools/cpp/MiraiSDK/`

### Swift

```swift
import MiraiSDK

let agent = MiraiAgent(edgeName: "My iPhone")

agent.register(
    name: "greet",
    description: "Greet someone by name",
    parameters: [
        .init("name", type: .string, description: "Person to greet"),
    ]
) { args in
    let name = args.string("name") ?? "World"
    return "Hello, \(name)!"
}

agent.runInBackground()
```

- Product: `MiraiSDK` (SwiftPM)
- Edge workspace target: `mirai_tools/swift/MiraiSDK/`

### Go

```go
package main

import "mirai_sdk"

func main() {
    agent := mirai_sdk.NewAgent(mirai_sdk.AgentOptions{
        EdgeName: "My Go Service",
    })

    agent.Register(mirai_sdk.RegisterOptions{
        Name:        "greet",
        Description: "Greet someone by name",
        Parameters:  []mirai_sdk.ToolParameter{
            {Name: "name", Type: "string", Description: "Person to greet"},
        },
        Handler: func(args mirai_sdk.ToolArguments) (string, error) {
            return "Hello, " + args.GetString("name", "World") + "!", nil
        },
    })

    agent.RunInBackground()

    // ... your main loop ...
}
```

- Runtime dependency: `gorilla/websocket`
- Edge workspace target: `mirai_tools/go/mirai_sdk/`
- Add to `go.mod`:

```text
require mirai_sdk v0.0.0
replace mirai_sdk => ./mirai_tools/go/mirai_sdk
```

### Java

```java
import io.mirai.*;

public class Main {
    public static void main(String[] args) {
        var agent = new MiraiAgent("mirai-lan_...", "My Java App");

        agent.register(new RegisterOptions()
            .name("greet")
            .description("Greet someone by name")
            .parameters(new ToolParameter("name", "string", "Person to greet"))
            .handler(a -> "Hello, " + a.getString("name", "World") + "!"));

        agent.runInBackground();

        // ... your main app ...
    }
}
```

- JDK 11+ native `java.net.http.WebSocket`
- Only external dependency: Gson
- Edge workspace target: `mirai_tools/java/mirai_sdk/`

### C#

```csharp
using Mirai;

var agent = new MiraiAgent("mirai-lan_...", "My C# App");

agent.Register(new RegisterOptions()
    .SetName("greet")
    .SetDescription("Greet someone by name")
    .SetParameters(new ToolParameter("name", "string", "Person to greet"))
    .SetHandler(args => $"Hello, {args.GetString("name", "World")}!"));

agent.RunInBackground();

// ... your main app continues here ...
```

- .NET 6+ native `System.Net.WebSockets.ClientWebSocket`
- Zero external dependencies (`System.Text.Json` is built-in)
- Edge workspace target: `mirai_tools/csharp/mirai_sdk/`

### Unreal Engine 5

- Native UE5 module under `ue5/MiraiSDK/`
- Uses UE's own WebSocket, HTTP, and JSON systems
- Edge workspace target: `mirai_tools/ue5/MiraiSDK/`
- **CI:** GitHub Actions does **not** compile the UE5 module (a full Unreal toolchain is required). Build and test the module in your local UE project.

## Configuration Rules Across SDKs

Connection resolution is intentionally similar across languages:

1. `MIRAI_RELAY_URL` + `MIRAI_ACCESS_TOKEN`
2. Explicit connection code passed to the SDK
3. `MIRAI_CONNECTION_CODE`
4. Legacy `BRAIN_URL` when supported by that SDK
5. Local fallback such as `ws://127.0.0.1:8000/ws/edge`

Common connection code forms:

- `mirai-lan_...` for LAN
- `mirai_...` for relay pairing
- `ws://...` or `wss://...`
- `http://...` or `https://...`

Tool confirmation policy is persisted when the host platform supports local disk writes. Browser-based TypeScript keeps it in memory.

## `mirai --edge` Mapping

| Command | Generated result |
|---|---|
| `mirai --edge` | all language templates + SDK copies |
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

Use more than one language in one run, e.g. `mirai --edge --lang rust --lang python` or `mirai --edge --lang rust,python`.

## Where To Go Next

- End users: open [`mirai/edge/template/mirai_tools/README.md`](../edge/template/mirai_tools/README.md)
- Maintainers: update SDK logic here first, then let `mirai --edge` copy it into user projects
