package io.mirai.edge

import io.mirai.sdk.AgentOptions
import io.mirai.sdk.MiraiAgent
import io.mirai.sdk.RegisterOptions
import io.mirai.sdk.ToolHandler
import io.mirai.sdk.ToolParameter

fun initMirai() {
    val agent = MiraiAgent(
        AgentOptions(
            connectionCode = null,
            edgeName = "My Kotlin App",
            envPath = null,
        ),
    )
    agent.register(
        RegisterOptions(
            name = "hello",
            description = "Say hello to someone",
            parameters = listOf(
                ToolParameter(
                    name = "name",
                    typeName = "string",
                    description = "Person to greet",
                ),
            ),
            handler = ToolHandler { args -> "Hello, ${args.string("name")}!" },
        ),
    )
    agent.runInBackground()
}
