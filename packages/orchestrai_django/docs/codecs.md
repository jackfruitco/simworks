# Codecs

`DjangoBaseCodec` is available for response decoding/persistence compatibility flows.

## Base Import

```python
from orchestrai_django.components.codecs import DjangoBaseCodec
```

## Typical Use

```python
class MyCodec(DjangoBaseCodec):
    abstract = False
```

## Notes

- Modern v0.5.0 service execution is instruction-first and schema-driven.
- Use codecs only when you need custom decode/persist behavior.
- Registry checks still validate codec/service pairing expectations.
