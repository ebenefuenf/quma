===================
Reusing connections
===================

To reuse connections you can pass a carrier object to `db`. *quma* then
creates the attribute `__quma_conn__` on the carrier holding the 
connection object. You should only use this feature if this fact doesn't
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
        with db(request).cursor as c:
            db.user.remove(c, id=user_id)


    @view_config(route_name='user')
    def user_view(request):
        with db(request).cursor as c:
            user = db.user.by_name(c, name='Username')
            do_more(request, user.id)
            c.commit()

