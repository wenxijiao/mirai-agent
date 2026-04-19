package main

import (
	"fmt"

	mirai "mirai_sdk"
)

// ── Configuration ──
// Set your connection code here (LAN: "mirai-lan_...", remote: "mirai_...").
// Leave empty to read from MIRAI_CONNECTION_CODE env var or mirai_tools/.env.
const miraiConnectionCode = ""
const miraiEdgeName = "My Go App"

// InitMirai creates and starts the Mirai edge agent.
// Call from main.go (see mirai_tools/go/main.go) or from your own main.
func InitMirai() {
	agent := mirai.NewAgent(mirai.AgentOptions{
		ConnectionCode: miraiConnectionCode,
		EdgeName:       miraiEdgeName,
	})

	// Register your tools below.
	// Each tool needs a name, description, parameters, and a handler function.

	agent.Register(mirai.RegisterOptions{
		Name:        "hello",
		Description: "Say hello to someone",
		Parameters: []mirai.ToolParameter{
			{Name: "name", Type: "string", Description: "Person to greet"},
		},
		Handler: func(args mirai.ToolArguments) string {
			name := args.String("name")
			if name == "" {
				name = "World"
			}
			return fmt.Sprintf("Hello, %s!", name)
		},
	})

	// Example: tool with confirmation required
	// agent.Register(mirai.RegisterOptions{
	//     Name:                "dangerous_action",
	//     Description:         "Do something irreversible",
	//     RequireConfirmation: true,
	//     Handler: func(args mirai.ToolArguments) string {
	//         return "done"
	//     },
	// })

	agent.RunInBackground()
}
