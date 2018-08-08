from quma import Namespace


class Root(Namespace):
    alias = 'root'

    def get_test(self, cursor):
        return 'Test'
