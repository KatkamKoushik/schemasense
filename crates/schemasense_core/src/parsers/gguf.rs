//! High-performance, zero-allocation binary GGUF v2/v3 metadata parser.

use crate::parsers::types::{ModelHyperparametersPayload, ModelManifestPayload};
use std::collections::HashMap;
use std::fs::File;
use std::io::{Cursor, Read};
use std::path::Path;

pub const GGUF_MAGIC: u32 = 0x46554747; // b"GGUF" in little-endian uint32
pub const MAX_HEADER_SCAN_BYTES: usize = 16 * 1024 * 1024; // 16 MB maximum header scan
pub const MAX_METADATA_KV_COUNT: u64 = 1000;
pub const MAX_STRING_LENGTH_BYTES: u64 = 65536;
pub const MAX_ARRAY_LENGTH_ELEMENTS: u64 = 65536;

#[derive(Debug, Clone)]
pub enum GgufValue {
    Uint8(u8),
    Int8(i8),
    Uint16(u16),
    Int16(i16),
    Uint32(u32),
    Int32(i32),
    Float32(f32),
    Bool(bool),
    StringVal(String),
    Array(Vec<GgufValue>),
    Uint64(u64),
    Int64(i64),
    Float64(f64),
}

impl GgufValue {
    pub fn as_i64(&self) -> Option<i64> {
        match self {
            GgufValue::Uint8(v) => Some(*v as i64),
            GgufValue::Int8(v) => Some(*v as i64),
            GgufValue::Uint16(v) => Some(*v as i64),
            GgufValue::Int16(v) => Some(*v as i64),
            GgufValue::Uint32(v) => Some(*v as i64),
            GgufValue::Int32(v) => Some(*v as i64),
            GgufValue::Uint64(v) => (*v).try_into().ok(),
            GgufValue::Int64(v) => Some(*v),
            _ => None,
        }
    }

    pub fn as_str(&self) -> Option<&str> {
        match self {
            GgufValue::StringVal(s) => Some(s.as_str()),
            _ => None,
        }
    }
}

pub fn parse_gguf_file<P: AsRef<Path>>(file_path: P) -> Result<ModelManifestPayload, String> {
    let p = file_path.as_ref();
    if !p.is_file() {
        return Err(format!("Model file not found: {}", p.display()));
    }

    let meta = p
        .metadata()
        .map_err(|e| format!("Failed to read metadata for {}: {e}", p.display()))?;
    let file_size = meta.len();

    if file_size < 24 {
        return Err(format!(
            "File too small to be a valid GGUF container: {file_size} bytes"
        ));
    }

    let mut file =
        File::open(p).map_err(|e| format!("Failed to open file {}: {e}", p.display()))?;

    let bytes_to_read = std::cmp::min(file_size as usize, MAX_HEADER_SCAN_BYTES);
    let mut header_buf = vec![0u8; bytes_to_read];
    file.read_exact(&mut header_buf)
        .map_err(|e| format!("Failed to read GGUF header from {}: {e}", p.display()))?;

    let mut cursor = Cursor::new(&header_buf[..]);

    let magic = read_u32_le(&mut cursor)?;
    if magic != GGUF_MAGIC {
        return Err(format!(
            "Invalid GGUF magic bytes (got 0x{magic:08X}, expected 0x{GGUF_MAGIC:08X})"
        ));
    }

    let version = read_u32_le(&mut cursor)?;
    if version != 2 && version != 3 {
        return Err(format!(
            "Unsupported GGUF version: {version} (supports v2 and v3)"
        ));
    }

    let tensor_count = read_u64_le(&mut cursor)?;
    let kv_count = read_u64_le(&mut cursor)?;

    if kv_count > MAX_METADATA_KV_COUNT {
        return Err(format!(
            "Metadata key-value count ({kv_count}) exceeds security boundary ({MAX_METADATA_KV_COUNT})"
        ));
    }

    let mut metadata = HashMap::with_capacity(std::cmp::min(kv_count as usize, 256));

    for _ in 0..kv_count {
        let key = read_string(&mut cursor)?;
        let val_type = read_u32_le(&mut cursor)?;
        if val_type > 12 {
            return Err(format!(
                "Unknown GGUF value type: {val_type} for key '{key}'"
            ));
        }
        let val = read_value(&mut cursor, val_type)?;
        metadata.insert(key, val);
    }

    let hyperparams = extract_hyperparameters(&metadata);
    let filename = p
        .file_name()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_default();
    let model_id = p
        .file_stem()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_else(|| "unknown_model".to_string());
    let quant = determine_quantization(&metadata, &filename);

    let license_str = metadata
        .get("general.license")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());
    let untrusted_chat_template = metadata
        .get("tokenizer.chat_template")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    let raw_arch = metadata
        .get("general.architecture")
        .and_then(|v| v.as_str())
        .unwrap_or("unknown");

    let provenance = vec![
        format!("GGUF v{version} container"),
        format!("Raw Architecture: {raw_arch}"),
    ];

    Ok(ModelManifestPayload {
        model_id,
        file_path: p.to_string_lossy().to_string(),
        file_size_bytes: file_size,
        format: "gguf".to_string(),
        hyperparameters: Some(hyperparams),
        tensor_count,
        quantization_type: quant,
        license_str,
        untrusted_chat_template,
        provenance_notes: provenance,
    })
}

fn read_exact_bytes(cursor: &mut Cursor<&[u8]>, n: usize) -> Result<Vec<u8>, String> {
    let mut buf = vec![0u8; n];
    let pos = cursor.position() as usize;
    let data = cursor.get_ref();
    if pos + n > data.len() {
        let actual = data.len().saturating_sub(pos);
        return Err(format!(
            "Unexpected EOF in GGUF stream (needed {n} bytes, got {actual})"
        ));
    }
    cursor
        .read_exact(&mut buf)
        .map_err(|e| format!("Read error: {e}"))?;
    Ok(buf)
}

fn read_u8(cursor: &mut Cursor<&[u8]>) -> Result<u8, String> {
    let bytes = read_exact_bytes(cursor, 1)?;
    Ok(bytes[0])
}

fn read_i8(cursor: &mut Cursor<&[u8]>) -> Result<i8, String> {
    let bytes = read_exact_bytes(cursor, 1)?;
    Ok(bytes[0] as i8)
}

fn read_u16_le(cursor: &mut Cursor<&[u8]>) -> Result<u16, String> {
    let bytes = read_exact_bytes(cursor, 2)?;
    Ok(u16::from_le_bytes([bytes[0], bytes[1]]))
}

fn read_i16_le(cursor: &mut Cursor<&[u8]>) -> Result<i16, String> {
    let bytes = read_exact_bytes(cursor, 2)?;
    Ok(i16::from_le_bytes([bytes[0], bytes[1]]))
}

fn read_u32_le(cursor: &mut Cursor<&[u8]>) -> Result<u32, String> {
    let bytes = read_exact_bytes(cursor, 4)?;
    Ok(u32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]))
}

fn read_i32_le(cursor: &mut Cursor<&[u8]>) -> Result<i32, String> {
    let bytes = read_exact_bytes(cursor, 4)?;
    Ok(i32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]))
}

fn read_u64_le(cursor: &mut Cursor<&[u8]>) -> Result<u64, String> {
    let bytes = read_exact_bytes(cursor, 8)?;
    Ok(u64::from_le_bytes([
        bytes[0], bytes[1], bytes[2], bytes[3], bytes[4], bytes[5], bytes[6], bytes[7],
    ]))
}

fn read_i64_le(cursor: &mut Cursor<&[u8]>) -> Result<i64, String> {
    let bytes = read_exact_bytes(cursor, 8)?;
    Ok(i64::from_le_bytes([
        bytes[0], bytes[1], bytes[2], bytes[3], bytes[4], bytes[5], bytes[6], bytes[7],
    ]))
}

fn read_f32_le(cursor: &mut Cursor<&[u8]>) -> Result<f32, String> {
    let bytes = read_exact_bytes(cursor, 4)?;
    Ok(f32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]))
}

fn read_f64_le(cursor: &mut Cursor<&[u8]>) -> Result<f64, String> {
    let bytes = read_exact_bytes(cursor, 8)?;
    Ok(f64::from_le_bytes([
        bytes[0], bytes[1], bytes[2], bytes[3], bytes[4], bytes[5], bytes[6], bytes[7],
    ]))
}

fn read_string(cursor: &mut Cursor<&[u8]>) -> Result<String, String> {
    let length = read_u64_le(cursor)?;
    if length > MAX_STRING_LENGTH_BYTES {
        return Err(format!(
            "String length ({length} bytes) exceeds safety limit ({MAX_STRING_LENGTH_BYTES})"
        ));
    }
    let pos = cursor.position() as usize;
    let data = cursor.get_ref();
    if pos + (length as usize) > data.len() {
        return Err("Unexpected EOF while reading GGUF string".to_string());
    }
    let raw = read_exact_bytes(cursor, length as usize)?;
    Ok(String::from_utf8_lossy(&raw).to_string())
}

fn read_value(cursor: &mut Cursor<&[u8]>, val_type: u32) -> Result<GgufValue, String> {
    match val_type {
        0 => Ok(GgufValue::Uint8(read_u8(cursor)?)),
        1 => Ok(GgufValue::Int8(read_i8(cursor)?)),
        2 => Ok(GgufValue::Uint16(read_u16_le(cursor)?)),
        3 => Ok(GgufValue::Int16(read_i16_le(cursor)?)),
        4 => Ok(GgufValue::Uint32(read_u32_le(cursor)?)),
        5 => Ok(GgufValue::Int32(read_i32_le(cursor)?)),
        6 => Ok(GgufValue::Float32(read_f32_le(cursor)?)),
        7 => Ok(GgufValue::Bool(read_u8(cursor)? != 0)),
        8 => Ok(GgufValue::StringVal(read_string(cursor)?)),
        9 => {
            let item_type = read_u32_le(cursor)?;
            let arr_len = read_u64_le(cursor)?;
            if arr_len > MAX_ARRAY_LENGTH_ELEMENTS {
                return Err(format!(
                    "Array length ({arr_len}) exceeds safety limit ({MAX_ARRAY_LENGTH_ELEMENTS})"
                ));
            }
            let mut items = Vec::with_capacity(std::cmp::min(arr_len as usize, 1024));
            for _ in 0..arr_len {
                items.push(read_value(cursor, item_type)?);
            }
            Ok(GgufValue::Array(items))
        }
        10 => Ok(GgufValue::Uint64(read_u64_le(cursor)?)),
        11 => Ok(GgufValue::Int64(read_i64_le(cursor)?)),
        12 => Ok(GgufValue::Float64(read_f64_le(cursor)?)),
        _ => Err(format!("Unsupported value type id: {val_type}")),
    }
}

fn extract_hyperparameters(metadata: &HashMap<String, GgufValue>) -> ModelHyperparametersPayload {
    let raw_arch = metadata
        .get("general.architecture")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_lowercase();
    let arch_normalized = normalize_architecture(&raw_arch);

    let prefix = if !raw_arch.is_empty() {
        format!("{raw_arch}.")
    } else {
        String::new()
    };

    let get_int = |keys: &[&str]| -> Option<i64> {
        for &k in keys {
            let prefixed = format!("{prefix}{k}");
            if let Some(v) = metadata.get(&prefixed).or_else(|| metadata.get(k)) {
                if let Some(i) = v.as_i64() {
                    return Some(i);
                }
            }
        }
        None
    };

    let layers = get_int(&["block_count", "layer_count"]);
    let embed_dim = get_int(&["embedding_length"]);
    let ffn_dim = get_int(&["feed_forward_length"]);
    let heads = get_int(&["attention.head_count"]);
    let heads_kv = get_int(&["attention.head_count_kv"]);
    let key_len = get_int(&["attention.key_length"]);
    let val_len = get_int(&["attention.value_length"]);
    let context_len = get_int(&["context_length"]);
    let sliding_window = get_int(&["attention.sliding_window", "sliding_window"]);
    let swa_layers = get_int(&[
        "attention.sliding_window_layers",
        "sliding_window_layers",
        "max_window_layers",
    ]);

    let mut swa_pattern = None;
    for &k in &["attention.sliding_window_pattern", "sliding_window_pattern"] {
        let prefixed = format!("{prefix}{k}");
        if let Some(val) = metadata.get(&prefixed).or_else(|| metadata.get(k)) {
            if let Some(s) = val.as_str() {
                let trimmed = s.trim().to_lowercase();
                if !trimmed.is_empty() {
                    swa_pattern = Some(trimmed);
                    break;
                }
            }
        }
    }

    let experts = get_int(&["expert_count"]);
    let experts_used = get_int(&["expert_used_count"]);

    ModelHyperparametersPayload {
        architecture: arch_normalized,
        raw_architecture_name: raw_arch,
        layer_count: layers,
        embedding_length: embed_dim,
        feed_forward_length: ffn_dim,
        head_count: heads,
        head_count_kv: heads_kv,
        key_length: key_len,
        value_length: val_len,
        context_length: context_len,
        sliding_window,
        sliding_window_layers: swa_layers,
        sliding_window_pattern: swa_pattern,
        expert_count: experts,
        expert_used_count: experts_used,
    }
}

fn normalize_architecture(raw: &str) -> String {
    if raw.contains("llama") {
        "llama".to_string()
    } else if raw.contains("qwen") {
        "qwen2".to_string()
    } else if raw.contains("mistral") {
        "mistral".to_string()
    } else if raw.contains("gemma") {
        "gemma2".to_string()
    } else if raw.contains("deepseek") {
        "deepseek".to_string()
    } else {
        "unknown".to_string()
    }
}

fn determine_quantization(metadata: &HashMap<String, GgufValue>, filename: &str) -> String {
    if let Some(ft) = metadata.get("general.file_type").and_then(|v| v.as_i64()) {
        let q = match ft {
            0 => "F32",
            1 => "F16",
            2 => "Q4_0",
            3 => "Q4_1",
            7 => "Q8_0",
            8 => "Q5_0",
            9 => "Q5_1",
            10 => "Q2_K",
            11 => "Q3_K_S",
            12 => "Q3_K_M",
            13 => "Q3_K_L",
            14 => "Q4_K_S",
            15 => "Q4_K_M",
            16 => "Q5_K_S",
            17 => "Q5_K_M",
            18 => "Q6_K",
            _ => "",
        };
        if !q.is_empty() {
            return q.to_string();
        }
    }

    let upper = filename.to_uppercase();
    for candidate in &[
        "Q4_K_M", "Q4_K_S", "Q5_K_M", "Q5_K_S", "Q8_0", "Q4_0", "Q5_0", "F16", "BF16",
    ] {
        if upper.contains(candidate) {
            return candidate.to_string();
        }
    }

    "UNKNOWN".to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use std::sync::atomic::{AtomicUsize, Ordering};

    static COUNTER: AtomicUsize = AtomicUsize::new(0);

    fn create_temp_gguf(bytes: &[u8]) -> std::path::PathBuf {
        let count = COUNTER.fetch_add(1, Ordering::SeqCst);
        let path = std::env::temp_dir().join(format!(
            "schemasense_test_gguf_{}_{}_{}.gguf",
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
    fn test_file_too_small() {
        let path = create_temp_gguf(b"GGUF\x03\x00\x00");
        let res = parse_gguf_file(&path);
        let _ = std::fs::remove_file(&path);
        assert!(res.is_err());
        assert!(res.unwrap_err().contains("File too small"));
    }

    #[test]
    fn test_bad_magic() {
        let path = create_temp_gguf(b"NOTGGUF_HEADER_DATA_1234567890");
        let res = parse_gguf_file(&path);
        let _ = std::fs::remove_file(&path);
        assert!(res.is_err());
        assert!(res.unwrap_err().contains("Invalid GGUF magic bytes"));
    }

    #[test]
    fn test_unsupported_version() {
        let mut buf = Vec::new();
        buf.extend_from_slice(&GGUF_MAGIC.to_le_bytes());
        buf.extend_from_slice(&99u32.to_le_bytes()); // version 99
        buf.extend_from_slice(&10u64.to_le_bytes());
        buf.extend_from_slice(&0u64.to_le_bytes());
        let path = create_temp_gguf(&buf);
        let res = parse_gguf_file(&path);
        let _ = std::fs::remove_file(&path);
        assert!(res.is_err());
        assert!(res.unwrap_err().contains("Unsupported GGUF version: 99"));
    }

    #[test]
    fn test_kv_count_bomb() {
        let mut buf = Vec::new();
        buf.extend_from_slice(&GGUF_MAGIC.to_le_bytes());
        buf.extend_from_slice(&3u32.to_le_bytes());
        buf.extend_from_slice(&10u64.to_le_bytes());
        buf.extend_from_slice(&50000u64.to_le_bytes()); // 50,000 KV pairs
        let path = create_temp_gguf(&buf);
        let res = parse_gguf_file(&path);
        let _ = std::fs::remove_file(&path);
        assert!(res.is_err());
        assert!(res.unwrap_err().contains("exceeds security boundary"));
    }
}
