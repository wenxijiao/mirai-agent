# Mirai Edge — Unreal Engine 5

Use this when you want to expose UE5 gameplay or subsystem functions to Mirai.

## Quick Start

1. Copy the bundled `MiraiSDK/` module into your project's `Source/` directory
2. Add `MiraiSDK` to your game's `.Build.cs`
3. Edit `MiraiSetup.h` / `MiraiSetup.cpp`
4. Call `InitMirai()` early in your game lifecycle

## Add The Module

In your game's `.Build.cs`:

```csharp
PublicDependencyModuleNames.AddRange(new string[] { "MiraiSDK" });
```

Then regenerate project files.

## Configure Connection

The simplest path is to edit `MiraiConnectionCode` and `MiraiEdgeName` directly in `MiraiSetup.h`.

You can also place `mirai_tools/.env` in the project root:

```env
MIRAI_CONNECTION_CODE=mirai-lan_...
EDGE_NAME=My UE5 Game
```

## Register Tools

```cpp
FMiraiRegisterOptions Opts;
Opts.Name = TEXT("set_light");
Opts.Description = TEXT("Control room lights");
Opts.Parameters = {
    { TEXT("room"), TEXT("string"), TEXT("Room name"), true },
    { TEXT("on"), TEXT("boolean"), TEXT("Turn on or off"), true },
};
Opts.Handler.BindLambda([](const FMiraiToolArguments& Args) -> FString {
    FString Room = Args.GetString(TEXT("room"), TEXT("living_room"));
    bool bOn = Args.GetBool(TEXT("on"), false);
    return SetLight(Room, bOn);
});
Agent->RegisterTool(MoveTemp(Opts));
```

Use `bRequireConfirmation = true` for dangerous tools.

## Start It From Your Game

Typical place:

```cpp
void UMyGameInstance::Init()
{
    Super::Init();
    InitMirai();
}
```

## Notes

- `FMiraiAgent` is a plain C++ class, not a `UObject`
- Uses UE's own WebSocket, HTTP, and JSON modules
- Reconnects automatically with exponential backoff
