from types import SimpleNamespace

from orchestrai.client.utils import _resolve_from_env
from orchestrai.components.providerkit.provider import ProviderConfig


def test_resolve_from_env_returns_value(monkeypatch):
    env_key = "ORCHESTRAI_TEST_API_KEY"
    env_value = "super-secret-value"
    monkeypatch.setenv(env_key, env_value)

    client = SimpleNamespace(api_key_env=env_key)
    provider = ProviderConfig(alias="alias", backend="backend", api_key_env="OTHER_ENV")

    assert _resolve_from_env(client, provider) == env_value
