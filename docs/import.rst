===================
Importable database
===================

Sometimes it isn't enough to create a global ``Database`` instance 
and import it into other modules. For example, if you read the database 
credentials from a configuration file at runtime and then initialize
the instance while the uninitialized global is already imported 
elsewhere. The following code shows a way to keep the quma API in place
and allows to import the ``db`` wrapper class even if the connection is
not established yet.

.. code-block:: python
    
    #####  my_db_module.py

    import quma

    _db = None

    class MetaDB(type):
        def __getattr__(cls, attr):
            return getattr(_db, attr)

    class db(object, metaclass=MetaDB):
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

    import my_db_module

    my_db_module.connect()

Now you can import the class ``my_db_module.db`` from everywhere
and use it the same way as a usual instance of ``quma.Database``.

.. code-block:: python
    
    #####  e. g. model.py

    from my_db_module import db

    with db.cursor as cur:
        cur.users.all()
