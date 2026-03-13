from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
TRAINERLAB_SSE_LOCATION = "location ~ ^/api/v1/trainerlab/simulations/[0-9]+/events/stream/$ {"
REQUIRED_DIRECTIVES = (
    "proxy_http_version 1.1;",
    "proxy_buffering off;",
    "proxy_cache off;",
    "gzip off;",
    "proxy_read_timeout 3600s;",
    "proxy_send_timeout 3600s;",
)


@pytest.mark.parametrize(
    "config_path",
    [
        REPO_ROOT / "nginx" / "default.conf",
        REPO_ROOT / "nginx" / "default.dev.conf",
    ],
)
def test_trainerlab_sse_location_disables_proxy_buffering(config_path):
    config = config_path.read_text(encoding="utf-8")

    assert TRAINERLAB_SSE_LOCATION in config
    assert config.index(TRAINERLAB_SSE_LOCATION) < config.index("location / {")
    for directive in REQUIRED_DIRECTIVES:
        assert directive in config
