"""Logs, request ids and Prometheus metrics.

- Every request gets an id (X-Request-ID, taken from the caller or generated), returned in the
  response and attached to every log line written while handling it.
- log_format "json" writes one JSON object per line (for log shippers); "text" is for humans.
- /metrics serves HTTP counters plus business gauges read from the database (the same for
  every process), in the Prometheus text format. With several server processes, set
  metrics_dir: each process keeps its counters in a file there and a scrape, whichever
  process answers it, sums them all.
"""

import json
import logging
import os
import re
import time
import uuid
from collections import defaultdict
from contextvars import ContextVar
from pathlib import Path
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


# --- metrics ---------------------------------------------------------------------------

_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_FLUSH_SECONDS = 1.0


class HttpCounters:
    """Request counts and latency histograms, keyed by (method, route[, status | bucket])."""

    def __init__(self) -> None:
        self.requests: dict[tuple[str, str, str], int] = defaultdict(int)
        self.duration_sum: dict[tuple[str, str], float] = defaultdict(float)
        self.duration_count: dict[tuple[str, str], int] = defaultdict(int)
        self.duration_buckets: dict[tuple[str, str, float], int] = defaultdict(int)

    def observe(self, method: str, route: str, status: int, elapsed: float) -> None:
        self.requests[(method, route, str(status))] += 1
        self.duration_sum[(method, route)] += elapsed
        self.duration_count[(method, route)] += 1
        for bucket in _BUCKETS:
            if elapsed <= bucket:
                self.duration_buckets[(method, route, bucket)] += 1

    def to_json(self) -> dict[str, list[list[Any]]]:
        return {
            "requests": [[*k, v] for k, v in self.requests.items()],
            "duration_sum": [[*k, v] for k, v in self.duration_sum.items()],
            "duration_count": [[*k, v] for k, v in self.duration_count.items()],
            "duration_buckets": [[*k, v] for k, v in self.duration_buckets.items()],
        }

    def add(self, data: dict[str, list[list[Any]]]) -> None:
        for m, r, s, n in data.get("requests", []):
            self.requests[(m, r, s)] += n
        for m, r, v in data.get("duration_sum", []):
            self.duration_sum[(m, r)] += v
        for m, r, n in data.get("duration_count", []):
            self.duration_count[(m, r)] += n
        for m, r, b, n in data.get("duration_buckets", []):
            self.duration_buckets[(m, r, float(b))] += n


_counters = HttpCounters()  # this process
_metrics_dir: Path | None = None
# pid + a random part: a pid reused after a restart never adds to an old process's file
_metrics_file = f"http-{os.getpid()}-{uuid.uuid4().hex[:8]}.json"
_flushed_at = 0.0


def configure_metrics(directory: str | None) -> None:
    global _metrics_dir  # set once at startup
    _metrics_dir = Path(directory) if directory else None
    if _metrics_dir is not None:
        _metrics_dir.mkdir(parents=True, exist_ok=True)


def flush_metrics(*, force: bool = False) -> None:
    """Write this process's counters to the shared directory (at most once a second)."""
    global _flushed_at
    if _metrics_dir is None or (not force and time.monotonic() - _flushed_at < _FLUSH_SECONDS):
        return
    _flushed_at = time.monotonic()
    target = _metrics_dir / _metrics_file
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(_counters.to_json()))
    tmp.replace(target)  # atomic: a scrape never reads half a file


def _all_counters() -> HttpCounters:
    if _metrics_dir is None:
        return _counters
    flush_metrics(force=True)
    total = HttpCounters()
    for path in _metrics_dir.glob("http-*.json"):
        try:
            total.add(json.loads(path.read_text()))
        except (OSError, ValueError):
            continue  # replaced or removed while reading: counted on the next scrape
    return total


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
            _counters.observe(request.method, route, status, elapsed)
            flush_metrics()
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
    c = _all_counters()
    lines = [
        "# HELP finance_acc_http_requests_total HTTP requests handled (all server processes).",
        "# TYPE finance_acc_http_requests_total counter",
        *[
            f"finance_acc_http_requests_total{_labels(method=m, route=r, status=s)} {n}"
            for (m, r, s), n in sorted(c.requests.items())
        ],
        "# HELP finance_acc_http_request_duration_seconds Request latency.",
        "# TYPE finance_acc_http_request_duration_seconds histogram",
    ]
    for (m, r), count in sorted(c.duration_count.items()):
        series = "finance_acc_http_request_duration_seconds"
        for bucket in _BUCKETS:
            le = _labels(method=m, route=r, le=str(bucket))
            lines.append(f"{series}_bucket{le} {c.duration_buckets[(m, r, bucket)]}")
        lines.append(f"{series}_bucket{_labels(method=m, route=r, le='+Inf')} {count}")
        lines.append(f"{series}_sum{_labels(method=m, route=r)} {c.duration_sum[(m, r)]:.6f}")
        lines.append(f"{series}_count{_labels(method=m, route=r)} {count}")
    return lines


def gauge(name: str, help_text: str, values: list[tuple[dict[str, str], float]]) -> list[str]:
    return [
        f"# HELP {name} {help_text}",
        f"# TYPE {name} gauge",
        *[f"{name}{_labels(**labels)} {value:g}" for labels, value in values],
    ]
