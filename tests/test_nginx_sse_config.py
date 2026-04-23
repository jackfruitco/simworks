from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SSE_LOCATION = (
    "location ~ ^/api/v1/trainerlab/(events/stream|simulations/[0-9]+/events/stream)/?$ {"
)
REQUIRED_SSE_DIRECTIVES = (
    "proxy_http_version 1.1;",
    "proxy_buffering off;",
    "proxy_cache off;",
    "gzip off;",
    "proxy_read_timeout 3600s;",
    "proxy_send_timeout 3600s;",
)


def _extract_location_block(config: str, location_header: str) -> str:
    """Return the text of the nginx location block starting with *location_header*.

    Walks the source character-by-character from the opening ``{`` to the matching
    closing ``}``, so directives in sibling blocks cannot produce false positives.
    """
    start = config.find(location_header)
    if start == -1:
        return ""

    brace_start = config.index("{", start)
    depth = 0
    for i, ch in enumerate(config[brace_start:], start=brace_start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return config[brace_start : i + 1]
    return ""


@pytest.mark.parametrize(
    "config_path",
    [
        REPO_ROOT / "nginx" / "default.conf",
        REPO_ROOT / "nginx" / "default.dev.conf",
    ],
)
def test_sse_location_disables_proxy_buffering(config_path):
    config = config_path.read_text(encoding="utf-8")

    assert SSE_LOCATION in config, f"Missing SSE location block in {config_path.name}"
    assert config.index(SSE_LOCATION) < config.index("location / {"), (
        f"SSE block must appear before 'location / {{' in {config_path.name}"
    )

    block = _extract_location_block(config, SSE_LOCATION)
    for directive in REQUIRED_SSE_DIRECTIVES:
        assert directive in block, f"{directive!r} not found inside SSE block in {config_path.name}"
