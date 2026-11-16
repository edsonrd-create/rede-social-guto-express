"""Durable, approval-first Instagram publishing queue. No credentials stored in SQLite."""
from contextlib import contextmanager
import hashlib
import os
import re
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from brand import validate_caption
from urllib.parse import urlsplit
import httpx


def utc(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Informe fuso horário, por exemplo -03:00.')
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


class Queue:
    def __init__(self, path='guto-social.sqlite3'):
        self.path = path
        with self.db() as c:
            c.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS posts (
              id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL,
              caption TEXT NOT NULL, image_url TEXT NOT NULL, alt_text TEXT NOT NULL,
              state TEXT NOT NULL DEFAULT 'draft', scheduled_at TEXT,
              container_id TEXT, media_id TEXT, error TEXT,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT OR IGNORE INTO settings VALUES ('paused','1');
            CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, post_id INTEGER,
              action TEXT NOT NULL, at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            ''')
            columns={r[1] for r in c.execute('PRAGMA table_info(posts)')}
            for name in ['reviewer','reviewed_sha256']:
                if name not in columns:
                    c.execute(f'ALTER TABLE posts ADD COLUMN {name} TEXT')

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def create(self, caption, image_url, alt_text):
        caption, alt_text = caption.strip(), alt_text.strip()
        validate_caption(caption)
        u = urlsplit(image_url)
        allowed = [h.strip().lower() for h in os.getenv('MEDIA_ALLOWED_HOSTS', '').split(',') if h.strip()]
        if not caption or len(caption) > 2200 or not alt_text:
            raise ValueError('Legenda obrigatória até 2200 caracteres e descrição da imagem obrigatória.')
        if u.scheme != 'https' or not u.hostname or u.username or u.password or u.fragment or u.port not in (None, 443):
            raise ValueError('Use imagem JPEG pública em HTTPS, sem credenciais.')
        if u.hostname not in allowed:
            raise ValueError('Domínio da imagem não consta em MEDIA_ALLOWED_HOSTS.')
        fingerprint = hashlib.sha256((caption + '\n' + image_url + '\n' + alt_text).encode()).hexdigest()
        with self.db() as c:
            c.execute('INSERT OR IGNORE INTO posts(fingerprint,caption,image_url,alt_text) VALUES (?,?,?,?)',
                      (fingerprint,caption,image_url,alt_text))
            c.execute('INSERT INTO audit(post_id,action) SELECT id,? FROM posts WHERE fingerprint=?',('draft_saved',fingerprint))
            row = c.execute('SELECT * FROM posts WHERE fingerprint=?',(fingerprint,)).fetchone()
        return dict(row)

    def list(self):
        with self.db() as c:
            return [dict(r) for r in c.execute('SELECT * FROM posts ORDER BY id DESC LIMIT 100')]

    def review(self, post_id, reviewer, image_sha256):
        if not reviewer.strip() or len(reviewer)>100 or not re.fullmatch(r'[a-f0-9]{64}',image_sha256):
            raise ValueError('Revisor identificado e SHA-256 da arte revisada são obrigatórios.')
        with self.db() as c:
            if c.execute("UPDATE posts SET reviewer=?, reviewed_sha256=? WHERE id=? AND state='draft'",
                         (reviewer.strip(),image_sha256,post_id)).rowcount!=1:
                raise ValueError('Somente rascunhos podem receber revisão.')
            c.execute('INSERT INTO audit(post_id,action) VALUES (?,?)',(post_id,'visual_review_recorded'))
        return {'id':post_id,'reviewed':True}

    def approve(self, post_id, scheduled_at):
        scheduled_at = utc(scheduled_at)
        if scheduled_at <= datetime.now(timezone.utc).isoformat():
            raise ValueError('O horário precisa estar no futuro.')
        with self.db() as c:
            if c.execute("UPDATE posts SET state='approved', scheduled_at=? WHERE id=? AND state='draft' AND reviewer IS NOT NULL AND reviewed_sha256 IS NOT NULL",
                         (scheduled_at,post_id)).rowcount != 1:
                raise ValueError('Aprovação exige rascunho e revisão visual da arte com SHA-256.')
            c.execute('INSERT INTO audit(post_id,action) VALUES (?,?)',(post_id,'approved'))
        return {'id':post_id,'state':'approved','scheduled_at':scheduled_at}

    def pause(self, paused=True):
        if type(paused) is not bool:
            raise ValueError('paused precisa ser booleano.')
        with self.db() as c:
            c.execute("UPDATE settings SET value=? WHERE key='paused'",('1' if paused else '0',))
            c.execute('INSERT INTO audit(action) VALUES (?)',('paused' if paused else 'resumed',))
        return {'paused':paused}

    def cancel(self, post_id):
        with self.db() as c:
            if c.execute("UPDATE posts SET state='canceled' WHERE id=? AND state IN ('draft','approved')",(post_id,)).rowcount != 1:
                raise ValueError('Cancelamento indisponível para este estado.')
            c.execute('INSERT INTO audit(post_id,action) VALUES (?,?)',(post_id,'canceled'))
        return {'id':post_id,'state':'canceled'}

    def status(self):
        with self.db() as c:
            return {'paused':c.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0]=='1',
                    'counts':dict(c.execute('SELECT state,COUNT(*) FROM posts GROUP BY state').fetchall()),
                    'target':'@gutoexpress', 'live_enabled':os.getenv('LIVE_PUBLISH')=='true'}

    def run_due(self, publisher):
        """Claim atomically; uncertain writes are quarantined, never blindly retried."""
        if os.getenv('LIVE_PUBLISH') != 'true':
            return {'processed':0,'reason':'Publicação real desativada.'}
        results=[]
        # One daily post by design; avoids a burst after prolonged downtime.
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0]=='1':
                return {'processed':0,'reason':'Fila pausada.'}
            if c.execute("SELECT 1 FROM posts WHERE state IN ('publishing','unknown') LIMIT 1").fetchone():
                return {'processed':0,'reason':'Há tentativa em andamento ou pendente de conferência.'}
            if c.execute("SELECT 1 FROM audit WHERE action='published' AND at >= datetime('now','-24 hours') LIMIT 1").fetchone():
                return {'processed':0,'reason':'Limite local: um post a cada 24 horas.'}
            cutoff=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat(timespec='microseconds')
            stale=[r[0] for r in c.execute("SELECT id FROM posts WHERE state='approved' AND scheduled_at<?",(cutoff,))]
            for stale_id in stale:
                c.execute("UPDATE posts SET state='expired' WHERE id=?",(stale_id,))
                c.execute('INSERT INTO audit(post_id,action) VALUES (?,?)',(stale_id,'expired'))
            row=c.execute("SELECT * FROM posts WHERE state='approved' AND reviewer IS NOT NULL AND reviewed_sha256 IS NOT NULL AND scheduled_at<=? ORDER BY scheduled_at,id LIMIT 1",
                          (datetime.now(timezone.utc).isoformat(),)).fetchone()
            if not row:
                return {'processed':0,'reason':'Sem posts aprovados vencidos.'}
            c.execute("UPDATE posts SET state='publishing' WHERE id=?",(row['id'],))
            c.execute('INSERT INTO audit(post_id,action) VALUES (?,?)',(row['id'],'publishing'))
        post=dict(row)
        phase='preflight'
        try:
            validate_caption(post['caption'])
            publisher.verify_account()
            publisher.validate_media(post)
            phase='container'
            container=publisher.create_container(post)
            with self.db() as c:
                c.execute('UPDATE posts SET container_id=? WHERE id=?',(container,post['id']))
            publisher.wait_ready(container)
            phase='publish'
            media=publisher.publish(container)
            if not media:
                raise RuntimeError('Resposta sem identificador de publicação.')
            state, error = 'published', None
        except Exception:
            # Never persist raw SDK/API errors: they can contain URLs or secrets.
            media=None
            state='unknown' if phase=='publish' else ('blocked' if phase=='preflight' else 'failed')
            error={'preflight':'Conta, conteúdo ou mídia não passou na verificação. Revisão necessária.',
                   'container':'Falha antes de solicitar publicação. Revisão necessária.',
                   'publish':'Conferir tentativa na Meta antes de qualquer reenvio.'}[phase]
        with self.db() as c:
            c.execute('UPDATE posts SET state=?,media_id=?,error=? WHERE id=?',(state,media,error,post['id']))
            c.execute('INSERT INTO audit(post_id,action) VALUES (?,?)',(post['id'],state))
        results.append({'id':post['id'],'state':state,'media_id':media,'error':error})
        return {'processed':len(results),'results':results}


class MetaPublisher:
    """Instagram Login API. Tokens stay in environment/server secret manager."""
    def __init__(self, client=None):
        version=os.environ['META_GRAPH_VERSION']
        if os.getenv('TOKEN_ENCRYPTION_KEY'):
            from owner_auth import Store
            from meta_login import configured_login
            store=Store(Queue(os.getenv('DATABASE_PATH','guto-social.sqlite3')),os.environ['TOKEN_ENCRYPTION_KEY'])
            record=configured_login(store,os.environ['PUBLIC_BASE_URL'],os.environ['META_APP_ID'],os.environ['META_APP_SECRET'],version).credentials()
            token=record['token'];self.account=record['account']
        else:
            token=os.environ['META_ACCESS_TOKEN']
            self.account=os.environ['INSTAGRAM_ACCOUNT_ID']
        if not re.fullmatch(r'v\d+\.\d+',version) or not self.account.isdigit():
            raise ValueError('Versão da API ou ID da conta inválido.')
        self.unified=os.getenv('META_LOGIN_MODE')=='unified'
        host='graph.facebook.com' if self.unified else 'graph.instagram.com'
        self.base=f'https://{host}/{version}'
        self.client=client or httpx.Client(timeout=30, follow_redirects=False)
        self.headers={'Authorization':f'Bearer {token}'}

    def request(self, method, path, **kwargs):
        r=self.client.request(method,f'{self.base}/{path}',headers=self.headers,**kwargs)
        r.raise_for_status()
        result=r.json()
        if 'error' in result:
            raise RuntimeError('Falha na Meta.')
        return result

    def verify_account(self):
        result=self.request('GET',self.account if self.unified else 'me',params={'fields':'id,username' if self.unified else 'user_id,username'})
        from meta_login import single
        result=single(result)
        account_id=result.get('id') if self.unified else result.get('user_id')
        if result.get('username','').lower()!='gutoexpress' or str(account_id)!=self.account:
            raise ValueError('Conta autorizada difere de @gutoexpress.')
        return {'id':account_id,'username':result['username']}

    def validate_media(self, post):
        import io
        import ipaddress
        import socket
        from PIL import Image
        url=urlsplit(post['image_url'])
        hosts=[h.strip().lower() for h in os.getenv('MEDIA_ALLOWED_HOSTS','').split(',') if h.strip()]
        if url.scheme!='https' or url.hostname not in hosts or url.username or url.password or url.port not in (None,443):
            raise ValueError('Origem da mídia não autorizada.')
        # Defense in depth. Allowlist must contain only owner-controlled immutable CDN hosts.
        addresses=socket.getaddrinfo(url.hostname,443,type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError('Mídia precisa estar em servidor público.')
        raw=bytearray()
        # Never attach Meta Authorization header to image hosting requests.
        with self.client.stream('GET',post['image_url']) as response:
            response.raise_for_status()
            if response.status_code!=200:
                raise ValueError('Mídia indisponível ou redirecionada.')
            for chunk in response.iter_bytes():
                raw.extend(chunk)
                if len(raw)>10*1024*1024:
                    raise ValueError('Mídia excede o limite local de 10 MiB.')
        if hashlib.sha256(raw).hexdigest()!=post['reviewed_sha256']:
            raise ValueError('Imagem mudou após revisão.')
        with Image.open(io.BytesIO(raw)) as image:
            if image.format!='JPEG' or image.size!=(1080,1350):
                raise ValueError('Esta edição aceita somente JPEG de feed 1080x1350.')
            image.verify()

    def create_container(self, post):
        return self.request('POST',f'{self.account}/media',data={
            'image_url':post['image_url'],'caption':post['caption'],'alt_text':post['alt_text']})['id']

    def wait_ready(self, container):
        for attempt in range(5):
            status=self.request('GET',container,params={'fields':'status_code'})['status_code']
            if status=='FINISHED':
                return
            if status!='IN_PROGRESS':
                raise RuntimeError('Container indisponível.')
            if attempt<4:
                time.sleep(60)
        raise TimeoutError('Processamento da imagem pendente.')

    def publish(self,container):
        return self.request('POST',f'{self.account}/media_publish',data={'creation_id':container})['id']
