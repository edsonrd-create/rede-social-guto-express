"""Single-owner OAuth provider for MCP. PKCE/token protocol handled by official SDK.
Not multi-tenant. Requires an exact callback allowlist and independent owner password.
"""
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlencode
from cryptography.fernet import Fernet
from mcp.server.auth.provider import AuthorizationCode, RefreshToken, AccessToken, TokenError, RegistrationError, AuthorizeError
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


def password_hash(password, salt=None):
    salt=salt or secrets.token_hex(16)
    return salt+'$'+hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()


def matches(password, encoded):
    try:
        return hmac.compare_digest(password_hash(password,encoded.split('$')[0]),encoded)
    except (ValueError,TypeError):
        return False


class Store:
    def __init__(self,queue,key):
        self.queue=queue; self.cipher=Fernet(key)
        with queue.db() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS auth_records (
                kind TEXT NOT NULL, key TEXT NOT NULL, client TEXT NOT NULL,
                expires REAL NOT NULL, payload BLOB NOT NULL, PRIMARY KEY(kind,key));
                CREATE TABLE IF NOT EXISTS auth_attempts(at REAL NOT NULL);''')
    @staticmethod
    def hashed(value): return hashlib.sha256(value.encode()).hexdigest()
    def put(self,kind,key,data,expires,client='owner'):
        payload=self.cipher.encrypt(json.dumps(data).encode())
        with self.queue.db() as c:
            c.execute('DELETE FROM auth_records WHERE expires<?',(time.time(),))
            c.execute('INSERT OR REPLACE INTO auth_records VALUES (?,?,?,?,?)',(kind,self.hashed(key),client,expires,payload))
    def get(self,kind,key,consume=False):
        with self.queue.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM auth_records WHERE kind=? AND key=?',(kind,self.hashed(key))).fetchone()
            if row is None: return None
            if consume or row['expires']<=time.time():
                c.execute('DELETE FROM auth_records WHERE kind=? AND key=?',(kind,self.hashed(key)))
            if row['expires']<=time.time(): return None
            return json.loads(self.cipher.decrypt(row['payload']))
    def password_allowed(self):
        with self.queue.db() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('DELETE FROM auth_attempts WHERE at<?',(time.time()-900,))
            if c.execute('SELECT COUNT(*) FROM auth_attempts').fetchone()[0]>=5: return False
            c.execute('INSERT INTO auth_attempts VALUES (?)',(time.time(),))
            return True


class OwnerOAuth:
    def __init__(self,store,base,redirects,owner_hash):
        from urllib.parse import urlsplit
        origin=urlsplit(base)
        if origin.scheme!='https' or not origin.netloc or origin.path or origin.query or origin.fragment or origin.username:
            raise ValueError('PUBLIC_BASE_URL precisa ser uma origem HTTPS sem caminho.')
        if any(not r.startswith('https://') for r in redirects):
            raise ValueError('Configure callbacks HTTPS exatos do ChatGPT.')
        if not owner_hash or '$' not in owner_hash:
            raise ValueError('OWNER_PASSWORD_HASH ausente.')
        self.store=store;self.base=base;self.resource=base+'/mcp';self.redirects=redirects;self.owner_hash=owner_hash

    async def get_client(self,client_id):
        item=self.store.get('client',client_id)
        return OAuthClientInformationFull.model_validate(item) if item else None
    async def register_client(self,client_info):
        with self.store.queue.db() as c:
            if c.execute("SELECT COUNT(*) FROM auth_records WHERE kind='client'").fetchone()[0]>=20:
                raise RegistrationError('invalid_client_metadata','Limite de clientes atingido; contate o administrador.')
        if any(str(uri) not in self.redirects for uri in client_info.redirect_uris or []):
            raise RegistrationError('invalid_redirect_uri','Callback não autorizado.')
        if client_info.token_endpoint_auth_method not in ('none','client_secret_post','client_secret_basic'):
            raise RegistrationError('invalid_client_metadata','Método de autenticação não suportado.')
        self.store.put('client',client_info.client_id,client_info.model_dump(mode='json'),time.time()+10*365*86400,client_info.client_id)
    async def authorize(self,client,params):
        with self.store.queue.db() as c:
            if c.execute("SELECT COUNT(*) FROM auth_records WHERE kind='flow' AND expires>?",(time.time(),)).fetchone()[0]>=100:
                raise AuthorizeError('temporarily_unavailable','Muitas autorizações pendentes.')
        if params.resource not in (None,self.resource) or set(params.scopes or [])-{'guto:social'}:
            raise AuthorizeError('invalid_request','Recurso ou escopo inválido.')
        if str(params.redirect_uri) not in self.redirects:
            raise AuthorizeError('access_denied','Callback não autorizado.')
        flow=secrets.token_urlsafe(32)
        self.store.put('flow',flow,{'client_id':client.client_id,'params':params.model_dump(mode='json')},time.time()+600)
        return self.base+'/consent?flow='+flow
    def finish(self,flow,password):
        if not self.store.password_allowed(): raise ValueError('Muitas tentativas. Aguarde 15 minutos.')
        if not matches(password,self.owner_hash): raise ValueError('Autenticação inválida.')
        item=self.store.get('flow',flow,consume=True)
        if not item: raise ValueError('Autorização expirada ou já usada.')
        params=item['params'];code=secrets.token_urlsafe(32)
        data=AuthorizationCode(code=code,scopes=['guto:social'],expires_at=time.time()+120,
            client_id=item['client_id'],code_challenge=params['code_challenge'],
            redirect_uri=params['redirect_uri'],redirect_uri_provided_explicitly=params['redirect_uri_provided_explicitly'],
            resource=self.resource,subject='guto-owner')
        self.store.put('code',code,data.model_dump(mode='json'),data.expires_at,item['client_id'])
        query={'code':code}
        if params['state'] is not None: query['state']=params['state']
        return str(params['redirect_uri'])+('&' if '?' in str(params['redirect_uri']) else '?')+urlencode(query)
    async def load_authorization_code(self,client,authorization_code):
        item=self.store.get('code',authorization_code)
        if not item or item['client_id']!=client.client_id: return None
        return AuthorizationCode.model_validate(item)
    def issue(self,client_id,scopes):
        now=int(time.time());access=secrets.token_urlsafe(32);refresh=secrets.token_urlsafe(32)
        data=AccessToken(token=access,client_id=client_id,scopes=scopes,expires_at=now+3600,resource=self.resource,subject='guto-owner')
        ref=RefreshToken(token=refresh,client_id=client_id,scopes=scopes,expires_at=now+30*86400,subject='guto-owner')
        self.store.put('access',access,data.model_dump(mode='json'),data.expires_at,client_id)
        self.store.put('refresh',refresh,ref.model_dump(mode='json'),ref.expires_at,client_id)
        return OAuthToken(access_token=access,refresh_token=refresh,expires_in=3600,scope=' '.join(scopes))
    async def exchange_authorization_code(self,client,authorization_code):
        item=self.store.get('code',authorization_code.code,consume=True)
        if not item or item['client_id']!=client.client_id: raise TokenError('invalid_grant')
        return self.issue(client.client_id,authorization_code.scopes)
    async def load_refresh_token(self,client,refresh_token):
        item=self.store.get('refresh',refresh_token)
        if not item or item['client_id']!=client.client_id: return None
        return RefreshToken.model_validate(item)
    async def exchange_refresh_token(self,client,refresh_token,scopes):
        item=self.store.get('refresh',refresh_token.token,consume=True)
        if not item or item['client_id']!=client.client_id or set(scopes)-set(item['scopes']):
            raise TokenError('invalid_grant')
        await self.revoke_token(refresh_token)
        return self.issue(client.client_id,scopes)
    async def load_access_token(self,token):
        item=self.store.get('access',token)
        if not item or item.get('resource')!=self.resource: return None
        return AccessToken.model_validate(item)
    async def revoke_token(self,token):
        with self.store.queue.db() as c:
            c.execute("DELETE FROM auth_records WHERE client=? AND kind IN ('access','refresh')",(token.client_id,))
