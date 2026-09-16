"""
Phase 5: lightweight in-process metrics (no new dependencies).

Counters + a bounded latency sample for chat requests, exposed via
GET /api/metrics (auth required). For Prometheus scraping, the same
payload is rendered in text exposition format at /api/metrics/prom.
"""
import threading
import time

_START = time.time()
_lock = threading.Lock()
_counters: dict = {}
_lat_ms: list = []
_LAT_CAP = 1000


def incr(name: str, value: int = 1) -> None:
    with _lock:
        _counters[name] = _counters.get(name, 0) + value


def observe_chat_latency(ms: float) -> None:
    with _lock:
        _lat_ms.append(ms)
        if len(_lat_ms) > _LAT_CAP:
            del _lat_ms[: len(_lat_ms) - _LAT_CAP]


def _percentile(sorted_vals: list, pct: float):
    if not sorted_vals:
        return None
    idx = min(len(sorted_vals) - 1, int(pct / 100 * len(sorted_vals)))
    return round(sorted_vals[idx], 1)


def snapshot() -> dict:
    with _lock:
        vals = sorted(_lat_ms)
        counters = dict(_counters)
    return {
        "uptime_seconds": round(time.time() - _START, 1),
        "counters": counters,
        "chat_latency_ms": {
            "count": len(vals),
            "p50": _percentile(vals, 50),
            "p95": _percentile(vals, 95),
            "max": round(vals[-1], 1) if vals else None,
        },
    }


def snapshot_prometheus() -> str:
    snap = snapshot()
    lines = []
    for name, value in sorted(snap["counters"].items()):
        lines.append(f'samvaad_{name} {value}')
    lat = snap["chat_latency_ms"]
    for key in ("p50", "p95", "max"):
        if lat[key] is not None:
            lines.append(f'samvaad_chat_latency_ms_{key} {lat[key]}')
    lines.append(f'samvaad_uptime_seconds {snap["uptime_seconds"]}')
    return "\n".join(lines) + "\n"
