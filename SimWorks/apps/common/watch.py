from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any

from django.core.paginator import Paginator
from django.core.serializers.json import DjangoJSONEncoder

WATCH_PAGE_SIZE_OPTIONS: tuple[int, ...] = (25, 50, 100)
DEFAULT_WATCH_PAGE_SIZE = WATCH_PAGE_SIZE_OPTIONS[0]
DEFAULT_EVENTS_FILTER = "all"
DEFAULT_EVENTS_SORT = "desc"
_QUERY_TEXT_MAX_LENGTH = 200


@dataclass(frozen=True)
class WatchPageState:
    events_page: int = 1
    events_page_size: int = DEFAULT_WATCH_PAGE_SIZE
    events_filter: str = DEFAULT_EVENTS_FILTER
    events_q: str = ""
    events_sort: str = DEFAULT_EVENTS_SORT
    sc_page: int = 1
    sc_page_size: int = DEFAULT_WATCH_PAGE_SIZE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _parse_page_size(value: Any, default: int = DEFAULT_WATCH_PAGE_SIZE) -> int:
    parsed = _parse_positive_int(value, default)
    return parsed if parsed in WATCH_PAGE_SIZE_OPTIONS else default


def parse_watch_page_state(query_params) -> WatchPageState:
    events_sort = (query_params.get("events_sort") or DEFAULT_EVENTS_SORT).strip().lower()
    if events_sort not in {"asc", "desc"}:
        events_sort = DEFAULT_EVENTS_SORT

    events_filter = (query_params.get("events_filter") or DEFAULT_EVENTS_FILTER).strip()
    if not events_filter:
        events_filter = DEFAULT_EVENTS_FILTER

    return WatchPageState(
        events_page=_parse_positive_int(query_params.get("events_page"), 1),
        events_page_size=_parse_page_size(query_params.get("events_page_size")),
        events_filter=events_filter,
        events_q=(query_params.get("events_q") or "").strip()[:_QUERY_TEXT_MAX_LENGTH],
        events_sort=events_sort,
        sc_page=_parse_positive_int(query_params.get("sc_page"), 1),
        sc_page_size=_parse_page_size(query_params.get("sc_page_size")),
    )


def serialize_outbox_events(outbox_events) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    previous_event_type: str | None = None
    sequence_group_id = 0

    for event in outbox_events:
        if event.event_type != previous_event_type:
            sequence_group_id += 1

        serialized.append(
            {
                "event_id": str(event.id),
                "event_type": event.event_type,
                "created_at": event.created_at.isoformat(),
                "correlation_id": event.correlation_id or "",
                "payload": event.payload,
                "status": event.status,
                "delivery_attempts": event.delivery_attempts,
                "last_error": event.last_error,
                "idempotency_key": event.idempotency_key,
                "sequence_group_id": sequence_group_id,
            }
        )
        previous_event_type = event.event_type

    return serialized


def dump_outbox_events_json(outbox_events) -> str:
    return json.dumps(serialize_outbox_events(outbox_events), cls=DjangoJSONEncoder)


def build_url_with_query(base_url: str, query_params) -> str:
    encoded = query_params.urlencode()
    if not encoded:
        return base_url
    return f"{base_url}?{encoded}"


def build_watch_service_calls_context(
    *,
    request,
    service_calls_qs,
    service_calls_url: str,
    watch_url: str,
) -> dict[str, Any]:
    watch_state = parse_watch_page_state(request.GET)
    service_calls_page = Paginator(service_calls_qs, watch_state.sc_page_size).get_page(
        watch_state.sc_page
    )

    return {
        "watch_state": watch_state,
        "watch_state_json": json.dumps(watch_state.to_dict(), cls=DjangoJSONEncoder),
        "watch_url": watch_url,
        "service_calls": service_calls_page.object_list,
        "service_calls_page": service_calls_page,
        "service_call_ids_json": json.dumps(
            [str(service_call.id) for service_call in service_calls_page.object_list]
        ),
        "service_calls_url": service_calls_url,
        "service_calls_partial_url": build_url_with_query(service_calls_url, request.GET),
        "watch_page_size_options": WATCH_PAGE_SIZE_OPTIONS,
    }


def build_watch_page_context(
    *,
    request,
    simulation,
    outbox_events,
    service_calls_qs,
    stream_url: str,
    realtime_transport: str,
    realtime_session_payload: dict[str, Any] | None = None,
    service_calls_url: str,
    watch_url: str,
    back_url: str,
    lab_name: str,
    can_go_to_simulation: bool,
    go_to_simulation_url: str,
) -> dict[str, Any]:
    """Build shared admin watch context with an explicit transport selection."""
    if realtime_transport not in {"websocket", "sse"}:
        raise ValueError(f"Unsupported realtime transport: {realtime_transport}")

    context = build_watch_service_calls_context(
        request=request,
        service_calls_qs=service_calls_qs,
        service_calls_url=service_calls_url,
        watch_url=watch_url,
    )
    context.update(
        {
            "simulation": simulation,
            "outbox_events_json": dump_outbox_events_json(outbox_events),
            "stream_url": stream_url,
            "realtime_transport": realtime_transport,
            "realtime_session_payload_json": json.dumps(
                realtime_session_payload or {},
                cls=DjangoJSONEncoder,
            ),
            "back_url": back_url,
            "lab_name": lab_name,
            "can_go_to_simulation": can_go_to_simulation,
            "go_to_simulation_url": go_to_simulation_url if can_go_to_simulation else "",
        }
    )
    return context
