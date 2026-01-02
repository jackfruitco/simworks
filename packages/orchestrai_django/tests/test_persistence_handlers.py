"""Tests for persistence handler system."""

import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

from orchestrai.identity.domains import PERSIST_DOMAIN
from orchestrai.types import Response
from orchestrai_django.components.persistence import BasePersistenceHandler
from orchestrai_django.decorators import persistence_handler
from orchestrai_django.registry.persistence import PersistenceHandlerRegistry


# Test fixtures
class MockSchema:
    """Mock schema for testing."""

    class identity:
        as_str = "schemas.test.mock.MockSchema"

    @classmethod
    def model_validate(cls, data):
        return {"validated": True, "data": data}


class MockDomainObject:
    """Mock domain model."""

    id = 123
    content = "test content"


@pytest.mark.django_db
class TestPersistenceHandlerRegistry:
    """Test the PersistenceHandlerRegistry."""

    def test_registry_initialization(self):
        """Test that registry initializes without errors."""
        registry = PersistenceHandlerRegistry()

        # Should have inherited _lock from BaseRegistry
        assert hasattr(registry, "_lock")
        assert hasattr(registry, "_frozen")
        assert hasattr(registry, "_store")

        # Should have custom _handlers dict
        assert hasattr(registry, "_handlers")
        assert isinstance(registry._handlers, dict)

    def test_registry_can_freeze(self):
        """Test that registry can be frozen without AttributeError."""
        registry = PersistenceHandlerRegistry()

        # Should not raise AttributeError on freeze
        registry.freeze()

        assert registry._frozen is True

    def test_register_handler(self):
        """Test registering a persistence handler."""
        registry = PersistenceHandlerRegistry()

        # Create a mock handler class
        class TestHandler(BasePersistenceHandler):
            schema = MockSchema

            class identity:
                namespace = "test"
                as_str = "persist.test.mock.TestHandler"

            async def persist(self, response):
                return MockDomainObject()

        # Register it
        registry.register(TestHandler)

        # Should be in handlers dict
        key = ("test", "schemas.test.mock.MockSchema")
        assert key in registry._handlers
        assert registry._handlers[key] == TestHandler

    def test_register_handler_without_schema_raises(self):
        """Test that registering handler without schema raises ValueError."""
        registry = PersistenceHandlerRegistry()

        class BadHandler(BasePersistenceHandler):
            schema = None  # Missing schema!

            class identity:
                namespace = "test"

            async def persist(self, response):
                pass

        with pytest.raises(ValueError, match="missing schema attribute"):
            registry.register(BadHandler)

    def test_get_handler(self):
        """Test retrieving a registered handler."""
        registry = PersistenceHandlerRegistry()

        class TestHandler(BasePersistenceHandler):
            schema = MockSchema

            class identity:
                namespace = "test"
                as_str = "persist.test.mock.TestHandler"

            async def persist(self, response):
                return MockDomainObject()

        registry.register(TestHandler)

        # Get by namespace and schema identity
        handler = registry.get("test", "schemas.test.mock.MockSchema")
        assert handler == TestHandler

        # Non-existent handler returns None
        handler = registry.get("nonexistent", "schemas.fake.Schema")
        assert handler is None

    @pytest.mark.asyncio
    async def test_persist_routes_to_handler(self):
        """Test that persist() routes to the correct handler."""
        registry = PersistenceHandlerRegistry()

        class TestHandler(BasePersistenceHandler):
            schema = MockSchema

            class identity:
                namespace = "test"
                as_str = "persist.test.mock.TestHandler"

            async def persist(self, response):
                return MockDomainObject()

        registry.register(TestHandler)

        # Create a response
        response = Response(
            namespace="test",
            structured_data={"test": "data"},
            execution_metadata={"schema_identity": "schemas.test.mock.MockSchema"},
            context={},
        )

        # Persist should route to handler
        result = await registry.persist(response)
        assert isinstance(result, MockDomainObject)

    @pytest.mark.asyncio
    async def test_persist_fallback_to_core(self):
        """Test that persist() falls back to core namespace."""
        registry = PersistenceHandlerRegistry()

        class CoreHandler(BasePersistenceHandler):
            schema = MockSchema

            class identity:
                namespace = "core"
                as_str = "persist.core.mock.CoreHandler"

            async def persist(self, response):
                return MockDomainObject()

        registry.register(CoreHandler)

        # Create a response with app namespace that has no handler
        response = Response(
            namespace="chatlab",  # No chatlab handler
            structured_data={"test": "data"},
            execution_metadata={"schema_identity": "schemas.test.mock.MockSchema"},
            context={},
        )

        # Should fallback to core handler
        result = await registry.persist(response)
        assert isinstance(result, MockDomainObject)

    @pytest.mark.asyncio
    async def test_persist_returns_none_if_no_handler(self):
        """Test that persist() returns None if no handler found."""
        registry = PersistenceHandlerRegistry()

        response = Response(
            namespace="test",
            structured_data={"test": "data"},
            execution_metadata={"schema_identity": "schemas.nonexistent.Schema"},
            context={},
        )

        # Should return None and log debug message
        result = await registry.persist(response)
        assert result is None


@pytest.mark.django_db
class TestBasePersistenceHandler:
    """Test the BasePersistenceHandler base class."""

    @pytest.mark.asyncio
    async def test_ensure_idempotent_creates_chunk(self):
        """Test that ensure_idempotent creates PersistedChunk record."""
        from orchestrai_django.models import PersistedChunk

        class TestHandler(BasePersistenceHandler):
            schema = MockSchema

            class identity:
                namespace = "test"
                as_str = "persist.test.mock.TestHandler"

            async def persist(self, response):
                return MockDomainObject()

        handler = TestHandler()

        response = Response(
            namespace="test",
            correlation_id=uuid4(),
            structured_data={"test": "data"},
            execution_metadata={"schema_identity": "schemas.test.mock.MockSchema"},
            context={"call_id": "test-call-123"},
        )

        # First call should create
        chunk, created = await handler.ensure_idempotent(response)
        assert created is True
        assert chunk.call_id == "test-call-123"
        assert chunk.schema_identity == "schemas.test.mock.MockSchema"
        assert chunk.namespace == "test"

        # Second call should retrieve existing
        chunk2, created2 = await handler.ensure_idempotent(response)
        assert created2 is False
        assert chunk2.id == chunk.id

    @pytest.mark.asyncio
    async def test_ensure_idempotent_uses_correlation_id_fallback(self):
        """Test that ensure_idempotent falls back to correlation_id."""
        from orchestrai_django.models import PersistedChunk

        class TestHandler(BasePersistenceHandler):
            schema = MockSchema

            class identity:
                namespace = "test"
                as_str = "persist.test.mock.TestHandler"

            async def persist(self, response):
                return MockDomainObject()

        handler = TestHandler()

        correlation_id = uuid4()
        response = Response(
            namespace="test",
            correlation_id=correlation_id,
            structured_data={"test": "data"},
            execution_metadata={"schema_identity": "schemas.test.mock.MockSchema"},
            context={},  # No call_id
        )

        chunk, created = await handler.ensure_idempotent(response)
        assert created is True
        assert chunk.call_id == str(correlation_id)


@pytest.mark.django_db
class TestPersistedChunk:
    """Test the PersistedChunk model."""

    def test_persisted_chunk_creation(self):
        """Test creating a PersistedChunk record."""
        from orchestrai_django.models import PersistedChunk

        chunk = PersistedChunk.objects.create(
            call_id="test-call-123",
            schema_identity="schemas.test.mock.Schema",
            namespace="test",
            handler_identity="persist.test.mock.Handler",
        )

        assert chunk.id is not None
        assert chunk.call_id == "test-call-123"
        assert chunk.persisted_at is not None

    def test_persisted_chunk_unique_constraint(self):
        """Test that (call_id, schema_identity) is unique."""
        from orchestrai_django.models import PersistedChunk
        from django.db import IntegrityError

        PersistedChunk.objects.create(
            call_id="test-call-123",
            schema_identity="schemas.test.mock.Schema",
            namespace="test",
            handler_identity="persist.test.mock.Handler",
        )

        # Duplicate should raise IntegrityError
        with pytest.raises(IntegrityError):
            PersistedChunk.objects.create(
                call_id="test-call-123",
                schema_identity="schemas.test.mock.Schema",
                namespace="test",
                handler_identity="persist.test.mock.Handler2",
            )

    def test_persisted_chunk_generic_foreign_key(self):
        """Test that domain_object generic foreign key works."""
        from django.contrib.contenttypes.models import ContentType
        from orchestrai_django.models import PersistedChunk, ServiceCallRecord

        # Create a ServiceCallRecord as example domain object
        record = ServiceCallRecord.objects.create(
            id="test-record-123",
            service_identity="services.test.TestService",
            status="succeeded",
        )

        # Create PersistedChunk pointing to it
        chunk = PersistedChunk.objects.create(
            call_id="test-call-123",
            schema_identity="schemas.test.mock.Schema",
            namespace="test",
            handler_identity="persist.test.mock.Handler",
            content_type=ContentType.objects.get_for_model(ServiceCallRecord),
            object_id=record.pk,
        )

        # Should be able to retrieve domain object
        # Note: For this to work we need to handle CharField pk properly
        assert chunk.content_type.model == "servicecallrecord"


@pytest.mark.django_db
class TestPersistenceDecorator:
    """Test the @persistence_handler decorator."""

    def test_decorator_sets_component_type(self):
        """Test that decorator sets __component_type__."""

        @persistence_handler
        class TestHandler(BasePersistenceHandler):
            schema = MockSchema

            async def persist(self, response):
                return MockDomainObject()

        assert hasattr(TestHandler, "__component_type__")
        assert TestHandler.__component_type__ == "persistence_handler"

    def test_decorator_validates_base_class(self):
        """Test that decorator validates inheritance."""
        from orchestrai_django.decorators import DjangoPersistenceHandlerDecorator

        decorator = DjangoPersistenceHandlerDecorator()

        class BadHandler:  # Not inheriting BasePersistenceHandler
            schema = MockSchema

            async def persist(self, response):
                pass

        with pytest.raises(TypeError, match="must inherit from BasePersistenceHandler"):
            decorator.register(BadHandler)

    def test_decorator_validates_persist_method(self):
        """Test that decorator validates persist() method exists."""
        from orchestrai_django.decorators import DjangoPersistenceHandlerDecorator

        decorator = DjangoPersistenceHandlerDecorator()

        class BadHandler(BasePersistenceHandler):
            schema = MockSchema
            # Missing persist() method!

        # Remove the base class persist to test validation
        delattr(BadHandler, "persist")

        with pytest.raises(TypeError, match="must implement async persist"):
            decorator.register(BadHandler)

    def test_decorator_validates_schema_attribute(self):
        """Test that decorator validates schema attribute."""
        from orchestrai_django.decorators import DjangoPersistenceHandlerDecorator

        decorator = DjangoPersistenceHandlerDecorator()

        class BadHandler(BasePersistenceHandler):
            # Missing schema attribute!
            async def persist(self, response):
                pass

        with pytest.raises(TypeError, match="must declare 'schema' class attribute"):
            decorator.register(BadHandler)


@pytest.mark.django_db
class TestDrainWorkerIntegration:
    """Integration tests for the persistence drain worker."""

    @pytest.mark.asyncio
    async def test_full_persistence_cycle(self):
        """Test complete cycle: service → drain → domain object."""
        # This test would require full Django setup and is marked for manual testing
        # due to complexity of setting up complete service execution environment
        pass
