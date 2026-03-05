"""Tests for orchestrai.utils.json - JSON serialization utilities."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
import json
from uuid import UUID, uuid4

from pydantic import BaseModel

from orchestrai.utils.json import json_default, make_json_safe


class SampleEnum(Enum):
    """Sample enum for testing."""

    OPTION_A = "a"
    OPTION_B = "b"


class SampleModel(BaseModel):
    """Sample Pydantic model for testing."""

    name: str
    value: int


class NestedModel(BaseModel):
    """Nested Pydantic model with UUID field."""

    id: UUID
    data: SampleModel


# -----------------------------------------------------------------------------
# make_json_safe tests
# -----------------------------------------------------------------------------


class TestMakeJsonSafe:
    """Tests for make_json_safe function."""

    def test_none_passthrough(self):
        """None values pass through unchanged."""
        assert make_json_safe(None) is None

    def test_primitives_passthrough(self):
        """Primitive JSON types pass through unchanged."""
        assert make_json_safe("hello") == "hello"
        assert make_json_safe(42) == 42
        assert make_json_safe(3.14) == 3.14
        assert make_json_safe(True) is True
        assert make_json_safe(False) is False

    def test_uuid_converts_to_string(self):
        """UUID converts to string."""
        val = uuid4()
        result = make_json_safe(val)
        assert result == str(val)
        assert isinstance(result, str)

    def test_uuid_from_string(self):
        """UUID created from string converts correctly."""
        val = UUID("12345678-1234-5678-1234-567812345678")
        result = make_json_safe(val)
        assert result == "12345678-1234-5678-1234-567812345678"

    def test_datetime_converts_to_isoformat(self):
        """datetime converts to ISO format string."""
        val = datetime(2024, 1, 15, 10, 30, 45)
        result = make_json_safe(val)
        assert result == "2024-01-15T10:30:45"
        assert isinstance(result, str)

    def test_date_converts_to_isoformat(self):
        """date converts to ISO format string."""
        val = date(2024, 1, 15)
        result = make_json_safe(val)
        assert result == "2024-01-15"
        assert isinstance(result, str)

    def test_time_converts_to_isoformat(self):
        """time converts to ISO format string."""
        val = time(10, 30, 45)
        result = make_json_safe(val)
        assert result == "10:30:45"
        assert isinstance(result, str)

    def test_timedelta_converts_to_seconds(self):
        """timedelta converts to total seconds."""
        val = timedelta(hours=1, minutes=30)
        result = make_json_safe(val)
        assert result == 5400.0
        assert isinstance(result, float)

    def test_decimal_converts_to_string_preserving_precision(self):
        """Decimal converts to string (preserves precision)."""
        val = Decimal("3.14159265358979323846")
        result = make_json_safe(val)
        assert result == "3.14159265358979323846"
        assert isinstance(result, str)

    def test_decimal_whole_number(self):
        """Decimal whole numbers convert correctly."""
        val = Decimal("100")
        result = make_json_safe(val)
        assert result == "100"

    def test_enum_converts_to_value(self):
        """Enum converts to its value."""
        result = make_json_safe(SampleEnum.OPTION_A)
        assert result == "a"

    def test_bytes_converts_to_base64_string(self):
        """bytes converts to base64-encoded string."""
        val = b"hello world"
        result = make_json_safe(val)
        assert result == "aGVsbG8gd29ybGQ="  # base64 of "hello world"
        assert isinstance(result, str)

    def test_bytes_binary_data(self):
        """Binary bytes (e.g., image data) encodes to base64."""
        val = b"\xff\xfe\x00\x01"
        result = make_json_safe(val)
        assert result == "//4AAQ=="  # base64 of the binary data
        assert isinstance(result, str)

    def test_pydantic_model_converts_to_dict(self):
        """Pydantic model converts via model_dump(mode='json')."""
        model = SampleModel(name="test", value=42)
        result = make_json_safe(model)
        assert result == {"name": "test", "value": 42}
        assert isinstance(result, dict)

    def test_pydantic_model_with_uuid_field(self):
        """Pydantic model with UUID field serializes correctly."""
        uid = uuid4()
        model = NestedModel(id=uid, data=SampleModel(name="nested", value=100))
        result = make_json_safe(model)
        assert result["id"] == str(uid)
        assert result["data"] == {"name": "nested", "value": 100}

    def test_dict_recursively_converts(self):
        """Dict values are recursively converted."""
        val = {
            "uuid": uuid4(),
            "date": date(2024, 1, 15),
            "decimal": Decimal("99.99"),
        }
        result = make_json_safe(val)
        assert isinstance(result["uuid"], str)
        assert result["date"] == "2024-01-15"
        assert result["decimal"] == "99.99"

    def test_dict_with_non_string_keys(self):
        """Dict with non-string keys converts keys to strings."""
        val = {1: "one", 2: "two"}
        result = make_json_safe(val)
        assert result == {"1": "one", "2": "two"}

    def test_list_recursively_converts(self):
        """List values are recursively converted."""
        val = [uuid4(), date(2024, 1, 15), "plain"]
        result = make_json_safe(val)
        assert isinstance(result[0], str)
        assert result[1] == "2024-01-15"
        assert result[2] == "plain"

    def test_tuple_converts_to_list(self):
        """Tuple converts to list with values converted."""
        val = (uuid4(), 42, "text")
        result = make_json_safe(val)
        assert isinstance(result, list)
        assert len(result) == 3

    def test_set_converts_to_list(self):
        """Set converts to list with values converted."""
        val = {1, 2, 3}
        result = make_json_safe(val)
        assert isinstance(result, list)
        assert set(result) == {1, 2, 3}

    def test_frozenset_converts_to_list(self):
        """Frozenset converts to list with values converted."""
        val = frozenset([1, 2, 3])
        result = make_json_safe(val)
        assert isinstance(result, list)
        assert set(result) == {1, 2, 3}

    def test_nested_structures(self):
        """Nested structures are fully converted."""
        uid = uuid4()
        val = {
            "items": [
                {"id": uid, "created": datetime(2024, 1, 15, 10, 0)},
                {"id": uuid4(), "amount": Decimal("123.45")},
            ],
            "metadata": {
                "enum": SampleEnum.OPTION_B,
            },
        }
        result = make_json_safe(val)

        assert isinstance(result["items"][0]["id"], str)
        assert result["items"][0]["created"] == "2024-01-15T10:00:00"
        assert result["items"][1]["amount"] == "123.45"
        assert result["metadata"]["enum"] == "b"

    def test_object_with_dict_attr(self):
        """Object with __dict__ attribute is converted."""

        class SimpleObj:
            def __init__(self):
                self.name = "test"
                self.value = 42

        obj = SimpleObj()
        result = make_json_safe(obj)
        assert result == {"name": "test", "value": 42}

    def test_unknown_type_converts_to_string(self):
        """Unknown types without __dict__ fall back to string representation."""

        class CustomType:
            __slots__ = ()  # No __dict__ attribute

            def __str__(self):
                return "custom_value"

        obj = CustomType()
        result = make_json_safe(obj)
        assert result == "custom_value"

    def test_empty_object_with_dict(self):
        """Object with empty __dict__ converts to empty dict."""

        class EmptyObj:
            pass

        obj = EmptyObj()
        result = make_json_safe(obj)
        assert result == {}


# -----------------------------------------------------------------------------
# json_default tests
# -----------------------------------------------------------------------------


class TestJsonDefault:
    """Tests for json_default function (for use with json.dumps)."""

    def test_uuid_serializes(self):
        """json.dumps with default=json_default handles UUID."""
        data = {"id": uuid4()}
        result = json.dumps(data, default=json_default)
        assert '"id":' in result

    def test_datetime_serializes(self):
        """json.dumps with default=json_default handles datetime."""
        data = {"timestamp": datetime(2024, 1, 15, 10, 30)}
        result = json.dumps(data, default=json_default)
        assert "2024-01-15T10:30:00" in result

    def test_decimal_serializes(self):
        """json.dumps with default=json_default handles Decimal."""
        data = {"amount": Decimal("99.99")}
        result = json.dumps(data, default=json_default)
        assert "99.99" in result

    def test_complex_nested_structure(self):
        """json.dumps handles complex nested structures."""
        uid = uuid4()
        data = {
            "correlation_id": uid,
            "items": [
                {"date": date(2024, 1, 15)},
                {"enum": SampleEnum.OPTION_A},
            ],
            "metadata": {
                "delta": timedelta(hours=2),
            },
        }
        result = json.dumps(data, default=json_default)
        parsed = json.loads(result)

        assert parsed["correlation_id"] == str(uid)
        assert parsed["items"][0]["date"] == "2024-01-15"
        assert parsed["items"][1]["enum"] == "a"
        assert parsed["metadata"]["delta"] == 7200.0

    def test_pydantic_model_serializes(self):
        """json.dumps handles Pydantic models."""
        model = SampleModel(name="test", value=42)
        result = json.dumps({"model": model}, default=json_default)
        parsed = json.loads(result)
        assert parsed["model"] == {"name": "test", "value": 42}


# -----------------------------------------------------------------------------
# Integration tests
# -----------------------------------------------------------------------------


class TestIntegration:
    """Integration tests for JSON utilities."""

    def test_service_call_like_payload(self):
        """Test payload structure similar to ServiceCall."""
        payload = {
            "id": "call-123",
            "status": "completed",
            "input": {"prompt": "Hello"},
            "context": {"correlation_id": uuid4()},
            "result": {
                "response": "Hi there",
                "tokens": 10,
                "created_at": datetime.now(),
            },
            "error": None,
            "dispatch": {
                "backend": "celery",
                "task_id": uuid4(),
            },
            "created_at": datetime.now(),
        }

        # Should not raise
        result = make_json_safe(payload)
        json_str = json.dumps(result)

        # Verify roundtrip
        parsed = json.loads(json_str)
        assert parsed["id"] == "call-123"
        assert isinstance(parsed["context"]["correlation_id"], str)
        assert isinstance(parsed["dispatch"]["task_id"], str)

    def test_websocket_event_payload(self):
        """Test payload structure similar to WebSocket events."""
        event = {
            "type": "chat.message",
            "message_id": uuid4(),
            "created_at": datetime.now(),
            "content": {
                "text": "Hello",
                "metadata": {
                    "simulation_id": 123,
                    "timestamp": datetime.now(),
                },
            },
        }

        # Should serialize without error
        json_str = json.dumps(event, default=json_default)
        parsed = json.loads(json_str)

        assert parsed["type"] == "chat.message"
        assert isinstance(parsed["message_id"], str)
        assert isinstance(parsed["created_at"], str)
