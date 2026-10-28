# Shorts Server Auto

Автоматизация мониторинга YouTube Shorts трёх каналов: **@i11ush**, **@keymood_yt** и **@world_edges** для подготовки видео к TikTok **@kaspy_58**.

## Статус
По умолчанию **только проверка ссылок**: никакие видео не скачиваются, не загружаются в облако и не публикуются. Ежедневная проверка запускается GitHub Actions; ПК может быть выключен.

Режим `publish` (отдельно включаемый владельцем) рассчитан на одну публикацию в день: проверка RSS/Shorts по трём каналам → доступный короткий ролик → зеркальное отражение FFmpeg → Cloudinary → Buffer (запланированный TikTok).

> Использовать исходные ролики для скачивания и повторного размещения можно лишь при наличии соответствующих прав или разрешений. Зеркальное отражение не отменяет авторские права. Не предусмотрен обход DRM, авторизации или ограничений платных платформ.

## Проверка без публикации
1. Откройте вкладку [Actions](https://github.com/ascer22/shorts-server-auto/actions).
2. Найдите **YouTube Shorts to TikTok (daily)** → **Run workflow** → режим `check`.
3. После выполнения проверьте лог **Check source / optional publishing**: он должен содержать ссылки YouTube и строку `CHECK ONLY`.

## Настройка для публикаций (пока НЕ включена)
1. Подключите TikTok к [Buffer](https://publish.buffer.com/) и получите ключ в [Buffer API Settings](https://publish.buffer.com/settings/api).
2. Зарегистрируйте бесплатный [Cloudinary](https://cloudinary.com/users/register/free). Проще использовать **три отдельных секрета** вместо сборки строки CLOUDINARY_URL: `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`. Приоритет у этой тройки.
3. В GitHub откройте **Settings → Secrets and variables → Actions**:
   - **Secrets**: `BUFFER_API_KEY`, `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` (либо один корректно сформированный `CLOUDINARY_URL`)
   - **Variables**: `TARGET_TIKTOK_HANDLE=kaspy_58`, при необходимости `BUFFER_CHANNEL_ID`
4. Только после теста и подтверждения прав на публикацию установите переменную `ENABLE_AUTOMATION=true`.
5. Проверить вручную: **Actions → Run workflow → publish**.

Без `ENABLE_AUTOMATION=true` даже ручной запрос `publish` остаётся проверкой ссылок.

### Проверка хранения, не публикующая ролики

Откройте [Actions](https://github.com/ascer22/shorts-server-auto/actions) → **Smoke test Cloudinary to Buffer draft** → **Run workflow**. Она генерирует короткое оригинальное тестовое видео, загружает его в Cloudinary и создаёт **только черновик** в Buffer. Никаких постов в TikTok эта проверка не публикует.

Не отправляйте секреты в чат или в содержимое репозитория: только в **Settings → Secrets and variables → Actions → Repository secrets**. Старую некорректную запись `CLOUDINARY_URL` можно не трогать, когда все три отдельных секрета заполнены.

## Расписание
Проверка в **08:17 UTC (11:17 МСК)**. В режиме публикаций скрипт планирует ролик на **18:00 МСК** текущего дня или следующего, если времени до 18:00 осталось менее 30 минут. GitHub может задерживать scheduled runs.

## Источники Shorts

В `config.json` задан список `youtube_sources`:

- [@i11ush](https://www.youtube.com/@i11ush/shorts)
- [@keymood_yt](https://www.youtube.com/@keymood_yt/shorts)
- [@world_edges](https://www.youtube.com/@world_edges/shorts)

При запуске проверяются все три канала. Новые Shorts помечаются каналом-источником, а уже запланированные ролики не добавляются повторно. При последующей публикации источники чередуются, чтобы один канал не занимал всю очередь. Если отдельный канал недоступен, его ошибка сохраняется в журнале, но проверка остальных продолжается. Для каналов без ID используется публичная страница Shorts через yt-dlp.

Добавление канала **не включает автопубликацию**. Проверить список источников можно через `Actions → Run workflow → check`.

## Важные ограничения
- RSS отдаёт ограниченное количество последних роликов; не каждый ролик может быть доступен для получения yt-dlp.
- Счётчики и лимиты бесплатных аккаунтов Buffer / Cloudinary могут меняться. Возможны остановки по квотам.
- Буферу нужна публичная HTTPS-ссылка на видео; облачный файл нельзя удалять до публикации.
- `data/state.json` хранит сведения о созданных запланированных постах. Для проверки реальной публикации используйте Buffer Sent / TikTok.
- GitHub Secrets никогда не нужно отправлять в чат или помещать в код.

## Локально
```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python pipeline.py --mode check
```

Документация: [Buffer Video Post API](https://developers.buffer.com/examples/create-video-post.html) · [GitHub Actions Schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
