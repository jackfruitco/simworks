# tests/types/test_dtos_streaming.py

from uuid import UUID

from simcore_ai.types.transport import StreamChunk


def test_stream_chunk_defaults():
    chunk = StreamChunk(lab_key="chatlab", simulation_id=123)

    assert isinstance(chunk.correlation_id, UUID)
    assert chunk.lab_key == "chatlab"
    assert chunk.simulation_id == 123
    assert chunk.is_final is False
    assert chunk.delta == ""
    assert chunk.tool_call_delta is None
    assert chunk.usage_partial is None


def test_stream_chunk_with_partial_usage_and_tool_delta():
    chunk = StreamChunk(
        lab_key="chatlab",
        simulation_id=123,
        is_final=True,
        delta="Hello",
        usage_partial={"input_tokens": 5, "output_tokens": 10},
    )

    assert chunk.is_final is True
    assert chunk.delta == "Hello"
    assert chunk.usage_partial["input_tokens"] == 5
    assert chunk.usage_partial["output_tokens"] == 10