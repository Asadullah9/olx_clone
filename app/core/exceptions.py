"""Project-wide DRF exception handling.

Every error response produced by the API has the same shape::

    {"error": {"code": "<machine_code>", "message": "<human text>", "details": {...}}}
"""
from rest_framework import exceptions, status
from rest_framework.views import exception_handler


def _first_message(details):
    """Return the first human-readable message found in DRF error details."""
    if isinstance(details, dict):
        for value in details.values():
            return _first_message(value)
    if isinstance(details, list) and details:
        return _first_message(details[0])
    return str(details)


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        # Unhandled exception: let Django return a 500 (and log it).
        return None

    if isinstance(exc, exceptions.ValidationError):
        code = 'validation_error'
        message = _first_message(exc.detail) if exc.detail else 'Invalid input.'
        details = exc.detail if isinstance(exc.detail, dict) else {'non_field_errors': exc.detail}
    elif isinstance(exc, exceptions.APIException):
        codes = exc.get_codes()
        code = codes if isinstance(codes, str) else 'error'
        message = _first_message(exc.detail)
        details = {}
    else:
        # Http404 / PermissionDenied from Django, converted by DRF.
        code = 'not_found' if response.status_code == status.HTTP_404_NOT_FOUND else 'error'
        message = _first_message(response.data)
        details = {}

    response.data = {'error': {'code': code, 'message': message, 'details': details}}
    return response
