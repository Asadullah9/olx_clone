"""Block until the database is available."""
import time

from django.core.management.base import BaseCommand
from django.db import connections
from django.db.utils import OperationalError
from psycopg import OperationalError as PsycopgOperationalError


class Command(BaseCommand):
    help = 'Wait for the default database to accept connections.'

    def handle(self, *args, **options):
        self.stdout.write('Waiting for database...')
        while True:
            try:
                connections['default'].ensure_connection()
                break
            except (OperationalError, PsycopgOperationalError):
                self.stdout.write('Database unavailable, retrying in 1 second...')
                time.sleep(1)
        self.stdout.write(self.style.SUCCESS('Database available!'))
