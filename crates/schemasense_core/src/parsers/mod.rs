//! Binary model format parsers (GGUF and SafeTensors).

pub mod gguf;
pub mod safetensors;
pub mod types;

pub use gguf::parse_gguf_file;
pub use safetensors::parse_safetensors_file;
pub use types::{ModelHyperparametersPayload, ModelManifestPayload};
