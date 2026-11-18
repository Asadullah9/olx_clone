"""HTTP views for the ads API. Thin by design: parse input, call a service or
selector, wrap the result in the standard envelope."""
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
)
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser

from ads import selectors, services
from ads.serializers import (
    AdCreateSerializer,
    AdListQuerySerializer,
    AdminAdSerializer,
    AdRejectSerializer,
    AdSerializer,
    AdUpdateSerializer,
    MyAdsQuerySerializer,
)
from core.responses import success_response
from core.serializers import ErrorResponseSerializer, envelope

# --- OpenAPI building blocks -------------------------------------------------

AD_ENVELOPE = envelope('AdResponse', AdSerializer)
AD_LIST_ENVELOPE = envelope('AdListResponse', AdSerializer, many=True, paginated=True)
ADMIN_AD_ENVELOPE = envelope('AdminAdResponse', AdminAdSerializer)
ADMIN_AD_LIST_ENVELOPE = envelope(
    'AdminAdListResponse', AdminAdSerializer, many=True, paginated=True,
)
EMPTY_ENVELOPE = envelope('EmptyResponse')

ERR_400 = OpenApiResponse(ErrorResponseSerializer, description='Validation error.')
ERR_401 = OpenApiResponse(ErrorResponseSerializer, description='Not authenticated.')
ERR_403 = OpenApiResponse(ErrorResponseSerializer, description='Not allowed.')
ERR_404 = OpenApiResponse(ErrorResponseSerializer, description='Advertisement not found.')
ERR_500 = OpenApiResponse(
    ErrorResponseSerializer, description='Internal or image-storage error.',
)

AD_ID = OpenApiParameter('id', OpenApiTypes.INT, OpenApiParameter.PATH)

EXAMPLE_AD = {
    'id': 42,
    'userId': 7,
    'title': 'iPhone 15 Pro 256GB',
    'description': 'Natural titanium, 6 months old, with box and charger.',
    'price': '950.00',
    'status': 'ACTIVE',
    'rejectionReason': '',
    'categoryId': 3,
    'category': {
        'id': 3, 'name': 'Mobile Phones', 'slug': 'mobile-phones', 'description': '',
    },
    'creator': {'id': 7, 'name': 'Asad'},
    'images': [
        {
            'id': 101 + i,
            'imageUrl': f'http://localhost:8000/media/ads/42/{"abcd"[i]}.jpg',
            'displayOrder': i,
            'createdAt': '2026-11-18T10:00:00Z',
        }
        for i in range(4)
    ],
    'createdAt': '2026-11-18T10:00:00Z',
    'updatedAt': '2026-11-18T10:00:00Z',
}
LIST_EXAMPLE = OpenApiExample(
    'Paginated list',
    response_only=True,
    value={
        'success': True,
        'message': 'Advertisements retrieved successfully',
        'data': [EXAMPLE_AD],
        'pagination': {
            'total': 100, 'page': 1, 'limit': 10, 'totalPages': 10,
            'hasNextPage': True, 'hasPreviousPage': False,
        },
    },
)
NOT_FOUND_EXAMPLE = OpenApiExample(
    'Not found',
    response_only=True,
    status_codes=['404'],
    value={
        'success': False,
        'message': 'Advertisement not found.',
        'data': None,
        'error': {'code': 'not_found', 'message': 'Advertisement not found.', 'details': {}},
    },
)
CREATE_EXAMPLE = OpenApiExample(
    'Multipart create',
    request_only=True,
    summary='multipart/form-data with 4 files',
    description=(
        'curl -X POST http://localhost:8000/api/ads \\\n'
        '  -H "Authorization: Token <token>" \\\n'
        '  -F title="iPhone 15 Pro" -F description="Like new, with box." \\\n'
        '  -F price=950 -F categoryId=3 \\\n'
        '  -F images=@1.jpg -F images=@2.jpg -F images=@3.png -F images=@4.webp'
    ),
    value={
        'title': 'iPhone 15 Pro 256GB',
        'description': 'Natural titanium, 6 months old, with box and charger.',
        'price': '950.00',
        'categoryId': 3,
        'images': ['<binary 1.jpg>', '<binary 2.jpg>', '<binary 3.png>', '<binary 4.webp>'],
    },
)
UPDATE_EXAMPLE = OpenApiExample(
    'Replace one image and change the price',
    request_only=True,
    description=(
        'curl -X PUT http://localhost:8000/api/ads/42 -H "Authorization: Token <token>" \\\n'
        '  -F price=900 -F removeImageIds=102 -F images=@new.jpg'
    ),
    value={'price': '900.00', 'removeImageIds': [102], 'images': ['<binary new.jpg>']},
)
DEACTIVATE_EXAMPLE = OpenApiExample(
    'Deactivate (JSON, no image changes)',
    request_only=True,
    value={'status': 'INACTIVE'},
)


def _serializer_for(viewer):
    return AdminAdSerializer if selectors.is_admin(viewer) else AdSerializer


@extend_schema_view(
    list=extend_schema(
        summary='List, search and filter advertisements',
        description=(
            'Public. One endpoint for listing, search, category and price filtering, '
            'sorting and pagination; all filters are optional and combine with AND. '
            'Only ACTIVE ads are returned unless an admin passes `status`. '
            '`categoryId` includes the category\'s subcategories.'
        ),
        parameters=[AdListQuerySerializer],
        responses={200: AD_LIST_ENVELOPE, 400: ERR_400, 403: ERR_403},
        examples=[LIST_EXAMPLE],
        auth=[{}, {'tokenAuth': []}],
    ),
    create=extend_schema(
        summary='Create an advertisement',
        description=(
            'Send `multipart/form-data` with 4-5 `images` (JPEG, PNG or WebP, max 5 MB each). '
            'The owner is the authenticated user and the status is always PENDING; '
            'any `userId` or `status` in the body is ignored.'
        ),
        request={'multipart/form-data': AdCreateSerializer},
        examples=[CREATE_EXAMPLE],
        responses={201: AD_ENVELOPE, 400: ERR_400, 401: ERR_401, 500: ERR_500},
    ),
    retrieve=extend_schema(
        summary='Get an advertisement',
        description=(
            'Public for ACTIVE ads. PENDING, INACTIVE and REJECTED ads are visible '
            'only to their owner and admins; everyone else gets 404.'
        ),
        parameters=[AD_ID],
        responses={200: AD_ENVELOPE, 404: ERR_404},
        examples=[NOT_FOUND_EXAMPLE],
        auth=[{}, {'tokenAuth': []}],
    ),
    update=extend_schema(
        summary='Update an advertisement',
        description=(
            'Owner or admin. All fields are optional (omitted fields are kept). '
            'Use `multipart/form-data` to upload images, JSON otherwise.\n\n'
            '**Images:** final images = existing − `removeImageIds` '
            '(re-ordered by `imageOrder` if given) + new `images` appended. '
            'The result must contain 4-5 images. Sending no image fields keeps them.\n\n'
            '**Status:** owners may set INACTIVE or move INACTIVE back to PENDING; '
            'admins may set any status. Owner edits to an ACTIVE or REJECTED ad '
            'send it back to PENDING for review.'
        ),
        parameters=[AD_ID],
        request={
            'multipart/form-data': AdUpdateSerializer,
            'application/json': AdUpdateSerializer,
        },
        examples=[UPDATE_EXAMPLE, DEACTIVATE_EXAMPLE],
        responses={
            200: AD_ENVELOPE, 400: ERR_400, 401: ERR_401, 403: ERR_403, 404: ERR_404,
            500: ERR_500,
        },
    ),
    partial_update=extend_schema(
        summary='Update an advertisement (same as PUT)',
        parameters=[AD_ID],
        request={
            'multipart/form-data': AdUpdateSerializer,
            'application/json': AdUpdateSerializer,
        },
        responses={
            200: AD_ENVELOPE, 400: ERR_400, 401: ERR_401, 403: ERR_403, 404: ERR_404,
        },
    ),
    destroy=extend_schema(
        summary='Delete an advertisement',
        description='Owner or admin. Deletes the ad, its image records and stored files.',
        parameters=[AD_ID],
        responses={200: EMPTY_ENVELOPE, 401: ERR_401, 403: ERR_403, 404: ERR_404},
    ),
    my_ads=extend_schema(
        summary="List the current user's advertisements",
        description=(
            'Every status by default; filter with `status=ACTIVE|PENDING|INACTIVE|REJECTED`. '
            'Supports the same search, filters, sorting and pagination as the public list.'
        ),
        parameters=[MyAdsQuerySerializer],
        responses={200: AD_LIST_ENVELOPE, 400: ERR_400, 401: ERR_401},
        examples=[LIST_EXAMPLE],
    ),
)
@extend_schema(tags=['Advertisements'])
class AdViewSet(viewsets.GenericViewSet):
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    serializer_class = AdSerializer
    lookup_value_regex = r'\d+'

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def _list_response(self, scope, query_serializer_class):
        query = query_serializer_class(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        page = selectors.list_ads(
            viewer=self.request.user, scope=scope, params=query.validated_data,
        )
        serializer_class = _serializer_for(self.request.user)
        data = serializer_class(page.items, many=True, context=self.get_serializer_context()).data
        return success_response(
            data, 'Advertisements retrieved successfully', pagination=page.meta,
        )

    def _ad_response(self, ad, message, status_code=status.HTTP_200_OK):
        serializer_class = _serializer_for(self.request.user)
        data = serializer_class(ad, context=self.get_serializer_context()).data
        return success_response(data, message, status=status_code)

    def list(self, request):
        return self._list_response(selectors.SCOPE_PUBLIC, AdListQuerySerializer)

    @action(detail=False, methods=['get'], url_path='my-ads', url_name='my-ads')
    def my_ads(self, request):
        return self._list_response(selectors.SCOPE_MINE, MyAdsQuerySerializer)

    def create(self, request):
        serializer = AdCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ad = services.create_ad(user=request.user, **serializer.validated_data)
        return self._ad_response(ad, 'Advertisement created successfully', status.HTTP_201_CREATED)

    def retrieve(self, request, pk):
        ad = selectors.get_visible_ad(viewer=request.user, ad_id=pk)
        return self._ad_response(ad, 'Advertisement retrieved successfully')

    def update(self, request, pk):
        serializer = AdUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ad = services.update_ad(user=request.user, ad_id=pk, data=serializer.validated_data)
        return self._ad_response(ad, 'Advertisement updated successfully')

    def partial_update(self, request, pk):
        return self.update(request, pk)

    def destroy(self, request, pk):
        services.delete_ad(user=request.user, ad_id=pk)
        return success_response(None, 'Advertisement deleted successfully')


@extend_schema_view(
    list=extend_schema(
        summary='List all advertisements (admin)',
        description=(
            'Every status by default; same filters as the public list, including '
            '`status` and `userId`. Includes the creator\'s email.'
        ),
        parameters=[AdListQuerySerializer],
        responses={200: ADMIN_AD_LIST_ENVELOPE, 400: ERR_400, 401: ERR_401, 403: ERR_403},
    ),
    approve=extend_schema(
        summary='Approve a pending advertisement (admin)',
        parameters=[AD_ID],
        request=None,
        responses={200: ADMIN_AD_ENVELOPE, 400: ERR_400, 401: ERR_401, 403: ERR_403,
                   404: ERR_404},
    ),
    reject=extend_schema(
        summary='Reject a pending advertisement (admin)',
        parameters=[AD_ID],
        request=AdRejectSerializer,
        examples=[OpenApiExample(
            'With reason', request_only=True,
            value={'rejectionReason': 'Photos do not show the actual product.'},
        )],
        responses={200: ADMIN_AD_ENVELOPE, 400: ERR_400, 401: ERR_401, 403: ERR_403,
                   404: ERR_404},
    ),
)
@extend_schema(tags=['Admin: Advertisements'])
class AdminAdViewSet(viewsets.GenericViewSet):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = AdminAdSerializer
    lookup_value_regex = r'\d+'

    def list(self, request):
        query = AdListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        page = selectors.list_ads(
            viewer=request.user, scope=selectors.SCOPE_ADMIN, params=query.validated_data,
        )
        data = AdminAdSerializer(page.items, many=True, context=self.get_serializer_context()).data
        return success_response(
            data, 'Advertisements retrieved successfully', pagination=page.meta,
        )

    def _respond(self, ad, message):
        data = AdminAdSerializer(ad, context=self.get_serializer_context()).data
        return success_response(data, message)

    @action(detail=True, methods=['patch'])
    def approve(self, request, pk):
        ad = services.approve_ad(admin=request.user, ad_id=pk)
        return self._respond(ad, 'Advertisement approved successfully')

    @action(detail=True, methods=['patch'])
    def reject(self, request, pk):
        serializer = AdRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ad = services.reject_ad(admin=request.user, ad_id=pk, **serializer.validated_data)
        return self._respond(ad, 'Advertisement rejected successfully')
