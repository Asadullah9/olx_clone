"""URL routes for the category API, mounted at /api/."""
from rest_framework.routers import SimpleRouter

from category.views import CategoryViewSet

app_name = 'category'

router = SimpleRouter()
router.register('categories', CategoryViewSet, basename='category')

urlpatterns = router.urls
