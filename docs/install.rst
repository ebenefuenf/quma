============
Installation
============

If you like to use quma with **SQLite** Python has everything covered
and you only need to install quma itself:

::

    pip install quma


To access a **PostgreSQL** or **MySQL/MariaDB** database you need to install
the matching driver:

::
    
    # PostgreSQL
    pip install quma psycopg2
    # or
    pip install quma psycopg2cffi


    # MySQL/MariaDB
    pip install quma mysqlclient

Templates
---------

You need to install the `*Mako template library* <http://www.makotemplates.org>`_ 
if you want to use dynamic sql scripts using :doc:`templates <templates>`.

::

    pip install mako

Development:
------------

::

    git clone https://github.com/ebenefuenf/quma
    cd quma
    pip install -e '.[test,templates,postgres,mysql]'
