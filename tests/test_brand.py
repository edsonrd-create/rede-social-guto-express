import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
import httpx
from PIL import Image, ImageDraw
from brand import validate_caption, prepare_post
from render_post import render, digest
from core import Queue, MetaPublisher
from test_core import FakeMeta

class BrandTests(unittest.TestCase):
    def test_models(self):
        seen=[]
        for _ in range(7):
            p=prepare_post('2026-11-16',seen)
            self.assertEqual(p['account'],'@gutoexpress')
            self.assertTrue(validate_caption(p['caption']))
            self.assertNotIn(p['theme'],seen)
            seen.append(p['theme'])
        self.assertEqual(len(set(seen)),7)
    def test_reject_other_brand(self):
        with self.assertRaises(ValueError): validate_caption('Pizza de outra loja')
    def test_forbidden(self):
        for value in ['Guto Express por R$ 39,99','Guto Express promoção','Guto Express 10% OFF',
                      'Guto Express no WhatsApp','Guto Express forno a lenha','Guto Express @outraloja',
                      'Guto Express https://outro.site']:
            with self.subTest(value=value),self.assertRaises(ValueError): validate_caption(value)
    def test_allowed_site(self):
        self.assertTrue(validate_caption('Peça na Guto Express: www.gutoexpress.com.br'))

class RenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        # Synthetic fixtures are strictly for automated layout tests, never actual brand assets.
        p=Image.new('RGB',(1200,900),'#bc946c'); d=ImageDraw.Draw(p)
        d.ellipse((250,100,950,800),fill='#d8a243'); d.text((450,430),'TESTE - FOTO SINTETICA',fill='black')
        p.save(self.root/'photo.jpg')
        logo=Image.new('RGBA',(300,300),'#c82030'); ImageDraw.Draw(logo).text((80,130),'TESTE',fill='white');logo.save(self.root/'logo.png')
        self.data={'brand':'gutoexpress','reviewer':'QA fixture',
          'caption':'Calabresa ou frango? A Guto Express quer saber!','headline':'Qual ganha hoje?',
          'photo':{'file':'photo.jpg','reviewed':True,'sha256':digest(self.root/'photo.jpg')},
          'logo':{'file':'logo.png','reviewed':True,'sha256':digest(self.root/'logo.png')}}
    def tearDown(self): self.tmp.cleanup()
    def run_render(self):
        manifest=self.root/'manifest.json';manifest.write_text(json.dumps(self.data))
        return render(manifest,self.root/'post.jpg')
    def test_real_output_jpeg(self):
        report=self.run_render()
        with Image.open(self.root/'post.jpg') as p:
            self.assertEqual(p.size,(1080,1350));self.assertEqual(p.format,'JPEG')
        self.assertEqual(report['sha256'],digest(self.root/'post.jpg'))
        self.assertTrue(report['visual_review_required'])
    def test_changed_asset(self):
        self.data['photo']['sha256']='a'*64
        with self.assertRaises(ValueError): self.run_render()
    def test_unreviewed_logo(self):
        self.data['logo']['reviewed']=False
        with self.assertRaises(ValueError): self.run_render()
    def test_wrong_brand(self):
        self.data['brand']='other'
        with self.assertRaises(ValueError): self.run_render()
    def test_low_resolution(self):
        Image.new('RGB',(40,40)).save(self.root/'photo.jpg')
        self.data['photo']['sha256']=digest(self.root/'photo.jpg')
        with self.assertRaises(ValueError): self.run_render()
    def test_headline_restrictions(self):
        self.data['headline']='Promoção grátis'
        with self.assertRaises(ValueError): self.run_render()

class QueueReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.env=patch.dict(os.environ,{'MEDIA_ALLOWED_HOSTS':'cdn.gutoexpress.com.br','LIVE_PUBLISH':'true'});self.env.start()
        self.q=Queue(self.tmp.name+'/queue.db')
        self.id=self.q.create('Qual seu sabor na Guto Express?','https://cdn.gutoexpress.com.br/photo.jpg','Pizza real')['id']
    def tearDown(self): self.env.stop(); self.tmp.cleanup()
    def test_approval_without_review_blocked(self):
        with self.assertRaises(ValueError): self.q.approve(self.id,'2099-01-01T18:00:00-03:00')
    def test_review_hash_validation(self):
        with self.assertRaises(ValueError): self.q.review(self.id,'Edson','abc')
        with self.assertRaises(ValueError): self.q.review(self.id,'','a'*64)
    def test_old_posts_expire(self):
        self.q.review(self.id,'Edson','a'*64)
        self.q.approve(self.id,'2099-01-01T18:00:00-03:00')
        with self.q.db() as c:
            c.execute('UPDATE posts SET scheduled_at=?',((datetime.now(timezone.utc)-timedelta(hours=3)).isoformat(),))
        self.q.pause(False)
        self.assertEqual(self.q.run_due(FakeMeta())['processed'],0)
        self.assertEqual(self.q.list()[0]['state'],'expired')
    def test_media_failure_no_publish(self):
        self.q.review(self.id,'Edson','a'*64);self.q.approve(self.id,'2099-01-01T18:00:00-03:00')
        with self.q.db() as c:
            c.execute('UPDATE posts SET scheduled_at=?',((datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(),))
        self.q.pause(False); meta=FakeMeta()
        def fail(post): raise ValueError('changed')
        meta.validate_media=fail
        self.assertEqual(self.q.run_due(meta)['results'][0]['state'],'blocked')
        self.assertEqual(meta.calls,0)

class RemoteMediaTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'META_ACCESS_TOKEN':'secret','META_GRAPH_VERSION':'v27.0','INSTAGRAM_ACCOUNT_ID':'123','MEDIA_ALLOWED_HOSTS':'cdn.gutoexpress.com.br'});self.env.start()
        b=io.BytesIO();Image.new('RGB',(1080,1350)).save(b,'JPEG');self.raw=b.getvalue()
        self.post={'image_url':'https://cdn.gutoexpress.com.br/a.jpg','reviewed_sha256':hashlib.sha256(self.raw).hexdigest()}
    def tearDown(self): self.env.stop()
    def publisher(self,raw=None,status=200):
        def handle(req):
            self.assertNotIn('authorization',req.headers)
            return httpx.Response(status,content=self.raw if raw is None else raw)
        return MetaPublisher(httpx.Client(transport=httpx.MockTransport(handle)))
    @patch('socket.getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))])
    def test_exact_reviewed_jpeg(self,_): self.publisher().validate_media(self.post)
    @patch('socket.getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))])
    def test_changed_bytes(self,_):
        with self.assertRaises(ValueError): self.publisher(b'changed').validate_media(self.post)
    @patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))])
    def test_private_ip(self,_):
        with self.assertRaises(ValueError): self.publisher().validate_media(self.post)
    @patch('socket.getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))])
    def test_wrong_dimensions(self,_):
        b=io.BytesIO();Image.new('RGB',(20,20)).save(b,'JPEG');raw=b.getvalue()
        self.post['reviewed_sha256']=hashlib.sha256(raw).hexdigest()
        with self.assertRaises(ValueError): self.publisher(raw).validate_media(self.post)
    @patch('socket.getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))])
    def test_redirect_blocked(self,_):
        with self.assertRaises((ValueError,httpx.HTTPStatusError)): self.publisher(status=302).validate_media(self.post)
