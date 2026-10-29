"""Property-based fuzz testing for SQLGuard AST parser using Hypothesis."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from schemasense.sql_guard import SQLGuard

WRITE_KEYWORDS = [
    "DROP",
    "DELETE",
    "UPDATE",
    "INSERT",
    "ALTER",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
]


@given(
    verb=st.sampled_from(WRITE_KEYWORDS),
    table_name=st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=20),
    suffix=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz0123456789 _=;", min_size=0, max_size=30
    ),
)
@settings(max_examples=50, deadline=None)
def test_hypothesis_write_operations_strictly_rejected(
    verb: str, table_name: str, suffix: str
):
    """Property invariant: Any statement containing write keywords must never be marked valid."""
    query = f"{verb} TABLE {table_name} {suffix}"
    result = SQLGuard.validate(query, allowed_tables=[table_name], dialect="postgres")
    assert result.is_valid is False
    assert result.error_message is not None


@given(
    table=st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=15),
    col=st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=15),
    limit=st.integers(min_value=1, max_value=5000),
)
@settings(max_examples=50, deadline=None)
def test_hypothesis_safe_select_invariant(table: str, col: str, limit: int):
    """Property invariant: Valid SELECT queries against allowed tables are valid or clean syntax error."""
    query = f"SELECT {col} FROM {table} LIMIT {limit};"
    result = SQLGuard.validate(query, allowed_tables=[table], dialect="postgres")
    assert isinstance(result.is_valid, bool)
    if result.is_valid:
        assert table in [t.lower() for t in result.extracted_tables]
