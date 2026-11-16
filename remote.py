"""Authenticated remote entry point. No secrets in HTTP responses or access logs."""
import html
import hmac
import logging
import os
import secrets
from urllib.parse import urlsplit
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.transport_security import TransportSecuritySettings
from owner_auth import OwnerOAuth, Store, matches
from meta_login import InstagramLogin
from server import mcp, queue, owner, store

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
base=os.environ['PUBLIC_BASE_URL']


def login():
    return InstagramLogin(store,base,os.environ['META_APP_ID'],os.environ['META_APP_SECRET'],os.environ['META_GRAPH_VERSION'])


def page(body,status=200):
    return HTMLResponse('<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Guto Express Social</title><body><main><h1>Guto Express Social</h1>'+body+'</main></body></html>',status_code=status,
        headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff',
                 'Content-Security-Policy':"default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"})


def owner_form(action,nonce,extra=''):
    return '<form method="post" action="'+action+'"><input type="hidden" name="nonce" value="'+html.escape(nonce)+'">'+extra+'<label>Senha administrativa desta integração <input type="password" name="password" required maxlength="256" autocomplete="current-password"></label><p>Não use sua senha do Instagram aqui. O login do Instagram será feito no site oficial da Meta.</p><button type="submit">Autorizar</button></form>'


async def form(request):
    if request.headers.get('origin')!=base: raise ValueError('Origem inválida.')
    if int(request.headers.get('content-length','0'))>8192: raise ValueError('Requisição excessiva.')
    # Streaming bound, before decoding, also covers chunked requests.
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>8192: raise ValueError('Requisição excessiva.')
    from urllib.parse import parse_qs
    parsed=parse_qs(raw.decode())
    values={k:v[0] for k,v in parsed.items() if len(v)==1}
    if not values.get('nonce') or not hmac.compare_digest(values['nonce'],request.cookies.get('__Host-guto-consent','')):
        raise ValueError('Sessão inválida. Abra a tela novamente.')
    return values


@mcp.custom_route('/health',methods=['GET'])
async def health(request:Request):
    return JSONResponse({'status':'ok','service':'guto-express-social'})


@mcp.custom_route('/setup',methods=['GET'])
async def setup(request:Request):
    nonce=secrets.token_urlsafe(32)
    response=page('<p>Conecte exclusivamente o Instagram @gutoexpress. A fila começa pausada.</p>'+owner_form('/meta/start',nonce))
    response.set_cookie('__Host-guto-consent',nonce,secure=True,httponly=True,samesite='strict',max_age=600,path='/')
    return response


@mcp.custom_route('/consent',methods=['GET','POST'])
async def consent(request:Request):
    try:
        if request.method=='GET':
            flow=request.query_params.get('flow','')
            item=store.get('flow',flow)
            if not item: return page('<p>Autorização expirada.</p>',400)
            nonce=secrets.token_urlsafe(32)
            client=await owner.get_client(item['client_id'])
            body='<p>Permitir ao cliente '+html.escape(client.client_name or 'MCP')+' gerenciar rascunhos, artes e agendamentos da Guto Express? A publicação continua sujeita à revisão e aprovação.</p>'
            response=page(body+owner_form('/consent',nonce,'<input type="hidden" name="flow" value="'+html.escape(flow)+'">'))
            response.set_cookie('__Host-guto-consent',nonce,secure=True,httponly=True,samesite='strict',max_age=600,path='/')
            return response
        values=await form(request)
        return RedirectResponse(owner.finish(values['flow'],values.get('password','')),303,headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
    except Exception:
        return page('<p>Autorização recusada ou expirada. Confira os dados; após muitas tentativas aguarde 15 minutos.</p>',400)


@mcp.custom_route('/meta/start',methods=['POST'])
async def meta_start(request:Request):
    try:
        values=await form(request)
        if not store.password_allowed() or not matches(values.get('password',''),owner.owner_hash):
            return page('<p>Autenticação recusada. Após muitas tentativas aguarde 15 minutos.</p>',403)
        state,url=login().begin()
        response=RedirectResponse(url,303,headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
        response.set_cookie('__Host-guto-meta',state,secure=True,httponly=True,samesite='lax',max_age=600,path='/')
        return response
    except Exception:
        return page('<p>Confira a configuração do aplicativo Meta e tente novamente.</p>',400)


@mcp.custom_route('/meta/callback',methods=['GET'])
async def callback(request:Request):
    try:
        state=request.query_params.get('state','')
        if not state or not hmac.compare_digest(state,request.cookies.get('__Host-guto-meta','')):
            raise ValueError('Estado inválido.')
        if request.query_params.get('error') or not request.query_params.get('code'):
            store.get('meta_state',state,consume=True)
            raise ValueError('Autorização cancelada.')
        # Network I/O offloaded: other MCP requests stay responsive.
        from starlette.concurrency import run_in_threadpool
        await run_in_threadpool(login().complete,state,request.query_params['code'])
        response=page('<p>@gutoexpress conectado. Nenhum post foi publicado. A fila permanece sob aprovação.</p>')
        response.delete_cookie('__Host-guto-meta',path='/',secure=True,httponly=True,samesite='lax')
        return response
    except Exception:
        return page('<p>Não foi possível conectar @gutoexpress. Confira conta, permissões e configuração Meta.</p>',400)


@mcp.custom_route('/privacy',methods=['GET'])
async def privacy(request:Request):
    return page('<p>Integração privada da Pizzaria Guto Express para administrar suas próprias publicações. Armazena conteúdo editorial, registros de aprovação e credenciais cifradas para operar a conta autorizada. Não acessa mensagens privadas ou contatos e não comercializa esses dados.</p><p>O responsável pela pizzaria administra acesso, retenção e exclusão dos registros. Para encerrar o acesso, revogue a integração no Instagram e solicite ao administrador a remoção das credenciais e registros, inclusive em backups.</p>')


async def revoke_compatible(request:Request):
    # SDK 1.29 RevocationRequest incorrectly requires client_secret for public clients.
    # Retain SDK client authentication, then implement RFC 7009 token handling.
    from mcp.server.auth.middleware.client_auth import ClientAuthenticator
    try:
        client=await ClientAuthenticator(owner).authenticate_request(request)
        values=await request.form()
        token=str(values.get('token',''))
        if not token or len(token)>2048:
            return JSONResponse({'error':'invalid_request'},400)
        record=await owner.load_access_token(token) or await owner.load_refresh_token(client,token)
        if record and record.client_id==client.client_id:
            await owner.revoke_token(record)
        from starlette.responses import Response
        return Response(status_code=200,headers={'Cache-Control':'no-store'})
    except Exception:
        return JSONResponse({'error':'invalid_client'},401)


def create_app():
    app=mcp.streamable_http_app()
    from starlette.routing import Route
    app.routes[:]=[Route('/revoke',revoke_compatible,methods=['POST']) if getattr(route,'path',None)=='/revoke' else route for route in app.routes]
    return app

app=create_app()
