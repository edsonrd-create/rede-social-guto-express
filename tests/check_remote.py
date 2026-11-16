"""HTTP OAuth/PKCE end-to-end through actual SDK handlers. Test secrets only."""
import base64
import hashlib
import json
import os
import re
import tempfile
from urllib.parse import urlsplit,parse_qs
from cryptography.fernet import Fernet
from starlette.testclient import TestClient
from owner_auth import password_hash

with tempfile.TemporaryDirectory() as tmp:
    base='https://social.example.com';redirect='https://chatgpt.com/connector/oauth/test'
    os.environ.update({'REMOTE_MODE':'true','DATABASE_PATH':tmp+'/remote.db','PUBLIC_BASE_URL':base,
        'TOKEN_ENCRYPTION_KEY':Fernet.generate_key().decode(),'OWNER_PASSWORD_HASH':password_hash('qa-password'),
        'MCP_ALLOWED_REDIRECT_URIS':redirect,'LIVE_PUBLISH':'false'})
    from remote import app
    with TestClient(app,base_url=base,follow_redirects=False) as client:
        assert client.get('/health').status_code==200
        assert client.post('/mcp',json={}).status_code==401
        metadata=client.get('/.well-known/oauth-authorization-server').json()
        assert 'S256' in metadata['code_challenge_methods_supported']
        registration=client.post('/register',json={'client_name':'QA ChatGPT','redirect_uris':[redirect],
            'token_endpoint_auth_method':'none','grant_types':['authorization_code','refresh_token'],'response_types':['code'],'scope':'guto:social'})
        assert registration.status_code==201,registration.text
        client_id=registration.json()['client_id']
        verifier='x'*64;challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        auth=client.get('/authorize',params={'client_id':client_id,'redirect_uri':redirect,'response_type':'code',
            'code_challenge':challenge,'code_challenge_method':'S256','scope':'guto:social','state':'qa-state','resource':base+'/mcp'})
        assert auth.status_code in (302,303),auth.text
        flow_url=auth.headers['location'];form=client.get(flow_url)
        nonce=re.search(r'name="nonce" value="([^"]+)"',form.text)[1]
        flow=parse_qs(urlsplit(flow_url).query)['flow'][0]
        csrf=client.post('/consent',data={'nonce':nonce,'flow':flow,'password':'qa-password'},headers={'origin':'https://evil.example'})
        assert csrf.status_code==400
        approved=client.post('/consent',data={'nonce':nonce,'flow':flow,'password':'qa-password'},headers={'origin':base})
        assert approved.status_code==303,approved.text
        params=parse_qs(urlsplit(approved.headers['location']).query)
        assert params['state']==['qa-state'];code=params['code'][0]
        wrong=client.post('/token',data={'grant_type':'authorization_code','client_id':client_id,'redirect_uri':redirect,
            'code':code,'code_verifier':'wrong','resource':base+'/mcp'})
        assert wrong.status_code==400
        token=client.post('/token',data={'grant_type':'authorization_code','client_id':client_id,'redirect_uri':redirect,
            'code':code,'code_verifier':verifier,'resource':base+'/mcp'})
        assert token.status_code==200,token.text
        access=token.json()['access_token']
        replay=client.post('/token',data={'grant_type':'authorization_code','client_id':client_id,'redirect_uri':redirect,
            'code':code,'code_verifier':verifier})
        assert replay.status_code==400
        headers={'Authorization':'Bearer '+access,'Accept':'application/json, text/event-stream'}
        response=client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':1,'method':'initialize','params':{
            'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'QA','version':'1'}}})
        assert response.status_code==200,response.text
        revoke=client.post('/revoke',data={'token':access,'client_id':client_id})
        assert revoke.status_code==200,revoke.text
        assert client.post('/mcp',headers=headers,json={}).status_code==401
        print('HTTP OAuth E2E OK: discovery, registration, consent, CSRF, PKCE, token, protected MCP, replay rejection, revocation.')
