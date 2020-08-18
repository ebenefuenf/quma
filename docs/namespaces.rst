=================
Custom namespaces
=================

quma automatically creates namespace objects when it reads in your sql scripts.
Each subfolder in the script directory will result in a namespace object
as a direct member of *db* or *cur*. 

You can add custom methods to these objects by putting a :file:`__init__.py`
file into the subfolder which is your namespace and by adding a subclass of
:class:`quma.Namespace` to it. The class must have the same name as the folder
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
        # the method must accept the cursor as its first parameter
        def get_test(self, cur):
            return 'Test'

        def get_address(self, cur, username):
            user = cur.users.by_username(username=username)
            return cur.address.by_user(user.id)
            


Public methods of the namespace **must** be definied with the cursor
as second parameter. It will automatically be passed when you use
the *cur* api.

Now you can call the method the same way as you would call scripts:

.. code-block:: python

    db.users.get_test(cur)
    cur.users.get_test() # no need to pass cur
    address = cur.users.get_address('username')


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
