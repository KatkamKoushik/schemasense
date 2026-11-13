"""Typed tool registry and execution implementations for SchemaSense 2.0 Agent lifecycle."""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine

from schemasense.agent.state import ToolInvocationResult
from schemasense.profiler import detect_column_pii
from schemasense.schema_inspector import inspect_database_schema
from schemasense.sql_guard import SQLGuard, execute_safe_query

logger = logging.getLogger("schemasense.agent.tools")

# ─────────────────────────────────────────────────────────────
# SERVER-SIDE CONNECTION ENGINE REGISTRY (Zero Secret Leakage)
# ─────────────────────────────────────────────────────────────
_ENGINE_REGISTRY: dict[str, Engine] = {}
_REGISTRY_LOCK = threading.RLock()


def register_connection_engine(connection_id: str, engine: Engine) -> None:
    """Binds an active SQLAlchemy Engine to a connection reference ID on the server.

    This ensures agent state and LangGraph checkpoints only ever store the opaque
    `connection_id`, completely avoiding leakage of database credentials.
    """
    with _REGISTRY_LOCK:
        _ENGINE_REGISTRY[connection_id] = engine


def unregister_connection_engine(connection_id: str) -> None:
    """Removes a connection engine binding."""
    with _REGISTRY_LOCK:
        _ENGINE_REGISTRY.pop(connection_id, None)


def get_connection_engine(connection_id: str) -> Engine | None:
    """Retrieves an active SQLAlchemy Engine for a given connection reference ID."""
    with _REGISTRY_LOCK:
        return _ENGINE_REGISTRY.get(connection_id)


def clear_connection_engines() -> None:
    """Clears all registered engines (used primarily in test tear-down)."""
    with _REGISTRY_LOCK:
        _ENGINE_REGISTRY.clear()


# ─────────────────────────────────────────────────────────────
# EXECUTION CONTEXT & BASE TOOL
# ─────────────────────────────────────────────────────────────
@dataclass
class ExecutionContext:
    """Security and authorization context under which an agent tool executes."""

    tenant_id: str
    user_id: str
    user_roles: list[str]
    connection_id: str
    dry_run: bool = False


class BaseAgentTool(ABC):
    """Abstract base class for typed agent tools."""

    name: str
    description: str
    is_high_risk: bool = False

    @abstractmethod
    def execute(
        self,
        parameters: dict[str, Any],
        context: ExecutionContext,
        idempotency_key: str = "",
    ) -> ToolInvocationResult:
        """Executes the tool logic within the authorized security context."""
        raise NotImplementedError


# ─────────────────────────────────────────────────────────────
# TOOL IMPLEMENTATIONS
# ─────────────────────────────────────────────────────────────
class InspectSchemaTool(BaseAgentTool):
    """Inspects database tables, columns, indexes, and relationships without dumping data."""

    name = "inspect_schema"
    description = (
        "Inspects database schema structure, tables, columns, and foreign keys."
    )
    is_high_risk = False

    def execute(
        self,
        parameters: dict[str, Any],
        context: ExecutionContext,
        idempotency_key: str = "",
    ) -> ToolInvocationResult:
        start_time = time.perf_counter()
        engine = get_connection_engine(context.connection_id)
        if engine is None:
            return ToolInvocationResult(
                tool_name=self.name,
                idempotency_key=idempotency_key,
                success=False,
                error=f"No active engine registered for connection_id '{context.connection_id}'.",
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )

        try:
            target_tables = parameters.get("table_names")
            schema_data = inspect_database_schema(engine)

            discovered_tables: list[str] = list(schema_data.tables.keys())
            if target_tables:
                filtered_tables = [
                    t for t in discovered_tables if t in set(target_tables)
                ]
            else:
                filtered_tables = discovered_tables

            table_summaries = {}
            for t_name in filtered_tables:
                table_info = schema_data.tables[t_name]
                table_summaries[t_name] = {
                    "columns": [
                        {
                            "name": c.name,
                            "type": str(c.data_type),
                            "nullable": c.nullable,
                            "is_pk": c.is_primary_key,
                        }
                        for c in table_info.columns
                    ],
                    "primary_key": table_info.primary_key,
                    "column_count": len(table_info.columns),
                    "foreign_keys": [
                        {
                            "constrained_columns": fk.constrained_columns,
                            "referred_table": fk.referred_table,
                            "referred_columns": fk.referred_columns,
                        }
                        for fk in table_info.foreign_keys
                    ],
                }

            return ToolInvocationResult(
                tool_name=self.name,
                idempotency_key=idempotency_key,
                success=True,
                output={
                    "database_name": schema_data.database_name,
                    "dialect": schema_data.dialect,
                    "table_count": len(filtered_tables),
                    "tables": table_summaries,
                },
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )
        except Exception as e:
            logger.exception("Error executing inspect_schema: %s", e)
            return ToolInvocationResult(
                tool_name=self.name,
                idempotency_key=idempotency_key,
                success=False,
                error=str(e),
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )


class ProfileColumnTool(BaseAgentTool):
    """Profiles statistical properties and distribution of a specified column."""

    name = "profile_column"
    description = (
        "Profiles column statistical distribution, null ratios, and cardinality."
    )
    is_high_risk = False

    def execute(
        self,
        parameters: dict[str, Any],
        context: ExecutionContext,
        idempotency_key: str = "",
    ) -> ToolInvocationResult:
        start_time = time.perf_counter()
        table_name = parameters.get("table_name")
        column_name = parameters.get("column_name")
        max_rows = min(int(parameters.get("max_sample_rows", 1000)), 5000)

        if not table_name or not column_name:
            return ToolInvocationResult(
                tool_name=self.name,
                idempotency_key=idempotency_key,
                success=False,
                error="Both 'table_name' and 'column_name' must be provided.",
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )

        engine = get_connection_engine(context.connection_id)
        if engine is None:
            return ToolInvocationResult(
                tool_name=self.name,
                idempotency_key=idempotency_key,
                success=False,
                error=f"No active engine registered for connection_id '{context.connection_id}'.",
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )

        try:
            # Query sample values securely using SQLGuard bounded query
            query = f"SELECT {column_name} FROM {table_name} LIMIT {max_rows}"  # noqa: S608
            df, _ = execute_safe_query(
                engine, query, dialect="sqlite", max_rows=max_rows
            )
            series = df[column_name] if column_name in df.columns else None

            if series is None:
                return ToolInvocationResult(
                    tool_name=self.name,
                    idempotency_key=idempotency_key,
                    success=False,
                    error=f"Column '{column_name}' not found in query results.",
                    duration_ms=(time.perf_counter() - start_time) * 1000,
                )

            total_count = len(series)
            null_count = int(series.isna().sum())
            distinct_count = int(series.nunique())
            null_percentage = (
                round((null_count / total_count) * 100, 2) if total_count > 0 else 0.0
            )

            # Detect PII sample if text
            pii_type, pii_conf = detect_column_pii(series.dropna().tolist())

            return ToolInvocationResult(
                tool_name=self.name,
                idempotency_key=idempotency_key,
                success=True,
                output={
                    "table_name": table_name,
                    "column_name": column_name,
                    "sample_size": total_count,
                    "null_count": null_count,
                    "null_percentage": null_percentage,
                    "distinct_count": distinct_count,
                    "pii_detected": pii_type,
                    "pii_confidence": pii_conf,
                },
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )
        except Exception as e:  # noqa: BLE001
            return ToolInvocationResult(
                tool_name=self.name,
                idempotency_key=idempotency_key,
                success=False,
                error=str(e),
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )


class ScanPIITool(BaseAgentTool):
    """Scans sample string values for PII patterns using regex and native SIMD acceleration."""

    name = "scan_pii"
    description = (
        "Scans string values for sensitive PII entities (email, phone, cards, SSN, IP)."
    )
    is_high_risk = False

    def execute(
        self,
        parameters: dict[str, Any],
        context: ExecutionContext,
        idempotency_key: str = "",
    ) -> ToolInvocationResult:
        start_time = time.perf_counter()
        samples = parameters.get("samples", [])
        if not isinstance(samples, list):
            return ToolInvocationResult(
                tool_name=self.name,
                idempotency_key=idempotency_key,
                success=False,
                error="'samples' parameter must be a list of values.",
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )

        try:
            pii_type, confidence = detect_column_pii(samples)
            return ToolInvocationResult(
                tool_name=self.name,
                idempotency_key=idempotency_key,
                success=True,
                output={
                    "samples_checked": len(samples),
                    "pii_detected": pii_type,
                    "confidence": confidence,
                    "is_sensitive": pii_type is not None,
                },
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )
        except Exception as e:  # noqa: BLE001
            return ToolInvocationResult(
                tool_name=self.name,
                idempotency_key=idempotency_key,
                success=False,
                error=str(e),
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )


class ValidateSQLTool(BaseAgentTool):
    """Performs AST parsing, forbidden function detection, and double-lock verification."""

    name = "validate_sql"
    description = (
        "Validates SQL queries against AST security rules and schema fidelity."
    )
    is_high_risk = False

    def execute(
        self,
        parameters: dict[str, Any],
        context: ExecutionContext,
        idempotency_key: str = "",
    ) -> ToolInvocationResult:
        start_time = time.perf_counter()
        sql_query = parameters.get("sql_query", "")
        dialect = parameters.get("dialect", "postgres")
        allowed_tables = parameters.get("allowed_tables")

        try:
            val_result = SQLGuard.validate(
                sql_query,
                dialect=dialect,
                allowed_tables=allowed_tables,
            )
            return ToolInvocationResult(
                tool_name=self.name,
                idempotency_key=idempotency_key,
                success=val_result.is_valid,
                output={
                    "is_valid": val_result.is_valid,
                    "error_message": val_result.error_message,
                    "extracted_tables": val_result.extracted_tables,
                    "normalized_sql": val_result.normalized_sql,
                },
                error=val_result.error_message if not val_result.is_valid else None,
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )
        except Exception as e:  # noqa: BLE001
            return ToolInvocationResult(
                tool_name=self.name,
                idempotency_key=idempotency_key,
                success=False,
                error=str(e),
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )


class ExecuteSafeQueryTool(BaseAgentTool):
    """Executes a bounded, read-only SELECT query against the registered target database."""

    name = "execute_query"
    description = "Executes read-only queries with strict timeout and row limits."
    is_high_risk = True  # Always gated by pre-execution human approval!

    def execute(
        self,
        parameters: dict[str, Any],
        context: ExecutionContext,
        idempotency_key: str = "",
    ) -> ToolInvocationResult:
        start_time = time.perf_counter()
        sql_query = parameters.get("sql_query", "")
        dialect = parameters.get("dialect", "postgres")
        max_rows = min(int(parameters.get("max_rows", 100)), 1000)

        engine = get_connection_engine(context.connection_id)
        if engine is None:
            return ToolInvocationResult(
                tool_name=self.name,
                idempotency_key=idempotency_key,
                success=False,
                error=f"No active engine registered for connection_id '{context.connection_id}'.",
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )

        try:
            df, _ = execute_safe_query(
                engine=engine,
                query=sql_query,
                dialect=dialect,
                max_rows=max_rows,
            )
            return ToolInvocationResult(
                tool_name=self.name,
                idempotency_key=idempotency_key,
                success=True,
                output={
                    "row_count": len(df),
                    "columns": list(df.columns),
                    "rows": df.to_dict(orient="records"),
                },
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )
        except Exception as e:  # noqa: BLE001
            return ToolInvocationResult(
                tool_name=self.name,
                idempotency_key=idempotency_key,
                success=False,
                error=str(e),
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )


# ─────────────────────────────────────────────────────────────
# TOOL REGISTRY
# ─────────────────────────────────────────────────────────────
class ToolRegistry:
    """Thread-safe registry for agent tools."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseAgentTool] = {}
        self._lock = threading.RLock()

    def register(self, tool: BaseAgentTool) -> None:
        with self._lock:
            self._tools[tool.name] = tool

    def get(self, name: str) -> BaseAgentTool | None:
        with self._lock:
            return self._tools.get(name)

    def list_tools(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "name": t.name,
                    "description": t.description,
                    "is_high_risk": t.is_high_risk,
                }
                for t in self._tools.values()
            ]


# Create default pre-populated registry
default_tool_registry = ToolRegistry()
default_tool_registry.register(InspectSchemaTool())
default_tool_registry.register(ProfileColumnTool())
default_tool_registry.register(ScanPIITool())
default_tool_registry.register(ValidateSQLTool())
default_tool_registry.register(ExecuteSafeQueryTool())
