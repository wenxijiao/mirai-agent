mod mirai_setup;

#[tokio::main]
async fn main() {
    mirai_setup::init_mirai();
    eprintln!("Mirai edge running. Press Ctrl+C to stop.");
    let _ = tokio::signal::ctrl_c().await;
}
