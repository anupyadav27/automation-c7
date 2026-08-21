"""
Optional OpenTelemetry wiring.

`configure_telemetry(engine_name, app)` instruments the FastAPI app when the
OTel SDK is installed and OTEL_EXPORTER_OTLP_ENDPOINT is set; otherwise it is
a no-op. Engines must run identically with or without telemetry, so this
module never raises.
"""
import logging
import os

logger = logging.getLogger(__name__)


def configure_telemetry(engine_name: str, app=None) -> bool:
    """Instrument `app` for tracing if OTel is available. Returns True if enabled."""
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(
            resource=Resource.create({"service.name": engine_name})
        )
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)
        if app is not None:
            FastAPIInstrumentor.instrument_app(app)
        logger.info("Telemetry enabled for %s → %s", engine_name, endpoint)
        return True
    except Exception as exc:  # missing SDK, bad endpoint — never fatal
        logger.debug("Telemetry disabled for %s: %s", engine_name, exc)
        return False
