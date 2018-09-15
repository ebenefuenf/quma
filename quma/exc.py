
class APIError(Exception):
    pass


class MultipleRecordsError(Exception):
    pass


class DoesNotExistError(Exception):
    pass


class OperationalError(Exception):
    pass
