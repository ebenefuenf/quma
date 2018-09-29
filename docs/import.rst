===================
Importable instance
===================

Sometimes it isn't enough to create a global ``Database`` instance 
and import it into other modules. For example if you read the
database credentials from a configuration file at runtime while
the global is already imported into other modules. The following 
code shows a way to keep the quma API in place and allows to import
the ``db`` wrapper class even if the connection is not established yet.

.. code-block:: python
    
    #####  database.py

    import quma

    _db = None

    class DB(type):
        def __getattr__(cls, attr):
            return getattr(_db, attr)

    class db(object, metaclass=DB):
        def __init__(self, carrier=None, autocommit=None):
            self.carrier = carrier
            self.autocommit = autocommit

        def __getattr__(self, attr):
            return getattr(_db(carrier=self.carrier,
                            autocommit=self.autocommit), attr)

    def connect():
        global _db
        sqldir = '/path/to/sql/scripts'

        _db = quma.Database(uri, sqldir)

Create the instance in your main module:

.. code-block:: python
    
    #####  main.py

    import database

    database.connect()

Now you can import the class ``database.db`` from everywhere
and use it like a usual instance of ``quma.Database``.

.. code-block:: python
    
    #####  e. g. model.py

    from database import db

    with db.cursor as cur:
        cur.users.all()
