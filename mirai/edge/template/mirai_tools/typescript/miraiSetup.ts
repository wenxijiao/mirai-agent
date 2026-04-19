/**
 * Mirai Edge — TypeScript tool registration
 *
 * Register your functions with `agent.register()` and call `initMirai()`
 * from your app entry point.
 *
 *     import { initMirai } from "./mirai_tools/typescript/miraiSetup";
 *     initMirai();
 *
 * Quick test: ``npx tsx miraiSetup.ts`` (from mirai_tools/typescript/)
 *
 * Requires: npm install (from the mirai_tools/typescript/mirai_sdk directory)
 */

import path from "node:path";
import { pathToFileURL } from "node:url";

import { MiraiAgent } from "./mirai_sdk/src";

// ── Connection (edit here, or set in .env) ──

const MIRAI_CONNECTION_CODE = "mirai-lan_..."; // paste from `mirai --server`, or mirai_... for relay
const MIRAI_EDGE_NAME = "My Node App";

export function initMirai(): MiraiAgent {
  const agent = new MiraiAgent({
    connectionCode: MIRAI_CONNECTION_CODE,
    edgeName: MIRAI_EDGE_NAME,
  });

  // ── Register tools: name + description + parameters + handler ──

  // agent.register({
  //   name: "jump",
  //   description: "Make the character jump",
  //   parameters: [
  //     { name: "height", type: "number", description: "Jump height in meters" },
  //   ],
  //   handler: async (args) => {
  //     const height = args.number("height") ?? 1.0;
  //     return `Jumped ${height} meters`;
  //   },
  // });

  // Dangerous tools: user confirms in the Mirai web UI or `mirai --chat` (not on device):
  // agent.register({
  //   name: "delete_all",
  //   description: "Delete all data",
  //   requireConfirmation: true,
  //   handler: async () => "Deleted everything",
  // });

  agent.runInBackground();
  return agent;
}

/** True when this file is executed directly (e.g. `npx tsx miraiSetup.ts`). */
function isDirectRun(): boolean {
  if (typeof process === "undefined" || !process.argv[1]) {
    return false;
  }
  return import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;
}

if (isDirectRun()) {
  initMirai();
  console.log("Mirai edge running (miraiSetup as entry). Press Ctrl+C to stop.");
}
