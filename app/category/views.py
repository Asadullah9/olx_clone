"""Views for the category API."""
from collections import defaultdict

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import mixins, viewsets
from rest_framework.response import Response

from category.serializers import CategorySerializer, CategoryTreeSerializer
from core.models import Category
from core.permissions import IsAdminOrReadOnly
from core.serializers import ErrorResponseSerializer


@extend_schema_view(
    list=extend_schema(
        summary='List the category tree',
        description=(
            'Public. Returns top-level categories, each with its subcategories '
            'nested in `children`, sorted by name.'
        ),
        auth=[],
    ),
    create=extend_schema(
        summary='Create a category (staff only)',
        responses={
            201: CategorySerializer,
            400: OpenApiResponse(ErrorResponseSerializer, description='Invalid input.'),
            401: OpenApiResponse(ErrorResponseSerializer, description='Not authenticated.'),
            403: OpenApiResponse(ErrorResponseSerializer, description='Not a staff user.'),
        },
    ),
)
@extend_schema(tags=['Categories'])
class CategoryViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    queryset = Category.objects.all()
    permission_classes = [IsAdminOrReadOnly]
    pagination_class = None

    def get_serializer_class(self):
        if self.action == 'list':
            return CategoryTreeSerializer
        return CategorySerializer

    def list(self, request, *args, **kwargs):
        # One query for the whole tree, then group children by parent in memory.
        children_map = defaultdict(list)
        for category in self.get_queryset():
            children_map[category.parent_id].append(category)

        context = {**self.get_serializer_context(), 'children_map': children_map}
        serializer = CategoryTreeSerializer(children_map[None], many=True, context=context)
        return Response(serializer.data)
