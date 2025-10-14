from simcore_ai.codecs.exceptions import CodecNotFoundError
from simcore_ai.exceptions.base import SimCoreError


class ServiceError(SimCoreError): ...


class ServiceConfigError(ServiceError): ...


class ServiceCodecResolutionError(ServiceError, CodecNotFoundError): ...


class ServiceBuildRequestError(ServiceError): ...


class ServiceStreamError(ServiceError): ...
