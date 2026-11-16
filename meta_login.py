"""Server-side Instagram Login with encrypted storage, exact target and rotation."""
import re
import secrets
import time
from urllib.parse import urlencode
import httpx

SCOPES={'instagram_business_basic','instagram_business_content_publish'}


def single(data):
    if 'data' in data:
        if 'access_token' in data or 'user_id' in data or len(data['data'])!=1:
            raise ValueError('Resposta Meta ambígua.')
        return data['data'][0]
    return data


class InstagramLogin:
    def __init__(self,store,base,app_id,app_secret,version,client=None):
        if not app_id.isdigit() or not app_secret or not re.fullmatch(r'v\d+\.\d+',version):
            raise ValueError('Configure Instagram App ID, Secret e versão Meta.')
        self.store=store;self.base=base;self.app_id=app_id;self.app_secret=app_secret;self.version=version
        self.callback=base+'/meta/callback'
        self.client=client or httpx.Client(timeout=30,follow_redirects=False)
    def begin(self):
        state=secrets.token_urlsafe(32)
        self.store.put('meta_state',state,{'created':time.time()},time.time()+600)
        return state,'https://www.instagram.com/oauth/authorize?'+urlencode({
            'client_id':self.app_id,'redirect_uri':self.callback,'response_type':'code',
            'scope':','.join(sorted(SCOPES)),'state':state})
    def checked(self,r):
        r.raise_for_status();data=r.json()
        if 'error' in data or 'error_type' in data: raise ValueError('Meta recusou a autorização.')
        return data
    def complete(self,state,code):
        if not self.store.get('meta_state',state,consume=True): raise ValueError('Estado inválido ou expirado.')
        short=single(self.checked(self.client.post('https://api.instagram.com/oauth/access_token',data={
            'client_id':self.app_id,'client_secret':self.app_secret,'grant_type':'authorization_code',
            'redirect_uri':self.callback,'code':code})))
        perms=short.get('permissions',[])
        if isinstance(perms,str): perms=perms.split(',')
        if not SCOPES.issubset(set(perms)):
            raise ValueError('Permissões de publicação incompletas.')
        long=self.checked(self.client.get('https://graph.instagram.com/access_token',params={
            'grant_type':'ig_exchange_token','client_secret':self.app_secret,'access_token':short['access_token']}))
        token=long['access_token']
        profile=single(self.checked(self.client.get('https://graph.instagram.com/'+self.version+'/me',
            headers={'Authorization':'Bearer '+token},params={'fields':'user_id,username'})))
        account=str(profile.get('user_id',''))
        if profile.get('username','').lower()!='gutoexpress' or not account.isdigit():
            raise ValueError('A conta autorizada não é @gutoexpress.')
        self.save(token,account,long['expires_in'])
        return {'username':'gutoexpress','account_id':account}
    def save(self,token,account,lifetime):
        lifetime=int(lifetime)
        if lifetime<=0 or lifetime>366*86400: raise ValueError('Validade do token inválida.')
        now=time.time()
        self.store.put('meta','gutoexpress',{'token':token,'account':account,'issued_at':now,'expires_at':now+lifetime},now+lifetime)
    def credentials(self):
        item=self.store.get('meta','gutoexpress')
        if not item: raise ValueError('Instagram precisa ser autorizado.')
        now=time.time()
        if item['expires_at']-now<7*86400 and now-item['issued_at']>=86400:
            new=self.checked(self.client.get('https://graph.instagram.com/refresh_access_token',params={
                'grant_type':'ig_refresh_token','access_token':item['token']}))
            self.save(new['access_token'],item['account'],new['expires_in'])
            item=self.store.get('meta','gutoexpress')
        return item
