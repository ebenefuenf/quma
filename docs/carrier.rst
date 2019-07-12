===================
Reusing connections
===================

To reuse connections you can pass an object - the so-called carrier - 
to *db* when you create a cursor. quma then remembers the carrier object's 
identity and and returns the same connection which was returned the
first time when you pass the same carrier again.

A good example is the request object in web applications:

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

            # either exlicitly close the cursor as last step
            cur.close()

        # or release the carrier using the database object
        db.release(request)

**Note**: It is always a good idea to close a connection if you're done.
If you are using a carrier and a :doc:`connection pool <pool>` it is absolutely 
necessary and you have to explicitly close the cursor or release the carrier. You can 
do it using ``cur.close()`` or by passing the carrier to ``db.release(carrier)``,
otherwise the connection would not be returned to the pool.
