import pytest

from orchestrai import OrchestrAI
from orchestrai.identity.utils import DEFAULT_IDENTITY_STRIP_TOKENS, get_effective_strip_tokens


@pytest.fixture(autouse=True)
def reset_env(monkeypatch):
    monkeypatch.delenv("IDENTITY_STRIP_TOKENS", raising=False)
    monkeypatch.delenv("SIMCORE_IDENTITY_STRIP_TOKENS", raising=False)
    monkeypatch.delenv("ORCHESTRAI_CONFIG_MODULE", raising=False)


def test_strip_tokens_merge_conf_and_env(monkeypatch):
    monkeypatch.setenv("IDENTITY_STRIP_TOKENS", "Foo, Bar")

    app = OrchestrAI()
    app.configure({"IDENTITY_STRIP_TOKENS": ("Baz",)})
    app.set_as_current()
    app.setup()

    tokens = get_effective_strip_tokens()

    assert {"Foo", "Bar", "Baz"}.issubset(set(tokens))
    assert set(tokens).issuperset(DEFAULT_IDENTITY_STRIP_TOKENS)
    assert tuple(tokens) == tuple(app.conf["IDENTITY_STRIP_TOKENS"])


def test_strip_tokens_include_settings_module(monkeypatch, tmp_path):
    module = tmp_path / "custom_settings.py"
    module.write_text("IDENTITY_STRIP_TOKENS = ('Alpha', 'Beta')\n")

    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("ORCHESTRAI_CONFIG_MODULE", "custom_settings")

    app = OrchestrAI()
    with app.as_current():
        app.setup()
        tokens = get_effective_strip_tokens()

    assert {"Alpha", "Beta"}.issubset(set(tokens))
    assert {"Alpha", "Beta"}.issubset(set(app.conf["IDENTITY_STRIP_TOKENS"]))
