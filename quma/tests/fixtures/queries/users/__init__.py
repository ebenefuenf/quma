from quma import Namespace


class Users(Namespace):
    alias = 'user'

    def get_hans(self, cursor):
        return 'Hans'
