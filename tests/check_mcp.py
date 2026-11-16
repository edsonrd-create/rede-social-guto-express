"""Real protocol handshake through the installed MCP SDK; no Meta access."""
import asyncio
import os
import tempfile
from pathlib import Path
import json
import hashlib
from PIL import Image
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    with tempfile.TemporaryDirectory() as tmp:
        env={**os.environ,'DATABASE_PATH':tmp+'/mcp.sqlite3','LIVE_PUBLISH':'false','MEDIA_ALLOWED_HOSTS':'cdn.gutoexpress.com.br'}
        assets=Path(tmp)/'assets'; assets.mkdir()
        Image.new('RGB',(1000,1000),'orange').save(assets/'photo.jpg')
        Image.new('RGB',(300,300),'red').save(assets/'logo.png')
        manifest={'brand':'gutoexpress','reviewer':'QA synthetic fixture',
                  'caption':'Qual sabor na Guto Express?','headline':'Qual ganha hoje?'}
        for kind,file in [('photo','photo.jpg'),('logo','logo.png')]:
            manifest[kind]={'file':file,'reviewed':True,'sha256':hashlib.sha256((assets/file).read_bytes()).hexdigest()}
        (assets/'qa.json').write_text(json.dumps(manifest))
        env.update({'ASSETS_ROOT':str(assets),'ARTIFACTS_ROOT':str(Path(tmp)/'output')})
        params=StdioServerParameters(command='python',args=['server.py'],env=env)
        async with stdio_client(params) as (read,write):
            async with ClientSession(read,write) as session:
                info=await session.initialize()
                tools=await session.list_tools()
                assert len(tools.tools)==11
                result=await session.call_tool('status_integracao',{})
                assert not result.isError
                brief=await session.call_tool('preparar_conteudo',{'data_iso':'2026-11-16'})
                assert not brief.isError
                bad=await session.call_tool('criar_rascunho',{'legenda':'Outra pizzaria','imagem_url':'https://cdn.gutoexpress.com.br/a.jpg','descricao_imagem':'pizza'})
                assert bad.isError
                draft=await session.call_tool('criar_rascunho',{'legenda':'Qual sabor na Guto Express?','imagem_url':'https://cdn.gutoexpress.com.br/a.jpg','descricao_imagem':'Pizza real'})
                assert not draft.isError
                post_id=json.loads(draft.content[0].text)['id']
                denied=await session.call_tool('aprovar_e_agendar',{'post_id':post_id,'horario_iso':'2099-01-01T18:00:00-03:00'})
                assert denied.isError
                reviewed=await session.call_tool('registrar_revisao_visual',{'post_id':post_id,'revisor':'QA','imagem_sha256':'a'*64})
                assert not reviewed.isError
                approved=await session.call_tool('aprovar_e_agendar',{'post_id':post_id,'horario_iso':'2099-01-01T18:00:00-03:00'})
                assert not approved.isError
                canceled=await session.call_tool('cancelar_post',{'post_id':post_id})
                assert not canceled.isError
                rejected=await session.call_tool('montar_arte',{'manifesto_id':'../escape'})
                assert rejected.isError
                rendered=await session.call_tool('montar_arte',{'manifesto_id':'qa'})
                assert not rendered.isError
                artifact=json.loads(rendered.content[0].text)
                assert Path(artifact['file']).is_file()
                assert artifact['report']['width']==1080
                print('MCP flow: brief, draft, denied approval, review, approval, cancellation, rendering OK')
                print('MCP handshake OK; 11 tools; status_integracao OK; server:',info.serverInfo.name)
asyncio.run(main())
