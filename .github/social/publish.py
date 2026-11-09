"""Instagram paylaşım görevi (GitHub Actions).

queue/*.json içindeki status "ready" ve zamanı gelmiş (at <= şimdi) paylaşımları @tekqrcom'a gönderir.
Medya dosyaları media/ içinde bekler. Paylaşım anında:
  1) dosya sunucuya GEÇİCİ olarak yüklenir (tekqr.com/paylasim/<rastgele>-<ad>, FTPS),
  2) Instagram dosyayı kendi sunucusuna kopyalar ve paylaşım yapılır,
  3) dosya sunucudan HEMEN silinir (başarılı da olsa hatalı da olsa) ve repodaki media kopyası kaldırılır,
  4) kuyruk dosyasına status "published" + media_id yazılır (tekrar paylaşılmaz).
Erişim kodu ve FTP şifresi yalnızca ortam değişkeninde; hiçbir yere yazılmaz.

Kuyruk dosyası:
{
  "status": "ready",                      # ready | published | failed
  "at": "2026-11-10T19:30:00+03:00",       # isteğe bağlı; yoksa hemen
  "type": "STORY_IMAGE",                   # STORY_IMAGE | STORY_VIDEO | IMAGE | REELS | CAROUSEL
  "files": ["story-02.jpg"],               # media/ altındaki dosyalar (CAROUSEL'de birden çok)
  "caption": "..."                         # story'de kullanılmaz
}
"""
import json, os, sys, time, glob, secrets, subprocess, urllib.parse, urllib.request
from datetime import datetime, timezone

API = 'https://graph.facebook.com/v23.0'
TOKEN = os.environ['IG_ACCESS_TOKEN']
IG = os.environ['IG_USER_ID']
MEDIA_DIR = 'media'
REMOTE_DIR = 'public/paylasim'            # FTP kökü = /home/tekqrtr/tekqr-v2 → tekqr.com/paylasim/
PUBLIC_BASE = 'https://tekqr.com/paylasim/'


def call(method, path, **params):
    params['access_token'] = TOKEN
    data = urllib.parse.urlencode(params)
    url = f'{API}/{path}'
    req = urllib.request.Request(url + ('?' + data if method == 'GET' else ''), data=None if method == 'GET' else data.encode(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'{e.code} {e.read().decode(errors="replace").replace(TOKEN, "***")}')


def ftp(commands):
    script = 'set ftp:ssl-force true\nset ssl:verify-certificate yes\nset net:max-retries 2\n' + commands + '\nquit\n'
    r = subprocess.run(['lftp', '-u', f'{os.environ["SITE_FTP_USERNAME"]},{os.environ["SITE_FTP_PASSWORD"]}', f'ftp://{os.environ["FTP_SERVER"]}'],
                       input=script, text=True, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError('FTP: ' + (r.stderr or r.stdout).replace(os.environ['SITE_FTP_PASSWORD'], '***')[:400])


def wait_public(url):
    for _ in range(24):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method='HEAD'), timeout=20) as r:
                if r.status == 200:
                    return
        except Exception:
            pass
        time.sleep(5)
    raise RuntimeError(f'dosya adreste açılmadı: {url}')


def wait_ready(cid):
    for _ in range(60):  # en fazla ~5 dk (video işleme)
        st = call('GET', cid, fields='status_code').get('status_code')
        if st == 'FINISHED':
            return
        if st in ('ERROR', 'EXPIRED'):
            raise RuntimeError(f'medya işlenemedi: {st}')
        time.sleep(5)
    raise RuntimeError('medya işleme zaman aşımı')


def is_video(name):
    return name.lower().endswith(('.mp4', '.mov'))


def container(item, urls):
    t, cap = item['type'], item.get('caption', '')
    if t == 'STORY_IMAGE':
        return call('POST', f'{IG}/media', media_type='STORIES', image_url=urls[0])['id']
    if t == 'STORY_VIDEO':
        return call('POST', f'{IG}/media', media_type='STORIES', video_url=urls[0])['id']
    if t == 'IMAGE':
        return call('POST', f'{IG}/media', image_url=urls[0], caption=cap)['id']
    if t == 'REELS':
        return call('POST', f'{IG}/media', media_type='REELS', video_url=urls[0], caption=cap, share_to_feed='true')['id']
    if t == 'CAROUSEL':
        kids = []
        for u in urls:
            k = call('POST', f'{IG}/media', is_carousel_item='true', **({'media_type': 'VIDEO', 'video_url': u} if is_video(u) else {'image_url': u}))['id']
            wait_ready(k)
            kids.append(k)
        return call('POST', f'{IG}/media', media_type='CAROUSEL', children=','.join(kids), caption=cap)['id']
    raise RuntimeError(f'bilinmeyen tür: {t}')


def publish(item):
    files = item.get('files') or []
    remote = []  # sunucuya yüklenen geçici adlar
    try:
        if files:
            put = ['mkdir -p -f ' + REMOTE_DIR]
            for f in files:
                local = os.path.join(MEDIA_DIR, f)
                if not os.path.isfile(local):
                    raise RuntimeError(f'medya yok: {local}')
                name = secrets.token_hex(6) + '-' + f
                put.append(f'put {local} -o {REMOTE_DIR}/{name}')
                remote.append(name)
            ftp('\n'.join(put))
            urls = [PUBLIC_BASE + n for n in remote]
            for u in urls:
                wait_public(u)
        else:
            urls = item['media']  # eski biçim: hazır herkese açık adresler
        cid = container(item, urls)
        wait_ready(cid)
        return call('POST', f'{IG}/media_publish', creation_id=cid)['id']
    finally:
        if remote:
            try:
                ftp('\n'.join(f'rm -f {REMOTE_DIR}/{n}' for n in remote))
                print('  sunucudaki geçici dosyalar silindi')
            except Exception as e:
                print(f'  UYARI: sunucudan silinemedi: {e}')


def main():
    now = datetime.now(timezone.utc)
    failed = False
    for path in sorted(glob.glob('queue/*.json')):
        item = json.load(open(path, encoding='utf-8'))
        if item.get('status') != 'ready':
            continue
        at = item.get('at')
        if at and datetime.fromisoformat(at) > now:
            print(f'{path}: zamanı gelmedi ({at})')
            continue
        print(f'{path}: paylaşılıyor ({item["type"]})')
        try:
            mid = publish(item)
            item.update(status='published', media_id=mid, published_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
            item.pop('error', None)
            for f in item.get('files') or []:  # paylaşılan medya repodan da kalkar (geçmişte durur)
                p = os.path.join(MEDIA_DIR, f)
                if os.path.isfile(p):
                    os.remove(p)
            print(f'  yayınlandı: media_id={mid}')
        except Exception as e:
            item.update(status='failed', error=str(e)[:500])
            failed = True
            print(f'  HATA: {e}')
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(item, fh, ensure_ascii=False, indent=2)
            fh.write('\n')
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
