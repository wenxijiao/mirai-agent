/// Mirai Edge — Swift tool registration
///
/// Add the local Swift package at ``MiraiSDK/`` (contains ``Package.swift``)
/// via Xcode → File → Add Package Dependencies → Add Local…, then
/// ``import MiraiSDK``. See ``README.md`` for same-target (no SPM) setup.
///
/// Call ``initMirai()`` early in your app lifecycle (e.g. from ``@main``).

import MiraiSDK

// MARK: - Import your tool functions
// import MyApp

// MARK: - Connection (edit here — simplest on iPhone; no bundle file needed)

private let miraiConnectionCode = "mirai-lan_..."  // paste from `mirai --server`, or mirai_... for relay
private let miraiEdgeName = "My IOS Device"            // shown in the Mirai UI

func initMirai() -> MiraiAgent {
    let agent = MiraiAgent(
        connectionCode: miraiConnectionCode,
        edgeName: miraiEdgeName
    )

    // MARK: - Register tools: name + description + parameters + handler

    // agent.register(
    //     name: "jump",
    //     description: "Make the character jump",
    //     parameters: [
    //         .init("height", type: .number, description: "Jump height in meters"),
    //     ]
    // ) { args in
    //     let height = args.double("height") ?? 1.0
    //     return jump(height: height)
    // }

    // Dangerous tools: user confirms in the Mirai web UI or `mirai --chat` (not on device):
    // agent.register(
    //     name: "delete_all",
    //     description: "Delete all data",
    //     requireConfirmation: true
    // ) { _ in
    //     return deleteAll()
    // }

    agent.runInBackground()
    return agent
}
