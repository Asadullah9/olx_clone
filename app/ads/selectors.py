"""Read-side queries for ads: one filtering/sorting/pagination pipeline for every listing.

The public listing, "my ads" and the admin listing differ only in *scope*
(which rows the caller may see); filters, search, sorting and pagination are
shared.
"""
from collections import defaultdict

from django.db.models import Prefetch, Q
from django.db.models.functions import Lower
from rest_framework.exceptions import NotFound, PermissionDenied

from core.models import Ad, AdImage, AdStatus, Category
from core.pagination import paginate

SCOPE_PUBLIC = 'public'
SCOPE_MINE = 'mine'
SCOPE_ADMIN = 'admin'

_SORT_COLUMNS = {
    'createdAt': 'created_at',
    'price': 'price',
    'title': Lower('title'),
}


def is_admin(user):
    return bool(user and user.is_authenticated and user.is_staff)


def ads_with_relations():
    """Ads with category, creator and ordered images loaded in 2 extra queries max."""
    return Ad.objects.select_related('category', 'user').prefetch_related(
        Prefetch('images', queryset=AdImage.objects.order_by('display_order', 'id')),
    )


def category_and_descendant_ids(category_id):
    """IDs of a category and its whole subtree (one query over the category table)."""
    children = defaultdict(list)
    for pk, parent_id in Category.objects.values_list('id', 'parent_id'):
        children[parent_id].append(pk)
    ids, stack = [], [category_id]
    while stack:
        current = stack.pop()
        ids.append(current)
        stack.extend(children[current])
    return ids


def filter_ads(queryset, *, search=None, categoryId=None, minPrice=None, maxPrice=None,
               status=None, userId=None, **_ignored):
    """Apply every optional filter independently; any combination composes with AND."""
    if search:
        # icontains -> UPPER(col) LIKE UPPER('%term%'), served by the trigram indexes.
        queryset = queryset.filter(Q(title__icontains=search) | Q(description__icontains=search))
    if categoryId is not None:
        queryset = queryset.filter(category_id__in=category_and_descendant_ids(categoryId))
    if minPrice is not None:
        queryset = queryset.filter(price__gte=minPrice)
    if maxPrice is not None:
        queryset = queryset.filter(price__lte=maxPrice)
    if status:
        queryset = queryset.filter(status=status)
    if userId is not None:
        queryset = queryset.filter(user_id=userId)
    return queryset


def sort_ads(queryset, *, sortBy='createdAt', sortOrder='DESC', **_ignored):
    column = _SORT_COLUMNS[sortBy]
    if isinstance(column, str):
        ordering = f'-{column}' if sortOrder == 'DESC' else column
    else:
        ordering = column.desc() if sortOrder == 'DESC' else column.asc()
    # id breaks ties so pages never overlap or skip rows.
    tiebreak = '-id' if sortOrder == 'DESC' else 'id'
    return queryset.order_by(ordering, tiebreak)


def _scope_queryset(queryset, *, scope, viewer, params):
    if scope == SCOPE_MINE:
        # Ownership always comes from the authenticated user, never from input.
        params.pop('userId', None)
        return queryset.filter(user=viewer)
    if scope == SCOPE_ADMIN:
        return queryset
    # Public listing: ACTIVE only, unless an admin explicitly asks for a status.
    requested = params.get('status')
    if is_admin(viewer):
        params.setdefault('status', AdStatus.ACTIVE)
    elif requested and requested != AdStatus.ACTIVE:
        raise PermissionDenied(
            'Only administrators can list non-active advertisements. '
            'Use /api/ads/my-ads to see your own.'
        )
    else:
        params['status'] = AdStatus.ACTIVE
    return queryset


def list_ads(*, viewer, scope, params):
    """Filter, sort and paginate ads for ``viewer`` within ``scope``. Returns a Page."""
    params = dict(params)
    page, limit = params.pop('page'), params.pop('limit')
    queryset = _scope_queryset(ads_with_relations(), scope=scope, viewer=viewer, params=params)
    queryset = filter_ads(queryset, **params)
    queryset = sort_ads(queryset, **params)
    return paginate(queryset, page=page, limit=limit)


def can_view(viewer, ad):
    if ad.status == AdStatus.ACTIVE:
        return True
    return is_admin(viewer) or (viewer.is_authenticated and ad.user_id == viewer.id)


def get_visible_ad(*, viewer, ad_id, for_update=False):
    """Return the ad if ``viewer`` may see it, else raise 404.

    Non-active ads of other users answer 404 rather than 403 so their existence
    is not disclosed.
    """
    queryset = Ad.objects.select_for_update(of=('self',)) if for_update else ads_with_relations()
    ad = queryset.filter(pk=ad_id).first()
    if ad is None or not can_view(viewer, ad):
        raise NotFound('Advertisement not found.')
    return ad
