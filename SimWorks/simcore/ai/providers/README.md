# SimWorks Providers Package

## Overview

The Providers system in SimWorks is designed to enable integration of various backend services or APIs through a standardized interface. Providers act as adapters that conform to a common contract, allowing SimWorks to interact with different external systems seamlessly. This modular approach facilitates extensibility, maintainability, and customization of backend integrations.

---

## Minimum Requirements to Add a New Provider

To add a new provider to SimWorks, you need to:

- Create a dedicated Python package for the provider.
- Implement a `base.py` module defining the provider's core class.
- Implement a `constructor.py` module defining the provider's constructor.
- Ensure the provider class inherits from the appropriate base provider class.
- Implement required methods and overrides to match the provider's API.
- Optionally provide schema overrides, tool adapters, and streaming support.
- Register and expose your provider through the package's `__init__.py`.

---

## Step-by-Step Guide to Adding a New Provider

### 1. Package Structure

Your provider package should follow this structure:

```
your_provider/
├── __init__.py             # required
├── base.py                 # required
├── constructor.py          # required
├── tools.py                # optional
└── schema_overrides.py     # optional
```

- `__init__.py`: Re-export the main provider class and any tools or utilities.
- `base.py`: Define the main provider class with core logic.
- `constructor.py`: Define the provider's constructor and any overrides.
- `tools.py`: Define any provider-specific tools or adapters.
- `schema_overrides.py`: Override or extend the provider's schema if necessary.

### 2. Re-exports

In `__init__.py`, re-export the main provider class and any tools to simplify imports:

```python
from .base import YourProvider
from .constructor import YourProviderConstructor
from .tools import YourProviderTool

__all__ = ["YourProvider", "YourProviderConstructor", "YourProviderTool"]
```

### 3. Implementing `base.py`

Define your provider's main class in `base.py`, inheriting from the appropriate base provider class (e.g., `BaseProvider` or a relevant subclass). Implement core methods such as initialization, request handling, and response parsing.

Example skeleton:

```python
from simcore.providers.base import BaseProvider

class YourProvider(BaseProvider):
    def __init__(self, api_key: str, **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key

    def send_request(self, payload):
        # Implement request sending logic here
        pass

    def parse_response(self, response):
        # Implement response parsing logic here
        pass
```

### 4. Constructor and Overrides

- The constructor should accept necessary credentials and settings.
- Override methods to handle provider-specific behavior.
- Use schema overrides to customize the provider's data schema if needed.
- Override or extend tools to provide additional functionality.

### 5. Tools

Define any provider-specific tools in `tools.py`. Tools can be utilities or adapters that interact with the provider or enhance its functionality.

Example:

```python
class YourProviderTool:
    def __init__(self, provider: YourProvider):
        self.provider = provider

    def perform_action(self):
        # Implement tool-specific action
        pass
```

---

## Options Available for Providers

- **Schema Overrides**: Customize or extend the provider's data schema by defining overrides in `schema_overrides.py`.
- **Tool Adapters**: Provide additional tools or utilities specific to the provider.
- **Streaming Support**: Implement streaming interfaces if the provider supports streaming data.
- **Construction from Settings**: Support instantiation of the provider from configuration or settings files.
- **Cache Clearing**: Implement cache clearing methods to reset or clear any cached data within the provider.

---

## Example Skeleton Provider Code

```python
# base.py
from simworks.providers.base import BaseProvider

class YourProvider(BaseProvider):
    def __init__(self, api_key: str, **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key

    def send_request(self, payload):
        # Send request to provider API
        pass

    def parse_response(self, response):
        # Parse the response from provider API
        pass

# tools.py
class YourProviderTool:
    def __init__(self, provider: YourProvider):
        self.provider = provider

    def perform_action(self):
        # Tool-specific logic here
        pass

# __init__.py
from .base import YourProvider
from .tools import YourProviderTool

__all__ = ["YourProvider", "YourProviderTool"]
```

---

## Summary of Contracts Between Client and Provider

- **Initialization**: Provider must be initialized with necessary credentials and settings.
- **Request Handling**: Provider must implement methods to send requests and receive responses.
- **Response Parsing**: Provider must parse responses into a format consumable by SimWorks.
- **Schema Compliance**: Provider should comply with or extend the expected data schema.
- **Tool Integration**: Provider may expose tools for additional functionalities.
- **Streaming and Caching**: Providers may implement streaming and caching mechanisms as needed.

By following these guidelines, you ensure your provider integrates smoothly within the SimWorks ecosystem, providing a consistent and reliable backend interface.
