"""Gunicorn for Metrolinks on the shared Soma Smart VPS.

Default bind is a unix socket so we never collide with elearning (or anything on :8000).
"""
import multiprocessing
import os

bind = os.getenv('GUNICORN_BIND', 'unix:/run/metrolinks/metrolinks.sock')
# Keep workers modest — this VPS also runs Soma Smart (/srv/elearning).
workers = int(os.getenv('GUNICORN_WORKERS', max(2, min(4, multiprocessing.cpu_count() + 1))))
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
