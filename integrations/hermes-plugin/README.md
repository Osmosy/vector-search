# Плагин Hermes: vector-search

Даёт агенту три инструмента: `vsearch_fetch`, `vsearch_check`, `vsearch_status`.

## Установка

```bash
ln -s ~/projects/vector-search/integrations/hermes-plugin ~/.hermes/plugins/vector-search
hermes plugins enable vector-search
systemctl --user restart hermes-gateway   # инструменты читаются при старте
hermes tools list | grep vector_search
```

Библиотека берётся из исходников репозитория: `VSEARCH_SRC` (по умолчанию
`~/projects/vector-search/src`). Журнал — `VSEARCH_LEDGER` (по умолчанию
`~/.hermes/vector-search/ledger.jsonl`).

## Что делают инструменты

- `vsearch_fetch(url, allow_browser=false, timeout=60, min_chars=400)` — строгое чтение
  страницы: только http/https, проверка каждого редиректа, тип и размер, отказ на 404,
  капче и скане-PDF. Пишет источник в журнал (финальный URL, статус, тип, sha256, время)
  и возвращает `id` — его используют как `source_id` в досье.
- `vsearch_check(dossier)` — гейт: утверждения с `source_ids`, дословными цитатами и
  числами, оценка достаточности. `ok=false`, если утверждение не раскрыто, число не из
  текста, цитата не найдена, есть противоречие или вопрос без утверждения.
- `vsearch_status()` — что уже прочитано и что отказало.

## Контракт ответа

Успешный ответ — плоский JSON без ключей `"error"` и `"failed"` в начале строки:
Hermes (`agent/display.py::_detect_tool_failure`) считает такие ответы сбоем инструмента
и рисует `[error]`, хотя данные получены. Поэтому при успехе поле ошибки не выводится
вовсе, а при отказе чтения возвращается `{"ok": false, "error": ...}` — это честный сбой.

## Проверка

```bash
uv run pytest tests/test_plugin_contract.py
```

Тест регистрирует инструменты через фейковый контекст, читает временный журнал и
проверяет, что успешные ответы не содержат маркеров сбоя.
