# simcore_ai

A lightweight, provider-agnostic orchestration layer for building structured AI workflows in pure Python. `simcore_ai` focuses on predictable data contracts, modular prompt construction, and provider plug-ins that can be swapped without rewriting business logic.

## Key features

- **Prompt-first composition** &mdash; build prompts from reusable sections that render to provider-ready messages.
- **Typed data models** &mdash; normalized request, response, and tool DTOs keep transport details out of your domain logic.
- **Codec pipeline** &mdash; attach validation and transformation rules so raw provider responses become strongly-typed Python objects.
- **Service abstraction** &mdash; encapsulate AI calls behind class-based or function-based services with built-in retry and telemetry hooks.
- **Provider adapters** &mdash; implement an adapter once and reuse it across services without leaking provider-specific details.

## Installation

```bash
pip install simcore-ai
```

Extras are provided for specific AI backends. Install the extra that matches your target provider:

```bash
pip install simcore-ai[openai]
```

## Documentation

Comprehensive guides live in the [`docs/`](docs/) directory:

- [Quick Start](docs/quick_start.md) &mdash; install the package, configure a provider, and run your first service call.
- [Full Guide](docs/full_documentation.md) &mdash; deep dive into DTOs, prompt composition, codecs, providers, and extension patterns.

## Contributing

1. Create a virtual environment and install the package in editable mode: `pip install -e .[dev]`.
2. Run the test suite before submitting changes: `pytest`.
3. Follow conventional commit messages and open a pull request with a clear summary of your changes.

## License

MIT License © 2024 simcore_ai contributors
