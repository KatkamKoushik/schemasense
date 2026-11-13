"""Prometheus Metrics Endpoint for SchemaSense 2.0 API Gateway."""

from __future__ import annotations

from fastapi import APIRouter, Response

from schemasense.observability.metrics import get_metrics_registry

router = APIRouter(tags=["Observability"])


@router.get("/metrics", summary="Export Prometheus Platform Metrics")
def export_metrics() -> Response:
    """Exports application, agent, tool, and system metrics in standard Prometheus exposition format."""
    registry = get_metrics_registry()
    exposition_text = registry.generate_exposition()
    return Response(
        content=exposition_text,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
