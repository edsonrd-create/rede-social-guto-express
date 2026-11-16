"""Local MCP adapter. Remote production requires authenticated deployment."""
import os
import re
import uuid
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from core import Queue, MetaPublisher
from brand import BRAND, prepare_post
from render_post import render

queue=Queue(os.getenv('DATABASE_PATH','guto-social.sqlite3'))
remote_options={}
if os.getenv('REMOTE_MODE')=='true':
    from owner_auth import OwnerOAuth, Store
    from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
    from mcp.server.transport_security import TransportSecuritySettings
    from urllib.parse import urlsplit
    base=os.environ['PUBLIC_BASE_URL']
    store=Store(queue,os.environ['TOKEN_ENCRYPTION_KEY'])
    owner=OwnerOAuth(store,base,[s.strip() for s in os.getenv('MCP_ALLOWED_REDIRECT_URIS','').split(',') if s.strip()],os.environ['OWNER_PASSWORD_HASH'])
    remote_options={'auth_server_provider':owner,'stateless_http':True,
        'auth':AuthSettings(issuer_url=base,resource_server_url=base+'/mcp',required_scopes=['guto:social'],
            client_registration_options=ClientRegistrationOptions(enabled=True,valid_scopes=['guto:social'],default_scopes=['guto:social']),
            revocation_options=RevocationOptions(enabled=True)),
        'transport_security':TransportSecuritySettings(enable_dns_rebinding_protection=True,
            allowed_hosts=[urlsplit(base).netloc],allowed_origins=[base])}
mcp=FastMCP('Guto Express Social',host='127.0.0.1',port=8765,**remote_options,
    instructions='Gerencie conteúdo do @gutoexpress. Use fotos reais e logo oficial. Não invente preços, ofertas ou depoimentos. Prepare rascunhos antes da aprovação. Não publique sem autorização.')
read=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False)
write=ToolAnnotations(readOnlyHint=False,destructiveHint=False,openWorldHint=False)

@mcp.tool(annotations=read)
def status_integracao() -> dict:
    """Consulte fila, pausa e configuração, sem revelar segredos."""
    result=queue.status()
    if os.getenv('REMOTE_MODE')=='true':
        result['meta_configured']=all(os.getenv(k) for k in ['META_APP_ID','META_APP_SECRET','META_GRAPH_VERSION'])
        result['meta_authorized']=store.get('meta','gutoexpress') is not None
    else:
        result['meta_configured']=all(os.getenv(k) for k in ['META_ACCESS_TOKEN','META_GRAPH_VERSION','INSTAGRAM_ACCOUNT_ID'])
        result['meta_authorized']=result['meta_configured']
    result['account_verified']=None
    result['account_verification_note']='Não verificada nesta consulta; use verificar_conta_meta.'
    return result

@mcp.tool(annotations=read)
def listar_posts() -> list[dict]:
    """Liste rascunhos, agenda e tentativas de publicação."""
    return queue.list()

@mcp.tool(annotations=write)
def criar_rascunho(legenda:str, imagem_url:str, descricao_imagem:str) -> dict:
    """Salve legenda e URL pública JPEG da arte aprovada. Não publica."""
    return queue.create(legenda,imagem_url,descricao_imagem)

@mcp.tool(annotations=read)
def regras_da_marca() -> dict:
    """Consulte identidade e restrições exclusivas da Guto Express."""
    return BRAND

@mcp.tool(annotations=read)
def preparar_conteudo(data_iso:str, temas_recentes:list[str] | None=None) -> dict:
    """Prepare tema, título e legenda próprios para a Guto Express; arte exige fotos e logo reais."""
    return prepare_post(data_iso,temas_recentes)

@mcp.tool(annotations=write)
def montar_arte(manifesto_id:str) -> dict:
    """Monte JPEG 1080x1350 a partir de manifesto local revisado. Não publica nem hospeda a mídia."""
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',manifesto_id):
        raise ValueError('Identificador de manifesto inválido.')
    if not os.getenv('ASSETS_ROOT') or not os.getenv('ARTIFACTS_ROOT'):
        raise ValueError('Configure os diretórios de materiais e saída no servidor.')
    root=Path(os.environ['ASSETS_ROOT']).resolve()
    manifest=root/(manifesto_id+'.json')
    if not manifest.resolve().is_relative_to(root):
        raise ValueError('Manifesto fora do diretório autorizado.')
    destination=Path(os.environ['ARTIFACTS_ROOT']).resolve()
    destination.mkdir(parents=True,exist_ok=True)
    output=destination/('guto-'+uuid.uuid4().hex+'.jpg')
    report=render(manifest,output)
    return {'file':str(output),'report':report,'state':'needs_visual_review_and_hosting'}

@mcp.tool(annotations=write)
def registrar_revisao_visual(post_id:int, revisor:str, imagem_sha256:str) -> dict:
    """Registre conferência humana da arte e hash dos bytes revisados. Não analisa autenticidade automaticamente."""
    return queue.review(post_id,revisor,imagem_sha256)

@mcp.tool(annotations=write)
def aprovar_e_agendar(post_id:int, horario_iso:str) -> dict:
    """Aprove conteúdo revisado e agende horário ISO com fuso, por exemplo -03:00."""
    return queue.approve(post_id,horario_iso)

@mcp.tool(annotations=write)
def pausar_publicacoes(pausado:bool=True) -> dict:
    """Pause ou retome a fila. Retomar permite ao worker publicar posts aprovados vencidos."""
    return queue.pause(pausado)

@mcp.tool(annotations=write)
def cancelar_post(post_id:int) -> dict:
    """Cancele um rascunho ou agendamento ainda não iniciado."""
    return queue.cancel(post_id)

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,openWorldHint=True))
def verificar_conta_meta() -> dict:
    """Verifique online se o token corresponde a @gutoexpress. Não publica."""
    return MetaPublisher().verify_account()

if __name__=='__main__':
    # stdio is private/local; HTTP is loopback only, never an unauthenticated public server.
    mcp.run(transport=os.getenv('MCP_TRANSPORT','stdio'))
