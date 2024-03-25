from quma import Namespace


class Users(Namespace):
    alias = "user"

    def get_test(self, cursor):
        return "Test"
