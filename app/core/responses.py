"""Uniform success envelope: {"success": true, "message": ..., "data": ..., "pagination": ...}."""
from rest_framework import status as http_status
from rest_framework.response import Response


def success_response(data=None, message='', status=http_status.HTTP_200_OK, pagination=None):
    body = {'success': True, 'message': message, 'data': data}
    if pagination is not None:
        body['pagination'] = pagination
    return Response(body, status=status)
