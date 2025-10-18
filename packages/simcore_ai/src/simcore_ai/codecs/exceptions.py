from simcore_ai.exceptions.registry_exceptions import RegistryLookupError
from simcore_ai.exceptions.base import SimCoreError


class CodecError(SimCoreError): ...


class CodecNotFoundError(CodecError, RegistryLookupError): ...


class CodecSchemaError(CodecError): ...  # bad/missing schema_cls


class CodecDecodeError(CodecError): ...  # failed to parse response


class CodecEncodeError(CodecError): ...


class CodecRegistrationError(CodecError): ...  # unable to register codec
