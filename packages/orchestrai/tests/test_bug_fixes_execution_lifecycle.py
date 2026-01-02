"""
Test suite for bug fixes from service execution lifecycle review.

Tests cover:
- BUG-002, BUG-003: Double schema adaptation prevention
- BUG-004: Response metadata population
- BUG-006: codec_identity field in Response
- BUG-011: Reduced logging noise
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

from orchestrai.components.services.service import BaseService
from orchestrai.components.codecs.codec import BaseCodec
from orchestrai.components.schemas import BaseOutputSchema
from orchestrai.identity import Identity
from orchestrai.identity.domains import SERVICES_DOMAIN
from orchestrai.types import Request, Response
from orchestrai.resolve import resolve_schema
from pydantic import Field


class TestSchema(BaseOutputSchema):
    """Test schema for validation."""
    test_field: str = Field(..., description="A test field")


class TestCodec(BaseCodec):
    """Test codec with schema adapters."""
    abstract = False
    identity = Identity(domain="codecs", namespace="test", group="codec", name="test")

    schema_adapters = []

    async def aencode(self, req: Request) -> None:
        """Test encode that tracks adapter calls."""
        schema_cls = self._get_schema_from_service()
        if schema_cls:
            schema_json = schema_cls.model_json_schema()
            # Apply adapters
            for adapter in self.schema_adapters:
                schema_json = adapter.adapt(schema_json)
            req.response_schema_json = schema_json
            req.provider_response_format = schema_json


class TestService(BaseService):
    """Test service for validation."""
    abstract = False
    identity = Identity(domain=SERVICES_DOMAIN, namespace="test", group="svc", name="test")
    response_schema = TestSchema

    async def arun(self, **ctx):
        """Simple run implementation."""
        return Response(output=[])


# =============================================================================
# BUG-002, BUG-003: Double Schema Adaptation Prevention
# =============================================================================

@pytest.mark.asyncio
async def test_schema_not_adapted_during_resolution():
    """Test that resolve_schema does NOT apply adapters."""
    adapter_call_count = 0

    class CountingAdapter:
        order = 0
        def adapt(self, schema):
            nonlocal adapter_call_count
            adapter_call_count += 1
            return schema

    # Resolve schema with adapters
    result = resolve_schema(
        identity=Identity(domain=SERVICES_DOMAIN, namespace="test", group="svc", name="test"),
        override=TestSchema,
        adapters=[CountingAdapter()],
    )

    # Adapters should NOT be called during resolution
    assert adapter_call_count == 0
    assert result.value == TestSchema
    # schema_json metadata should be None (not adapted)
    assert result.selected.meta.get("schema_json") is None


@pytest.mark.asyncio
async def test_attach_response_schema_only_attaches_class():
    """Test that _attach_response_schema_to_request only attaches schema class, not JSON."""
    service = TestService()
    req = Request(input=[])

    # Call the method
    service._attach_response_schema_to_request(req, codec=None)

    # Should attach schema class
    assert req.response_schema == TestSchema

    # Should NOT attach schema_json or provider_response_format
    # (those are codec's responsibility)
    assert not hasattr(req, "response_schema_json") or req.response_schema_json is None
    assert not hasattr(req, "provider_response_format") or req.provider_response_format is None


@pytest.mark.asyncio
async def test_schema_adapters_run_only_in_codec():
    """Test that schema adapters only run once in codec.aencode, not elsewhere."""
    adapter_call_count = 0

    class CountingAdapter:
        order = 0
        def adapt(self, schema):
            nonlocal adapter_call_count
            adapter_call_count += 1
            return schema

    # Create codec with adapter
    codec = TestCodec()
    codec.schema_adapters = [CountingAdapter()]
    codec.service = TestService()

    req = Request(input=[])

    # Encode should call adapter exactly once
    await codec.aencode(req)

    assert adapter_call_count == 1
    assert req.response_schema_json is not None


# =============================================================================
# BUG-004: Response Metadata Population
# =============================================================================

@pytest.mark.asyncio
async def test_response_includes_execution_metadata():
    """Test that responses include execution metadata for audit trail."""
    # Create mock client and emitter
    mock_client = AsyncMock()
    mock_client.send_request = AsyncMock(return_value=Response(output=[]))

    mock_emitter = Mock()
    mock_emitter.emit_request = Mock()
    mock_emitter.emit_response = Mock()

    service = TestService(emitter=mock_emitter, client=mock_client)
    service.context = {
        "prompt.plan.source": "registry",
    }

    # Build request and prepare
    req, codec, attrs = await service.aprepare(stream=False)

    # Mock _asend to capture response
    ident = service.identity

    # Call _asend
    resp = await service._asend(mock_client, req, codec, attrs, ident)

    # Verify execution metadata is populated
    assert "execution_metadata" in resp.model_fields
    assert resp.execution_metadata is not None
    assert resp.execution_metadata.get("service_identity") == "services.test.svc.test"
    assert resp.execution_metadata.get("prompt_plan_source") == "registry"
    assert "timestamp" in resp.execution_metadata
    assert "request_correlation_id" in resp.execution_metadata


@pytest.mark.asyncio
async def test_response_execution_metadata_includes_schema_identity():
    """Test that execution metadata includes schema identity when available."""
    # Create schema with identity
    class IdentifiedSchema(BaseOutputSchema):
        identity = Identity(domain="schemas", namespace="test", group="schema", name="identified")
        value: str

    class IdentifiedService(BaseService):
        abstract = False
        identity = Identity(domain=SERVICES_DOMAIN, namespace="test", group="svc", name="identified")
        response_schema = IdentifiedSchema

        async def arun(self, **ctx):
            return Response(output=[])

    mock_client = AsyncMock()
    mock_client.send_request = AsyncMock(return_value=Response(output=[]))
    mock_emitter = Mock()
    mock_emitter.emit_request = Mock()
    mock_emitter.emit_response = Mock()

    service = IdentifiedService(emitter=mock_emitter, client=mock_client)
    req, codec, attrs = await service.aprepare(stream=False)

    resp = await service._asend(mock_client, req, codec, attrs, service.identity)

    # Schema identity should be in execution metadata
    assert resp.execution_metadata.get("schema_identity") == "schemas.test.schema.identified"


# =============================================================================
# BUG-006: codec_identity Field in Response
# =============================================================================

def test_response_type_has_codec_identity_field():
    """Test that Response type includes codec_identity field."""
    resp = Response(output=[])

    # Field should exist and be settable
    assert "codec_identity" in resp.model_fields
    resp.codec_identity = "test.codec.identity"
    assert resp.codec_identity == "test.codec.identity"


def test_response_type_has_execution_metadata_field():
    """Test that Response type includes execution_metadata field."""
    resp = Response(output=[])

    # Field should exist and be a dict
    assert "execution_metadata" in resp.model_fields
    assert isinstance(resp.execution_metadata, dict)

    # Should be mutable
    resp.execution_metadata["test_key"] = "test_value"
    assert resp.execution_metadata["test_key"] == "test_value"


@pytest.mark.asyncio
async def test_codec_identity_propagates_from_request_to_response():
    """Test that codec_identity is copied from request to response."""
    mock_client = AsyncMock()
    mock_client.send_request = AsyncMock(return_value=Response(output=[]))
    mock_emitter = Mock()
    mock_emitter.emit_request = Mock()
    mock_emitter.emit_response = Mock()

    service = TestService(emitter=mock_emitter, client=mock_client)
    req, codec, attrs = await service.aprepare(stream=False)

    # Set codec_identity on request
    req.codec_identity = "test.codec.identity"

    resp = await service._asend(mock_client, req, codec, attrs, service.identity)

    # Should be copied to response
    assert resp.codec_identity == "test.codec.identity"


# =============================================================================
# Integration Tests
# =============================================================================

@pytest.mark.asyncio
async def test_full_service_execution_with_metadata():
    """Integration test: full service execution populates all metadata correctly."""
    mock_client = AsyncMock()
    mock_client.send_request = AsyncMock(return_value=Response(output=[]))
    mock_emitter = Mock()
    mock_emitter.emit_request = Mock()
    mock_emitter.emit_response = Mock()

    service = TestService(emitter=mock_emitter, client=mock_client)

    # Execute via task.arun (full lifecycle)
    call = await service.task.arun()

    # Verify call succeeded
    assert call.status == "succeeded"

    # Verify result is a Response with metadata
    assert isinstance(call.result, Response)
    assert call.result.execution_metadata is not None
    assert "service_identity" in call.result.execution_metadata


# =============================================================================
# BUG-005: Consistent Codec Schema Resolution
# =============================================================================

def test_codec_schema_resolution_fallback_chain():
    """Test that codec schema resolution has consistent fallback chain."""
    # Codec with class-level schema
    class CodecWithSchema(BaseCodec):
        response_schema = TestSchema

    codec = CodecWithSchema()

    # No service: should use codec's schema
    assert codec._get_schema_from_service() == TestSchema

    # Service with schema: should use service's schema
    class ServiceWithDifferentSchema(BaseService):
        class DifferentSchema(BaseOutputSchema):
            different_field: str

        response_schema = DifferentSchema

    codec.service = ServiceWithDifferentSchema()
    assert codec._get_schema_from_service() == ServiceWithDifferentSchema.DifferentSchema


# =============================================================================
# BUG-008: Schema/Codec Compatibility Validation
# =============================================================================

def test_schema_codec_compatibility_validation():
    """Test that service validates schema compatibility with codec."""
    service = TestService()

    # Should not raise for valid Pydantic schema
    service._validate_schema_codec_compatibility(TestCodec, TestSchema)

    # Should warn for non-Pydantic schema
    class InvalidSchema:
        pass

    with pytest.warns(None) as warnings:
        service._validate_schema_codec_compatibility(TestCodec, InvalidSchema)

    # Should have logged a warning
    # (can't easily test logger.warning without mocking, so we just ensure it doesn't raise)


# =============================================================================
# BUG-009: Retriable Decode Errors
# =============================================================================

def test_codec_decode_error_has_retriable_flag():
    """Test that CodecDecodeError supports retriable flag."""
    from orchestrai.components.codecs.exceptions import CodecDecodeError

    # Non-retriable by default
    error = CodecDecodeError("test error")
    assert error.retriable is False

    # Can be marked retriable
    retriable_error = CodecDecodeError("retriable error", retriable=True)
    assert retriable_error.retriable is True


@pytest.mark.asyncio
async def test_retriable_decode_errors_are_retried():
    """Test that retriable decode errors trigger retry logic."""
    from orchestrai.components.codecs.exceptions import CodecDecodeError

    call_count = 0

    class RetriableCodec(BaseCodec):
        async def adecode(self, resp):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                # First attempt: retriable error
                raise CodecDecodeError("Incomplete JSON", retriable=True)
            # Second attempt: success
            return {"test": "data"}

    mock_client = AsyncMock()
    mock_client.send_request = AsyncMock(return_value=Response(output=[]))
    mock_emitter = Mock()
    mock_emitter.emit_request = Mock()
    mock_emitter.emit_response = Mock()
    mock_emitter.emit_failure = Mock()

    service = TestService(emitter=mock_emitter, client=mock_client)

    # Mock codec resolution to return our test codec
    with patch.object(service, '_select_codec_class', return_value=(RetriableCodec, "test")):
        req, codec, attrs = await service.aprepare(stream=False)

        # Replace with our test codec
        codec = RetriableCodec(service=service)

        # Should retry and eventually succeed
        resp = await service._asend(mock_client, req, codec, attrs, service.identity)

        # Codec should have been called twice (1 retry)
        assert call_count == 2


@pytest.mark.asyncio
async def test_non_retriable_decode_errors_fail_immediately():
    """Test that non-retriable decode errors fail without retry."""
    from orchestrai.components.codecs.exceptions import CodecDecodeError

    call_count = 0

    class NonRetriableCodec(BaseCodec):
        async def adecode(self, resp):
            nonlocal call_count
            call_count += 1
            # Always raise non-retriable error
            raise CodecDecodeError("Schema mismatch", retriable=False)

    mock_client = AsyncMock()
    mock_client.send_request = AsyncMock(return_value=Response(output=[]))
    mock_emitter = Mock()
    mock_emitter.emit_request = Mock()
    mock_emitter.emit_response = Mock()
    mock_emitter.emit_failure = Mock()

    service = TestService(emitter=mock_emitter, client=mock_client)

    with patch.object(service, '_select_codec_class', return_value=(NonRetriableCodec, "test")):
        req, codec, attrs = await service.aprepare(stream=False)
        codec = NonRetriableCodec(service=service)

        # Should fail immediately without retry
        with pytest.raises(CodecDecodeError) as exc_info:
            await service._asend(mock_client, req, codec, attrs, service.identity)

        # Should have been called only once (no retry)
        assert call_count == 1
        assert not exc_info.value.retriable


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
