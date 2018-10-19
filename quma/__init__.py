import platform

from .database import (  # noqa: F401
    Database,
    connect,
)
from .exc import (  # noqa: F401
    APIError,
    DoesNotExistError,
    FetchError,
    MultipleRowsError,
    OperationalError,
    TimeoutError,
)
from .namespace import Namespace

try:
    import psycopg2  # noqa: F401
except ImportError:
    try:
        from psycopg2cffi import compat  # noqa: F401
    except ImportError:
        pass
    else:
        compat.register()

PLATFORM = platform.python_implementation()

__all__ = [
    'Database',
    'Namespace',
    'connect'
    'APIError',
    'DoesNotExistError',
    'FetchError',
    'MultipleRowsError',
    'OperationalError',
    'TimeoutError',
]

__version__ = '0.1.0a4'
