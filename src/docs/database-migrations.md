# Database Migrations with Alembic

**Created**: 2025-12-30
**Database**: PostgreSQL (lupin_db_dev / lupin_db_prod)

---

## Overview

Lupin uses **Alembic** for database schema migrations. Alembic provides version control for the database schema, allowing controlled upgrades and rollbacks.

---

## Quick Reference

```bash
# Check current migration status
export DATABASE_URL="postgresql://lupin_dev:<DB_PASSWORD>@localhost:5432/lupin_db_dev"
alembic current

# Apply all pending migrations
alembic upgrade head

# Rollback last migration
alembic downgrade -1

# View migration history
alembic history

# Create a new migration (after modifying models)
alembic revision -m "description_of_change"
```

---

## Directory Structure

```
src/migrations/
├── env.py                    # Alembic environment configuration
├── script.py.mako            # Migration template
├── README                    # Alembic readme
└── versions/                 # Migration files
    ├── 210acf4d54dd_initial_schema.py
    └── 275fb8d9c75c_add_notifications_table.py
```

---

## Migration History

| Revision | Description | Date |
|----------|-------------|------|
| `210acf4d54dd` | Initial schema (stamped) | 2025-11-17 |
| `275fb8d9c75c` | Add notifications table | 2025-12-30 |

---

## Creating New Migrations

### 1. Modify the ORM Model

Edit `src/cosa/rest/postgres_models.py` to add/modify the SQLAlchemy model.

### 2. Update the SQL Schema

Add the corresponding SQL to `src/scripts/sql/schema.sql` for documentation.

### 3. Create Migration File

```bash
# Generate revision ID
python3 -c "import uuid; print(uuid.uuid4().hex[:12])"

# Create migration file manually in src/migrations/versions/
# Or use alembic revision (requires env.py setup with target_metadata)
```

### 4. Apply Migration

```bash
export DATABASE_URL="postgresql://lupin_dev:<DB_PASSWORD>@localhost:5432/lupin_db_dev"
alembic upgrade head
```

### 5. Verify

Run the ORM model smoke test:
```bash
source src/cosa/.venv/bin/activate
PYTHONPATH="$PWD/src:$PYTHONPATH" python3 -m cosa.rest.postgres_models
```

---

## Environment Configuration

The `DATABASE_URL` environment variable controls which database Alembic connects to:

| Environment | Database URL |
|-------------|--------------|
| Development | `postgresql://lupin_dev:<DB_PASSWORD>@localhost:5432/lupin_db_dev` |
| Testing | `postgresql://lupin_dev:<DB_PASSWORD>@localhost:5432/lupin_db_test` |
| Production | Set via `CLOUD_SQL_CONNECTION_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` |

---

## Troubleshooting

### "No alembic_version table found"

The database hasn't been stamped with a migration version. Stamp it:
```bash
alembic stamp <revision_id>  # e.g., alembic stamp 210acf4d54dd
```

### Migration fails with foreign key error

Ensure the referenced table exists. Migrations are applied in order by `down_revision` chain.

### Model and table out of sync

Run the ORM smoke test to compare:
```bash
PYTHONPATH="$PWD/src:$PYTHONPATH" python3 -m cosa.rest.postgres_models
```

---

## Related Files

- **ORM Models**: `src/cosa/rest/postgres_models.py`
- **Database Session**: `src/cosa/rest/db/database.py`
- **Repositories**: `src/cosa/rest/db/repositories/`
- **SQL Schema**: `src/scripts/sql/schema.sql`
