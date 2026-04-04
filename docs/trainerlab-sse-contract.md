# TrainerLab SSE Contract

TrainerLab runtime SSE uses `GET /api/v1/trainerlab/simulations/{id}/events/stream/`.

## Wire Contract

- Event payloads use the canonical outbox transport envelope (`EventEnvelope`).
- The `cursor` query parameter resumes from the referenced outbox event (delivers only events strictly after that cursor).
- **Stale cursor:** If the referenced cursor has been pruned or is otherwise unavailable, the stream request fails with **HTTP 410 Gone** and the client must re-bootstrap before opening a new stream. No successful `200 OK` stream is opened for stale or pruned cursors.
- **Bootstrap:** After loading state via `GET /trainerlab/simulations/{id}/state/`, pass the `latest_event_cursor` from that response as the `cursor` parameter when connecting to the SSE stream so only events created after that point are delivered.
- While the stream is idle, the server emits an SSE comment heartbeat every 10 seconds or less:

  ```text
  : keep-alive

  ```

- A clean server-side close remains reconnectable behavior for clients. Idle streams are not terminal.

## Serving Assumptions

- Django sends the stream with `Content-Type: text/event-stream`.
- SSE responses include `Cache-Control: no-cache, no-transform` and `X-Accel-Buffering: no`.
- The checked-in nginx configs route the TrainerLab SSE path through a dedicated non-buffered proxy location with HTTP/1.1 and long read/send timeouts.

## External Infra Requirements

- Any proxy, tunnel, load balancer, or CDN in front of nginx must preserve `text/event-stream` responses and must not buffer or transform SSE comment frames.
- Any idle timeout on the deployed path must be greater than the client stale threshold of 45 seconds.
- If production infrastructure strips SSE comments, the backend fallback is an explicit heartbeat event:

  ```text
  event: heartbeat
  data: {}

  ```

  The current iOS transport can treat that explicit `heartbeat` event as a keep-alive, but the backend should still prefer comment heartbeats by default.
