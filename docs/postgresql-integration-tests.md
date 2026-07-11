# PostgreSQL integration tests

The `integration` test marker uses `POSTGRES_TEST_URL` only. The fixture refuses the configured
application URL and accepts only a database named `test`, `integration`, `*_test`, or `*_integration`.
It creates and drops tables in that dedicated database; it never uses the working database.

Example:

```bash
POSTGRES_TEST_URL=postgresql+asyncpg://integration:integration@127.0.0.1:55432/integration \
  .venv/bin/python -m pytest -m integration
```
