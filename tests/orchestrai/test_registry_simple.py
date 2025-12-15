from orchestrai.registry.simple import AppRegistry


def test_finalize_callbacks_registered_and_invoked_with_app():
    registry = AppRegistry()
    calls = []

    def callback(app):
        calls.append(app)

    returned = registry.add_finalize_callback(callback)

    assert returned is callback
    registry.finalize(app="sentinel-app")

    assert calls == ["sentinel-app"]
    assert registry._frozen is True


def test_finalize_defaults_to_registry_when_no_app_provided():
    registry = AppRegistry()
    captured = []

    registry.add_finalize_callback(lambda app: captured.append(app))

    registry.finalize()

    assert captured == [registry]
    assert registry._frozen is True
