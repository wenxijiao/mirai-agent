# Mirai Edge — Java

Use this when your app is written in Java and you want to expose functions to Mirai through JDK 11+ native WebSocket.

## Quick Start

1. Add the bundled SDK to your project
2. Edit `mirai_tools/java/MiraiSetup.java`
3. **Quick test:** run `MiraiEdgeMain` from your IDE, or configure `exec:java` with main class `MiraiEdgeMain`. Delete `MiraiEdgeMain.java` when you call `initMirai()` from your own `main`.
4. Otherwise call `MiraiSetup.initMirai()` from your app entry point and keep your JVM process alive as usual

## Files In This Folder

```text
mirai_tools/java/
├── README.md
├── MiraiSetup.java         # edit this
├── MiraiEdgeMain.java      # optional standalone entry; delete when embedding
└── mirai_sdk/              # bundled Maven project
    ├── pom.xml
    └── src/main/java/io/mirai/
```

## Add The SDK To Your Project

Choose one of these approaches:

### Maven multi-module

Add `mirai_tools/java/mirai_sdk` as a module in your existing build.

### Install locally

```bash
cd mirai_tools/java/mirai_sdk
mvn install
```

Then depend on it from your app:

```xml
<dependency>
    <groupId>io.mirai</groupId>
    <artifactId>mirai-sdk</artifactId>
    <version>0.1.0</version>
</dependency>
```

### Copy sources

Copy `src/main/java/io/mirai/` into your project if that better fits your setup.

## Configure Connection

Edit the constants in `MiraiSetup.java`, or use `mirai_tools/.env`:

```env
MIRAI_CONNECTION_CODE=mirai-lan_...
EDGE_NAME=My Java App
```

## Register Tools

```java
agent.register(new RegisterOptions()
    .name("set_light")
    .description("Control room lights")
    .parameters(
        new ToolParameter("room", "string", "Room name"),
        new ToolParameter("on", "boolean", "Turn on or off")
    )
    .handler(args -> {
        String room = args.getString("room", "living_room");
        boolean on = args.getBoolean("on", false);
        return "Light in " + room + ": " + on;
    })
);
```

Use `.requireConfirmation(true)` for dangerous tools.

## Start It From Your App

```java
public class Main {
    public static void main(String[] args) throws Exception {
        MiraiSetup.initMirai();
        Thread.currentThread().join();
    }
}
```

## Notes

- Requires JDK 11+
- Uses native `java.net.http.WebSocket`
- The only external dependency is Gson
