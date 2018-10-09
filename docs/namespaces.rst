=================
Custom namespaces
=================

quma automatically creates namespace objects when it reads in your sql scripts.
Each subfolder in the script directory will result in a namespace object
as a direct member of *db* or *cur*. 

You can add custom methods to these objects by putting a :file:`__init__.py`
file to the subfolder which is your namespace and add a subclass of
:class:`quma.Namespace` to it. The class must have the name of the folder
with the first letter uppercase.

::

    path/to/sql/scripts
    ├─ users
    │   ├─ __init__.py
    │   ├─ all.sql
    │   ├─ by_city.sql
    ..

.. code-block:: python

    from quma import Namespace

    # If the subfolder's name is 'users' the 
    # class must be named 'Users'.
    class Users(Namespace):
        def get_test(self):
            return 'Test'


Now you can call the method the same way as you would call scripts:

.. code-block:: python

    cur.users.get_test()

Root members
------------

If you want to add root level methods you need to add :file:`__init__.py`
to the root of your script directory and name the subclass `Root`.

::

    path/to/sql/scripts
    ├─ __init__.py
    ├─ users
    │   ├─ all.sql
    ..

.. code-block:: python

    class Root(Namespace):
        def root_method(self, cursor):
            return 'Test'

.. code-block:: python

    db.root_method()
    cur.root_method()

Aliasing
--------

If you add the class level attribute ``alias`` to your custom
namespace, you can call it by that name too.

.. code-block:: python

    from quma import Namespace

    class Users(Namespace):
        alias = 'user'

.. code-block:: python

    cur.user.all()
    # This is the same as.
    cur.users.all()
