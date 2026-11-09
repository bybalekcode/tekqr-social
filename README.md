# TekQR sosyal medya paylaşımları

@tekqrcom Instagram hesabının otomatik paylaşım kuyruğu. Burada site kodu yok; yalnızca paylaşılacak
görseller/videolar ve paylaşım programı durur (bu içerikler zaten Instagram'da herkese açık olur).

- `queue/*.json` → paylaşım (status `ready`, `type` STORY_IMAGE | STORY_VIDEO | IMAGE | REELS | CAROUSEL,
  `files`, `caption`, isteğe bağlı `at`).
- `media/` → paylaşılacak dosyalar. Paylaşıldıktan sonra buradan silinir.
- `.github/social/publish.py` → dosyayı geçici olarak sunucuya yükler, Instagram'a gönderir, sunucudan siler.
- `social-publish.yml` (push'ta anında), `social-schedule.yml` (zamanı gelen), `social-watch.yml` (bekçi: her dakika
  kuyruğa bakar), `social-check.yml` (yalnızca bağlantı kontrolü).

Depo herkese açık olmalı (bekçi 7/24 çalışır; gizli depoda Actions dakikaları biter).
Gizli bilgiler: `IG_ACCESS_TOKEN`, `IG_USER_ID`, `FTP_SERVER`, `SITE_FTP_USERNAME`, `SITE_FTP_PASSWORD`.
