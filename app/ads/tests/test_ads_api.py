"""Integration tests for the ads API (HTTP -> view -> service -> DB/storage)."""
from decimal import Decimal
from unittest import mock

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from ads.tests.helpers import (
    MediaTestCase,
    create_ad,
    create_category,
    make_image,
    make_images,
)
from core.models import Ad, AdImage, AdStatus

ADS_URL = reverse('ads:ad-list')
MY_ADS_URL = reverse('ads:ad-my-ads')
ADMIN_ADS_URL = reverse('ads:admin-ad-list')


def detail_url(ad_id):
    return reverse('ads:ad-detail', args=[ad_id])


def approve_url(ad_id):
    return reverse('ads:admin-ad-approve', args=[ad_id])


def reject_url(ad_id):
    return reverse('ads:admin-ad-reject', args=[ad_id])


class CreateAdTests(MediaTestCase):

    def payload(self, images=4, **overrides):
        data = {
            'title': '  iPhone 15 Pro  ',
            'description': 'Natural titanium, with box and charger.',
            'price': '950.50',
            'categoryId': self.category.id,
            'images': make_images(images),
        }
        data.update(overrides)
        return data

    def test_requires_authentication(self):
        res = self.client.post(ADS_URL, self.payload(), format='multipart')
        self.assertError(res, status.HTTP_401_UNAUTHORIZED, 'not_authenticated')
        self.assertFalse(Ad.objects.exists())

    def test_create_with_four_images(self):
        self.auth(self.owner)
        res = self.client.post(ADS_URL, self.payload(), format='multipart')

        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        self.assertTrue(res.data['success'])
        self.assertEqual(res.data['message'], 'Advertisement created successfully')
        data = res.data['data']
        self.assertEqual(data['title'], 'iPhone 15 Pro')
        self.assertEqual(data['price'], '950.50')
        self.assertEqual(data['status'], AdStatus.PENDING)
        self.assertEqual(data['userId'], self.owner.id)
        self.assertEqual(data['category']['name'], 'Mobile Phones')
        self.assertEqual(data['creator'], {'id': self.owner.id, 'name': 'owner'})
        self.assertEqual([img['displayOrder'] for img in data['images']], [0, 1, 2, 3])
        self.assertTrue(data['images'][0]['imageUrl'].startswith('http://testserver/'))
        self.assertIsNotNone(data['createdAt'])
        self.assertIsNotNone(data['updatedAt'])

        ad = Ad.objects.get(id=data['id'])
        names = list(ad.images.values_list('image', flat=True))
        self.assertEqual(len(names), 4)
        for name in names:
            self.assertTrue(default_storage.exists(name))
            self.assertTrue(name.startswith(f'ads/{ad.id}/'))

    def test_create_with_five_mixed_format_images(self):
        self.auth(self.owner)
        images = [
            make_image('a.jpg'), make_image('b.jpeg'), make_image('c.png', 'PNG'),
            make_image('d.webp', 'WEBP'), make_image('e.PNG', 'PNG'),
        ]
        res = self.client.post(ADS_URL, self.payload() | {'images': images}, format='multipart')

        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        self.assertEqual(len(res.data['data']['images']), 5)

    def test_too_few_or_too_many_images_rejected(self):
        self.auth(self.owner)
        for count in (0, 3, 6):
            with self.subTest(count=count):
                data = self.payload(images=count)
                if count == 0:
                    data.pop('images')
                res = self.client.post(ADS_URL, data, format='multipart')
                self.assertError(res, status.HTTP_400_BAD_REQUEST, 'validation_error')
                self.assertIn('images', res.data['error']['details'])
        self.assertFalse(Ad.objects.exists())

    def test_invalid_image_files_rejected(self):
        self.auth(self.owner)
        bad_files = {
            'gif': make_image('anim.gif', 'GIF'),
            'renamed text': SimpleUploadedFile('fake.jpg', b'not an image', 'image/jpeg'),
            'png named .bmp': SimpleUploadedFile(
                'x.bmp', make_image('x.png', 'PNG').read(), 'image/bmp',
            ),
        }
        for label, bad in bad_files.items():
            with self.subTest(label):
                res = self.client.post(
                    ADS_URL, self.payload(images=3) | {'images': make_images(3) + [bad]},
                    format='multipart',
                )
                self.assertError(res, status.HTTP_400_BAD_REQUEST, 'validation_error')
                self.assertIn('images', res.data['error']['details'])
        self.assertFalse(Ad.objects.exists())

    @override_settings(ADS_MAX_IMAGE_SIZE=100)
    def test_oversized_image_rejected(self):
        self.auth(self.owner)
        big = make_image('big.jpg', size=(400, 400))
        res = self.client.post(
            ADS_URL, self.payload() | {'images': make_images(3) + [big]}, format='multipart',
        )
        self.assertError(res, status.HTTP_400_BAD_REQUEST, 'validation_error')
        self.assertIn('larger than', str(res.data['error']['details']))

    def test_required_fields_and_values_validated(self):
        self.auth(self.owner)
        cases = {
            'title': {'title': ''},
            'description': {'description': 'short'},
            'price': {'price': '-1'},
            'categoryId': {'categoryId': 99999},
        }
        for field, override in cases.items():
            with self.subTest(field):
                res = self.client.post(ADS_URL, self.payload(**override), format='multipart')
                self.assertError(res, status.HTTP_400_BAD_REQUEST, 'validation_error')
                self.assertIn(field, res.data['error']['details'])

    def test_user_id_and_status_in_body_are_ignored(self):
        self.auth(self.owner)
        res = self.client.post(
            ADS_URL,
            self.payload(userId=self.other.id, user=self.other.id, status=AdStatus.ACTIVE),
            format='multipart',
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        ad = Ad.objects.get()
        self.assertEqual(ad.user, self.owner)
        self.assertEqual(ad.status, AdStatus.PENDING)

    def test_storage_failure_rolls_back_and_cleans_up(self):
        self.auth(self.owner)
        real_save = default_storage.save
        calls = []

        def flaky_save(name, content, **kwargs):
            calls.append(name)
            if len(calls) == 3:
                raise OSError('disk full')
            return real_save(name, content, **kwargs)

        with mock.patch('ads.storage.default_storage.save', side_effect=flaky_save), \
                self.assertLogs('ads.storage', level='ERROR'):
            res = self.client.post(ADS_URL, self.payload(), format='multipart')

        self.assertError(res, status.HTTP_500_INTERNAL_SERVER_ERROR, 'image_storage_error')
        self.assertFalse(Ad.objects.exists())
        self.assertFalse(AdImage.objects.exists())
        for name in calls[:2]:
            self.assertFalse(default_storage.exists(name))


class ListAdsTests(MediaTestCase):

    def setUp(self):
        super().setUp()
        self.laptops = create_category('Laptops')
        self.android = create_category('Android', parent=self.category)
        self.iphone = create_ad(self.owner, self.category, title='Apple iPhone 13',
                                price='500', images=1)
        self.pixel = create_ad(self.other, self.android, title='Google Pixel',
                               description='An android phone like an IPHONE killer.',
                               price='300', images=1)
        self.macbook = create_ad(self.owner, self.laptops, title='MacBook Air',
                                 price='1200', images=1)
        self.pending = create_ad(self.owner, self.category, title='iPhone pending',
                                 status=AdStatus.PENDING, images=1)
        self.rejected = create_ad(self.other, self.category, title='Rejected iPhone',
                                  status=AdStatus.REJECTED, images=1)

    def ids(self, res):
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        return [ad['id'] for ad in res.data['data']]

    def test_public_list_shows_only_active_newest_first(self):
        res = self.client.get(ADS_URL)

        self.assertTrue(res.data['success'])
        self.assertEqual(res.data['message'], 'Advertisements retrieved successfully')
        self.assertEqual(self.ids(res), [self.macbook.id, self.pixel.id, self.iphone.id])
        ad = res.data['data'][0]
        self.assertEqual(ad['category']['id'], self.laptops.id)
        self.assertEqual(len(ad['images']), 1)
        self.assertNotIn('email', ad['creator'])

    def test_pagination_metadata(self):
        res = self.client.get(ADS_URL, {'page': 2, 'limit': 2})

        self.assertEqual(self.ids(res), [self.iphone.id])
        self.assertEqual(res.data['pagination'], {
            'total': 3, 'page': 2, 'limit': 2, 'totalPages': 2,
            'hasNextPage': False, 'hasPreviousPage': True,
        })

    def test_page_past_end_is_empty(self):
        res = self.client.get(ADS_URL, {'page': 9})
        self.assertEqual(self.ids(res), [])
        self.assertEqual(res.data['pagination']['total'], 3)

    def test_search_is_partial_and_case_insensitive_on_title_and_description(self):
        res = self.client.get(ADS_URL, {'search': 'iphone'})
        self.assertCountEqual(self.ids(res), [self.iphone.id, self.pixel.id])

        res = self.client.get(ADS_URL, {'search': 'MACB'})
        self.assertEqual(self.ids(res), [self.macbook.id])

    def test_category_filter_includes_subcategories(self):
        res = self.client.get(ADS_URL, {'categoryId': self.category.id})
        self.assertCountEqual(self.ids(res), [self.iphone.id, self.pixel.id])

        res = self.client.get(ADS_URL, {'categoryId': self.android.id})
        self.assertEqual(self.ids(res), [self.pixel.id])

    def test_price_filters(self):
        res = self.client.get(ADS_URL, {'minPrice': 400})
        self.assertCountEqual(self.ids(res), [self.iphone.id, self.macbook.id])
        res = self.client.get(ADS_URL, {'maxPrice': 500})
        self.assertCountEqual(self.ids(res), [self.iphone.id, self.pixel.id])
        res = self.client.get(ADS_URL, {'minPrice': 300, 'maxPrice': 500})
        self.assertCountEqual(self.ids(res), [self.iphone.id, self.pixel.id])

    def test_filters_combine(self):
        res = self.client.get(ADS_URL, {
            'search': 'iphone', 'categoryId': self.category.id,
            'minPrice': 100, 'maxPrice': 1000, 'page': 1, 'limit': 10,
        })
        self.assertCountEqual(self.ids(res), [self.iphone.id, self.pixel.id])

        res = self.client.get(ADS_URL, {'search': 'iphone', 'userId': self.other.id})
        self.assertEqual(self.ids(res), [self.pixel.id])

    def test_sorting(self):
        res = self.client.get(ADS_URL, {'sortBy': 'price', 'sortOrder': 'asc'})
        self.assertEqual(self.ids(res), [self.pixel.id, self.iphone.id, self.macbook.id])

        res = self.client.get(ADS_URL, {'sortBy': 'title', 'sortOrder': 'ASC'})
        self.assertEqual(self.ids(res), [self.iphone.id, self.pixel.id, self.macbook.id])

        res = self.client.get(ADS_URL, {'sortBy': 'createdAt', 'sortOrder': 'ASC'})
        self.assertEqual(self.ids(res), [self.iphone.id, self.pixel.id, self.macbook.id])

    def test_invalid_query_parameters(self):
        cases = [
            {'page': 0}, {'page': 'abc'}, {'limit': 0}, {'limit': 101},
            {'minPrice': -5}, {'minPrice': 500, 'maxPrice': 100}, {'sortBy': 'password'},
            {'sortOrder': 'sideways'}, {'status': 'DELETED'}, {'categoryId': 99999},
        ]
        for params in cases:
            with self.subTest(params):
                res = self.client.get(ADS_URL, params)
                self.assertError(res, status.HTTP_400_BAD_REQUEST, 'validation_error')

    def test_non_admin_cannot_list_other_statuses(self):
        res = self.client.get(ADS_URL, {'status': 'PENDING'})
        self.assertError(res, status.HTTP_403_FORBIDDEN)

        self.auth(self.owner)
        res = self.client.get(ADS_URL, {'status': 'pending'})
        self.assertError(res, status.HTTP_403_FORBIDDEN)

        res = self.client.get(ADS_URL, {'status': 'ACTIVE'})
        self.assertEqual(len(self.ids(res)), 3)

    def test_admin_can_list_other_statuses(self):
        self.auth(self.admin)
        res = self.client.get(ADS_URL, {'status': 'PENDING'})
        self.assertEqual(self.ids(res), [self.pending.id])
        self.assertIn('email', res.data['data'][0]['creator'])

        # Without a status even admins get the public view on this endpoint.
        res = self.client.get(ADS_URL)
        self.assertEqual(len(self.ids(res)), 3)

    def test_query_count_does_not_grow_with_results(self):
        for i in range(5):
            create_ad(self.other, self.category, title=f'Extra {i}', images=2)
        # count + page + images prefetch (category/user are joined).
        with self.assertNumQueries(3):
            res = self.client.get(ADS_URL)
        self.assertEqual(len(res.data['data']), 8)


class RetrieveAdTests(MediaTestCase):

    def test_active_ad_is_public(self):
        ad = create_ad(self.owner, self.category)
        res = self.client.get(detail_url(ad.id))

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['success'])
        data = res.data['data']
        self.assertEqual(data['id'], ad.id)
        self.assertEqual(data['category']['id'], self.category.id)
        self.assertEqual(data['creator']['id'], self.owner.id)
        self.assertEqual(len(data['images']), 4)

    def test_missing_ad_returns_404(self):
        res = self.client.get(detail_url(424242))
        self.assertError(res, status.HTTP_404_NOT_FOUND, 'not_found')
        self.assertEqual(res.data['message'], 'Advertisement not found.')

    def test_non_active_ads_visible_only_to_owner_and_admin(self):
        for ad_status in (AdStatus.PENDING, AdStatus.INACTIVE, AdStatus.REJECTED):
            with self.subTest(ad_status):
                ad = create_ad(self.owner, self.category, status=ad_status, images=1)

                self.client.force_authenticate(None)
                self.assertError(self.client.get(detail_url(ad.id)), 404)
                self.auth(self.other)
                self.assertError(self.client.get(detail_url(ad.id)), 404)

                self.auth(self.owner)
                self.assertEqual(self.client.get(detail_url(ad.id)).status_code, 200)
                self.auth(self.admin)
                res = self.client.get(detail_url(ad.id))
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.data['data']['creator']['email'], self.owner.email)


class UpdateAdTests(MediaTestCase):

    def setUp(self):
        super().setUp()
        self.ad = create_ad(self.owner, self.category, images=4)
        self.image_ids = list(self.ad.images.values_list('id', flat=True))

    def put(self, data, fmt='multipart', ad=None):
        return self.client.put(detail_url((ad or self.ad).id), data, format=fmt)

    def test_requires_authentication(self):
        self.assertError(self.put({'title': 'New title'}), 401)

    def test_owner_updates_fields_and_keeps_images(self):
        self.auth(self.owner)
        before = self.ad.updated_at
        other_category = create_category('Tablets')
        res = self.put({
            'title': 'iPhone 15 Pro Max', 'price': '999.99', 'categoryId': other_category.id,
        }, fmt='json')

        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(res.data['message'], 'Advertisement updated successfully')
        data = res.data['data']
        self.assertEqual(data['title'], 'iPhone 15 Pro Max')
        self.assertEqual(data['price'], '999.99')
        self.assertEqual(data['category']['id'], other_category.id)
        self.assertEqual([img['id'] for img in data['images']], self.image_ids)
        self.ad.refresh_from_db()
        self.assertGreater(self.ad.updated_at, before)

    def test_owner_content_edit_sends_active_ad_back_to_review(self):
        self.auth(self.owner)
        res = self.put({'title': 'Swapped content', 'status': 'ACTIVE'}, fmt='json')

        self.assertEqual(res.data['data']['status'], AdStatus.PENDING)

    def test_admin_edit_keeps_status(self):
        self.auth(self.admin)
        res = self.put({'title': 'Fixed typo'}, fmt='json')
        self.assertEqual(res.data['data']['status'], AdStatus.ACTIVE)

    def test_user_id_cannot_be_changed(self):
        self.auth(self.owner)
        res = self.put({'title': 'Mine still', 'userId': self.other.id}, fmt='json')
        self.assertEqual(res.status_code, 200)
        self.ad.refresh_from_db()
        self.assertEqual(self.ad.user, self.owner)

    def test_non_owner_forbidden(self):
        self.auth(self.other)
        self.assertError(self.put({'title': 'Hijacked'}, fmt='json'), 403, 'permission_denied')
        self.ad.refresh_from_db()
        self.assertEqual(self.ad.title, 'iPhone 15 Pro')

    def test_non_owner_gets_404_for_hidden_ad(self):
        pending = create_ad(self.owner, self.category, status=AdStatus.PENDING, images=4)
        self.auth(self.other)
        self.assertError(self.put({'title': 'Hijacked'}, fmt='json', ad=pending), 404)

    def test_missing_ad_returns_404(self):
        self.auth(self.owner)
        res = self.client.put(detail_url(999999), {'title': 'Nope'}, format='json')
        self.assertError(res, 404)

    def test_empty_update_rejected(self):
        self.auth(self.owner)
        self.assertError(self.put({}, fmt='json'), 400)

    def test_add_image(self):
        self.auth(self.owner)
        res = self.put({'images': [make_image('new.png', 'PNG')]})

        self.assertEqual(res.status_code, 200, res.data)
        images = res.data['data']['images']
        self.assertEqual([img['displayOrder'] for img in images], [0, 1, 2, 3, 4])
        self.assertEqual([img['id'] for img in images[:4]], self.image_ids)

    def test_cannot_exceed_five_images(self):
        self.auth(self.owner)
        res = self.put({'images': make_images(2)})
        self.assertError(res, 400, 'validation_error')
        self.assertEqual(self.ad.images.count(), 4)

    def test_cannot_drop_below_four_images(self):
        self.auth(self.owner)
        res = self.put({'removeImageIds': [self.image_ids[0]]})
        self.assertError(res, 400, 'validation_error')
        self.assertEqual(self.ad.images.count(), 4)

    def test_replace_image_deletes_old_file_after_commit(self):
        self.auth(self.owner)
        old = AdImage.objects.get(id=self.image_ids[1])
        old_name = old.image.name

        with self.captureOnCommitCallbacks(execute=True):
            res = self.put({'removeImageIds': [old.id], 'images': [make_image('n.webp', 'WEBP')]})

        self.assertEqual(res.status_code, 200, res.data)
        images = res.data['data']['images']
        ids = [img['id'] for img in images]
        self.assertEqual(ids[:3], [self.image_ids[0], self.image_ids[2], self.image_ids[3]])
        self.assertNotIn(old.id, ids)
        self.assertEqual([img['displayOrder'] for img in images], [0, 1, 2, 3])
        self.assertFalse(default_storage.exists(old_name))
        self.assertTrue(images[3]['imageUrl'].endswith('.webp'))

    def test_reorder_images(self):
        self.auth(self.owner)
        new_order = list(reversed(self.image_ids))
        res = self.put({'imageOrder': new_order})

        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual([img['id'] for img in res.data['data']['images']], new_order)

    def test_reorder_must_cover_every_kept_image(self):
        self.auth(self.owner)
        res = self.put({'imageOrder': self.image_ids[:3]})
        self.assertError(res, 400)

    def test_cannot_remove_another_ads_image(self):
        foreign = create_ad(self.other, self.category, images=1).images.get()
        self.auth(self.owner)
        res = self.put({'removeImageIds': [foreign.id], 'images': [make_image()]})
        self.assertError(res, 400)
        self.assertTrue(AdImage.objects.filter(id=foreign.id).exists())

    def test_invalid_new_image_rejected(self):
        self.auth(self.owner)
        res = self.put({'images': [SimpleUploadedFile('x.jpg', b'nope', 'image/jpeg')]})
        self.assertError(res, 400)

    def test_owner_can_deactivate_and_resubmit(self):
        self.auth(self.owner)
        res = self.put({'status': 'inactive'}, fmt='json')
        self.assertEqual(res.data['data']['status'], AdStatus.INACTIVE)

        res = self.put({'status': 'PENDING'}, fmt='json')
        self.assertEqual(res.data['data']['status'], AdStatus.PENDING)

    def test_owner_cannot_approve_or_reject(self):
        pending = create_ad(self.owner, self.category, status=AdStatus.PENDING, images=4)
        self.auth(self.owner)
        for new_status in (AdStatus.ACTIVE, AdStatus.REJECTED):
            with self.subTest(new_status):
                res = self.put({'status': new_status}, fmt='json', ad=pending)
                self.assertError(res, 403)
        res = self.put({'rejectionReason': 'x'}, fmt='json', ad=pending)
        self.assertError(res, 403)
        pending.refresh_from_db()
        self.assertEqual(pending.status, AdStatus.PENDING)

    def test_admin_can_set_any_status(self):
        self.auth(self.admin)
        res = self.put({'status': 'REJECTED', 'rejectionReason': 'Stock photo'}, fmt='json')
        self.assertEqual(res.data['data']['status'], AdStatus.REJECTED)
        self.assertEqual(res.data['data']['rejectionReason'], 'Stock photo')

        res = self.put({'status': 'ACTIVE'}, fmt='json')
        self.assertEqual(res.data['data']['status'], AdStatus.ACTIVE)
        self.assertEqual(res.data['data']['rejectionReason'], '')

    def test_patch_behaves_like_put(self):
        self.auth(self.owner)
        res = self.client.patch(detail_url(self.ad.id), {'price': '10'}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['data']['price'], '10.00')


class DeleteAdTests(MediaTestCase):

    def test_owner_deletes_ad_and_files(self):
        ad = create_ad(self.owner, self.category)
        names = list(ad.images.values_list('image', flat=True))
        self.auth(self.owner)

        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.delete(detail_url(ad.id))

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data, {
            'success': True, 'message': 'Advertisement deleted successfully', 'data': None,
        })
        self.assertFalse(Ad.objects.filter(id=ad.id).exists())
        self.assertFalse(AdImage.objects.filter(ad_id=ad.id).exists())
        for name in names:
            self.assertFalse(default_storage.exists(name))

    def test_non_owner_forbidden(self):
        ad = create_ad(self.owner, self.category, images=1)
        self.auth(self.other)
        self.assertError(self.client.delete(detail_url(ad.id)), 403)
        self.assertTrue(Ad.objects.filter(id=ad.id).exists())

    def test_admin_can_delete(self):
        ad = create_ad(self.owner, self.category, status=AdStatus.PENDING, images=1)
        self.auth(self.admin)
        self.assertEqual(self.client.delete(detail_url(ad.id)).status_code, 200)
        self.assertFalse(Ad.objects.filter(id=ad.id).exists())

    def test_missing_ad_returns_404(self):
        self.auth(self.owner)
        self.assertError(self.client.delete(detail_url(31337)), 404)

    def test_requires_authentication(self):
        ad = create_ad(self.owner, self.category, images=1)
        self.assertError(self.client.delete(detail_url(ad.id)), 401)

    def test_deleting_user_cleans_up_files(self):
        ad = create_ad(self.owner, self.category, images=2)
        names = list(ad.images.values_list('image', flat=True))
        with self.captureOnCommitCallbacks(execute=True):
            self.owner.delete()
        for name in names:
            self.assertFalse(default_storage.exists(name))


class MyAdsTests(MediaTestCase):

    def setUp(self):
        super().setUp()
        self.mine = {
            s: create_ad(self.owner, self.category, status=s, title=f'My {s.lower()} ad',
                         images=1)
            for s in AdStatus.values
        }
        self.theirs = create_ad(self.other, self.category, images=1)

    def test_requires_authentication(self):
        self.assertError(self.client.get(MY_ADS_URL), 401)

    def test_returns_all_statuses_of_own_ads_only(self):
        self.auth(self.owner)
        res = self.client.get(MY_ADS_URL)

        self.assertEqual(res.status_code, 200)
        self.assertCountEqual([a['id'] for a in res.data['data']],
                              [a.id for a in self.mine.values()])
        self.assertEqual(res.data['pagination']['total'], 4)

    def test_filter_by_each_status(self):
        self.auth(self.owner)
        for ad_status, ad in self.mine.items():
            with self.subTest(ad_status):
                res = self.client.get(MY_ADS_URL, {'status': ad_status})
                self.assertEqual([a['id'] for a in res.data['data']], [ad.id])

    def test_combined_filters(self):
        create_ad(self.owner, create_category('Cars'), status=AdStatus.ACTIVE, images=1)
        self.auth(self.owner)
        res = self.client.get(MY_ADS_URL, {
            'status': 'ACTIVE', 'categoryId': self.category.id, 'page': 1, 'limit': 10,
            'search': 'active', 'maxPrice': 1000, 'sortBy': 'price',
        })
        self.assertEqual([a['id'] for a in res.data['data']], [self.mine[AdStatus.ACTIVE].id])

    def test_user_id_param_cannot_override_ownership(self):
        self.auth(self.owner)
        res = self.client.get(MY_ADS_URL, {'userId': self.other.id})
        ids = [a['id'] for a in res.data['data']]
        self.assertNotIn(self.theirs.id, ids)
        self.assertEqual(len(ids), 4)

    def test_invalid_status_rejected(self):
        self.auth(self.owner)
        self.assertError(self.client.get(MY_ADS_URL, {'status': 'SOLD'}), 400)


class AdminAdsTests(MediaTestCase):

    def setUp(self):
        super().setUp()
        self.pending = create_ad(self.owner, self.category, status=AdStatus.PENDING, images=1)
        self.active = create_ad(self.other, self.category, images=1)

    def test_regular_users_cannot_access_admin_endpoints(self):
        self.auth(self.owner)
        self.assertError(self.client.get(ADMIN_ADS_URL), 403)
        self.assertError(self.client.patch(approve_url(self.pending.id)), 403)
        self.assertError(self.client.patch(reject_url(self.pending.id)), 403)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, AdStatus.PENDING)

    def test_anonymous_gets_401(self):
        self.assertError(self.client.get(ADMIN_ADS_URL), 401)
        self.assertError(self.client.patch(approve_url(self.pending.id)), 401)

    def test_admin_lists_all_statuses_with_creator_details(self):
        self.auth(self.admin)
        res = self.client.get(ADMIN_ADS_URL)
        self.assertCountEqual([a['id'] for a in res.data['data']],
                              [self.pending.id, self.active.id])
        self.assertEqual(res.data['data'][0]['creator']['email'], self.other.email)

        res = self.client.get(ADMIN_ADS_URL, {'status': 'PENDING'})
        self.assertEqual([a['id'] for a in res.data['data']], [self.pending.id])

    def test_approve_pending(self):
        self.auth(self.admin)
        res = self.client.patch(approve_url(self.pending.id))

        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['message'], 'Advertisement approved successfully')
        self.assertEqual(res.data['data']['status'], AdStatus.ACTIVE)
        # Now publicly visible.
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(detail_url(self.pending.id)).status_code, 200)

    def test_reject_pending_with_reason(self):
        self.auth(self.admin)
        res = self.client.patch(
            reject_url(self.pending.id), {'rejectionReason': 'Prohibited item'}, format='json',
        )
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['data']['status'], AdStatus.REJECTED)
        self.assertEqual(res.data['data']['rejectionReason'], 'Prohibited item')

    def test_reject_without_reason(self):
        self.auth(self.admin)
        res = self.client.patch(reject_url(self.pending.id))
        self.assertEqual(res.data['data']['status'], AdStatus.REJECTED)

    def test_only_pending_ads_can_be_moderated(self):
        self.auth(self.admin)
        res = self.client.patch(approve_url(self.active.id))
        self.assertError(res, 400, 'invalid_status_transition')
        res = self.client.patch(reject_url(self.active.id))
        self.assertError(res, 400, 'invalid_status_transition')

    def test_moderating_missing_ad_returns_404(self):
        self.auth(self.admin)
        self.assertError(self.client.patch(approve_url(987654)), 404)


class TrailingSlashTests(MediaTestCase):

    def test_both_url_forms_work(self):
        create_ad(self.owner, self.category, images=1)
        self.assertEqual(self.client.get('/api/ads').status_code, 200)
        self.assertEqual(self.client.get('/api/ads/').status_code, 200)

    def test_price_returned_with_two_decimals(self):
        ad = create_ad(self.owner, self.category, images=1, price=Decimal('12'))
        res = self.client.get(detail_url(ad.id))
        self.assertEqual(res.data['data']['price'], '12.00')
