using Mirai;

/// <summary>
/// Mirai edge setup — register your tools here.
/// Call <see cref="MiraiSetup.InitMirai"/> from your application's entry point.
/// </summary>
public static class MiraiSetup
{
    // ── Configuration ──
    // Set your connection code here (LAN: "mirai-lan_...", remote: "mirai_...").
    // Leave empty to read from MIRAI_CONNECTION_CODE env var or mirai_tools/.env.
    private const string MiraiConnectionCode = "";
    private const string MiraiEdgeName = "My C# App";

    public static MiraiAgent InitMirai()
    {
        var agent = new MiraiAgent(MiraiConnectionCode, MiraiEdgeName);

        // Register your tools below.

        agent.Register(new RegisterOptions()
            .SetName("hello")
            .SetDescription("Say hello to someone")
            .SetParameters(
                new ToolParameter("name", "string", "Person to greet")
            )
            .SetHandler(args =>
            {
                var name = args.GetString("name", "World");
                return $"Hello, {name}!";
            })
        );

        // Example: tool with confirmation required
        // agent.Register(new RegisterOptions()
        //     .SetName("dangerous_action")
        //     .SetDescription("Do something irreversible")
        //     .SetRequireConfirmation(true)
        //     .SetHandler(args => "done")
        // );

        agent.RunInBackground();
        return agent;
    }
}
