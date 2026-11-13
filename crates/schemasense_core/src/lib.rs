//! SchemaSense Core Native Acceleration Engine.
//!
//! Provides zero-copy, memory-safe Rust primitives for SchemaSense AI,
//! exposed via PyO3 CPython ABI3 bindings.

#![allow(clippy::useless_conversion)]

pub mod graph;
pub mod parsers;
pub mod profiler;
pub mod sql_guard;

use graph::{analyze_dependencies_internal, diff_schemas_internal, SchemaPayload, TablePayload};
use profiler::{compute_numeric_stats_internal, detect_pii_internal};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use std::collections::HashMap;

pyo3::create_exception!(schemasense_core, NativeError, pyo3::exceptions::PyException);

/// Returns the semantic version of the native schemasense-core extension.
#[pyfunction]
fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

/// Returns true confirming that the native Rust acceleration engine is active.
#[pyfunction]
fn is_native_accelerated() -> bool {
    true
}

/// Returns diagnostic build and platform metadata about the compiled extension.
#[pyfunction]
fn build_info(py: Python<'_>) -> PyResult<Bound<'_, PyDict>> {
    let dict = PyDict::new_bound(py);
    dict.set_item("version", env!("CARGO_PKG_VERSION"))?;
    dict.set_item(
        "profile",
        if cfg!(debug_assertions) {
            "debug"
        } else {
            "release"
        },
    )?;
    dict.set_item("abi3", "cp310-abi3")?;
    dict.set_item("rustc_version", "1.100.0")?;
    Ok(dict)
}

/// Generates a structured schema diff between two database schemas serialized as JSON.
#[pyfunction]
fn diff_schemas<'py>(
    py: Python<'py>,
    old_schema_json: &str,
    new_schema_json: &str,
) -> PyResult<Bound<'py, PyDict>> {
    let old_payload: SchemaPayload = serde_json::from_str(old_schema_json)
        .map_err(|e| NativeError::new_err(format!("Invalid old_schema JSON: {e}")))?;
    let new_payload: SchemaPayload = serde_json::from_str(new_schema_json)
        .map_err(|e| NativeError::new_err(format!("Invalid new_schema JSON: {e}")))?;

    let result = py.allow_threads(|| diff_schemas_internal(&old_payload, &new_payload));

    let dict = PyDict::new_bound(py);
    dict.set_item("added_tables", result.added_tables)?;
    dict.set_item("removed_tables", result.removed_tables)?;

    let modified_dict = PyDict::new_bound(py);
    for (tbl, mod_diff) in result.modified_tables {
        let t_dict = PyDict::new_bound(py);
        t_dict.set_item("added_columns", mod_diff.added_columns)?;
        t_dict.set_item("removed_columns", mod_diff.removed_columns)?;
        t_dict.set_item("type_changes", mod_diff.type_changes)?;
        modified_dict.set_item(tbl, t_dict)?;
    }
    dict.set_item("modified_tables", modified_dict)?;

    Ok(dict)
}

/// Analyzes foreign key relationships, cycles, and topological sorting across database tables.
#[pyfunction]
fn analyze_fk_dependencies<'py>(
    py: Python<'py>,
    tables_json: &str,
) -> PyResult<Bound<'py, PyDict>> {
    let tables: HashMap<String, TablePayload> = serde_json::from_str(tables_json)
        .map_err(|e| NativeError::new_err(format!("Invalid tables JSON: {e}")))?;

    let result = py.allow_threads(|| analyze_dependencies_internal(&tables));

    let dict = PyDict::new_bound(py);
    dict.set_item("is_acyclic", result.is_acyclic)?;
    dict.set_item("topological_order", result.topological_order)?;
    dict.set_item("root_tables", result.root_tables)?;
    dict.set_item("leaf_tables", result.leaf_tables)?;

    let cycles_list = PyList::empty_bound(py);
    for cycle in result.cycles {
        cycles_list.append(cycle)?;
    }
    dict.set_item("cycles", cycles_list)?;

    Ok(dict)
}

/// Computes comprehensive numerical column statistics and IQR outliers.
#[pyfunction]
fn compute_numeric_column_stats<'py>(
    py: Python<'py>,
    values: Vec<f64>,
) -> PyResult<Bound<'py, PyDict>> {
    let stats = py.allow_threads(|| compute_numeric_stats_internal(&values));

    let dict = PyDict::new_bound(py);
    dict.set_item("min_value", stats.min_value)?;
    dict.set_item("max_value", stats.max_value)?;
    dict.set_item("mean_value", stats.mean_value)?;
    dict.set_item("median_value", stats.median_value)?;
    dict.set_item("std_value", stats.std_value)?;
    dict.set_item("q25", stats.q25)?;
    dict.set_item("q75", stats.q75)?;
    dict.set_item("iqr", stats.iqr)?;
    dict.set_item("outlier_count", stats.outlier_count)?;
    dict.set_item("outlier_ratio", stats.outlier_ratio)?;

    Ok(dict)
}

/// Scans sample string values to detect sensitive PII entities (email, phone, cards, SSN, IP).
#[pyfunction]
fn detect_column_pii(py: Python<'_>, samples: Vec<String>) -> PyResult<(Option<String>, f64)> {
    let result = py.allow_threads(|| detect_pii_internal(&samples));
    Ok(result)
}

fn manifest_to_pydict<'py>(
    py: Python<'py>,
    manifest: &parsers::ModelManifestPayload,
) -> PyResult<Bound<'py, PyDict>> {
    let dict = PyDict::new_bound(py);
    dict.set_item("model_id", &manifest.model_id)?;
    dict.set_item("file_path", &manifest.file_path)?;
    dict.set_item("file_size_bytes", manifest.file_size_bytes)?;
    dict.set_item("format", &manifest.format)?;
    dict.set_item("tensor_count", manifest.tensor_count)?;
    dict.set_item("quantization_type", &manifest.quantization_type)?;
    dict.set_item("license_str", &manifest.license_str)?;
    dict.set_item("untrusted_chat_template", &manifest.untrusted_chat_template)?;
    dict.set_item("provenance_notes", &manifest.provenance_notes)?;

    if let Some(ref hp) = manifest.hyperparameters {
        let hp_dict = PyDict::new_bound(py);
        hp_dict.set_item("architecture", &hp.architecture)?;
        hp_dict.set_item("raw_architecture_name", &hp.raw_architecture_name)?;
        hp_dict.set_item("layer_count", hp.layer_count)?;
        hp_dict.set_item("embedding_length", hp.embedding_length)?;
        hp_dict.set_item("feed_forward_length", hp.feed_forward_length)?;
        hp_dict.set_item("head_count", hp.head_count)?;
        hp_dict.set_item("head_count_kv", hp.head_count_kv)?;
        hp_dict.set_item("key_length", hp.key_length)?;
        hp_dict.set_item("value_length", hp.value_length)?;
        hp_dict.set_item("context_length", hp.context_length)?;
        hp_dict.set_item("sliding_window", hp.sliding_window)?;
        hp_dict.set_item("sliding_window_layers", hp.sliding_window_layers)?;
        hp_dict.set_item("sliding_window_pattern", &hp.sliding_window_pattern)?;
        hp_dict.set_item("expert_count", hp.expert_count)?;
        hp_dict.set_item("expert_used_count", hp.expert_used_count)?;
        dict.set_item("hyperparameters", hp_dict)?;
    } else {
        dict.set_item("hyperparameters", py.None())?;
    }

    Ok(dict)
}

/// Parses binary GGUF v2/v3 header metadata with bounded safety limits.
#[pyfunction]
fn parse_gguf_metadata<'py>(py: Python<'py>, file_path: &str) -> PyResult<Bound<'py, PyDict>> {
    let manifest = py
        .allow_threads(|| parsers::parse_gguf_file(file_path))
        .map_err(NativeError::new_err)?;
    manifest_to_pydict(py, &manifest)
}

/// Parses SafeTensors JSON header and merges companion config.json if present.
#[pyfunction]
fn parse_safetensors_metadata<'py>(
    py: Python<'py>,
    file_path: &str,
) -> PyResult<Bound<'py, PyDict>> {
    let manifest = py
        .allow_threads(|| parsers::parse_safetensors_file(file_path))
        .map_err(NativeError::new_err)?;
    manifest_to_pydict(py, &manifest)
}

/// Validates an SQL query against single-statement read-only rules using native sqlparser-rs AST.
#[pyfunction]
#[pyo3(signature = (query, dialect="postgres", allowed_tables=None))]
fn validate_sql<'py>(
    py: Python<'py>,
    query: &str,
    dialect: &str,
    allowed_tables: Option<Vec<String>>,
) -> PyResult<Bound<'py, PyDict>> {
    let res = py.allow_threads(|| {
        let allowed_slice = allowed_tables.as_deref();
        sql_guard::validate_sql_internal(query, dialect, allowed_slice)
    });

    let dict = PyDict::new_bound(py);
    dict.set_item("is_valid", res.is_valid)?;
    dict.set_item("error_message", res.error_message)?;
    dict.set_item("extracted_tables", res.extracted_tables)?;
    dict.set_item("normalized_sql", res.normalized_sql)?;
    Ok(dict)
}

/// The schemasense_core Python module definition.
#[pymodule]
fn schemasense_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(version, m)?)?;
    m.add_function(wrap_pyfunction!(is_native_accelerated, m)?)?;
    m.add_function(wrap_pyfunction!(build_info, m)?)?;
    m.add_function(wrap_pyfunction!(diff_schemas, m)?)?;
    m.add_function(wrap_pyfunction!(analyze_fk_dependencies, m)?)?;
    m.add_function(wrap_pyfunction!(compute_numeric_column_stats, m)?)?;
    m.add_function(wrap_pyfunction!(detect_column_pii, m)?)?;
    m.add_function(wrap_pyfunction!(parse_gguf_metadata, m)?)?;
    m.add_function(wrap_pyfunction!(parse_safetensors_metadata, m)?)?;
    m.add_function(wrap_pyfunction!(validate_sql, m)?)?;
    m.add("NativeError", m.py().get_type_bound::<NativeError>())?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_native_version() {
        assert_eq!(version(), "0.1.0");
    }

    #[test]
    fn test_is_accelerated() {
        assert!(is_native_accelerated());
    }
}
