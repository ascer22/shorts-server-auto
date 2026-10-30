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


## Автоматическая загрузка MP4 на Windows (когда GitHub облако заблокировано YouTube)

Для YouTube Shorts с аккаунтов **@i11ush**, **@keymood_yt**, **@world_edges** добавлен отдельный загрузчик `windows_short_collector.py`. Он не использует другие источники, не создаёт публикаций и не передаёт cookie-файлы в GitHub.

GitHub-hosted виртуальные машины могут получить от YouTube `Sign in to confirm you're not a bot`. При запуске с домашнего ПК иногда удаётся получить доступ к видео, которые реально доступны в браузере. **Гарантии нет:** YouTube может потребовать авторизацию или отказать в скачивании; скачивайте и публикуйте только контент, для которого у вас есть права и разрешения.

### Установка (один раз)

1. На Windows откройте <https://github.com/ascer22/shorts-server-auto> → **Code → Download ZIP**. Распакуйте в постоянную папку, например `C:\\ShortsAuto`.
2. Установите Python 3.11+ с официального сайта <https://www.python.org/downloads/windows/> (при установке отметьте **Add Python to PATH**).
3. Установите FFmpeg, если его ещё нет. В PowerShell: `winget install --id Gyan.FFmpeg -e`. Закройте и снова откройте PowerShell после установки.
4. Откройте PowerShell в папке с `windows_short_collector.py`, выполните:
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_windows_collector.ps1
   ```
   Скрипт устанавливает `yt-dlp` и добавляет ежедневное задание **Shorts MP4 Collector (Approved Channels Only)** на **11:30 по местному времени Windows**. Задание работает, когда ПК включён, а владелец вошёл в Windows. Это **не облачный 24/7-сервис**.

### Проверить первый MP4

В PowerShell из папки проекта:

```powershell
py -3 windows_short_collector.py --probe
py -3 windows_short_collector.py
```

Если YouTube запрашивает вход, войдите на YouTube в **своём** Edge и проверьте вариант:

```powershell
py -3 windows_short_collector.py --browser edge
```

Режим `--browser edge` использует сессию браузера **локально на ПК**, не экспортируя cookies в GitHub. Запускайте его только для видео, к которым у вас есть законный доступ и право на повторную публикацию. Этот режим может не работать или потребовать закрыть Edge, если хранилище cookies заблокировано. Для постоянного запуска с Edge пересоздайте задание:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_windows_collector.ps1 -Browser edge
```

Готовые файлы сохраняются по пути `local_downloads\@i11ush\VIDEO_ID.mp4` (аналогично для остальных двух каналов). Журнал работы — `local_downloads\collector.log`, история скачанных ID — `local_downloads\downloaded.json`. Папка полностью исключена из Git.

**Важно:** этот этап только автоматически получает MP4 и, если включено `mirror_horizontal`, горизонтально отражает ролик. Для полностью автоматической цепочки до Cloudinary/Buffer потребуется отдельно связать локальную папку с загрузкой в облако. Пока ничего в TikTok не публикуется.

---

## Локально
```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python pipeline.py --mode check
```

Документация: [Buffer Video Post API](https://developers.buffer.com/examples/create-video-post.html) · [GitHub Actions Schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
