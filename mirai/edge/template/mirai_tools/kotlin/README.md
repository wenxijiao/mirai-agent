# Mirai Edge — Kotlin (JVM)

## Quick Start

1. Run `mirai --edge --lang kotlin` (or `mirai --edge`) from your project root.
2. Edit `mirai_tools/kotlin/src/main/kotlin/io/mirai/edge/MiraiSetup.kt`.
3. From `mirai_tools/kotlin/`:

```bash
./gradlew run
```

(Use `gradle run` if you do not use the Gradle wrapper.)

## Dependencies

OkHttp WebSocket + Gson — declared in `build.gradle.kts`. The `io.mirai.sdk` package is copied into `src/main/kotlin/io/mirai/sdk/` by `mirai --edge`.

## Configure

Use `mirai_tools/.env`:

```env
MIRAI_CONNECTION_CODE=mirai-lan_...
EDGE_NAME=My Kotlin App
```
