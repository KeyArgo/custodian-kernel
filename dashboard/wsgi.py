"""Production WSGI entry point.

Run with: gunicorn -w 4 -b 0.0.0.0:8094 wsgi:app

Genuinely handles concurrent requests (4 worker processes) instead of the
Werkzeug dev server's single-threaded default -- the right choice when this
dashboard is reachable by real judge/spectator traffic, not just local
testing.
"""
from app import app

if __name__ == '__main__':
    app.run()
