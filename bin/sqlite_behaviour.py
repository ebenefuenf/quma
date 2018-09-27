import os
import sqlite3

test_db = '/tmp/quma_sqlite_behaviour.db'

try:
    os.remove(test_db)
except FileNotFoundError:
    pass


def create(cur):
    cur.execute('create table test (name);')
    cur.execute("insert into test (name) values ('hans');")
    cur.execute("insert into test (name) values ('franz');")


def show(title, cur):
    print(title)
    try:
        result = cur.execute("select * from test;")
        result = cur.fetchall()
        if len(result):
            for r in result:
                print(' ', r[0])
        else:
            print('  table test exists but holds no data')
    except sqlite3.OperationalError:
        print('  table test does not exist')


print('------------')
con = sqlite3.connect(test_db)
con.isolation_level = 'DEFERRED'  # the same as the default ''
cur = con.cursor()
create(cur)
print('Isolation level: "" or "DEFERRED"')
show('First connect (no BEGIN, no COMMIT)', cur)
con.close()
con = sqlite3.connect(test_db)
cur = con.cursor()
show('Second connect', cur)
con.close()
print('------------\n')

os.remove(test_db)

print('------------')
con = sqlite3.connect(test_db)
con.isolation_level = 'DEFERRED'  # the same as the default ''
cur = con.cursor()
cur.execute('BEGIN;')
create(cur)
print('Isolation level: "" or "DEFERRED"')
show('First connect (exlicit BEGIN, no COMMIT)', cur)
con.close()
con = sqlite3.connect(test_db)
cur = con.cursor()
show('Second connect', cur)
con.close()
print('------------\n')

os.remove(test_db)

print('------------')
print('Isolation level: None (autocommit)')
con = sqlite3.connect(test_db)
con.isolation_level = None
cur = con.cursor()
create(cur)
show('First connect (no BEGIN, no COMMIT)', cur)
con.close()
con = sqlite3.connect(test_db)
cur = con.cursor()
show('Second connect', cur)
con.close()
print('------------\n')
