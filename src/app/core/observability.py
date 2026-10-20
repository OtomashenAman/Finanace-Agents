"""Logs, request ids and Prometheus metrics.

- Every request gets an id (X-Request-ID, taken from the caller or generated), returned in the
  response and attached to every log line written while handling it.
- log_format "json" writes one JSON object per line (for log shippers); "text" is for humans.
- /metrics serves HTTP counters (per process) plus business gauges read from the database
  (the same for every process), in the Prometheus text format.
"""

import json
import logging
import re
import time
import uuid
from collections import defaultdict
from contextvars import ContextVar
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
access_log = logging.getLogger("finance_acc.access")

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get() or "-"
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        entry.update(getattr(record, "fields", {}))
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def setup_logging(level: str, fmt: str) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(_RequestIdFilter())
    handler.setFormatter(
        JsonFormatter()
        if fmt == "json"
        else logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())


# --- metrics (this process) -------------------------------------------------------------

_requests: dict[tuple[str, str, str], int] = defaultdict(int)
_duration_sum: dict[tuple[str, str], float] = defaultdict(float)
_duration_count: dict[tuple[str, str], int] = defaultdict(int)
_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_duration_buckets: dict[tuple[str, str, float], int] = defaultdict(int)


def _route(request: Request) -> str:
    """The route template (/api/v1/agents/{key}/runs/{run_id}), never raw ids.

    The matched route's path leaves out the prefix of the router it was included with
    (/api/v1), so that is taken from the URL: the template's segments are its last ones.
    """
    template = getattr(request.scope.get("route"), "path", None)
    if template is None:
        return "unmatched"
    parts = request.url.path.strip("/").split("/")
    tail = template.strip("/").split("/")
    return "/" + "/".join([*parts[: max(len(parts) - len(tail), 0)], *tail]).strip("/")


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if _SAFE_ID.match(incoming) else uuid.uuid4().hex
        token = request_id.set(rid)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            elapsed = time.perf_counter() - started
            route = _route(request)
            _requests[(request.method, route, str(status))] += 1
            _duration_sum[(request.method, route)] += elapsed
            _duration_count[(request.method, route)] += 1
            for bucket in _BUCKETS:
                if elapsed <= bucket:
                    _duration_buckets[(request.method, route, bucket)] += 1
            access_log.info(
                "%s %s %s %.0fms",
                request.method,
                route,
                status,
                elapsed * 1000,
                extra={
                    "fields": {
                        "method": request.method,
                        "route": route,
                        "path": request.url.path,
                        "status": status,
                        "duration_ms": round(elapsed * 1000, 1),
                    }
                },
            )
            request_id.reset(token)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels(**labels: str) -> str:
    inner = ",".join(f'{k}="{_escape(v)}"' for k, v in labels.items())
    return f"{{{inner}}}" if inner else ""


def http_metrics() -> list[str]:
    lines = [
        "# HELP finance_acc_http_requests_total HTTP requests handled by this process.",
        "# TYPE finance_acc_http_requests_total counter",
        *[
            f"finance_acc_http_requests_total{_labels(method=m, route=r, status=s)} {n}"
            for (m, r, s), n in sorted(_requests.items())
        ],
        "# HELP finance_acc_http_request_duration_seconds Request latency (this process).",
        "# TYPE finance_acc_http_request_duration_seconds histogram",
    ]
    for (m, r), count in sorted(_duration_count.items()):
        series = "finance_acc_http_request_duration_seconds"
        for bucket in _BUCKETS:
            le = _labels(method=m, route=r, le=str(bucket))
            lines.append(f"{series}_bucket{le} {_duration_buckets[(m, r, bucket)]}")
        lines.append(f"{series}_bucket{_labels(method=m, route=r, le='+Inf')} {count}")
        lines.append(f"{series}_sum{_labels(method=m, route=r)} {_duration_sum[(m, r)]:.6f}")
        lines.append(f"{series}_count{_labels(method=m, route=r)} {count}")
    return lines


def gauge(name: str, help_text: str, values: list[tuple[dict[str, str], float]]) -> list[str]:
    return [
        f"# HELP {name} {help_text}",
        f"# TYPE {name} gauge",
        *[f"{name}{_labels(**labels)} {value:g}" for labels, value in values],
    ]
