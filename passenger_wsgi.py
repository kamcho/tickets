import os
import sys

# # Add the project's root folder to the Python search path.
# # This ensures Passenger can find Django and core application files.
# project_dir = os.path.dirname(os.path.abspath(__file__))
# if project_dir not in sys.path:
#     sys.path.insert(0, project_dir)

# # Set the environment variable pointing to the Django settings file.
# os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ticket.settings")

# Import the standard WSGI application handler.
# Passenger hooks into this 'application' object to route requests.
from ticket.wsgi import application
