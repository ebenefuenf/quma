
class APIError(Exception):
    pass


class MultipleRecordsError(Exception):
    pass


class DoesNotExistError(Exception):
    pass


class OperationalError(Exception):
    pass


class IntegrityError(Exception):

    def __init__(self, *args, ref_entity=None, ref_id=None,
                 ref_label=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.ref_entity = ref_entity
        self.ref_id = ref_id
        self.ref_label = ref_label

    def as_json(self):
        return {
            'errors': str(self),
            'ref_entity': self.ref_entity,
            'ref_id': self.ref_id,
            'ref_label': self.ref_label
        }
