/**
 * Isomorphic runtime helpers — no Node built-in imports at module top level.
 */

export function isNode(): boolean {
  return (
    typeof process !== "undefined" &&
    process.versions != null &&
    typeof process.versions.node === "string"
  );
}

/** Safe `process.env` for browser bundles (Vite/Webpack define `process` optionally). */
export function getEnv(): Record<string, string | undefined> {
  if (typeof process !== "undefined" && process.env && typeof process.env === "object") {
    return process.env as Record<string, string | undefined>;
  }
  return {};
}

/** Relay credentials after bootstrap when `process.env` is not writable (browser). */
const browserRelay: { relayUrl?: string; accessToken?: string } = {};

export function getMiraiEnv(): Record<string, string | undefined> {
  const e = { ...getEnv() };
  if (browserRelay.relayUrl) {
    e.MIRAI_RELAY_URL = browserRelay.relayUrl;
    e.MIRAI_ACCESS_TOKEN = browserRelay.accessToken;
  }
  return e;
}

export function setRelayFromBootstrap(relayUrl: string, accessToken: string): void {
  if (isNode() && typeof process !== "undefined" && process.env) {
    process.env.MIRAI_RELAY_URL = relayUrl;
    process.env.MIRAI_ACCESS_TOKEN = accessToken;
  }
  browserRelay.relayUrl = relayUrl;
  browserRelay.accessToken = accessToken;
}
