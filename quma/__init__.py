from .database import (  # noqa: F401
    Database,
    connect,
)
from .exc import (  # noqa: F401
    APIError,
    ConnectionError,
    DoesNotExistError,
    FetchError,
    MultipleRowsError,
    OperationalError,
    TimeoutError,
)
from .namespace import Namespace

__all__ = [
    "Database",
    "Namespace",
    "connect",
    "APIError",
    "ConnectionError",
    "DoesNotExistError",
    "FetchError",
    "MultipleRowsError",
    "OperationalError",
    "TimeoutError",
]

__version__ = "0.2.2"
