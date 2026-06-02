import os
import sys

# Add the project's root folder to the Python search path
project_dir = os.path.dirname(os.path.abspath(__file__))
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

# Set Django settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ticket.settings")

# Import the WSGI application
from ticket.wsgi import application