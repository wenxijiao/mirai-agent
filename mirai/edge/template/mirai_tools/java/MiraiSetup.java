import io.mirai.MiraiAgent;
import io.mirai.RegisterOptions;
import io.mirai.ToolParameter;

/**
 * Mirai edge setup — register your tools here.
 * Call {@link #initMirai()} from your application's main method.
 */
public class MiraiSetup {

    // ── Configuration ──
    // Set your connection code here (LAN: "mirai-lan_...", remote: "mirai_...").
    // Leave empty to read from MIRAI_CONNECTION_CODE env var or mirai_tools/.env.
    private static final String MIRAI_CONNECTION_CODE = "";
    private static final String MIRAI_EDGE_NAME = "My Java App";

    public static void initMirai() {
        var agent = new MiraiAgent(MIRAI_CONNECTION_CODE, MIRAI_EDGE_NAME);

        // Register your tools below.

        agent.register(new RegisterOptions()
            .name("hello")
            .description("Say hello to someone")
            .parameters(
                new ToolParameter("name", "string", "Person to greet")
            )
            .handler(args -> {
                String name = args.getString("name", "World");
                return "Hello, " + name + "!";
            })
        );

        // Example: tool with confirmation required
        // agent.register(new RegisterOptions()
        //     .name("dangerous_action")
        //     .description("Do something irreversible")
        //     .requireConfirmation(true)
        //     .handler(args -> "done")
        // );

        agent.runInBackground();
    }
}
