from __future__ import annotations

import json
from typing import Any

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone

from apps.chatlab.media_payloads import build_message_media_payload, payload_message_id
from apps.chatlab.models import Message
from apps.chatlab.realtime import (
    PING,
    PONG,
    SESSION_HELLO,
    SESSION_READY,
    SESSION_RESUME,
    SESSION_RESUMED,
    SESSION_RESYNC_REQUIRED,
    TYPING_STARTED,
    TYPING_STOPPED,
    InboundMessageError,
    build_error_envelope,
    build_realtime_envelope,
    envelope_sort_key,
    is_durable_event_type,
    is_transient_event_type,
    merge_envelopes_in_order,
    parse_event_id,
    parse_inbound_message,
)
from apps.common.outbox.outbox import (
    build_canonical_envelope,
    get_events_after_event,
    get_replayable_outbox_event,
)
from apps.simcore.access import can_access_simulation_in_scope
from apps.simcore.models import Simulation
from apps.simcore.utils import get_user_initials
from config.logging import get_logger
from orchestrai.utils.json import json_default

logger = get_logger(__name__)

SYSTEM_USER = "system@medsim.local"
RESYNC_CLOSE_CODE = 4409
ACCESS_DENIED_CLOSE_CODE = 4403
AUTH_REQUIRED_CLOSE_CODE = 4401
SERVER_ERROR_CLOSE_CODE = 1011


class ChatConsumer(AsyncWebsocketConsumer):
    """Strict ChatLab realtime consumer using a negotiated WebSocket protocol."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Some tests instantiate the consumer directly without a Channels ASGI scope.
        self.scope = getattr(self, "scope", {})
        self.channel_name = getattr(self, "channel_name", "")
        self.simulation_id: int | None = None
        self.simulation: Simulation | None = None
        self.room_group_name: str | None = None
        self.session_established = False
        self.is_replaying = False
        self.replay_buffer: dict[str, dict[str, Any]] = {}
        self.deferred_transient_events: list[dict[str, Any]] = []

    @staticmethod
    def build_envelope(
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        event_id: str | None = None,
        correlation_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        """Compatibility wrapper for legacy tests and callers."""
        return build_realtime_envelope(
            event_type,
            payload,
            event_id=event_id,
            correlation_id=correlation_id,
            created_at=created_at,
        )

    async def connect(self) -> None:
        user = self.scope.get("user")
        user_id = getattr(user, "id", None)
        is_authenticated = bool(user and getattr(user, "is_authenticated", False))
        auth_mechanism = self.scope.get("auth_mechanism")
        account = self.scope.get("account")
        account_id = getattr(account, "id", None)
        account_uuid = str(getattr(account, "uuid", "")) if account else None
        account_context_source = self.scope.get("account_context_source")

        header_map = {
            key.decode("latin1").lower(): value.decode("latin1")
            for key, value in self.scope.get("headers", [])
        }
        host = header_map.get("host")
        origin = header_map.get("origin")
        x_forwarded_proto = header_map.get("x-forwarded-proto")
        x_forwarded_for = header_map.get("x-forwarded-for")
        x_account_uuid = header_map.get("x-account-uuid")
        authorization_present = "authorization" in header_map

        logger.info(
            "chatlab.ws.connect_attempt",
            user_id=user_id,
            channel_name=self.channel_name,
            path=self.scope.get("path"),
            is_authenticated=is_authenticated,
            auth_mechanism=auth_mechanism,
            account_id=account_id,
            account_uuid=account_uuid,
            account_context_source=account_context_source,
            scheme=self.scope.get("scheme"),
            host=host,
            origin=origin,
            x_forwarded_proto=x_forwarded_proto,
            x_forwarded_for=x_forwarded_for,
            x_account_uuid=x_account_uuid,
            authorization_present=authorization_present,
        )

        if not is_authenticated:
            logger.warning(
                "chatlab.ws.connect_rejected",
                user_id=user_id,
                channel_name=self.channel_name,
                account_id=account_id,
                account_uuid=account_uuid,
                account_context_source=account_context_source,
                reason="authentication_required",
                close_code=AUTH_REQUIRED_CLOSE_CODE,
                auth_mechanism=auth_mechanism,
                scheme=self.scope.get("scheme"),
                host=host,
                origin=origin,
                x_forwarded_proto=x_forwarded_proto,
                x_forwarded_for=x_forwarded_for,
                x_account_uuid=x_account_uuid,
                authorization_present=authorization_present,
            )
            await self.close(code=AUTH_REQUIRED_CLOSE_CODE)
            return

        await self.accept()
        logger.info(
            "chatlab.ws.connect_accepted",
            user_id=user_id,
            channel_name=self.channel_name,
            auth_mechanism=auth_mechanism,
            account_id=account_id,
            account_uuid=account_uuid,
            account_context_source=account_context_source,
            scheme=self.scope.get("scheme"),
            host=host,
            origin=origin,
            x_forwarded_proto=x_forwarded_proto,
            x_forwarded_for=x_forwarded_for,
            x_account_uuid=x_account_uuid,
            authorization_present=authorization_present,
        )

    async def disconnect(self, close_code: int) -> None:
        if self.room_group_name:
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        logger.info(
            "chatlab.ws.disconnect",
            simulation_id=self.simulation_id,
            account_id=getattr(self.simulation, "account_id", None),
            account_uuid=str(getattr(getattr(self.simulation, "account", None), "uuid", "") or ""),
            user_id=getattr(self.scope.get("user"), "id", None),
            channel_name=self.channel_name,
            room_group_name=self.room_group_name,
            close_code=close_code,
        )

    async def receive(self, text_data: str | None = None, bytes_data=None) -> None:
        del bytes_data
        raw_size = len(text_data or "")
        logger.debug(
            "chatlab.ws.inbound_received",
            simulation_id=self.simulation_id,
            user_id=getattr(self.scope.get("user"), "id", None),
            channel_name=self.channel_name,
            bytes=raw_size,
        )

        try:
            inbound = parse_inbound_message(text_data)
        except InboundMessageError as exc:
            logger.warning(
                "chatlab.ws.invalid_inbound",
                simulation_id=self.simulation_id,
                user_id=getattr(self.scope.get("user"), "id", None),
                channel_name=self.channel_name,
                reason=exc.code,
                details=exc.details,
                bytes=raw_size,
            )
            await self._send_envelope(
                build_error_envelope(
                    code=exc.code,
                    message=exc.message,
                    details=exc.details,
                )
            )
            return

        logger.info(
            "chatlab.ws.inbound_event",
            simulation_id=self.simulation_id,
            user_id=getattr(self.scope.get("user"), "id", None),
            channel_name=self.channel_name,
            event_type=inbound.event_type,
            correlation_id=inbound.correlation_id,
        )

        if inbound.event_type in {SESSION_HELLO, SESSION_RESUME}:
            await self._handle_session_event(inbound)
            return

        if not self.session_established or self.simulation is None:
            await self._send_envelope(
                build_error_envelope(
                    code="session_required",
                    message="session.hello or session.resume must complete before live events",
                    correlation_id=inbound.correlation_id,
                    details={"event_type": inbound.event_type},
                )
            )
            return

        if inbound.event_type == TYPING_STARTED:
            await self._handle_typing(
                started=True, payload=inbound.payload, correlation_id=inbound.correlation_id
            )
            return

        if inbound.event_type == TYPING_STOPPED:
            await self._handle_typing(
                started=False, payload=inbound.payload, correlation_id=inbound.correlation_id
            )
            return

        if inbound.event_type == PING:
            await self._handle_ping(inbound.payload, inbound.correlation_id)

    async def outbox_event(self, event: dict[str, Any]) -> None:
        envelope = event.get("event") or {}
        try:
            if not envelope.get("event_type"):
                raise ValueError("missing_event_type")
            if is_durable_event_type(str(envelope["event_type"])):
                envelope = await self._enrich_outbox_envelope(envelope)
        except Exception as exc:
            logger.exception(
                "chatlab.ws.outbox_forward_failed",
                simulation_id=self.simulation_id,
                user_id=getattr(self.scope.get("user"), "id", None),
                channel_name=self.channel_name,
                reason=str(exc),
                event_id=envelope.get("event_id"),
                event_type=envelope.get("event_type"),
            )
            return

        if self.is_replaying and is_durable_event_type(str(envelope.get("event_type") or "")):
            self.replay_buffer[str(envelope["event_id"])] = envelope
            logger.debug(
                "chatlab.ws.replay_buffered_live_event",
                simulation_id=self.simulation_id,
                channel_name=self.channel_name,
                event_id=envelope.get("event_id"),
                event_type=envelope.get("event_type"),
            )
            return

        await self._send_envelope(envelope)

    async def chatlab_transient(self, event: dict[str, Any]) -> None:
        envelope = event.get("event") or {}
        if not is_transient_event_type(str(envelope.get("event_type") or "")):
            logger.warning(
                "chatlab.ws.invalid_transient_forward",
                simulation_id=self.simulation_id,
                channel_name=self.channel_name,
                event_type=envelope.get("event_type"),
            )
            return

        if self._is_self_typing_event(envelope):
            logger.debug(
                "chatlab.ws.typing_self_suppressed",
                simulation_id=self.simulation_id,
                user_id=getattr(self.scope.get("user"), "id", None),
                channel_name=self.channel_name,
                event_type=envelope.get("event_type"),
                conversation_id=(envelope.get("payload") or {}).get("conversation_id"),
            )
            return

        if self.is_replaying:
            self.deferred_transient_events.append(envelope)
            return

        await self._send_envelope(envelope)

    def _is_self_typing_event(self, envelope: dict[str, Any]) -> bool:
        event_type = str(envelope.get("event_type") or "")
        if event_type not in {TYPING_STARTED, TYPING_STOPPED}:
            return False

        payload = envelope.get("payload") or {}
        if payload.get("actor_type") != "user":
            return False

        scope_user = self.scope.get("user")
        current_user_id = getattr(scope_user, "id", None)
        current_user_uuid = getattr(scope_user, "uuid", None)
        current_user_email = getattr(scope_user, "email", None)

        sender_id = payload.get("sender_id") or payload.get("actor_user_id")
        if sender_id is not None and current_user_id is not None:
            try:
                if int(sender_id) == int(current_user_id):
                    return True
            except (TypeError, ValueError):
                # Non-integer IDs may arrive from older clients; fall through to UUID/email checks.
                pass

        actor_user_uuid = payload.get("actor_user_uuid")
        if actor_user_uuid and current_user_uuid and str(actor_user_uuid) == str(current_user_uuid):
            return True

        payload_user = payload.get("user")
        return bool(
            payload_user
            and current_user_email
            and str(payload_user).lower() == str(current_user_email).lower()
        )

    async def _handle_session_event(self, inbound) -> None:
        if self.session_established:
            await self._send_envelope(
                build_error_envelope(
                    code="session_already_established",
                    message="This socket already has an active ChatLab session",
                    correlation_id=inbound.correlation_id,
                )
            )
            return

        simulation_id = int(inbound.payload["simulation_id"])
        header_map = {
            key.decode("latin1").lower(): value.decode("latin1")
            for key, value in self.scope.get("headers", [])
        }
        logger.info(
            "chatlab.ws.session_negotiation",
            event_type=inbound.event_type,
            simulation_id=simulation_id,
            last_event_id=inbound.payload.get("last_event_id"),
            user_id=getattr(self.scope.get("user"), "id", None),
            channel_name=self.channel_name,
            host=header_map.get("host"),
            origin=header_map.get("origin"),
            x_forwarded_proto=header_map.get("x-forwarded-proto"),
            x_forwarded_for=header_map.get("x-forwarded-for"),
            requested_account_uuid=header_map.get("x-account-uuid"),
            authorization_present="authorization" in header_map,
        )

        simulation = await self._resolve_authorized_simulation(simulation_id)
        if simulation is None:
            await self._send_envelope(
                build_error_envelope(
                    code="access_denied",
                    message="ChatLab session access denied",
                    correlation_id=inbound.correlation_id,
                )
            )
            await self._force_close(
                ACCESS_DENIED_CLOSE_CODE,
                reason="access_denied",
            )
            return

        self.simulation = simulation
        self.simulation_id = simulation.id
        self.room_group_name = f"simulation_{simulation.id}"

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        logger.info(
            "chatlab.ws.group_joined",
            simulation_id=self.simulation_id,
            account_id=getattr(simulation, "account_id", None),
            account_uuid=str(getattr(getattr(simulation, "account", None), "uuid", "") or ""),
            user_id=getattr(self.scope.get("user"), "id", None),
            channel_name=self.channel_name,
            room_group_name=self.room_group_name,
        )

        last_event_id = inbound.payload.get("last_event_id")
        replay_count = 0
        if last_event_id is not None:
            replay_ok, replay_count = await self._replay_after_event_id(
                last_event_id=last_event_id,
                correlation_id=inbound.correlation_id,
                event_type=inbound.event_type,
            )
            if not replay_ok:
                return

        lifecycle_event_type = (
            SESSION_READY if inbound.event_type == SESSION_HELLO else SESSION_RESUMED
        )
        lifecycle_payload = {
            "simulation_id": simulation.id,
            "patient_display_name": simulation.sim_patient_display_name,
            "patient_initials": simulation.sim_patient_initials,
            "status": simulation.status,
            "replay_count": replay_count,
            "last_event_id": last_event_id,
        }
        lifecycle_envelope = build_realtime_envelope(
            lifecycle_event_type,
            lifecycle_payload,
            correlation_id=inbound.correlation_id,
        )

        # Fresh connects announce readiness before any live tail events.
        # Resume flows complete durable replay first, then emit session.resumed,
        # then flush any transient live events buffered during replay.
        self.session_established = True
        await self._send_envelope(lifecycle_envelope)

        if self.deferred_transient_events:
            deferred = sorted(self.deferred_transient_events, key=envelope_sort_key)
            self.deferred_transient_events = []
            for envelope in deferred:
                await self._send_envelope(envelope)

        if inbound.event_type == SESSION_HELLO and await self._should_emit_initial_typing():
            await self._broadcast_system_typing(started=True, correlation_id=inbound.correlation_id)

    async def _resolve_authorized_simulation(self, simulation_id: int) -> Simulation | None:
        try:
            simulation = await sync_to_async(
                lambda: Simulation.objects.select_related("account", "user").get(id=simulation_id)
            )()
        except Simulation.DoesNotExist:
            logger.warning(
                "chatlab.ws.access_rejected",
                simulation_id=simulation_id,
                user_id=getattr(self.scope.get("user"), "id", None),
                channel_name=self.channel_name,
                reason="simulation_not_found_or_not_accessible",
            )
            return None

        user = self.scope.get("user")
        header_map = {
            key.decode("latin1").lower(): value.decode("latin1")
            for key, value in self.scope.get("headers", [])
        }
        scope_account = self.scope.get("account")
        has_access = bool(
            getattr(user, "is_staff", False)
            or await sync_to_async(can_access_simulation_in_scope)(user, simulation, self.scope)
        )
        logger.info(
            "chatlab.ws.access_result",
            simulation_id=simulation_id,
            account_id=getattr(simulation, "account_id", None),
            account_uuid=str(getattr(getattr(simulation, "account", None), "uuid", "") or ""),
            user_id=getattr(user, "id", None),
            channel_name=self.channel_name,
            access_granted=has_access,
            reason=None if has_access else "access_denied",
            scope_account_id=getattr(scope_account, "id", None),
            scope_account_uuid=(str(getattr(scope_account, "uuid", "")) if scope_account else None),
            account_context_source=self.scope.get("account_context_source"),
            requested_account_uuid=header_map.get("x-account-uuid"),
            host=header_map.get("host"),
            origin=header_map.get("origin"),
            x_forwarded_proto=header_map.get("x-forwarded-proto"),
            x_forwarded_for=header_map.get("x-forwarded-for"),
        )
        return simulation if has_access else None

    async def _replay_after_event_id(
        self,
        *,
        last_event_id: str,
        correlation_id: str | None,
        event_type: str,
    ) -> tuple[bool, int]:
        try:
            parsed_event_id = parse_event_id(last_event_id)
        except InboundMessageError:
            await self._emit_resync_required(
                reason="malformed_last_event_id",
                last_event_id=last_event_id,
                correlation_id=correlation_id,
                anchor_found=False,
            )
            return False, 0

        anchor_event = await get_replayable_outbox_event(
            simulation_id=self.simulation_id,
            event_id=parsed_event_id,
        )
        if anchor_event is None:
            await self._emit_resync_required(
                reason="unknown_last_event_id",
                last_event_id=last_event_id,
                correlation_id=correlation_id,
                anchor_found=False,
            )
            return False, 0

        self.is_replaying = True
        self.replay_buffer = {}
        self.deferred_transient_events = []

        logger.info(
            "chatlab.ws.replay_start",
            simulation_id=self.simulation_id,
            account_id=getattr(self.simulation, "account_id", None),
            account_uuid=str(getattr(getattr(self.simulation, "account", None), "uuid", "") or ""),
            user_id=getattr(self.scope.get("user"), "id", None),
            channel_name=self.channel_name,
            room_group_name=self.room_group_name,
            last_event_id=last_event_id,
            anchor_found=True,
            anchor_event_id=str(anchor_event.id),
            reason=event_type,
        )

        replay_events = await get_events_after_event(
            simulation_id=self.simulation_id,
            last_event_id=parsed_event_id,
        )

        replay_envelopes: list[dict[str, Any]] = []
        for outbox_event in replay_events:
            if not is_durable_event_type(outbox_event.event_type):
                continue
            replay_envelopes.append(await self._build_outbox_envelope(outbox_event))

        merged = merge_envelopes_in_order(
            replay_envelopes,
            list(self.replay_buffer.values()),
        )

        try:
            for envelope in merged:
                await self._send_envelope(envelope)
        finally:
            self.is_replaying = False
            self.replay_buffer = {}

        logger.info(
            "chatlab.ws.replay_complete",
            simulation_id=self.simulation_id,
            user_id=getattr(self.scope.get("user"), "id", None),
            channel_name=self.channel_name,
            room_group_name=self.room_group_name,
            last_event_id=last_event_id,
            replay_count=len(merged),
        )
        return True, len(merged)

    async def _build_outbox_envelope(self, outbox_event) -> dict[str, Any]:
        return await self._enrich_outbox_envelope(build_canonical_envelope(outbox_event))

    async def _enrich_outbox_envelope(self, envelope: dict[str, Any]) -> dict[str, Any]:
        if envelope.get("event_type") != "message.item.created":
            return envelope

        payload = dict(envelope.get("payload") or {})
        message_id = payload_message_id(payload)
        if message_id is None:
            return envelope

        try:
            message = await Message.objects.prefetch_related("media").aget(
                id=message_id,
                simulation_id=self.simulation_id,
            )
        except Message.DoesNotExist:
            payload.setdefault("media_list", [])
            return {**envelope, "payload": payload}

        headers = dict(self.scope.get("headers", []))
        host = headers.get(b"host", b"").decode() or None
        scheme = self.scope.get("scheme", "http")
        payload.update(
            build_message_media_payload(
                message,
                scheme=scheme,
                host=host,
            )
        )
        return {**envelope, "payload": payload}

    async def _handle_typing(
        self,
        *,
        started: bool,
        payload: dict[str, Any],
        correlation_id: str | None,
    ) -> None:
        if await self._simulation_has_ended():
            logger.info(
                "chatlab.ws.typing_ignored",
                simulation_id=self.simulation_id,
                user_id=getattr(self.scope.get("user"), "id", None),
                channel_name=self.channel_name,
                event_type=TYPING_STARTED if started else TYPING_STOPPED,
                reason="simulation_ended",
            )
            return

        scope_user = self.scope.get("user")
        user_label = getattr(scope_user, "email", None) or SYSTEM_USER
        display_initials = await sync_to_async(get_user_initials)(user_label)
        event_type = TYPING_STARTED if started else TYPING_STOPPED
        user_id = getattr(scope_user, "id", None)
        user_uuid = getattr(scope_user, "uuid", None)
        event_payload = {
            "conversation_id": payload.get("conversation_id"),
            "user": user_label,
            "display_initials": display_initials,
            "actor_type": "user",
            "sender_id": user_id,
            "actor_user_id": user_id,
            "actor_user_uuid": str(user_uuid) if user_uuid else None,
        }
        envelope = build_realtime_envelope(
            event_type,
            event_payload,
            correlation_id=correlation_id,
        )
        logger.info(
            "chatlab.ws.typing_event",
            simulation_id=self.simulation_id,
            user_id=getattr(scope_user, "id", None),
            channel_name=self.channel_name,
            room_group_name=self.room_group_name,
            event_type=event_type,
            correlation_id=correlation_id,
            conversation_id=payload.get("conversation_id"),
        )
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chatlab.transient",
                "event": envelope,
            },
        )

    async def _broadcast_system_typing(
        self,
        *,
        started: bool,
        correlation_id: str | None,
    ) -> None:
        if self.simulation is None or self.room_group_name is None:
            return
        envelope = build_realtime_envelope(
            TYPING_STARTED if started else TYPING_STOPPED,
            {
                "conversation_id": None,
                "user": SYSTEM_USER,
                "display_initials": self.simulation.sim_patient_initials,
                "actor_type": "system",
                "sender_id": None,
                "actor_user_id": None,
                "actor_user_uuid": None,
            },
            correlation_id=correlation_id,
        )
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chatlab.transient",
                "event": envelope,
            },
        )

    async def _handle_ping(
        self,
        payload: dict[str, Any],
        correlation_id: str | None,
    ) -> None:
        logger.debug(
            "chatlab.ws.ping",
            simulation_id=self.simulation_id,
            user_id=getattr(self.scope.get("user"), "id", None),
            channel_name=self.channel_name,
            correlation_id=correlation_id,
        )
        await self._send_envelope(
            build_realtime_envelope(
                PONG,
                payload,
                correlation_id=correlation_id,
            )
        )

    async def _simulation_has_ended(self) -> bool:
        if self.simulation is None:
            return False

        await sync_to_async(self.simulation.refresh_from_db)(fields=["status", "end_timestamp"])
        if self.simulation.status in {
            Simulation.SimulationStatus.COMPLETED,
            Simulation.SimulationStatus.TIMED_OUT,
            Simulation.SimulationStatus.FAILED,
            Simulation.SimulationStatus.CANCELED,
        }:
            return True
        if self.simulation.end_timestamp:
            return True
        if (
            self.simulation.time_limit
            and (self.simulation.start_timestamp + self.simulation.time_limit) < timezone.now()
        ):
            await sync_to_async(self.simulation.mark_timed_out)()
            return True
        return False

    async def _should_emit_initial_typing(self) -> bool:
        if self.simulation is None:
            return False
        if self.simulation.status != Simulation.SimulationStatus.IN_PROGRESS:
            return False
        return not await Message.objects.filter(simulation=self.simulation_id).aexists()

    async def _emit_resync_required(
        self,
        *,
        reason: str,
        last_event_id: str,
        correlation_id: str | None,
        anchor_found: bool | None = None,
    ) -> None:
        logger.warning(
            "chatlab.ws.resync_required",
            simulation_id=self.simulation_id,
            account_id=getattr(self.simulation, "account_id", None),
            account_uuid=str(getattr(getattr(self.simulation, "account", None), "uuid", "") or ""),
            user_id=getattr(self.scope.get("user"), "id", None),
            channel_name=self.channel_name,
            room_group_name=self.room_group_name,
            last_event_id=last_event_id,
            anchor_found=anchor_found,
            correlation_id=correlation_id,
            reason=reason,
        )
        await self._send_envelope(
            build_realtime_envelope(
                SESSION_RESYNC_REQUIRED,
                {
                    "simulation_id": self.simulation_id,
                    "last_event_id": last_event_id,
                    "reason": reason,
                },
                correlation_id=correlation_id,
            )
        )
        await self._force_close(
            RESYNC_CLOSE_CODE,
            reason=reason,
        )

    async def _force_close(self, close_code: int, *, reason: str) -> None:
        logger.warning(
            "chatlab.ws.force_close",
            simulation_id=self.simulation_id,
            account_id=getattr(self.simulation, "account_id", None),
            account_uuid=str(getattr(getattr(self.simulation, "account", None), "uuid", "") or ""),
            user_id=getattr(self.scope.get("user"), "id", None),
            channel_name=self.channel_name,
            room_group_name=self.room_group_name,
            close_code=close_code,
            reason=reason,
        )
        await self.close(code=close_code)

    async def _send_envelope(self, envelope: dict[str, Any]) -> None:
        event_type = envelope.get("event_type")
        payload = envelope.get("payload") or {}
        logger.info(
            "chatlab.ws.outbound_event",
            simulation_id=self.simulation_id,
            account_id=getattr(self.simulation, "account_id", None),
            account_uuid=str(getattr(getattr(self.simulation, "account", None), "uuid", "") or ""),
            user_id=getattr(self.scope.get("user"), "id", None),
            channel_name=self.channel_name,
            room_group_name=self.room_group_name,
            event_id=envelope.get("event_id"),
            event_type=event_type,
            correlation_id=envelope.get("correlation_id"),
            message_id=payload.get("message_id") or payload.get("id"),
        )
        try:
            await self.send(
                text_data=json.dumps(
                    envelope,
                    default=json_default,
                )
            )
        except Exception as exc:
            logger.exception(
                "chatlab.ws.send_failed",
                simulation_id=self.simulation_id,
                user_id=getattr(self.scope.get("user"), "id", None),
                channel_name=self.channel_name,
                event_id=envelope.get("event_id"),
                event_type=event_type,
                reason=str(exc),
            )
            raise
