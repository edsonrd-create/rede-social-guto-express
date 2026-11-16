import tempfile,time,unittest
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs
import httpx
from cryptography.fernet import Fernet
from core import Queue,MetaPublisher
from owner_auth import Store
from meta_login import UnifiedLogin

class UnifiedTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=Store(Queue(self.tmp.name+'/db'),Fernet.generate_key())
 def tearDown(self): self.tmp.cleanup()
 def login(self,wrong_account=False,wrong_business=False,scopes=None,expiry=None):
  def handle(req):
   assert req.url.host=='graph.facebook.com'
   path=req.url.path
   if path.endswith('/oauth/access_token'):return httpx.Response(200,json={'access_token':'qa-suat'})
   if path.endswith('/debug_token'):return httpx.Response(200,json={'data':{'is_valid':True,'app_id':'4841713669443386','scopes':scopes if scopes is not None else ['instagram_basic','instagram_content_publish'],'expires_at':expiry if expiry is not None else int(time.time())+60*86400}})
   if path.endswith('/assigned_instagram_accounts'):return httpx.Response(200,json={'data':[{'id':'123','username':'other' if wrong_account else 'gutoexpress'}]})
   if path.endswith('/me'):return httpx.Response(200,json={'client_business_id':'wrong' if wrong_business else '1375878014056924'})
   raise AssertionError(path)
  return UnifiedLogin(self.store,'https://example.com','4841713669443386','qa-secret','v27.0',httpx.Client(transport=httpx.MockTransport(handle)),config_id='2135916773978596',business_id='1375878014056924')
 def test_flow(self):
  login=self.login();state,url=login.begin();p=parse_qs(urlsplit(url).query)
  self.assertEqual(p['config_id'],['2135916773978596']);self.assertNotIn('scope',p)
  self.assertEqual(login.complete(state,'code')['account_id'],'123')
  self.assertEqual(login.credentials()['provider'],'unified')
  with self.assertRaises(ValueError):login.complete(state,'code')
 def test_wrong_account(self):
  login=self.login(wrong_account=True);state,_=login.begin()
  with self.assertRaises(ValueError):login.complete(state,'code')
 def test_wrong_business(self):
  login=self.login(wrong_business=True);state,_=login.begin()
  with self.assertRaises(ValueError):login.complete(state,'code')
 def test_missing_scope(self):
  login=self.login(scopes=['instagram_basic']);state,_=login.begin()
  with self.assertRaises(ValueError):login.complete(state,'code')
 def test_nonexpiring_rejected(self):
  login=self.login(expiry=0);state,_=login.begin()
  with self.assertRaises(ValueError):login.complete(state,'code')
 def test_expired_record(self):
  login=self.login();self.store.put('meta','gutoexpress',{'provider':'unified'},time.time()-1)
  with self.assertRaises(ValueError):login.credentials()
 def test_publisher_host_and_target(self):
  def handle(req):
   self.assertEqual(req.url.host,'graph.facebook.com');self.assertTrue(req.url.path.endswith('/123'))
   return httpx.Response(200,json={'id':'123','username':'gutoexpress'})
  with patch.dict('os.environ',{'META_LOGIN_MODE':'unified','META_ACCESS_TOKEN':'qa','META_GRAPH_VERSION':'v27.0','INSTAGRAM_ACCOUNT_ID':'123'}):
   publisher=MetaPublisher(httpx.Client(transport=httpx.MockTransport(handle)))
   self.assertEqual(publisher.verify_account()['id'],'123')
