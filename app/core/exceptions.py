"""Project-wide DRF exception handling.

Every error response produced by the API has the same shape::

    {
        "success": false,
        "message": "<human text>",
        "data": null,
        "error": {"code": "<machine_code>", "message": "<human text>", "details": {...}}
    }

``success``/``message``/``data`` match the success envelope (core.responses);
``error`` carries the machine-readable code and per-field details.
"""
import logging

from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler, set_rollback

logger = logging.getLogger(__name__)


def _first_message(details):
    """Return the first human-readable message found in DRF error details."""
    if isinstance(details, dict):
        for value in details.values():
            return _first_message(value)
    if isinstance(details, list) and details:
        return _first_message(details[0])
    return str(details)


def error_body(code, message, details=None):
    return {
        'success': False,
        'message': message,
        'data': None,
        'error': {'code': code, 'message': message, 'details': details or {}},
    }


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        # Unhandled exception: log it with the traceback and return a JSON 500
        # that leaks no internals. Roll back any open atomic block, as DRF does
        # for the exceptions it handles itself.
        view = context.get('view')
        logger.exception('Unhandled error in %s', type(view).__name__ if view else 'API')
        set_rollback()
        return Response(
            error_body('server_error', 'Internal server error.'),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

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

    response.data = error_body(code, message, details)
    return response
