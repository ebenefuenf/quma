from .mapper import (
    Database,
    Namespace,
    connect,
)
from .exc import (
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
__version__ = '0.1a1.dev1'
