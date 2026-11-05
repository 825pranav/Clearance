# One file, two images: `console` runs Django under uWSGI, and `nginx` serves the static files in front of it.

FROM python:3.11-slim AS console
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/clearance
# The uWSGI wheel links against libexpat, which the slim image leaves out.
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1
COPY requirements-console.txt .
RUN pip install --no-cache-dir -r requirements-console.txt
COPY app/ app/
COPY console/ console/
COPY web/ web/
COPY manage.py .
COPY evals/results.json evals/results.json
COPY deploy/uwsgi.ini deploy/uwsgi.ini
# Debug is on only for this one command, because collectstatic needs settings but no real secret key.
RUN DJANGO_DEBUG=1 python manage.py collectstatic --noinput
# uWSGI runs as an unprivileged user, so a bug in the app is not running as root.
RUN useradd --system --no-create-home clearance
USER clearance
EXPOSE 8000
CMD ["uwsgi", "--ini", "deploy/uwsgi.ini"]

FROM nginx:stable-alpine AS nginx
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=console /srv/clearance/staticfiles /srv/static
