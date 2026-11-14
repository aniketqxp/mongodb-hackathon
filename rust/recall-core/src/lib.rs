//! Rust port of core/planner.py. No I/O, no domain words: graph JSON in, plan JSON out.
//! Must match the Python planner on every fixture in core/fixtures/plan_*.json.
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};

type Map<'a> = BTreeMap<&'a str, Vec<&'a str>>;

fn act(id: &str, action: &str, reason: Option<&str>) -> Value {
    json!({"id": id, "action": action, "reason": reason})
}

fn walk<'a>(starts: &[&'a str], adj: &Map<'a>) -> BTreeSet<&'a str> {
    let mut seen = BTreeSet::new();
    let mut stack: Vec<&str> = starts.to_vec();
    while let Some(x) = stack.pop() {
        for &c in adj.get(x).map(|v| v.as_slice()).unwrap_or(&[]) {
            if seen.insert(c) {
                stack.push(c);
            }
        }
    }
    seen
}

fn empty(m: &Map, k: &str) -> bool {
    m.get(k).map_or(true, |v| v.is_empty())
}

/// Returns the plan: {"fault": .., "actions": [..]}. `policy` is "provenance" or "label_only".
pub fn plan(graph: &Value, fault: &str, policy: &str) -> Result<Value, String> {
    if policy != "provenance" && policy != "label_only" {
        return Err(format!("unknown policy {policy:?}"));
    }
    let empty_vec = vec![];
    let nodes_v = graph["nodes"].as_array().unwrap_or(&empty_vec);
    let edges_v = graph["edges"].as_array().unwrap_or(&empty_vec);
    let decs_v = graph["decisions"].as_array().unwrap_or(&empty_vec);

    let mut status: BTreeMap<&str, &str> = BTreeMap::new();
    for n in nodes_v {
        if let Some(id) = n["_id"].as_str() {
            status.insert(id, n["status"].as_str().unwrap_or("active"));
        }
    }
    let (mut incoming, mut outgoing): (Map, Map) = (BTreeMap::new(), BTreeMap::new());
    for e in edges_v {
        if let (Some(f), Some(t)) = (e["from"].as_str(), e["to"].as_str()) {
            if status.contains_key(f) && status.contains_key(t) {
                incoming.entry(t).or_default().push(f);
                outgoing.entry(f).or_default().push(t);
            }
        }
    }
    let mut new = status.clone();
    let mut actions: Vec<Value> = vec![];

    let anc = walk(&[fault], &incoming);
    // BTreeSet iterates sorted, matching Python's sorted()
    let evidence: Vec<&str> = anc
        .iter()
        .copied()
        .filter(|a| empty(&incoming, a) && status[a] == "active")
        .collect();

    if status.contains_key(fault) {
        new.insert(fault, "invalidated");
        actions.push(act(fault, "delete", None));
    }
    if policy == "provenance" {
        for &ev in &evidence {
            new.insert(ev, "retracted");
            actions.push(act(ev, "retract", Some("evidence_of_fault")));
        }
    }

    // derive: a derived node is on iff some supporter is on (derived) or active (evidence)
    let derived: Vec<&str> = status.keys().copied().filter(|i| !empty(&incoming, i)).collect();
    let mut on: BTreeMap<&str, bool> = derived.iter().map(|&i| (i, false)).collect();
    for _ in 0..=derived.len() {
        let mut changed = false;
        for &i in &derived {
            let v = i != fault
                && incoming[i].iter().any(|p| match on.get(p) {
                    Some(&b) => b,
                    None => new.get(p) == Some(&"active"),
                });
            if v != on[i] {
                on.insert(i, v);
                changed = true;
            }
        }
        if !changed {
            break;
        }
    }
    for (&i, &v) in &on {
        if i != fault && status[i] == "active" && !v {
            new.insert(i, "quarantined");
            actions.push(act(i, "quarantine", Some("no_active_support")));
        }
    }

    // siblings: other derived nodes built from the same evidence that stay active
    let desc = walk(&evidence, &outgoing);
    let siblings: Vec<&str> = desc.iter().copied().filter(|s| *s != fault && !anc.contains(s)).collect();
    for &s in &siblings {
        if new[s] == "active" {
            let own = walk(&[s], &incoming)
                .iter()
                .any(|p| empty(&incoming, p) && new[p] == "active" && !evidence.contains(p));
            actions.push(act(s, "preserve", Some(if own { "independent_support" } else { "evidence_still_active" })));
        }
    }

    // decision stage: independent-support check, then invalidate + replay
    let down: BTreeSet<&str> = status.keys().copied().filter(|i| status[i] == "active" && new[i] != "active").collect();
    let mut decs: Vec<&Value> = decs_v.iter().collect();
    decs.sort_by_key(|d| d["_id"].as_str().unwrap_or("").to_string());
    for d in decs {
        let id = d["_id"].as_str().unwrap_or("");
        if d["status"].as_str().unwrap_or("active") != "active" {
            continue;
        }
        let inputs: Vec<&str> = d["inputs"].as_array().unwrap_or(&empty_vec).iter().filter_map(|x| x.as_str()).collect();
        if !inputs.iter().any(|i| down.contains(i)) {
            continue;
        }
        if inputs.iter().any(|i| !down.contains(i) && new.get(i) == Some(&"active")) {
            actions.push(act(id, "preserve", Some("independent_support")));
        } else {
            actions.push(act(id, "invalidate", Some("lost_all_support")));
            actions.push(act(id, "replay", None));
        }
    }
    Ok(json!({"fault": fault, "actions": actions}))
}
