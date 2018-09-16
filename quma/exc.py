
class APIError(Exception):
    pass


class MultipleRecordsError(Exception):
    pass


class DoesNotExistError(Exception):
    pass


class OperationalError(Exception):
    pass


class FetchError(Exception):
    def __init__(self, error):
        super().__init__()
        self.error = error
