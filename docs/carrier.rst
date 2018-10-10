===================
Reusing connections
===================

To reuse connections you can pass a carrier object to *db* when you
create a cursor. quma then
creates the attribute ``__quma_conn__`` on the carrier holding the 
connection object. You should only use this feature if that fact doesn't
lead to problems in your application. Only objects which allow adding 
attributes at runtime are supported. A good example is the request
object in web applications:

.. code-block:: python

    from pyramid.view import view_config
    from quma import Database

    db = Database('sqlite:////path/to/db.sqlite', sqldir)


    def do_more(request, user_id):
        # reuses the same connection which was opened
        # in user_view.
        with db(request).cursor as cur:
            cur.user.remove(id=user_id)


    @view_config(route_name='user')
    def user_view(request):
        with db(request).cursor as cur:
            user = cur.user.by_name(name='Username').one()
            do_more(request, user['id'])

        with db(request).cursor as cur:
            # reuses the connection
            user = cur.user.rename(id=13, name='New Username')
            # commit every statement previously executed
            cur.commit()
            # exlicitly close the cursor
            cur.close()

**Note**: It is always a good idea to close a connection if you're done.
If you are using a carrier and a :doc:`connection pool <pool>` it is absolutely 
necessary and you have to explicitly close the cursor or release the carrier. You can 
do it using ``cur.close()`` or by passing the carrier to ``db.release(carrier)``,
otherwise the connection would not be returned to the pool.
