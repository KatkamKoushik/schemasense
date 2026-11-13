//! Common payloads and data transfer structures for model parsers.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ModelHyperparametersPayload {
    pub architecture: String,
    pub raw_architecture_name: String,
    pub layer_count: Option<i64>,
    pub embedding_length: Option<i64>,
    pub feed_forward_length: Option<i64>,
    pub head_count: Option<i64>,
    pub head_count_kv: Option<i64>,
    pub key_length: Option<i64>,
    pub value_length: Option<i64>,
    pub context_length: Option<i64>,
    pub sliding_window: Option<i64>,
    pub sliding_window_layers: Option<i64>,
    pub sliding_window_pattern: Option<String>,
    pub expert_count: Option<i64>,
    pub expert_used_count: Option<i64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ModelManifestPayload {
    pub model_id: String,
    pub file_path: String,
    pub file_size_bytes: u64,
    pub format: String,
    pub hyperparameters: Option<ModelHyperparametersPayload>,
    pub tensor_count: u64,
    pub quantization_type: String,
    pub license_str: Option<String>,
    pub untrusted_chat_template: Option<String>,
    pub provenance_notes: Vec<String>,
}
