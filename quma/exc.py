from collections.abc import Sequence


class APIError(Exception):
    pass


class MultipleRowsError(Exception):
    pass


class DoesNotExistError(Exception):
    pass


class OperationalError(Exception):
    pass


class FetchError(Exception):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error


class TimeoutError(Exception):
    """Raised when a connection pool times out on getting a connection."""


class ConnectionError(Exception):
    pass


class MappingError(Exception):
    """Raised when the rows of a query cannot be mapped to a target."""


class MissingColumnError(MappingError):
    """Raised when a column the mapping target requires is missing."""

    def __init__(self, columns: Sequence[str], target: type) -> None:
        self.columns = tuple(columns)
        self.target = target
        names = ", ".join(f'"{column}"' for column in self.columns)
        plural = "s" if len(self.columns) > 1 else ""
        super().__init__(
            f"Missing column{plural} {names} for {target.__qualname__}"
        )
