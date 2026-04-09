"""Tests for the public build info endpoint."""

from importlib.metadata import PackageNotFoundError

from django.test import Client
import pytest


@pytest.mark.django_db
class TestBuildInfoEndpoint:
    """Contract tests for /api/v1/build-info/."""

    def test_build_info_happy_path(self, monkeypatch):
        """Endpoint returns best-effort metadata when all sources exist."""
        monkeypatch.setenv("APP_GIT_SHA", "abc1234")

        def fake_safe_version(package_name: str) -> str | None:
            if package_name == "MedSim":
                return "0.10.2"
            if package_name == "orchestrai":
                return "0.5.1"
            return None

        monkeypatch.setattr(
            "apps.common.services.build_info.safe_package_version",
            fake_safe_version,
        )

        response = Client().get("/api/v1/build-info/")

        assert response.status_code == 200
        assert response["Content-Type"].startswith("application/json")
        assert response.json() == {
            "backend": {
                "version": "0.10.2",
                "commit": "abc1234",
                "build_time": None,
            },
            "orchestrai": {
                "version": "0.5.1",
            },
        }

    def test_build_info_missing_commit_env_var(self, monkeypatch):
        """Endpoint returns null commit when no build SHA was injected."""
        monkeypatch.delenv("APP_GIT_SHA", raising=False)
        monkeypatch.delenv("GIT_SHA", raising=False)
        monkeypatch.setattr(
            "apps.common.services.build_info.safe_package_version",
            lambda package_name: "0.10.2" if package_name == "MedSim" else "0.5.1",
        )

        response = Client().get("/api/v1/build-info/")

        assert response.status_code == 200
        data = response.json()
        assert data["backend"]["commit"] is None
        assert data["backend"]["build_time"] is None

    def test_build_info_missing_orchestrai_package_metadata(self, monkeypatch):
        """Endpoint degrades gracefully when OrchestrAI metadata is unavailable."""
        monkeypatch.setenv("APP_GIT_SHA", "abc1234")

        def fake_version(package_name: str) -> str:
            if package_name == "MedSim":
                return "0.10.2"
            if package_name == "orchestrai":
                raise PackageNotFoundError(package_name)
            raise AssertionError(f"Unexpected package lookup: {package_name}")

        monkeypatch.setattr("apps.common.services.build_info.version", fake_version)

        response = Client().get("/api/v1/build-info/")

        assert response.status_code == 200
        data = response.json()
        assert data["backend"]["version"] == "0.10.2"
        assert data["backend"]["commit"] == "abc1234"
        assert data["orchestrai"]["version"] is None

    def test_build_info_response_shape_always_present(self, monkeypatch):
        """Endpoint keeps a stable JSON shape even when values are null."""
        monkeypatch.delenv("APP_GIT_SHA", raising=False)
        monkeypatch.delenv("GIT_SHA", raising=False)
        monkeypatch.setattr("apps.common.services.build_info.safe_package_version", lambda _: None)

        response = Client().get("/api/v1/build-info/")

        assert response.status_code == 200
        assert response["Content-Type"].startswith("application/json")
        data = response.json()
        assert set(data.keys()) == {"backend", "orchestrai"}
        assert set(data["backend"].keys()) == {"version", "commit", "build_time"}
        assert set(data["orchestrai"].keys()) == {"version"}
