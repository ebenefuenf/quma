=======================
Mapping rows to objects
=======================

The methods :meth:`one()`, :meth:`first()`, :meth:`all()`,
:meth:`unbunch()` and :meth:`ManyResult.get()` accept a target class
and return instances of it instead of rows. quma matches the columns of
each row to the target by name.

.. code-block:: python

    from dataclasses import dataclass

    @dataclass
    class User:
        id: int
        email: str
        name: str | None = None

    with db.cursor as cur:
        user = cur.users.by_id(id=42).one(User)        # User
        user = cur.users.by_email(email=e).first(User)  # User or None
        users = cur.users.list().all(User)             # list of User
        for user in cur.users.list().unbunch(100, User):
            ...
        batch = cur.users.list().many().get(100, User)

:meth:`unbunch()` and :meth:`ManyResult.get()` take the size first, so
the target comes second, or pass it as ``target=User``. Iterating,
indexing and :meth:`value()` always return rows. The rows of a query
stay cached unmapped, so ``query.all(User)`` followed by ``query.all()``
does not execute the query again.


Classes
-------

quma calls the constructor of the class with one keyword argument per
parameter, taken from the column of the same name. This works with
dataclasses, attrs classes, pydantic models, msgspec structs,
:class:`typing.NamedTuple` and plain classes alike.

- A missing column falls back to the parameter's default. If the
  parameter has no default, quma raises :exc:`MissingColumnError`.
- A column that is present but ``NULL`` is passed as ``None``. It never
  falls back to the default.
- Extra columns are ignored, unless the constructor accepts
  ``**kwargs``. Then it receives them.
- Values are passed as the driver returns them. quma converts nothing;
  leave that to the class, for example in ``__post_init__`` or a
  pydantic validator.

To fill a parameter from a column with a different name, rename the
column in SQL:

.. code-block:: sql

    SELECT id, email_address AS email FROM users WHERE id = :id;


Dicts and TypedDicts
--------------------

With :class:`dict` as target, quma returns a plain dict of all
columns in column order. Rows are not dicts: PostgreSQL rows are
lists, so they become JSON arrays, and SQLite and MySQL rows are tuples
by default.

.. code-block:: python

    user = cur.users.by_id(id=42).one(dict)
    # {'id': 42, 'email': 'user@example.com', 'name': 'User'}

With a :class:`typing.TypedDict`, quma returns a dict of the columns
named by its keys. A missing required key raises
:exc:`MissingColumnError`; a missing ``NotRequired`` key is left out.
Extra columns are ignored.

.. code-block:: python

    from typing import NotRequired, TypedDict

    class UserDict(TypedDict):
        id: int
        email: str
        name: NotRequired[str]

    user = cur.users.by_id(id=42).one(UserDict)

.. Note::

    Python cannot see ``NotRequired`` and ``Required`` in string
    annotations, so in a module with ``from __future__ import
    annotations`` every key of a TypedDict counts as required.


Building instances yourself
---------------------------

If the class has a ``from_row()`` classmethod, quma calls it with a
mapping of column names to values instead of calling the constructor.
The method takes care of all conversion itself.

.. code-block:: python

    class User:
        def __init__(self, id: int, email: str) -> None:
            self.id = id
            self.email = email.lower()

        @classmethod
        def from_row(cls, row):
            return cls(row['user_id'], row['mail'])

The :class:`quma.FromRow` protocol describes the method for type
checkers. Classes do not need to inherit from it.


Choosing the class per row
--------------------------

Instead of a class you can pass a resolver: a function that is called
with a mapping of column names to values and returns the class for that
row. quma then maps the row to that class as described above.

.. code-block:: python

    def by_role(row):
        return Admin if row['role'] == 'admin' else User

    people = cur.users.list().all(by_role)


Errors
------

:exc:`MissingColumnError` names the missing columns in its ``columns``
attribute and the class in ``target``. It is a subclass of
:exc:`MappingError`, which quma raises when a target cannot be used:

- the class has no constructor (no ``__init__``, ``__new__`` or
  metaclass ``__call__`` of its own), or one that
  :func:`inspect.signature` cannot read,
- a constructor parameter is positional-only and has no default,
- a resolver returns something other than a class,
- the target uses a column name that appears more than once in the
  result, as in a join returning two ``id`` columns. ``from_row()``,
  :class:`dict` and resolvers receive every column, so any duplicate
  name raises there. Rename the columns with ``AS`` to fix it.

quma checks the target when it maps the first row, so a query without
rows raises none of these errors.


Typing
------

Mapped results are typed: ``one(User)`` returns ``User``,
``all(User)`` returns ``list[User]``, ``one(dict)`` returns
``dict[str, Any]``, and a resolver returning ``type[Admin] |
type[User]`` gives ``Admin | User``. Rows without a target are typed as
``Any``.
