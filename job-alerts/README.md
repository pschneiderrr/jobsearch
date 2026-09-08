# job-alerts

Два независимых сканера вакансий, шлют новые находки в Telegram.

- `direct_scan.py` — опрашивает Greenhouse/Lever/Ashby API по компаниям из `companies.json`. Запускается раз в 30 минут.
- `search_scan.py` — ищет по трём доменам через Google Custom Search API по запросам из `search_queries.json`. Запускается дважды в день.

## Установка

1. Создать пустой репозиторий на GitHub, залить туда все эти файлы (сохранив структуру папок, включая `.github/workflows/`).
2. В репозитории: Settings → Secrets and variables → Actions → New repository secret. Добавить четыре секрета:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `GOOGLE_API_KEY`
   - `GOOGLE_CSE_ID`
3. Заполнить `companies.json` реальными компаниями (см. ниже).
4. Проверить вручную: вкладка Actions → выбрать workflow → Run workflow (кнопка справа) — это запустит скрипт немедленно, не дожидаясь расписания.

## Как добавить компанию в шорт-лист

Открыть страницу вакансий компании на Greenhouse/Lever/Ashby, посмотреть в адресной строке slug (последний кусок URL), добавить в `companies.json`:

```json
{"name": "Название", "platform": "greenhouse", "slug": "company-slug"}
```

`platform` — один из: `greenhouse`, `lever`, `ashby`.

## Настройка фильтров

- `keywords.json` — какие слова должны/не должны быть в названии вакансии (для `direct_scan.py`).
- `search_queries.json` — поисковые запросы для Google CSE (для `search_scan.py`).

## Ограничения

- Google Custom Search API: 100 запросов/день бесплатно. При 3 запросах × 2 раза в день — 6/день, есть большой запас на добавление новых запросов.
- Ashby иногда меняет структуру JSON-ответа. Если бот не находит вакансии по компании на Ashby, а они точно есть — пришли пример ответа `https://api.ashbyhq.com/posting-api/job-board/{slug}`, поправим парсинг.
- GitHub Actions на бесплatном плане может слегка задерживать cron-запуски (обычно на 5-15 минут) в моменты пиковой нагрузки — это ограничение самого GitHub, не скрипта.
