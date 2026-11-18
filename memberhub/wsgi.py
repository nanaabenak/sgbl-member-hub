"""Gunicorn entry point: gunicorn -c deploy/gunicorn_conf.py wsgi:application"""
from memberhub import create_app

application = create_app()
app = application  # conventional alias for flask CLI and other tooling
