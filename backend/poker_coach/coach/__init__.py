"""Evidence-grounded teaching services and evaluation boundaries."""

from .external import ExternalModelTeacher
from .teacher import TeachingService
from .tools import TeachingToolGateway

__all__ = ["ExternalModelTeacher", "TeachingService", "TeachingToolGateway"]
