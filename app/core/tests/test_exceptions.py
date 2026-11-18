"""Tests for the project-wide exception handler."""
from django.http import Http404
from django.test import SimpleTestCase
from rest_framework import exceptions

from core.exceptions import custom_exception_handler


class ExceptionHandlerTests(SimpleTestCase):

    def test_validation_error_shape(self):
        exc = exceptions.ValidationError({'email': ['This field is required.']})
        res = custom_exception_handler(exc, {})

        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['error']['code'], 'validation_error')
        self.assertEqual(res.data['error']['message'], 'This field is required.')
        self.assertIn('email', res.data['error']['details'])

    def test_non_dict_validation_error_wrapped(self):
        res = custom_exception_handler(exceptions.ValidationError('Bad.'), {})
        self.assertIn('non_field_errors', res.data['error']['details'])

    def test_api_exception_shape(self):
        res = custom_exception_handler(exceptions.NotAuthenticated(), {})

        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.data['error']['code'], 'not_authenticated')
        self.assertEqual(res.data['error']['details'], {})

    def test_http404_shape(self):
        res = custom_exception_handler(Http404(), {})

        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.data['error']['code'], 'not_found')

    def test_unhandled_exception_returns_json_500(self):
        with self.assertLogs('core.exceptions', level='ERROR'):
            res = custom_exception_handler(ValueError('secret internals'), {})

        self.assertEqual(res.status_code, 500)
        self.assertFalse(res.data['success'])
        self.assertIsNone(res.data['data'])
        self.assertEqual(res.data['error']['code'], 'server_error')
        self.assertNotIn('secret', res.data['message'])

    def test_envelope_has_success_fields(self):
        res = custom_exception_handler(exceptions.NotFound('Advertisement not found.'), {})

        self.assertEqual(res.data['success'], False)
        self.assertEqual(res.data['message'], 'Advertisement not found.')
        self.assertIsNone(res.data['data'])
