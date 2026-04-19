"""Tests for the public build info endpoint."""

from importlib.metadata import PackageNotFoundError

from django.test import Client
import pytest

from apps.common.services import build_info as build_info_service


@pytest.mark.django_db
class TestBuildInfoHelpers:
    """Helper-level tests for build metadata resolution."""

    def test_backend_version_uses_canonical_project_name(self, monkeypatch, tmp_path):
        """Backend version lookup should follow ``[project].name`` from pyproject metadata."""
        pyproject_path = tmp_path / "pyproject.toml"
        pyproject_path.write_text('[project]\nname = "BackendDist"\n')
        monkeypatch.setattr(build_info_service, "PYPROJECT_TOML_PATH", pyproject_path)

        looked_up_names: list[str] = []

        def fake_version(package_name: str) -> str:
            looked_up_names.append(package_name)
            return "0.10.2"

        monkeypatch.setattr(build_info_service, "version", fake_version)

        assert build_info_service.get_backend_version() == "0.10.2"
        assert looked_up_names == ["BackendDist"]

    def test_commit_env_precedence_prefers_app_git_sha(self, monkeypatch):
        """APP_GIT_SHA should win over GIT_SHA when both are present."""
        monkeypatch.setenv("APP_GIT_SHA", "preferred-sha")
        monkeypatch.setenv("GIT_SHA", "fallback-sha")

        assert build_info_service.get_backend_commit() == "preferred-sha"

    def test_build_time_env_precedence_prefers_app_build_time(self, monkeypatch):
        """APP_BUILD_TIME should win over BUILD_TIME when both are present."""
        monkeypatch.setenv("APP_BUILD_TIME", "2026-04-09T17:12:44Z")
        monkeypatch.setenv("BUILD_TIME", "2026-04-09T12:00:00Z")

        assert build_info_service.get_backend_build_time() == "2026-04-09T17:12:44Z"

    def test_build_time_falls_back_to_build_time_env_var(self, monkeypatch):
        """BUILD_TIME should be used when APP_BUILD_TIME is unset."""
        monkeypatch.delenv("APP_BUILD_TIME", raising=False)
        monkeypatch.setenv("BUILD_TIME", "2026-04-09T12:00:00Z")

        assert build_info_service.get_backend_build_time() == "2026-04-09T12:00:00Z"

    def test_build_time_returns_none_for_missing_or_blank_values(self, monkeypatch):
        """Blank or missing build time env vars should resolve to None."""
        monkeypatch.setenv("APP_BUILD_TIME", "   ")
        monkeypatch.setenv("BUILD_TIME", "")

        assert build_info_service.get_backend_build_time() is None


@pytest.mark.django_db
class TestBuildInfoEndpoint:
    """Contract tests for /api/v1/build-info/."""

    def test_build_info_happy_path(self, monkeypatch):
        """Endpoint returns best-effort metadata when all sources exist."""
        monkeypatch.setenv("APP_GIT_SHA", "abc1234")
        monkeypatch.setenv("APP_BUILD_TIME", "2026-04-09T17:12:44Z")
        monkeypatch.setattr(
            "apps.common.services.build_info.get_backend_package_name",
            lambda: "backend-dist",
        )

        def fake_safe_version(package_name: str) -> str | None:
            if package_name == "backend-dist":
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
                "build_time": "2026-04-09T17:12:44Z",
            },
            "orchestrai": {
                "version": "0.5.1",
            },
        }

    def test_build_info_missing_commit_env_var(self, monkeypatch):
        """Endpoint returns null commit when no build SHA was injected."""
        monkeypatch.delenv("APP_GIT_SHA", raising=False)
        monkeypatch.delenv("GIT_SHA", raising=False)
        monkeypatch.delenv("APP_BUILD_TIME", raising=False)
        monkeypatch.delenv("BUILD_TIME", raising=False)
        monkeypatch.setattr(
            "apps.common.services.build_info.get_backend_package_name",
            lambda: "backend-dist",
        )
        monkeypatch.setattr(
            "apps.common.services.build_info.safe_package_version",
            lambda package_name: "0.10.2" if package_name == "backend-dist" else "0.5.1",
        )

        response = Client().get("/api/v1/build-info/")

        assert response.status_code == 200
        data = response.json()
        assert data["backend"]["commit"] is None
        assert data["backend"]["build_time"] is None

    def test_build_info_missing_orchestrai_package_metadata(self, monkeypatch):
        """Endpoint degrades gracefully when OrchestrAI metadata is unavailable."""
        monkeypatch.setenv("APP_GIT_SHA", "abc1234")
        monkeypatch.setenv("APP_BUILD_TIME", "2026-04-09T17:12:44Z")
        monkeypatch.setattr(
            "apps.common.services.build_info.get_backend_package_name",
            lambda: "backend-dist",
        )

        def fake_version(package_name: str) -> str:
            if package_name == "backend-dist":
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
        assert data["backend"]["build_time"] == "2026-04-09T17:12:44Z"
        assert data["orchestrai"]["version"] is None

    def test_build_info_build_time_falls_back_to_build_time_env(self, monkeypatch):
        """Endpoint should expose BUILD_TIME when APP_BUILD_TIME is unset."""
        monkeypatch.delenv("APP_BUILD_TIME", raising=False)
        monkeypatch.setenv("BUILD_TIME", "2026-04-09T17:12:44Z")
        monkeypatch.setattr(
            "apps.common.services.build_info.get_backend_package_name",
            lambda: "backend-dist",
        )
        monkeypatch.setattr(
            "apps.common.services.build_info.safe_package_version",
            lambda package_name: "0.10.2" if package_name == "backend-dist" else "0.5.1",
        )

        response = Client().get("/api/v1/build-info/")

        assert response.status_code == 200
        assert response.json()["backend"]["build_time"] == "2026-04-09T17:12:44Z"

    def test_build_info_response_shape_always_present(self, monkeypatch):
        """Endpoint keeps a stable JSON shape even when values are null."""
        monkeypatch.delenv("APP_GIT_SHA", raising=False)
        monkeypatch.delenv("GIT_SHA", raising=False)
        monkeypatch.delenv("APP_BUILD_TIME", raising=False)
        monkeypatch.delenv("BUILD_TIME", raising=False)
        monkeypatch.setattr("apps.common.services.build_info.safe_package_version", lambda _: None)

        response = Client().get("/api/v1/build-info/")

        assert response.status_code == 200
        assert response["Content-Type"].startswith("application/json")
        data = response.json()
        assert set(data.keys()) == {"backend", "orchestrai"}
        assert set(data["backend"].keys()) == {"version", "commit", "build_time"}
        assert set(data["orchestrai"].keys()) == {"version"}
