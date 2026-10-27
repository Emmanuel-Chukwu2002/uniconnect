#!/usr/bin/env bash
# Render runs this on every deploy (see render.yaml): install, gather static files, update the database.
set -o errexit
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate --noinput
# Accounts listed in SUPER_ADMINS (Render > Environment, e.g. "ada,ben") become Super Admins.
# Does nothing when it's empty, and never creates accounts or changes passwords.
python manage.py make_admin --from-env
