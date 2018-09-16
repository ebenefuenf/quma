
class APIError(Exception):
    pass


class MultipleRecordsError(Exception):
    pass


class DoesNotExistError(Exception):
    pass


class OperationalError(Exception):
    pass


class FetchError(Exception):
    def __init__(self, message, error):
        super().__init__(message)
        self.error = error
