# Mirai Edge — Rust

## Quick Start

1. Edit `mirai_tools/rust/src/mirai_setup.rs` and register your tools.
2. From `mirai_tools/rust/`, run:

```bash
cargo run
```

The bundled `mirai_sdk` crate is copied from Mirai; point your own crate at it with:

```toml
mirai_sdk = { path = "mirai_tools/rust/mirai_sdk" }
```

## Configure

Set `mirai_tools/.env` or environment variables:

```env
MIRAI_CONNECTION_CODE=mirai-lan_...
EDGE_NAME=My Rust App
```

Runtime: Tokio + `tokio-tungstenite`.
