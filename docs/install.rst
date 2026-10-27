============
Installation
============

Prerequisites
-------------

You may need to install the Python and database library develompment headers.

On Debian/Ubuntu derivates for example like this:
    
::

    # PostgreSQL
    sudo apt install python3-dev libpq-dev
    # MySQL/MariaDB
    sudo apt install python3-dev default-libmysqlclient-dev

Installing quma
---------------

If you like to use quma with **SQLite** Python has everything covered
and you only need to install quma itself:

::

    pip install quma


To connect to a **PostgreSQL** or **MySQL/MariaDB** database you need to install
the matching driver:

::
    
    # PostgreSQL with psycopg 3
    pip install quma psycopg
    # PostgreSQL with psycopg2
    pip install quma psycopg2

    # MySQL/MariaDB
    pip install quma mysqlclient

Templates for dynamic SQL
-------------------------

You need to install the `Mako template library <http://www.makotemplates.org>`_
if you want to use dynamic sql scripts using :doc:`templates <templates>`.

::

    pip install mako

Development
-----------

The development environment is managed with `uv <https://docs.astral.sh/uv/>`_:

::

    git clone https://github.com/ebenefuenf/quma
    cd quma
    uv sync --all-extras
