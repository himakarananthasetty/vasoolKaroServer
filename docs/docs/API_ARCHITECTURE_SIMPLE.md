# How our APIs work (simple guide)

This is a plain-English guide to how an API request travels through this project,
how the URLs are built, what "DTOs" are, and how to add a new endpoint.

---

## 1. What happens when someone calls an API

Example: the app calls `POST /api/v1/auth/login`.

```
1. FastAPI receives the request
        ↓
2. It finds the right function (routing)
        ↓
3. It checks the login details (a "DTO" validates the JSON body)
        ↓
4. It checks who is calling (auth dependency + rate limit)
        ↓
5. The router calls a service function (the business rules)
        ↓
6. The service talks to the database through SQLAlchemy models
        ↓
7. The router commits the change and returns a response DTO
        ↓
8. FastAPI turns that into JSON
   (on errors: a common error handler returns
    {"error": {"code": "...", "message": "..."}})
```

All of this is set up in `backend/src/main.py` in the `create_app()` function:
it creates the app, adds CORS + request-id + error handling, and then mounts
every feature router under `/api/v1`.

---

## 2. How the URLs ("navigation") are built

A URL is made of three pieces:

```
/api/v1   +   /auth   +   /login
   ↑            ↑           ↑
 main.py    auth/router.py  @router.post("/login")
 prefix     prefix          decorator on the function
```

Examples:

| Final URL | Where the pieces come from |
|---|---|
| `POST /api/v1/auth/login` | `/api/v1` (main.py) + `/auth` (auth/router.py) + `/login` (decorator) |
| `GET /api/v1/me` | `/api/v1` (main.py) + `/me` (users/router.py) |
| `POST /api/v1/retailer/offers` | `/api/v1` + `/retailer` (retailer_router in offers/router.py) + `/offers` |

So to "navigate" to the right code:

1. Look in `src/main.py` to see which routers are mounted.
2. Open that feature's `router.py`.
3. Find the decorator matching the URL.

**Security is part of navigation.** Endpoints say who may call them by adding a
dependency to the function, for example:
- `user = Depends(get_current_user)` → must be logged in.
- `user = Depends(require_roles("admin", "retailer"))` → must have one of those roles.

These live in `src/auth/dependencies.py`. If the check fails, the function is
never called.

---

## 3. What a DTO is (in our project, a "schema")

A **DTO** is just a Pydantic model (`BaseModel`) that describes the shape of data
coming in or going out. We name them `...In` and `...Out`.

Example from `src/auth/schemas.py`:

```python
class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # can read from a database object
    id: uuid.UUID
    email: str
    full_name: str | None
```

- **Request DTO (`LoginIn`)** — written as `body: LoginIn` in the router.
  FastAPI checks the JSON before your code runs (types, lengths, email format,
  whitespace trimming). Bad input → automatic 422 error.
- **Response DTO (`ProfileOut`)** — written as `response_model=ProfileOut` on the
  decorator, or used as `ProfileOut.model_validate(orm_object)`. It makes sure we
  only send the fields we intend to send (never password hashes, etc.).
- **Error DTO** — `src/core/errors.py`. Every error class has a stable code, e.g.
  `Conflict`/`NotFound`/`RateLimited`, and the handler in `main.py` always returns
  the same `{"error": {...}}` shape.

Where DTOs live today:
- `src/auth/schemas.py` and `src/users/schemas.py` — neat, dedicated files.
- Other features (offers, wallet, claims, todos, support, notifications, admin)
  keep their DTOs at the top of `service.py`. That works, but it is inconsistent —
  a cleanup would move them all to `schemas.py`.

---

## 4. How many layers are there?

The product app has **5 layers**:

| Layer | Which files | Job |
|---|---|---|
| 1. Router | `src/<feature>/router.py`, `src/main.py` | Match URL, check auth, pick status code, commit |
| 2. DTO | `schemas.py` or `...In/...Out` in `service.py` | Validate input, shape output |
| 3. Service | `src/<feature>/service.py` | Business rules ("can this user do this?"), errors |
| 4. ORM / session | `src/db/models.py`, `src/core/db.py` | Database tables and connections |
| 5. Database | Postgres | Stores the data |

Shared helpers used by every layer: `auth/dependencies.py`, `core/errors.py`,
`core/security.py`, `core/config.py`, `common/rate_limit.py`, `core/logging.py`.

The rule from `DEVELOPMENT_GUIDE.md`: **business rules go in the service, never in
the router.** The router should be thin.

---

## 5. How to add a new API (simple checklist)

Say we want `POST /api/v1/things`.

1. **Database** – if you need a new table, write an Alembic migration first, then
   add the table to `src/db/models.py` (UUID id, money as `*_cents bigint`).
2. **DTOs** – create `src/things/schemas.py` with `ThingCreateIn` (fields the user
   may send) and `ThingOut` (fields we return).
3. **Errors** – add any new error code to `src/core/errors.py`.
4. **Service** – create `src/things/service.py` with a function that checks the
   business rules and queries the DB using the logged-in user's id.
5. **Router** – create `src/things/router.py`:

   ```python
   router = APIRouter(prefix="/things", tags=["things"])

   @router.post("", response_model=ThingOut, status_code=201)
   def create_thing(
       body: ThingCreateIn,
       user: User = Depends(get_current_user),
       db: Session = Depends(get_db),
   ):
       thing = service.create_thing(db, user, body)
       db.commit()
       return thing
   ```

6. **Mount it** – in `src/main.py`:

   ```python
   from src.things.router import router as things_router
   ...
   app.include_router(things_router, prefix="/api/v1")
   ```

7. **Test it** – test success, plus abuse cases: someone else's id → 404,
   wrong role → 403, invalid input → 422.
8. **Document it** – update `docs/docs/API_REFERENCE.md`.

---

## 6. Two things to be aware of

1. **There are two app styles in this repo.**
   - Your product APIs (auth, users, offers, wallet, claims, referrals, etc.) are
     in `src/main.py` + `src/<feature>/router.py`. Run with
     `uvicorn src.main:app`.
   - The original boilerplate's "clean" app is in `src/interfaces/main.py` +
     `src/modules/...`, assembled by `src/wiring/app.py`. Run with
     `fastapi dev src/interfaces/main.py`.

   Right now `backend/Dockerfile` starts the **second one**, so the product
   endpoints are not served by the container. Pick one as the real app and make
   the Dockerfile, docs and local commands agree.

2. **The clean style has more layers (7):** entry → app factory → API prefix →
   router mounts (`wiring/app.py`) → routes → injected service → CRUD → model.
   It is the same idea as above, just split into more files, with async DB
   sessions and dependency aliases (`UserServiceDep`, `CurrentUserDep`, ...).
