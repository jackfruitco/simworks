"""Deprecated module.

`orchestrai.components.schemas.compiler` has been deprecated and replaced by
codec-local schema adaptation. Configure schema adapters on codec classes in
`orchestrai.components.codecs` instead of using this module.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "`orchestrai.components.schemas.compiler` is deprecated; use codec-local"
    " schema adaptation under `orchestrai.components.codecs` instead.",
    DeprecationWarning,
    stacklevel=2,
)

raise DeprecationWarning(
    "`orchestrai.components.schemas.compiler` has been removed. Configure "
    "schema adapters on codec classes in `orchestrai.components.codecs`."
)
