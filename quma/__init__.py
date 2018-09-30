from .mapper import (  # noqa: F401
    Database,
    Namespace,
    connect,
)
from .exc import (  # noqa: F401
    APIError,
    DoesNotExistError,
    FetchError,
    MultipleRecordsError,
    OperationalError,
    TimeoutError,
)


__all__ = [
    'Database',
    'Namespace',
    'connect'
    'APIError',
    'DoesNotExistError',
    'FetchError',
    'MultipleRecordsError',
    'OperationalError',
    'TimeoutError',
]
__version__ = '0.1.0a1'
