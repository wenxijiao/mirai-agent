# Mirai Edge — C#

Use this when your app is written in C# and you want to expose functions to Mirai through .NET 6+ native WebSocket.

## Quick Start

1. Add the bundled SDK to your project
2. Edit `mirai_tools/csharp/MiraiSetup.cs`
3. **Quick test:** use `Program.cs` as the entry (add a `.csproj` that references `mirai_sdk`), then `dotnet run`. Remove `Program.cs` when you call `InitMirai()` from your own `Main`.
4. Otherwise call `MiraiSetup.InitMirai()` from your app entry point and keep your process alive as usual

## Files In This Folder

```text
mirai_tools/csharp/
├── README.md
├── MiraiSetup.cs          # edit this
├── Program.cs             # optional standalone entry; remove when embedding
└── mirai_sdk/             # bundled .NET project
    ├── MiraiSDK.csproj
    └── *.cs
```

## Add The SDK To Your Project

Choose one of these approaches:

### Project reference

Add a project reference in your `.csproj`:

```xml
<ItemGroup>
    <ProjectReference Include="mirai_tools/csharp/mirai_sdk/MiraiSDK.csproj" />
</ItemGroup>
```

### Copy sources

Copy the `.cs` files from `mirai_sdk/` into your project if that better fits your setup.

## Configure Connection

Edit the constants in `MiraiSetup.cs`, or use `mirai_tools/.env`:

```env
MIRAI_CONNECTION_CODE=mirai-lan_...
EDGE_NAME=My C# App
```

## Register Tools

```csharp
agent.Register(new RegisterOptions()
    .SetName("set_light")
    .SetDescription("Control room lights")
    .SetParameters(
        new ToolParameter("room", "string", "Room name"),
        new ToolParameter("on", "boolean", "Turn on or off")
    )
    .SetHandler(args =>
    {
        var room = args.GetString("room", "living_room");
        var on = args.GetBool("on", false);
        return $"Light in {room}: {on}";
    })
);
```

Use `.SetRequireConfirmation(true)` for dangerous tools.

## Start It From Your App

```csharp
var agent = MiraiSetup.InitMirai();
// ... your application logic ...
// Call agent.Stop() or agent.Dispose() on shutdown
Console.ReadLine(); // keep alive
```

## Notes

- Requires .NET 6+
- Uses native `System.Net.WebSockets.ClientWebSocket`
- Uses `System.Text.Json` — no external dependencies
