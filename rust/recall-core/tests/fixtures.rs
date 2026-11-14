//! Parity with the Python planner: every core/fixtures/plan_*.json must produce the expected plan.
use std::fs;

#[test]
fn matches_shared_fixtures() {
    let dir = concat!(env!("CARGO_MANIFEST_DIR"), "/../../core/fixtures");
    let mut n = 0;
    for entry in fs::read_dir(dir).unwrap() {
        let p = entry.unwrap().path();
        let name = p.file_name().unwrap().to_string_lossy().to_string();
        if !(name.starts_with("plan_") && name.ends_with(".json")) {
            continue;
        }
        let f: serde_json::Value = serde_json::from_str(&fs::read_to_string(&p).unwrap()).unwrap();
        for (policy, expected) in f["expected"].as_object().unwrap() {
            let got = recall_core::plan(&f["graph"], f["fault"].as_str().unwrap(), policy).unwrap();
            assert_eq!(&got, expected, "{name} [{policy}]");
            n += 1;
        }
    }
    assert!(n >= 4, "expected at least 4 fixture cases, ran {n}");
}

#[test]
fn rejects_unknown_policy() {
    assert!(recall_core::plan(&serde_json::json!({}), "x", "nope").is_err());
}
