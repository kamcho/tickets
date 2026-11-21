"""Gunicorn settings for Hostinger VPS. Override bind/workers via env if needed."""
import multiprocessing
import os

bind = os.getenv('GUNICORN_BIND', '127.0.0.1:8000')
workers = int(os.getenv('GUNICORN_WORKERS', max(2, multiprocessing.cpu_count() * 2 + 1)))
threads = int(os.getenv('GUNICORN_THREADS', '2'))
worker_class = 'gthread'
timeout = int(os.getenv('GUNICORN_TIMEOUT', '60'))
keepalive = 5
max_requests = 1000
max_requests_jitter = 50
accesslog = '-'
errorlog = '-'
loglevel = os.getenv('GUNICORN_LOG_LEVEL', 'info')
capture_output = True
preload_app = True
wsgi_app = 'ticket.wsgi:application'
