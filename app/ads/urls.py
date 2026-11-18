"""URL routes for the ads API, mounted at /api/.

The trailing slash is optional, so both /api/ads and /api/ads/ work
(including for POST, which Django's APPEND_SLASH redirect cannot handle).
"""
from rest_framework.routers import SimpleRouter

from ads.views import AdminAdViewSet, AdViewSet

app_name = 'ads'

router = SimpleRouter()
router.trailing_slash = '/?'  # the constructor argument only accepts True/False
router.register('ads', AdViewSet, basename='ad')
router.register('admin/ads', AdminAdViewSet, basename='admin-ad')

urlpatterns = router.urls
