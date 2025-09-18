"""Custom exceptions for the memory service."""


class MemoryServiceError(Exception):
    """Base error for memory service."""


class AuthenticationError(MemoryServiceError):
    """Raised when authentication fails."""


class AuthorizationError(MemoryServiceError):
    """Raised when tenancy validation fails."""


class InvalidScopeError(MemoryServiceError):
    """Raised when an unsupported scope is requested."""


class DuplicateMemoryError(MemoryServiceError):
    """Raised when a request attempts to create a duplicate memory."""


class NotFoundError(MemoryServiceError):
    """Raised when a memory cannot be retrieved."""

