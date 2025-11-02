from simcore_ai.exceptions.base import SimCoreError
from simcore_ai.exceptions.registry_exceptions import RegistryLookupError, RegistryDuplicateError, RegistryError


class CodecError(SimCoreError): ...


class CodecSchemaError(CodecError): ...  # bad/missing schema_cls


class CodecDecodeError(CodecError): ...  # failed to parse response


class CodecEncodeError(CodecError): ...


class CodecRegistrationError(RegistryError, CodecError): ...  # unable to register codec


class CodecDuplicateRegistrationError(CodecRegistrationError, RegistryDuplicateError): ...


class CodecNotFoundError(CodecError, RegistryLookupError): ...
