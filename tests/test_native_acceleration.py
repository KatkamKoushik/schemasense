"""Tests for Phase 2: Schema Diffing, Foreign-Key Graph DAG, and Profiler Acceleration."""

from __future__ import annotations

import numpy as np
import pandas as pd

from schemasense.profiler import detect_column_pii, profile_dataframe
from schemasense.schema_inspector import (
    ColumnInfo,
    DatabaseSchema,
    ForeignKeyInfo,
    TableSchema,
    analyze_table_dependencies,
    diff_database_schemas,
)


def test_schema_diff_equivalence_native_vs_python(monkeypatch):
    """Verifies that native Rust diff_database_schemas produces identical output to pure-Python."""
    # Construct 2 schemas with changes
    cols_a1 = [
        ColumnInfo(name="id", data_type="INTEGER", nullable=False),
        ColumnInfo(name="username", data_type="VARCHAR(50)", nullable=False),
        ColumnInfo(name="status", data_type="VARCHAR(20)", nullable=True),
    ]
    cols_b1 = [
        ColumnInfo(name="id", data_type="BIGINT", nullable=False),  # type change
        ColumnInfo(name="username", data_type="VARCHAR(50)", nullable=False),
        ColumnInfo(name="created_at", data_type="TIMESTAMP", nullable=True),  # added
        # status removed
    ]
    t1_a = TableSchema(name="users", columns=cols_a1)
    t1_b = TableSchema(name="users", columns=cols_b1)

    t2 = TableSchema(
        name="legacy_table",
        columns=[ColumnInfo(name="id", data_type="INT", nullable=False)],
    )
    t3 = TableSchema(
        name="new_audit_log",
        columns=[ColumnInfo(name="id", data_type="UUID", nullable=False)],
    )

    schema_a = DatabaseSchema(
        database_name="prod",
        dialect="postgres",
        tables={"users": t1_a, "legacy_table": t2},
    )
    schema_b = DatabaseSchema(
        database_name="prod",
        dialect="postgres",
        tables={"users": t1_b, "new_audit_log": t3},
    )

    # 1. Native execution
    diff_native = diff_database_schemas(schema_a, schema_b)

    # 2. Force pure-Python execution
    monkeypatch.setenv("SCHEMASENSE_DISABLE_NATIVE_CORE", "1")
    # Re-evaluate with fallback
    diff_py = diff_database_schemas(schema_a, schema_b)

    assert diff_native["added_tables"] == ["new_audit_log"]
    assert diff_native["removed_tables"] == ["legacy_table"]
    assert "users" in diff_native["modified_tables"]

    user_diff = diff_native["modified_tables"]["users"]
    assert user_diff["added_columns"] == ["created_at"]
    assert user_diff["removed_columns"] == ["status"]
    assert user_diff["type_changes"] == ["id (INTEGER -> BIGINT)"]

    # Verify exact equivalence between native and python outputs
    assert diff_native["added_tables"] == diff_py["added_tables"]
    assert diff_native["removed_tables"] == diff_py["removed_tables"]
    assert (
        diff_native["modified_tables"]["users"] == diff_py["modified_tables"]["users"]
    )


def test_table_dependency_dag_and_topological_sort():
    """Verifies foreign key DAG analysis, root/leaf table identification, and topological ordering."""
    # customers -> orders -> order_items -> products
    # root tables: customers, products (no foreign keys)
    # leaf tables: order_items (not referenced by anything)
    tables = {
        "customers": TableSchema(name="customers", columns=[]),
        "products": TableSchema(name="products", columns=[]),
        "orders": TableSchema(
            name="orders",
            columns=[],
            foreign_keys=[
                ForeignKeyInfo(
                    constrained_columns=["customer_id"],
                    referred_table="customers",
                    referred_columns=["id"],
                )
            ],
        ),
        "order_items": TableSchema(
            name="order_items",
            columns=[],
            foreign_keys=[
                ForeignKeyInfo(
                    constrained_columns=["order_id"],
                    referred_table="orders",
                    referred_columns=["id"],
                ),
                ForeignKeyInfo(
                    constrained_columns=["product_id"],
                    referred_table="products",
                    referred_columns=["id"],
                ),
            ],
        ),
    }

    schema = DatabaseSchema(
        database_name="retail_db", dialect="postgres", tables=tables
    )
    analysis = analyze_table_dependencies(schema)

    assert analysis["is_acyclic"] is True
    assert set(analysis["root_tables"]) == {"customers", "products"}
    assert analysis["leaf_tables"] == ["order_items"]
    assert len(analysis["cycles"]) == 0

    order = analysis["topological_order"]
    assert len(order) == 4
    # customers and products must appear before orders and order_items
    assert order.index("customers") < order.index("orders")
    assert order.index("orders") < order.index("order_items")
    assert order.index("products") < order.index("order_items")


def test_table_dependency_cycle_detection():
    """Verifies that circular foreign-key relationships are flagged and isolated."""
    # table_a references table_b, and table_b references table_a
    tables = {
        "table_a": TableSchema(
            name="table_a",
            columns=[],
            foreign_keys=[
                ForeignKeyInfo(
                    constrained_columns=["b_id"],
                    referred_table="table_b",
                    referred_columns=["id"],
                )
            ],
        ),
        "table_b": TableSchema(
            name="table_b",
            columns=[],
            foreign_keys=[
                ForeignKeyInfo(
                    constrained_columns=["a_id"],
                    referred_table="table_a",
                    referred_columns=["id"],
                )
            ],
        ),
    }

    schema = DatabaseSchema(
        database_name="cyclic_db", dialect="postgres", tables=tables
    )
    analysis = analyze_table_dependencies(schema)

    assert analysis["is_acyclic"] is False
    assert len(analysis["cycles"]) > 0
    cycle_nodes = set(analysis["cycles"][0])
    assert cycle_nodes == {"table_a", "table_b"}


def test_profiler_numeric_stats_and_iqr_outliers():
    """Verifies that native numeric stats and IQR outlier calculation match expected statistical bounds."""
    np.random.seed(42)
    normal_data = np.random.normal(loc=100.0, scale=10.0, size=5000).tolist()
    # Explicitly inject 5 severe outliers
    outliers = [9999.0, 8888.0, 7777.0, -5000.0, -9000.0]
    all_data = normal_data + outliers

    df = pd.DataFrame({"metrics": all_data})
    report = profile_dataframe(df)

    assert len(report.columns) == 1
    col_prof = report.columns[0]
    assert col_prof.outlier_count >= 5
    assert col_prof.min_value is not None and col_prof.min_value <= -9000.0
    assert col_prof.max_value is not None and col_prof.max_value >= 9999.0
    assert 95.0 <= col_prof.mean_value <= 115.0


def test_pii_scanner_all_patterns():
    """Verifies that native PII scanner detects EMAIL, PHONE, CREDIT_CARD, SSN, and IP_ADDRESS."""
    cases = [
        (
            ["user1@example.com", "user2@corp.org", "test.user@sub.domain.co"],
            "EMAIL",
        ),
        (["+1-555-123-4567", "555-987-6543", "(555) 234-5678"], "PHONE"),
        (["4111111111111111", "5500000000000004", "378282246310005"], "CREDIT_CARD"),
        (["123-45-6789", "987-65-4321", "000-12-3456"], "SSN"),
        (["192.168.1.1", "10.0.0.1", "172.16.254.1"], "IP_ADDRESS"),
    ]

    for samples, expected_type in cases:
        pii_type, ratio = detect_column_pii(samples)
        assert pii_type == expected_type, f"Failed for {expected_type}: got {pii_type}"
        assert ratio >= 0.40


def test_native_gguf_parsing_and_fallback(tmp_path, monkeypatch):
    """Verifies that native Rust GGUF parser extracts parameters matching Python fallback."""
    from schemasense.runtime.parsers.gguf import GGUFParser
    from schemasense.runtime.types import ModelArchitecture, ModelFormat
    from tests.test_runtime_parsers import build_synthetic_gguf_v3

    gguf_bytes = build_synthetic_gguf_v3(
        architecture="qwen2",
        block_count=32,
        embedding_length=4096,
        head_count=32,
        head_count_kv=8,
        context_length=65536,
        sliding_window=8192,
        license_str="Apache-2.0",
        file_type=15,
    )
    p = tmp_path / "model.gguf"
    p.write_bytes(gguf_bytes)

    # 1. Native execution
    manifest_native = GGUFParser.read_manifest(p)
    assert manifest_native.format == ModelFormat.GGUF
    assert manifest_native.hyperparameters.architecture == ModelArchitecture.QWEN2
    assert manifest_native.hyperparameters.layer_count == 32
    assert manifest_native.hyperparameters.embedding_length == 4096
    assert manifest_native.hyperparameters.head_count == 32
    assert manifest_native.hyperparameters.head_count_kv == 8
    assert manifest_native.hyperparameters.context_length == 65536
    assert manifest_native.hyperparameters.sliding_window == 8192
    assert manifest_native.quantization_type == "Q4_K_M"
    assert manifest_native.license_str == "Apache-2.0"

    # 2. Python fallback execution
    monkeypatch.setenv("SCHEMASENSE_DISABLE_NATIVE_CORE", "1")
    manifest_py = GGUFParser.read_manifest(p)

    # Verify exact parity
    assert manifest_native.model_id == manifest_py.model_id
    assert manifest_native.format == manifest_py.format
    assert manifest_native.tensor_count == manifest_py.tensor_count
    assert manifest_native.quantization_type == manifest_py.quantization_type
    assert manifest_native.license_str == manifest_py.license_str
    assert (
        manifest_native.hyperparameters.layer_count
        == manifest_py.hyperparameters.layer_count
    )
    assert (
        manifest_native.hyperparameters.embedding_length
        == manifest_py.hyperparameters.embedding_length
    )
    assert (
        manifest_native.hyperparameters.context_length
        == manifest_py.hyperparameters.context_length
    )


def test_native_safetensors_parsing_and_fallback(tmp_path, monkeypatch):
    """Verifies that native Rust SafeTensors parser extracts parameters matching Python fallback."""
    import json
    import struct

    from schemasense.runtime.parsers.safetensors import SafeTensorsParser
    from schemasense.runtime.types import ModelArchitecture, ModelFormat

    tensors = {
        "model.layers.0.weight": {
            "dtype": "BF16",
            "shape": [10, 10],
            "data_offsets": [0, 200],
        },
        "__metadata__": {"license": "MIT", "chat_template": "{% for m in messages %}"},
    }
    json_bytes = json.dumps(tensors).encode("utf-8")
    st_bytes = struct.pack("<Q", len(json_bytes)) + json_bytes + (b"\x00" * 512)
    st_file = tmp_path / "model.safetensors"
    st_file.write_bytes(st_bytes)

    # Write companion config.json
    config_data = {
        "model_type": "llama",
        "num_hidden_layers": 32,
        "hidden_size": 4096,
        "num_attention_heads": 32,
        "num_key_value_heads": 8,
        "max_position_embeddings": 8192,
    }
    (tmp_path / "config.json").write_text(json.dumps(config_data), encoding="utf-8")

    # 1. Native execution
    manifest_native = SafeTensorsParser.read_manifest(st_file)
    assert manifest_native.format == ModelFormat.SAFETENSORS
    assert manifest_native.tensor_count == 1
    assert manifest_native.quantization_type == "BF16"
    assert manifest_native.license_str == "MIT"
    assert manifest_native.hyperparameters.architecture == ModelArchitecture.LLAMA
    assert manifest_native.hyperparameters.layer_count == 32
    assert manifest_native.hyperparameters.embedding_length == 4096

    # 2. Python fallback execution
    monkeypatch.setenv("SCHEMASENSE_DISABLE_NATIVE_CORE", "1")
    manifest_py = SafeTensorsParser.read_manifest(st_file)

    # Verify parity
    assert manifest_native.format == manifest_py.format
    assert manifest_native.tensor_count == manifest_py.tensor_count
    assert manifest_native.quantization_type == manifest_py.quantization_type
    assert manifest_native.license_str == manifest_py.license_str
    assert (
        manifest_native.hyperparameters.layer_count
        == manifest_py.hyperparameters.layer_count
    )
    assert (
        manifest_native.hyperparameters.embedding_length
        == manifest_py.hyperparameters.embedding_length
    )


def test_sqlguard_native_validation_direct():
    """Verifies that SQLGuard.validate_native invokes Rust AST security validator directly."""
    import pytest

    import schemasense

    if not schemasense.is_native_core_available():
        pytest.skip(
            "schemasense-core native extension not available in this environment"
        )

    from schemasense.sql_guard import SQLGuard

    # 1. Valid SELECT
    res_valid = SQLGuard.validate_native(
        "SELECT id, name FROM customers WHERE id = 10;",
        dialect="postgres",
        allowed_tables=["customers"],
    )
    assert res_valid.is_valid
    assert res_valid.extracted_tables == ["customers"]
    assert "SELECT" in res_valid.normalized_sql

    # 2. Adversarial DROP rejected
    res_drop = SQLGuard.validate_native(
        "DROP TABLE customers;",
        dialect="postgres",
        allowed_tables=["customers"],
    )
    assert not res_drop.is_valid
    assert "Drop" in res_drop.error_message

    # 3. Disallowed function rejected
    res_func = SQLGuard.validate_native(
        "SELECT pg_read_file('/etc/passwd');",
        dialect="postgres",
        allowed_tables=["customers"],
    )
    assert not res_func.is_valid
    assert "pg_read_file" in res_func.error_message

    # 4. CTE alias resolution
    cte_query = """
    WITH regional_users AS (SELECT * FROM customers WHERE city = 'Delhi')
    SELECT * FROM regional_users;
    """
    res_cte = SQLGuard.validate_native(
        cte_query, dialect="postgres", allowed_tables=["customers"]
    )
    assert res_cte.is_valid
    assert res_cte.extracted_tables == ["customers"]


def test_sqlguard_strict_conjunction_double_lock(monkeypatch):
    """Verifies Stage C: Strict Conjunction requires BOTH Python and Native validators to approve."""
    from schemasense.sql_guard import SQLGuard

    # Legitimate query with double lock enabled
    monkeypatch.setenv("SCHEMASENSE_SQLGUARD_DOUBLE_LOCK", "1")
    res_legit = SQLGuard.validate(
        "SELECT id, name FROM customers;",
        dialect="postgres",
        allowed_tables=["customers"],
    )
    res_valid_both = res_legit.is_valid
    assert res_valid_both

    # Adversarial query with double lock enabled
    res_adv = SQLGuard.validate(
        "DROP TABLE customers;",
        dialect="postgres",
        allowed_tables=["customers"],
    )
    assert not res_adv.is_valid
