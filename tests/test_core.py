import os
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import httpx
from core import Queue, MetaPublisher, utc

class FakeMeta:
    def __init__(self, fail=False):
        self.calls=0
        self.fail=fail
    def verify_account(self): return {'username':'gutoexpress'}
    def validate_media(self,post): pass
    def create_container(self,post): return 'container-1'
    def wait_ready(self,container): pass
    def publish(self,container):
        self.calls+=1
        if self.fail: raise TimeoutError('secret-must-not-leak')
        return 'media-1'

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'MEDIA_ALLOWED_HOSTS':'assets.gutoexpress.com.br','LIVE_PUBLISH':'true'})
        self.env.start()
        self.q=Queue(self.tmp.name+'/test.db')
    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()
    def draft(self):
        return self.q.create('Calabresa ou frango na Guto Express? 🍕','https://assets.gutoexpress.com.br/pizza.jpg','Pizza real de calabresa')['id']
    def due(self):
        post_id=self.draft()
        self.q.review(post_id,'Edson','a'*64)
        self.q.approve(post_id,(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
        # Move clock through DB fixture; real public API rejects past schedules.
        with self.q.db() as c:
            c.execute('UPDATE posts SET scheduled_at=? WHERE id=?',((datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(timespec='microseconds'),post_id))
        return post_id
    def test_duplicate_draft(self):
        self.assertEqual(self.draft(),self.draft())
        self.assertEqual(len(self.q.list()),1)
    def test_media_allowlist(self):
        with self.assertRaises(ValueError): self.q.create('a','https://evil.example/a.jpg','a')
        with self.assertRaises(ValueError): self.q.create('a','http://assets.gutoexpress.com.br/a.jpg','a')
    def test_timezone_required(self):
        with self.assertRaises(ValueError): utc('2026-11-20T18:00:00')
        self.assertEqual(utc('2026-11-20T18:00:00-03:00'),'2026-11-20T21:00:00.000000+00:00')
    def test_draft_not_published(self):
        self.draft(); self.q.pause(False)
        self.assertEqual(self.q.run_due(FakeMeta())['processed'],0)
    def test_paused_and_disabled(self):
        self.due()
        self.assertEqual(self.q.run_due(FakeMeta())['processed'],0)
        self.q.pause(False)
        with patch.dict(os.environ,{'LIVE_PUBLISH':'false'}):
            self.assertEqual(self.q.run_due(FakeMeta())['processed'],0)
    def test_success_once(self):
        self.due(); self.q.pause(False); meta=FakeMeta()
        self.assertEqual(self.q.run_due(meta)['results'][0]['state'],'published')
        self.q.run_due(meta)
        self.assertEqual(meta.calls,1)
    def test_unknown_no_blind_retry(self):
        self.due(); self.q.pause(False); meta=FakeMeta(True)
        self.assertEqual(self.q.run_due(meta)['results'][0]['state'],'unknown')
        self.q.run_due(meta)
        self.assertEqual(meta.calls,1)
        self.assertNotIn('secret-must-not-leak',str(self.q.list()))
    def test_two_workers(self):
        self.due(); self.q.pause(False); meta=FakeMeta()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.q.run_due(meta),range(2)))
        self.assertEqual(sum(r['processed'] for r in results),1)
        self.assertEqual(meta.calls,1)
    def test_cancel(self):
        post=self.draft(); self.q.cancel(post)
        with self.assertRaises(ValueError):
            self.q.approve(post,'2099-01-01T00:00:00-03:00')
    def test_graph_adapter_and_target_guard(self):
        requests=[]
        def handle(req):
            requests.append(req)
            if req.url.path.endswith('/media_publish'): return httpx.Response(200,json={'id':'real-response-id'})
            if req.url.path.endswith('/media'): return httpx.Response(200,json={'id':'container'})
            if req.url.path.endswith('/container'): return httpx.Response(200,json={'status_code':'FINISHED'})
            return httpx.Response(200,json={'user_id':'123','username':'gutoexpress'})
        with patch.dict(os.environ,{'META_ACCESS_TOKEN':'test-token','META_GRAPH_VERSION':'v27.0','INSTAGRAM_ACCOUNT_ID':'123'}):
            meta=MetaPublisher(httpx.Client(transport=httpx.MockTransport(handle)))
            meta.verify_account()
            container=meta.create_container({'image_url':'https://assets.gutoexpress.com.br/a.jpg','caption':'oi','alt_text':'pizza'})
            meta.wait_ready(container)
            self.assertEqual(meta.publish(container),'real-response-id')
            self.assertTrue(all(r.headers['Authorization']=='Bearer test-token' for r in requests))
            self.assertTrue(all('test-token' not in str(r.url) for r in requests))
            bad=MetaPublisher(httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'user_id':'123','username':'other'}))))
            with self.assertRaises(ValueError): bad.verify_account()

if __name__=='__main__': unittest.main()
