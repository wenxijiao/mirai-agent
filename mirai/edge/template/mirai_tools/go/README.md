# Mirai Edge — Go

Use this when your app is written in Go and you want the LLM to call functions inside the same process.

## Quick Start

1. Add the local SDK module to your app's `go.mod`
2. Edit `mirai_tools/go/mirai_setup.go`
3. **Quick test:** from `mirai_tools/go/`, run `go run .` — `main.go` calls `InitMirai()` and blocks until Ctrl+C. When you embed Mirai in a larger app, remove `main.go` and call `InitMirai()` from your own `main`.
4. Otherwise call `InitMirai()` from your `main` and keep the process alive as usual

## Files In This Folder

```text
mirai_tools/go/
├── README.md
├── main.go                 # standalone entry (`go run .`); delete when embedding
├── mirai_setup.go          # edit this
└── mirai_sdk/              # bundled local Go module
    ├── go.mod
    ├── agent.go
    ├── auth.go
    ├── connection.go
    ├── schema.go
    ├── types.go
    └── env.go
```

## Add The SDK To Your Project

In your app's root `go.mod`:

```text
require mirai_sdk v0.0.0
replace mirai_sdk => ./mirai_tools/go/mirai_sdk
```

Then use it normally from your app source.

## Configure Connection

Edit the constants in `mirai_setup.go`, or use `mirai_tools/.env`:

```env
MIRAI_CONNECTION_CODE=mirai-lan_...
EDGE_NAME=My Go App
```

## Register Tools

```go
agent.Register(mirai.RegisterOptions{
    Name:        "set_light",
    Description: "Control room lights",
    Parameters: []mirai.ToolParameter{
        {Name: "room", Type: "string", Description: "Room name"},
        {Name: "on", Type: "boolean", Description: "Turn on or off"},
    },
    Handler: func(args mirai.ToolArguments) string {
        room := args.String("room")
        on := args.Bool("on", false)
        return fmt.Sprintf("Light in %s: %v", room, on)
    },
})
```

Use `RequireConfirmation: true` for dangerous tools.

## Start It From Your App

```go
func main() {
    InitMirai()

    // your app continues to run
    select {}
}
```

## Notes

- Runtime dependency: `gorilla/websocket`
- Build with your normal Go workflow: `go run .` or `go build .`
