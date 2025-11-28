# -*- coding: utf-8 -*-

from fszn import create_app, db

app = create_app()

if __name__ == '__main__':
    # Create tables in the database if they do not exist
    with app.app_context():
        db.create_all()

    # Key: Explicitly specify the host + a relatively uncommon port + disable auto-reload
    app.run(
        debug=True,
        host="127.0.0.1",
        port=5050,
        use_reloader=False,
    )