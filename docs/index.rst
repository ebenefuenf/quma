Welcome to quma's docs
======================

.. Warning::

    This is alpha software and subject to change!

quma is a small SQL database library for **Python** and **PyPy** version 3.5 and higher.
It maps object methods to SQL script files and supports **SQLite**, **PostgreSQL**,
**MySQL** and **MariaDB**.

Unlike ORMs it allows to write SQL as it was intented and to use all featuers
the DBMS provides. As it uses plain SQL files you can fully utilize your database GUI tool.

It also provides a simple connection pool.

Learn more
----------

* If you want to know how to install quma and its dependencies,
  see :doc:`Installation <install>`.
* To get started read :doc:`How to use quma <usage>` from start to finish.
* To see what you can do with query results read :doc:`The Result class <result>`.
* In :doc:`Connecting <connecting>` you learn how to connect to SQLite, 
  PostgreSQL and MySQL/MariaDB databases.
* :doc:`Connection pool <pool>`.
* Learn what a :doc:`Changling cursor <changeling>` is and how it enables
  you to access result data in three different ways.
* Database management systems have different ways of parameter binding.
  :doc:`Passing parameters <parameters>` shows how it works in quma.
* SQL doesn't support every kind of dynamic queries. If you reach its limits
  you can circumvent this by using :doc:`Templates <templates>`.
* If you pass more than one directory to the constructor, quma shadows 
  duplicate files. See how this works in :doc:`Shadowing <shadowing>`.
* You can add custom methods to namespaces. Learn how to do it in 
  :doc:`Custom namespaces <namespaces>`. You will also learn about aliasing.
* If you like to work on quma itself, :doc:`Testing <tests>` has the
  information on how to run its tests.

License
-------

quma is released under the MIT license.

Copyright © 2018 ebene fünf GmbH. All rights reserved.
