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

class UnifiedLogin(InstagramLogin):
    """Business Integration SUAT: graph.facebook.com; no Instagram token refresh."""
    def __init__(self,store,base,app_id,app_secret,version,client=None,config_id=None,business_id=None):
        import os
        super().__init__(store,base,app_id,app_secret,version,client)
        self.config_id=config_id or os.environ.get('META_CONFIG_ID','')
        self.business_id=business_id or os.environ.get('META_BUSINESS_ID','')
        if not self.config_id.isdigit() or not self.business_id.isdigit():
            raise ValueError('Configure config_id e business ID da Meta.')
        self.graph='https://graph.facebook.com/'+version
    def begin(self):
        state=secrets.token_urlsafe(32)
        self.store.put('meta_state',state,{'config_id':self.config_id},time.time()+600)
        return state,'https://www.facebook.com/'+self.version+'/dialog/oauth?'+urlencode({
            'client_id':self.app_id,'config_id':self.config_id,'redirect_uri':self.callback,
            'response_type':'code','state':state})
    def complete(self,state,code):
        pending=self.store.get('meta_state',state,consume=True)
        if not pending or pending.get('config_id')!=self.config_id:
            raise ValueError('Estado inválido ou configuração alterada.')
        token=self.checked(self.client.get(self.graph+'/oauth/access_token',params={
            'client_id':self.app_id,'client_secret':self.app_secret,'redirect_uri':self.callback,'code':code}))['access_token']
        debug=self.checked(self.client.get(self.graph+'/debug_token',params={'input_token':token},
            headers={'Authorization':'Bearer '+self.app_id+'|'+self.app_secret}))['data']
        now=time.time()
        if not debug.get('is_valid') or str(debug.get('app_id'))!=self.app_id:
            raise ValueError('Token inválido ou emitido para outro aplicativo.')
        required={'instagram_basic','instagram_content_publish'}
        if not required.issubset(set(debug.get('scopes',[]))):
            raise ValueError('Permissões de publicação incompletas.')
        expiry=int(debug.get('expires_at',0))
        if expiry<=now or expiry>now+61*86400:
            raise ValueError('Token não corresponde à configuração com validade de 60 dias.')
        data_expiry=int(debug.get('data_access_expires_at',0))
        if data_expiry: expiry=min(expiry,data_expiry)
        if expiry<=now: raise ValueError('Acesso aos dados expirado.')
        headers={'Authorization':'Bearer '+token}
        business=self.checked(self.client.get(self.graph+'/me',params={'fields':'client_business_id'},headers=headers))
        if str(business.get('client_business_id'))!=self.business_id:
            raise ValueError('Portfólio autorizado difere do configurado.')
        matches=[];after=None
        for _ in range(10):
            params={'fields':'id,username','limit':100}
            if after: params['after']=after
            result=self.checked(self.client.get(self.graph+'/me/assigned_instagram_accounts',params=params,headers=headers))
            matches.extend(a for a in result.get('data',[]) if a.get('username','').lower()=='gutoexpress')
            paging=result.get('paging',{})
            if not paging.get('next'): break
            after=paging.get('cursors',{}).get('after')
            if not after: raise ValueError('Paginação da Meta incompleta.')
        else: raise ValueError('Lista de contas excede o limite de conferência.')
        if len(matches)!=1 or not str(matches[0].get('id','')).isdigit():
            raise ValueError('@gutoexpress não foi compartilhado de forma inequívoca.')
        account=str(matches[0]['id'])
        self.store.put('meta','gutoexpress',{'provider':'unified','token':token,'account':account,
            'business_id':self.business_id,'config_id':self.config_id,'app_id':self.app_id,
            'issued_at':now,'expires_at':expiry},expiry)
        return {'username':'gutoexpress','account_id':account,'expires_at':expiry}
    def credentials(self):
        item=self.store.get('meta','gutoexpress')
        if not item or item.get('provider')!='unified' or item.get('config_id')!=self.config_id or item.get('app_id')!=self.app_id or item.get('business_id')!=self.business_id:
            raise ValueError('Autorize @gutoexpress pelo login unificado.')
        # No automatic refresh: these minimal scopes do not include business_management.
        return item


def configured_login(store,base,app_id,app_secret,version,client=None):
    import os
    cls=UnifiedLogin if os.getenv('META_LOGIN_MODE')=='unified' else InstagramLogin
    return cls(store,base,app_id,app_secret,version,client)
