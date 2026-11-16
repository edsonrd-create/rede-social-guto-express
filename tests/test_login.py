import asyncio
import hashlib
import tempfile
import time
import unittest
from urllib.parse import urlsplit,parse_qs
from cryptography.fernet import Fernet
import httpx
from core import Queue
from owner_auth import Store,OwnerOAuth,password_hash,matches
from meta_login import InstagramLogin
from mcp.shared.auth import OAuthClientInformationFull
from mcp.server.auth.provider import AuthorizationParams,TokenError,RegistrationError

class AuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=self.tmp.name+'/auth.db'
        self.store=Store(Queue(self.path),Fernet.generate_key())
        self.password='test-owner-password'; self.base='https://social.example.com'
        self.uri='https://chatgpt.com/connector/oauth/test'
        self.auth=OwnerOAuth(self.store,self.base,[self.uri],password_hash(self.password))
        self.client=OAuthClientInformationFull(client_id='client1',redirect_uris=[self.uri],token_endpoint_auth_method='none')
        await self.auth.register_client(self.client)
    async def asyncTearDown(self): self.tmp.cleanup()
    async def flow(self):
        params=AuthorizationParams(state='state',scopes=['guto:social'],code_challenge='challenge',redirect_uri=self.uri,redirect_uri_provided_explicitly=True,resource=self.base+'/mcp')
        url=await self.auth.authorize(self.client,params)
        flow=parse_qs(urlsplit(url).query)['flow'][0]
        target=self.auth.finish(flow,self.password)
        code=parse_qs(urlsplit(target).query)['code'][0]
        return await self.auth.load_authorization_code(self.client,code)
    async def test_code_once_and_rotation(self):
        code=await self.flow();token=await self.auth.exchange_authorization_code(self.client,code)
        self.assertIsNotNone(await self.auth.load_access_token(token.access_token))
        with self.assertRaises(TokenError): await self.auth.exchange_authorization_code(self.client,code)
        refresh=await self.auth.load_refresh_token(self.client,token.refresh_token)
        rotated=await self.auth.exchange_refresh_token(self.client,refresh,['guto:social'])
        self.assertIsNone(await self.auth.load_access_token(token.access_token))
        self.assertIsNone(await self.auth.load_refresh_token(self.client,token.refresh_token))
        self.assertIsNotNone(await self.auth.load_access_token(rotated.access_token))
    async def test_registration_allowlist(self):
        bad=OAuthClientInformationFull(client_id='bad',redirect_uris=['https://evil.example/callback'])
        with self.assertRaises(RegistrationError): await self.auth.register_client(bad)
    async def test_password_throttle(self):
        self.assertFalse(matches('wrong',self.auth.owner_hash))
        self.assertTrue(matches(self.password,self.auth.owner_hash))
        for _ in range(5): self.assertTrue(self.store.password_allowed())
        self.assertFalse(self.store.password_allowed())
    async def test_store_encrypted_and_expiring(self):
        self.store.put('private','key',{'value':'unique-test-secret'},time.time()+10)
        self.assertNotIn(b'unique-test-secret',__import__('pathlib').Path(self.path).read_bytes())
        self.store.put('private','expired',{'value':1},time.time()-1)
        self.assertIsNone(self.store.get('private','expired'))
    async def test_revoke(self):
        code=await self.flow();token=await self.auth.exchange_authorization_code(self.client,code)
        access=await self.auth.load_access_token(token.access_token)
        await self.auth.revoke_token(access)
        self.assertIsNone(await self.auth.load_access_token(token.access_token))

class MetaLoginTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Queue(self.tmp.name+'/meta.db'),Fernet.generate_key())
    def tearDown(self): self.tmp.cleanup()
    def login(self,wrong=False,missing_permission=False):
        def handle(req):
            if req.url.host=='api.instagram.com':
                return httpx.Response(200,json={'data':[{'access_token':'short-secret','user_id':'app-scoped-id',
                    'permissions':'instagram_business_basic' if missing_permission else 'instagram_business_basic,instagram_business_content_publish'}]})
            if req.url.path.endswith('/me'):
                return httpx.Response(200,json={'data':[{'user_id':'123','username':'other' if wrong else 'gutoexpress'}]})
            return httpx.Response(200,json={'access_token':'long-secret','expires_in':60*86400})
        return InstagramLogin(self.store,'https://social.example.com','456','app-secret','v27.0',httpx.Client(transport=httpx.MockTransport(handle)))
    def test_authorization_and_state_once(self):
        login=self.login();state,url=login.begin()
        self.assertEqual(parse_qs(urlsplit(url).query)['state'],[state])
        result=login.complete(state,'code')
        self.assertEqual(result['username'],'gutoexpress')
        self.assertEqual(login.credentials()['account'],'123')
        with self.assertRaises(ValueError): login.complete(state,'replay')
    def test_wrong_account(self):
        login=self.login(wrong=True);state,_=login.begin()
        with self.assertRaises(ValueError): login.complete(state,'code')
        self.assertIsNone(self.store.get('meta','gutoexpress'))
    def test_permissions(self):
        login=self.login(missing_permission=True);state,_=login.begin()
        with self.assertRaises(ValueError): login.complete(state,'code')
    def test_refresh(self):
        login=self.login()
        self.store.put('meta','gutoexpress',{'token':'old','account':'123','issued_at':time.time()-2*86400,'expires_at':time.time()+86400},time.time()+86400)
        self.assertEqual(login.credentials()['token'],'long-secret')
