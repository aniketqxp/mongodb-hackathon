use std::io::Read;

fn main() {
    let policy = std::env::args().nth(1).unwrap_or_else(|| "provenance".into());
    let mut buf = String::new();
    std::io::stdin().read_to_string(&mut buf).expect("read stdin");
    let input: serde_json::Value = serde_json::from_str(&buf).unwrap_or_else(|e| {
        eprintln!("bad input json: {e}");
        std::process::exit(2)
    });
    let fault = input["fault"].as_str().unwrap_or_else(|| {
        eprintln!("missing string field `fault`");
        std::process::exit(2)
    });
    match recall_core::plan(&input["graph"], fault, &policy) {
        Ok(p) => println!("{p}"),
        Err(e) => {
            eprintln!("{e}");
            std::process::exit(2)
        }
    }
}
