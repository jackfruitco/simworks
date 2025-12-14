# Celery-inspired OrchestrAI app architecture

This repository introduces a lightweight, Celery-style application object for
OrchestrAI. The goals mirror Celery's ergonomics: a small app created early,
deferred heavy work, and a thread-local **current app** proxy that always
resolves to something usable.

## Key pieces

- **State + Proxy**: `orchestrai._state` stores the current app in thread-local
  storage and exposes a `current_app` proxy. Importing `current_app` does not
  trigger discovery or heavy setup.
- **App lifecycle**: `OrchestrAI` provides `setup()`, `start()`, and `run()`.
  `setup()` configures registries and providers/clients without discovery;
  `start()/run()` performs autodiscovery then finalizes the app.
- **Configuration**: `orchestrai.conf.settings.Settings` is a mapping-like
  object layered over defaults from `orchestrai.conf.defaults`, environment, or
  user modules. Configuration can be loaded via env var or module path and does
  not require Pydantic.
- **Loader seam**: `orchestrai.loaders.base.BaseLoader` defines the hooks for
  reading config and autodiscovery; `DefaultLoader` implements env-based config
  and simple module importing.
- **Fixups**: `orchestrai.fixups.base.BaseFixup` defines hooks for integrations
  to extend autodiscovery or add pre-import logic. Core remains free of Django
  imports.
- **Finalize callbacks + shared decorators**: finalize callbacks registered via
  `connect_on_app_finalize` run during `app.finalize()`. `@shared_service`
  captures a service function before any app exists and attaches it during
  finalize.
- **Registries**: `Registry` objects live on the app (`services`, `clients`,
  `providers`, `codecs`, `prompt_sections`) and are frozen on finalize.

## Lifecycle expectations

1. Create an app: `app = OrchestrAI("orca")`.
2. Optionally mark it current: `app.set_as_current()` or `with app.as_current():`.
3. Load configuration: `app.load_from_conf()` or `app.config_from_object(...)`.
4. `app.setup()` configures autoclient/clients/providers without discovery.
5. `app.start()` (or `run()`) triggers autodiscovery via the loader and runs
   finalize callbacks, freezing registries.

Calls to `setup()` and `start()` are idempotent; repeated invocations will not
duplicate registrations or imports.

