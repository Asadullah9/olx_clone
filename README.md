# OLX Clone API

Django 5.2 + Django REST Framework + PostgreSQL 17, run with Docker Compose.
Interactive API docs (Swagger UI) are served at **http://localhost:8000/api/docs/**.

## Setup

```sh
cp .env.example .env          # then set DJANGO_SECRET_KEY and DB_PASS
docker compose up --build     # waits for Postgres, runs migrations, starts on :8000
docker compose run --rm app sh -c "python manage.py createsuperuser"
```

Run the tests and the linter:

```sh
docker compose run --rm app sh -c "python manage.py test && flake8"
```

Validate the OpenAPI schema:

```sh
docker compose run --rm app sh -c "python manage.py spectacular --validate --fail-on-warn --file /tmp/schema.yml"
```

### Production notes

- `pg_trgm` is enabled by migration `core.0003`. It is a trusted extension (PG 13+), so the
  database owner can create it. If your role cannot, run `CREATE EXTENSION pg_trgm;` once as a superuser.
- Media files go to `DJANGO_MEDIA_ROOT` (`/vol/web/media` in Docker). Django serves them only when
  `DJANGO_DEBUG=1`; in production serve that directory from your web server, or switch
  `STORAGES['default']` to object storage (e.g. `django-storages` with S3). No code changes are needed,
  because ad images go through Django's storage API.
- `ADS_MAX_IMAGE_SIZE_MB` (default 5) caps each image.

## Authentication

```sh
curl -X POST http://localhost:8000/api/user/register/ -d email=me@example.com -d name=Me -d password='...'
curl -X POST http://localhost:8000/api/user/token/    -d email=me@example.com -d password='...'
# => {"token": "9944b0...", "user": {...}}
```

Send `Authorization: Token <token>` on authenticated requests. Admins are users with `is_staff=True`.

## Advertisements API

Trailing slashes are optional on every ads route.

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/api/ads` | anyone | List, search, filter, sort, paginate (ACTIVE ads only) |
| POST | `/api/ads` | authenticated | Create (multipart, 4-5 images). Status is always PENDING |
| GET | `/api/ads/:id` | anyone / owner / admin | Detail. Non-active ads are visible only to their owner and admins |
| PUT/PATCH | `/api/ads/:id` | owner, admin | Partial update, including images and status |
| DELETE | `/api/ads/:id` | owner, admin | Delete the ad, its image rows and its files |
| GET | `/api/ads/my-ads` | authenticated | The caller's own ads, all four statuses |
| GET | `/api/admin/ads` | admin | Every ad, any status, with the creator's email |
| PATCH | `/api/admin/ads/:id/approve` | admin | PENDING → ACTIVE |
| PATCH | `/api/admin/ads/:id/reject` | admin | PENDING → REJECTED, with an optional `rejectionReason` |

### List query parameters

`page` (default 1), `limit` (default 10, max 100), `search` (case-insensitive partial match on the
title or description), `categoryId` (includes subcategories), `minPrice`, `maxPrice`, `status`,
`userId` (not on `/my-ads`), `sortBy` = `createdAt` | `price` | `title`, `sortOrder` = `ASC` | `DESC`.
All filters are optional and can be combined. Invalid values return 400.
On `/api/ads`, non-admins may only pass `status=ACTIVE`.

### Status rules

| Who | Allowed |
|---|---|
| Owner | Deactivate (any → `INACTIVE`) or resubmit (`INACTIVE` → `PENDING`) |
| Owner | When they edit the content (title, description, price, category or images) of an `ACTIVE` or `REJECTED` ad, it goes back to `PENDING` for re-review |
| Admin | Approve or reject `PENDING` ads. Set any status with PUT |

`userId` and `status` sent when creating an ad are ignored. The owner always comes from the token.

### Images on update

The final set of images is built from:

1. the existing images, minus `removeImageIds`,
2. re-ordered by `imageOrder` if you send it (it must list every kept ID),
3. followed by the new `images` uploads.

The result must contain 4-5 images. If you send no image fields, the existing images are kept.
To replace an image, send `removeImageIds` and `images` together.
Allowed types are JPEG, JPG, PNG and WebP. The real image format is checked, not just the file extension.

### Sample requests

```sh
T="Authorization: Token <token>"

# Create
curl -X POST http://localhost:8000/api/ads -H "$T" \
  -F title="iPhone 15 Pro 256GB" -F description="Natural titanium, with box." \
  -F price=950 -F categoryId=3 \
  -F images=@1.jpg -F images=@2.jpg -F images=@3.png -F images=@4.webp

# Search + filters + pagination
curl "http://localhost:8000/api/ads?search=iphone&categoryId=3&minPrice=100&maxPrice=1000&sortBy=price&sortOrder=ASC&page=1&limit=10"

# Replace image 102 and change the price
curl -X PUT http://localhost:8000/api/ads/42 -H "$T" -F price=900 -F removeImageIds=102 -F images=@new.jpg

# Reorder images (JSON works when no files are uploaded)
curl -X PATCH http://localhost:8000/api/ads/42 -H "$T" -H "Content-Type: application/json" \
  -d '{"imageOrder": [104, 101, 103, 105]}'

# Deactivate
curl -X PUT http://localhost:8000/api/ads/42 -H "$T" -H "Content-Type: application/json" -d '{"status": "INACTIVE"}'

# My pending ads
curl "http://localhost:8000/api/ads/my-ads?status=PENDING" -H "$T"

# Moderate (admin token)
curl -X PATCH http://localhost:8000/api/admin/ads/42/approve -H "$T"
curl -X PATCH http://localhost:8000/api/admin/ads/42/reject -H "$T" \
  -H "Content-Type: application/json" -d '{"rejectionReason": "Photos do not show the item."}'
```

### Response format

Success:

```json
{
  "success": true,
  "message": "Advertisements retrieved successfully",
  "data": [{
    "id": 42, "userId": 7, "title": "iPhone 15 Pro 256GB",
    "description": "Natural titanium, with box.", "price": "950.00",
    "status": "ACTIVE", "rejectionReason": "",
    "categoryId": 3,
    "category": {"id": 3, "name": "Mobile Phones", "slug": "mobile-phones", "description": ""},
    "creator": {"id": 7, "name": "Asad"},
    "images": [{"id": 101, "imageUrl": "http://localhost:8000/media/ads/42/1f3c....jpg",
                "displayOrder": 0, "createdAt": "2026-11-18T10:00:00Z"}],
    "createdAt": "2026-11-18T10:00:00Z", "updatedAt": "2026-11-18T10:00:00Z"
  }],
  "pagination": {"total": 100, "page": 1, "limit": 10, "totalPages": 10,
                 "hasNextPage": true, "hasPreviousPage": false}
}
```

Error (every endpoint in the project returns this shape):

```json
{
  "success": false,
  "message": "Advertisement not found.",
  "data": null,
  "error": {"code": "not_found", "message": "Advertisement not found.", "details": {}}
}
```

Status codes: 200, 201 (created), 400 (validation or invalid status change), 401, 403, 404,
and 500 (including `image_storage_error`).

## Code layout

```
app/core/      models (User, Category, Ad, AdImage), exception handler, response/pagination helpers
app/ads/
  urls.py         routes (/api/ads, /api/admin/ads)
  views.py        thin controllers + OpenAPI docs
  serializers.py  request DTOs (body + query params) and response shapes
  selectors.py    read side: one shared filter/search/sort/paginate pipeline + visibility rules
  services.py     write side: create/update/delete/moderate, authorization, transactions
  storage.py      image storage on Django's storage API
  validators.py   image extension/size/format validation
  signals.py      deletes image files after the transaction commits
  tests/          integration (API) and unit tests
```
