from quma import Namespace


class Root(Namespace):
    alias = 'root'

    def get_test(self, cursor):
        return 'Test'

    def get_shadowed_test(self, cursor):
        return 'Shadowed Test'
