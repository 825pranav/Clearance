"""WSGI entry point, for serving the console from an application server."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "web.settings")
application = get_wsgi_application()
