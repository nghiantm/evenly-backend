# Evenly Backend

A Splitwise-style expense sharing API built with FastAPI, PostgreSQL, and Clerk authentication.

## Tech Stack

- **FastAPI** — async web framework
- **PostgreSQL** — database (via `asyncpg`)
- **SQLAlchemy 2.x** — async ORM
- **Alembic** — database migrations
- **Pydantic v2** — request/response validation
- **Clerk** — JWT authentication (RS256 via JWKS)

## Quick Start

### 1. Install dependencies

```bash
pip install -e ".[dev]"
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your DATABASE_URL and Clerk credentials
```

### 3. Run database migrations

```bash
DATABASE_URL=postgresql+asyncpg://... alembic upgrade head
```

### 4. Start the server

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`.
Interactive docs: `http://localhost:8000/docs`

## Authentication

All endpoints (except `/healthz`) require a valid Clerk JWT in the `Authorization: Bearer <token>` header.

On first request the local user record is automatically created/updated from the JWT claims (`sub`, `email`, `name`).

## Running Tests

Tests use an in-memory SQLite database and mock the `get_current_user` dependency — no real database or Clerk account required.

```bash
pytest
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/healthz` | Health check |
| GET | `/users/me` | Get own profile |
| PATCH | `/users/me` | Update own profile |
| GET | `/users/search?q=` | Search users |
| GET | `/users/{id}` | Get user by ID |
| POST | `/groups` | Create group |
| GET | `/groups` | List my groups |
| GET | `/groups/{id}` | Get group detail |
| PATCH | `/groups/{id}` | Update group |
| DELETE | `/groups/{id}` | Archive group |
| POST | `/groups/{id}/members` | Add member |
| DELETE | `/groups/{id}/members/{uid}` | Remove member |
| POST | `/groups/{id}/expenses` | Create expense |
| GET | `/groups/{id}/expenses` | List expenses |
| GET | `/groups/{id}/expenses/{eid}` | Get expense |
| PATCH | `/groups/{id}/expenses/{eid}` | Update expense |
| DELETE | `/groups/{id}/expenses/{eid}` | Delete expense |
| GET | `/groups/{id}/balances` | Group balance summary |
| GET | `/groups/{id}/balances/recalculate` | Recalculate balances |
| GET | `/users/me/balances` | My balances across all groups |
| POST | `/groups/{id}/settlements` | Record settlement |
| GET | `/groups/{id}/settlements` | List settlements |
| GET | `/groups/{id}/settlements/{sid}` | Get settlement |
| DELETE | `/groups/{id}/settlements/{sid}` | Delete settlement |

## Balance Model

- `GroupTransfer` records are the source of truth for balances
- `from_user_id` = debtor (owes money), `to_user_id` = creditor (is owed money)
- Expense creation generates transfers: for each split, if `split.user != payer`, create a transfer from the split user to the payer
- Settlements create a reverse transfer to offset existing debt
- Net balance for user X = `SUM(amount WHERE to_user=X) - SUM(amount WHERE from_user=X)`
