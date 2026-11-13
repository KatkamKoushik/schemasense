"""Property-based fuzz testing for SQLGuard AST parser using Hypothesis."""

from __future__ import annotations

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from schemasense.sql_guard import SQLGuard

RESERVED_SQL_KEYWORDS = {
    "select",
    "from",
    "where",
    "case",
    "when",
    "then",
    "else",
    "end",
    "and",
    "or",
    "not",
    "limit",
    "group",
    "order",
    "by",
    "having",
    "join",
    "on",
    "as",
    "is",
    "null",
    "in",
    "union",
    "all",
    "table",
    "distinct",
    "true",
    "false",
    "like",
    "ilike",
    "between",
    "user",
}

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


@given(
    table=st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=15),
    col=st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=15),
    predicate_val=st.integers(min_value=0, max_value=10000),
    dialect=st.sampled_from(["postgres", "mysql", "sqlite"]),
)
@settings(max_examples=50, deadline=None)
def test_hypothesis_differential_equivalence(
    table: str, col: str, predicate_val: int, dialect: str
):
    """Property invariant: Python and Native Rust SQLGuard produce identical validity verdicts."""
    assume(
        table.lower() not in RESERVED_SQL_KEYWORDS
        and not table.startswith("_")
        and not table.isdigit()
    )
    assume(
        col.lower() not in RESERVED_SQL_KEYWORDS
        and not col.startswith("_")
        and not col.isdigit()
    )
    from schemasense import is_native_core_available

    if not is_native_core_available():
        return

    query = f"SELECT {col} FROM {table} WHERE id = {predicate_val};"
    res_py = SQLGuard._validate_python(query, dialect=dialect, allowed_tables=[table])
    res_native = SQLGuard.validate_native(
        query, dialect=dialect, allowed_tables=[table]
    )

    assert res_py.is_valid == res_native.is_valid
    if res_py.is_valid:
        assert [t.lower() for t in res_py.extracted_tables] == [
            t.lower() for t in res_native.extracted_tables
        ]


@given(
    verb=st.sampled_from(WRITE_KEYWORDS),
    table=st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=15),
    dialect=st.sampled_from(["postgres", "mysql", "sqlite"]),
)
@settings(max_examples=50, deadline=None)
def test_hypothesis_differential_adversarial_rejection(
    verb: str, table: str, dialect: str
):
    """Property invariant: Both Python and Native engines strictly reject write operations."""
    from schemasense import is_native_core_available

    if not is_native_core_available():
        return

    query = f"{verb} TABLE {table};"
    res_py = SQLGuard._validate_python(query, dialect=dialect, allowed_tables=[table])
    res_native = SQLGuard.validate_native(
        query, dialect=dialect, allowed_tables=[table]
    )

    assert res_py.is_valid is False
    assert res_native.is_valid is False
