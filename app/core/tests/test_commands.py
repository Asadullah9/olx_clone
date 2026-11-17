"""Tests for custom management commands."""
from unittest.mock import patch

from django.core.management import call_command
from django.db.utils import OperationalError
from django.test import SimpleTestCase
from psycopg import OperationalError as PsycopgOperationalError


@patch('core.management.commands.wait_for_db.connections')
class WaitForDbCommandTests(SimpleTestCase):

    def test_wait_for_db_ready(self, patched_connections):
        call_command('wait_for_db')
        patched_connections['default'].ensure_connection.assert_called_once()

    @patch('time.sleep')
    def test_wait_for_db_delay(self, patched_sleep, patched_connections):
        patched_connections['default'].ensure_connection.side_effect = (
            [PsycopgOperationalError] * 2 + [OperationalError] * 3 + [None]
        )
        call_command('wait_for_db')
        self.assertEqual(patched_connections['default'].ensure_connection.call_count, 6)
        self.assertEqual(patched_sleep.call_count, 5)
