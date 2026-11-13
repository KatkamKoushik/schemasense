"""Zero-dependency Prometheus Metrics Registry & Formatter for SchemaSense 2.0.

Produces standard Prometheus text exposition format (version 0.0.4) while enforcing
privacy-preserving telemetry by forbidding raw SQL and secrets in metric labels
(Mandatory Correction 18).
"""

from __future__ import annotations

import threading
from typing import Any, Sequence

DEFAULT_HISTOGRAM_BUCKETS: tuple[float, ...] = (
    0.01,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
)


def _escape_label_value(val: Any) -> str:
    """Escapes Prometheus label value characters (quotes, backslashes, newlines)."""
    s = str(val)
    s = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return s


def _format_labels(labels: dict[str, Any]) -> str:
    if not labels:
        return ""
    sorted_items = sorted(labels.items())
    parts = [f'{k}="{_escape_label_value(v)}"' for k, v in sorted_items]
    return "{" + ",".join(parts) + "}"


class Metric:
    def __init__(self, name: str, doc: str, metric_type: str):
        self.name = name
        self.doc = doc
        self.metric_type = metric_type

    def collect(self) -> list[str]:
        return []


class Counter(Metric):
    def __init__(self, name: str, doc: str):
        super().__init__(name, doc, "counter")
        self._values: dict[tuple[tuple[str, str], ...], float] = {}
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0, **labels: Any) -> None:
        if amount < 0:
            raise ValueError(
                "Counters can only be incremented by non-negative amounts."
            )
        key = tuple(sorted((k, str(v)) for k, v in labels.items()))
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def collect(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.doc}", f"# TYPE {self.name} counter"]
        with self._lock:
            for key, val in sorted(self._values.items()):
                label_dict = dict(key)
                label_str = _format_labels(label_dict)
                # Render integers cleanly without decimal point if integer
                val_str = f"{int(val)}" if val.is_integer() else f"{val:.6g}"
                lines.append(f"{self.name}{label_str} {val_str}")
        return lines


class Gauge(Metric):
    def __init__(self, name: str, doc: str):
        super().__init__(name, doc, "gauge")
        self._values: dict[tuple[tuple[str, str], ...], float] = {}
        self._lock = threading.Lock()

    def set(self, value: float, **labels: Any) -> None:
        key = tuple(sorted((k, str(v)) for k, v in labels.items()))
        with self._lock:
            self._values[key] = float(value)

    def collect(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.doc}", f"# TYPE {self.name} gauge"]
        with self._lock:
            for key, val in sorted(self._values.items()):
                label_dict = dict(key)
                label_str = _format_labels(label_dict)
                val_str = f"{int(val)}" if val.is_integer() else f"{val:.6g}"
                lines.append(f"{self.name}{label_str} {val_str}")
        return lines


class Histogram(Metric):
    def __init__(
        self,
        name: str,
        doc: str,
        buckets: Sequence[float] = DEFAULT_HISTOGRAM_BUCKETS,
    ):
        super().__init__(name, doc, "histogram")
        self.buckets = tuple(sorted(buckets))
        self._counts: dict[tuple[tuple[str, str], ...], dict[float, int]] = {}
        self._sums: dict[tuple[tuple[str, str], ...], float] = {}
        self._totals: dict[tuple[tuple[str, str], ...], int] = {}
        self._lock = threading.Lock()

    def observe(self, amount: float, **labels: Any) -> None:
        key = tuple(sorted((k, str(v)) for k, v in labels.items()))
        with self._lock:
            if key not in self._counts:
                self._counts[key] = {b: 0 for b in self.buckets}
                self._sums[key] = 0.0
                self._totals[key] = 0

            self._sums[key] += amount
            self._totals[key] += 1
            for b in self.buckets:
                if amount <= b:
                    self._counts[key][b] += 1

    def collect(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.doc}", f"# TYPE {self.name} histogram"]
        with self._lock:
            for key in sorted(self._totals.keys()):
                base_labels = dict(key)
                counts = self._counts[key]
                total = self._totals[key]
                val_sum = self._sums[key]

                for b in self.buckets:
                    b_labels = dict(base_labels)
                    b_labels["le"] = f"{b:.6g}"
                    lines.append(
                        f"{self.name}_bucket{_format_labels(b_labels)} {counts[b]}"
                    )

                inf_labels = dict(base_labels)
                inf_labels["le"] = "+Inf"
                lines.append(f"{self.name}_bucket{_format_labels(inf_labels)} {total}")

                sum_str = (
                    f"{int(val_sum)}" if val_sum.is_integer() else f"{val_sum:.6g}"
                )
                lines.append(f"{self.name}_sum{_format_labels(base_labels)} {sum_str}")
                lines.append(f"{self.name}_count{_format_labels(base_labels)} {total}")
        return lines


class PrometheusRegistry:
    """Thread-safe Prometheus metrics registry for SchemaSense 2.0."""

    def __init__(self) -> None:
        self._metrics: dict[str, Metric] = {}
        self._lock = threading.RLock()
        self._init_standard_metrics()

    def _init_standard_metrics(self) -> None:
        self.agent_runs_total = Counter(
            "schemasense_agent_runs_total",
            "Total agent execution runs partitioned by tenant and terminal status",
        )
        self.agent_state_duration = Histogram(
            "schemasense_agent_state_duration_seconds",
            "Histogram of agent lifecycle state durations in seconds",
        )
        self.tool_invocations_total = Counter(
            "schemasense_tool_invocations_total",
            "Total typed tool invocations by tool name and outcome",
        )
        self.sqlguard_validations_total = Counter(
            "schemasense_sqlguard_validations_total",
            "Total SQLGuard AST security validations by decision and dialect",
        )
        self.http_requests_total = Counter(
            "schemasense_http_requests_total",
            "Total HTTP requests handled by the FastAPI application gateway",
        )
        self.http_request_duration = Histogram(
            "schemasense_http_request_duration_seconds",
            "Histogram of HTTP request latency in seconds",
        )
        self.rate_limit_rejections_total = Counter(
            "schemasense_rate_limit_rejections_total",
            "Total requests rejected by sliding-window rate limit gates",
        )
        self.queue_tasks_total = Counter(
            "schemasense_queue_tasks_total",
            "Total Celery background tasks by task name and lifecycle status",
        )

        with self._lock:
            self._metrics["schemasense_agent_runs_total"] = self.agent_runs_total
            self._metrics["schemasense_agent_state_duration_seconds"] = (
                self.agent_state_duration
            )
            self._metrics["schemasense_tool_invocations_total"] = (
                self.tool_invocations_total
            )
            self._metrics["schemasense_sqlguard_validations_total"] = (
                self.sqlguard_validations_total
            )
            self._metrics["schemasense_http_requests_total"] = self.http_requests_total
            self._metrics["schemasense_http_request_duration_seconds"] = (
                self.http_request_duration
            )
            self._metrics["schemasense_rate_limit_rejections_total"] = (
                self.rate_limit_rejections_total
            )
            self._metrics["schemasense_queue_tasks_total"] = self.queue_tasks_total

    def clear(self) -> None:
        """Resets all metrics (used for test isolation)."""
        with self._lock:
            self._metrics.clear()
            self._init_standard_metrics()

    def generate_exposition(self) -> str:
        """Renders Prometheus text exposition format (version 0.0.4)."""
        output_lines: list[str] = []
        with self._lock:
            for name, metric in sorted(self._metrics.items()):
                lines = metric.collect()
                if len(lines) > 2:  # Only output if metric has recordings
                    output_lines.extend(lines)
        if not output_lines:
            return "# SchemaSense 2.0 Metrics Registry (No events recorded yet)\n"
        return "\n".join(output_lines) + "\n"


_GLOBAL_REGISTRY: PrometheusRegistry | None = None


def get_metrics_registry() -> PrometheusRegistry:
    """Returns the singleton Prometheus metrics registry."""
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None:
        _GLOBAL_REGISTRY = PrometheusRegistry()
    return _GLOBAL_REGISTRY


# ─────────────────────────────────────────────────────────────
# Privacy-Preserving Helper Invocations (Mandatory Correction 18)
# No raw queries, no passwords, no customer table data in labels
# ─────────────────────────────────────────────────────────────


def record_agent_run(tenant_id: str, status: str, count: float = 1.0) -> None:
    reg = get_metrics_registry()
    safe_tenant = tenant_id if tenant_id and tenant_id.strip() else "default"
    reg.agent_runs_total.inc(amount=count, tenant_id=safe_tenant, status=status)


def record_agent_state_duration(
    state: str, status: str, duration_seconds: float
) -> None:
    reg = get_metrics_registry()
    reg.agent_state_duration.observe(
        amount=max(0.0, duration_seconds), state=state, status=status
    )


def record_tool_invocation(tool_name: str, status: str, count: float = 1.0) -> None:
    reg = get_metrics_registry()
    reg.tool_invocations_total.inc(amount=count, tool_name=tool_name, status=status)


def record_sqlguard_validation(
    decision: str, dialect: str = "postgres", count: float = 1.0
) -> None:
    reg = get_metrics_registry()
    reg.sqlguard_validations_total.inc(amount=count, decision=decision, dialect=dialect)


def record_http_request(
    endpoint: str, method: str, status_code: int, duration_seconds: float
) -> None:
    reg = get_metrics_registry()
    reg.http_requests_total.inc(
        endpoint=endpoint, method=method, status_code=status_code
    )
    reg.http_request_duration.observe(
        amount=max(0.0, duration_seconds), endpoint=endpoint, method=method
    )


def record_rate_limit_rejection(
    tenant_id: str, endpoint: str, count: float = 1.0
) -> None:
    reg = get_metrics_registry()
    safe_tenant = tenant_id if tenant_id and tenant_id.strip() else "default"
    reg.rate_limit_rejections_total.inc(
        amount=count, tenant_id=safe_tenant, endpoint=endpoint
    )


def record_queue_task(task_name: str, status: str, count: float = 1.0) -> None:
    reg = get_metrics_registry()
    reg.queue_tasks_total.inc(amount=count, task_name=task_name, status=status)
