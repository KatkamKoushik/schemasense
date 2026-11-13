//! High-performance SafeTensors container and companion configuration parser.

use crate::parsers::types::{ModelHyperparametersPayload, ModelManifestPayload};
use serde_json::Value;
use std::fs::File;
use std::io::Read;
use std::path::Path;

pub const MAX_SAFETENSORS_HEADER_BYTES: u64 = 16 * 1024 * 1024; // 16 MB boundary

pub fn parse_safetensors_file<P: AsRef<Path>>(
    file_path: P,
) -> Result<ModelManifestPayload, String> {
    let p = file_path.as_ref();
    if !p.is_file() {
        return Err(format!("SafeTensors file not found: {}", p.display()));
    }

    let meta = p
        .metadata()
        .map_err(|e| format!("Failed to read metadata for {}: {e}", p.display()))?;
    let file_size = meta.len();

    if file_size < 8 {
        return Err(format!(
            "File too small for SafeTensors container: {file_size} bytes"
        ));
    }

    let mut file =
        File::open(p).map_err(|e| format!("Failed to open file {}: {e}", p.display()))?;

    let mut raw_len = [0u8; 8];
    file.read_exact(&mut raw_len)
        .map_err(|e| format!("Failed to read SafeTensors header length: {e}"))?;
    let header_len = u64::from_le_bytes(raw_len);

    if header_len > MAX_SAFETENSORS_HEADER_BYTES {
        return Err(format!(
            "SafeTensors header length ({header_len} bytes) exceeds safety limit ({MAX_SAFETENSORS_HEADER_BYTES})"
        ));
    }

    if header_len > file_size - 8 {
        return Err("SafeTensors header length exceeds actual file size".to_string());
    }

    let mut raw_header = vec![0u8; header_len as usize];
    file.read_exact(&mut raw_header)
        .map_err(|_| "Unexpected EOF while reading SafeTensors header JSON".to_string())?;

    let header_json: Value = serde_json::from_slice(&raw_header)
        .map_err(|e| format!("Malformed SafeTensors JSON header: {e}"))?;

    let header_obj = match header_json.as_object() {
        Some(obj) => obj,
        None => return Err("Malformed SafeTensors JSON header: expected JSON object".to_string()),
    };

    let metadata_obj = header_obj.get("__metadata__").and_then(|v| v.as_object());
    let tensor_count = header_obj.keys().filter(|&k| k != "__metadata__").count() as u64;

    let dominant_dtype = determine_dominant_dtype(header_obj);

    let license_str = metadata_obj
        .and_then(|m| m.get("license"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());
    let untrusted_chat_template = metadata_obj
        .and_then(|m| m.get("chat_template"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    let (hyperparams, config_found) = if let Some(parent) = p.parent() {
        load_companion_config(parent)
    } else {
        (None, false)
    };

    let mut provenance = vec![
        "SafeTensors container".to_string(),
        format!("Tensor count: {tensor_count}"),
    ];
    if config_found {
        provenance.push("Architecture parameters merged from companion config.json".to_string());
    } else {
        provenance
            .push("No companion config.json found; architectural parameters unknown".to_string());
    }

    let model_id = p
        .file_stem()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_else(|| "unknown_safetensors".to_string());

    Ok(ModelManifestPayload {
        model_id,
        file_path: p.to_string_lossy().to_string(),
        file_size_bytes: file_size,
        format: "safetensors".to_string(),
        hyperparameters: hyperparams,
        tensor_count,
        quantization_type: dominant_dtype,
        license_str,
        untrusted_chat_template,
        provenance_notes: provenance,
    })
}

fn determine_dominant_dtype(obj: &serde_json::Map<String, Value>) -> String {
    for (k, v) in obj {
        if k == "__metadata__" {
            continue;
        }
        if let Some(t_info) = v.as_object() {
            if let Some(dtype) = t_info.get("dtype").and_then(|d| d.as_str()) {
                return dtype.to_string();
            }
        }
    }
    "F16".to_string()
}

fn load_companion_config(parent: &Path) -> (Option<ModelHyperparametersPayload>, bool) {
    let config_path = parent.join("config.json");
    if !config_path.is_file() {
        return (None, false);
    }

    let content = match std::fs::read_to_string(&config_path) {
        Ok(c) => c,
        Err(_) => return (None, false),
    };

    let cfg: Value = match serde_json::from_str(&content) {
        Ok(v) => v,
        Err(_) => return (None, false),
    };

    let raw_arch = cfg
        .get("model_type")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_lowercase();

    let arch_norm = if raw_arch.contains("llama") {
        "llama".to_string()
    } else if raw_arch.contains("qwen") {
        "qwen2".to_string()
    } else if raw_arch.contains("mistral") {
        "mistral".to_string()
    } else if raw_arch.contains("gemma") {
        "gemma2".to_string()
    } else if raw_arch.contains("deepseek") {
        "deepseek".to_string()
    } else {
        "unknown".to_string()
    };

    let get_i64 = |keys: &[&str]| -> Option<i64> {
        for &k in keys {
            if let Some(val) = cfg.get(k) {
                if let Some(i) = val.as_i64() {
                    return Some(i);
                }
            }
        }
        None
    };

    let layers = get_i64(&["num_hidden_layers", "n_layer"]);
    let embed_dim = get_i64(&["hidden_size", "n_embd"]);
    let ffn_dim = get_i64(&["intermediate_size"]);
    let heads = get_i64(&["num_attention_heads", "n_head"]);
    let heads_kv = get_i64(&["num_key_value_heads"]).or(heads);
    let context_len = get_i64(&["max_position_embeddings", "n_positions"]);
    let sliding_window = get_i64(&["sliding_window"]);
    let swa_layers = get_i64(&["max_window_layers", "sliding_window_layers"]);

    let mut swa_pattern = None;
    if let Some(val) = cfg.get("sliding_window_pattern").and_then(|v| v.as_str()) {
        let trimmed = val.trim().to_lowercase();
        if !trimmed.is_empty() {
            swa_pattern = Some(trimmed);
        }
    }

    (
        Some(ModelHyperparametersPayload {
            architecture: arch_norm,
            raw_architecture_name: raw_arch,
            layer_count: layers,
            embedding_length: embed_dim,
            feed_forward_length: ffn_dim,
            head_count: heads,
            head_count_kv: heads_kv,
            key_length: None,
            value_length: None,
            context_length: context_len,
            sliding_window,
            sliding_window_layers: swa_layers,
            sliding_window_pattern: swa_pattern,
            expert_count: None,
            expert_used_count: None,
        }),
        true,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use std::sync::atomic::{AtomicUsize, Ordering};

    static COUNTER: AtomicUsize = AtomicUsize::new(0);

    fn create_temp_st(bytes: &[u8]) -> std::path::PathBuf {
        let count = COUNTER.fetch_add(1, Ordering::SeqCst);
        let path = std::env::temp_dir().join(format!(
            "schemasense_test_st_{}_{}_{}.safetensors",
            std::process::id(),
            count,
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let mut f = File::create(&path).unwrap();
        f.write_all(bytes).unwrap();
        path
    }

    #[test]
    fn test_st_too_small() {
        let path = create_temp_st(b"1234");
        let res = parse_safetensors_file(&path);
        let _ = std::fs::remove_file(&path);
        assert!(res.is_err());
        assert!(res.unwrap_err().contains("File too small"));
    }

    #[test]
    fn test_st_header_exceeds_size() {
        let mut buf = Vec::new();
        buf.extend_from_slice(&1000u64.to_le_bytes());
        buf.extend_from_slice(b"0123456789");
        let path = create_temp_st(&buf);
        let res = parse_safetensors_file(&path);
        let _ = std::fs::remove_file(&path);
        assert!(res.is_err());
        assert!(res
            .unwrap_err()
            .contains("SafeTensors header length exceeds actual file size"));
    }

    #[test]
    fn test_st_oversized_header() {
        let mut buf = Vec::new();
        buf.extend_from_slice(&(32 * 1024 * 1024u64).to_le_bytes()); // 32MB > 16MB
        buf.extend_from_slice(b"{}");
        let path = create_temp_st(&buf);
        let res = parse_safetensors_file(&path);
        let _ = std::fs::remove_file(&path);
        assert!(res.is_err());
        assert!(res.unwrap_err().contains("exceeds safety limit"));
    }

    #[test]
    fn test_st_malformed_json() {
        let bad_json = b"{ not valid json ... ";
        let mut buf = Vec::new();
        buf.extend_from_slice(&(bad_json.len() as u64).to_le_bytes());
        buf.extend_from_slice(bad_json);
        let path = create_temp_st(&buf);
        let res = parse_safetensors_file(&path);
        let _ = std::fs::remove_file(&path);
        assert!(res.is_err());
        assert!(res
            .unwrap_err()
            .contains("Malformed SafeTensors JSON header"));
    }
}
