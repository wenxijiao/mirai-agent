# Mirai Edge — Dart

Targets **Dart VM** (CLI / server). For Flutter, use the same `mirai_sdk` package in your app.

## Quick Start

1. Edit `mirai_tools/dart/lib/mirai_setup.dart`.
2. From `mirai_tools/dart/`:

```bash
dart pub get
dart run
```

## Layout

- `mirai_sdk/` — copied Mirai SDK (`package:mirai_sdk`)
- `lib/mirai_setup.dart` — register tools and call `initMirai()` from your entrypoint

## Configure

`mirai_tools/.env`:

```env
MIRAI_CONNECTION_CODE=mirai-lan_...
EDGE_NAME=My Dart App
```
