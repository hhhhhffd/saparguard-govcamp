# Интеграционные тесты PostgreSQL

[English version](postgresql-integration-tests.md)

Маркер тестов `integration` использует только `POSTGRES_TEST_URL`. Фикстура отклоняет настроенный URL приложения и принимает только БД с именем `test`, `integration`, `*_test` или `*_integration`. Она создаёт и удаляет таблицы только в этой выделенной БД; рабочая БД не используется.

Пример:

```bash
POSTGRES_TEST_URL=postgresql+asyncpg://integration:integration@127.0.0.1:55432/integration \
  .venv/bin/python -m pytest -m integration
```
