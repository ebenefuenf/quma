
class APIError(Exception):
    pass


class MultipleRowsError(Exception):
    pass


class DoesNotExistError(Exception):
    pass


class OperationalError(Exception):
    pass


class FetchError(Exception):
    def __init__(self, error):
        super().__init__()
        self.error = error


class TimeoutError(Exception):
    """Raised when a connection pool times out on getting a connection."""
