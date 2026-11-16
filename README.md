# Guto Express Social v0.2

Plugin próprio para criação editorial, montagem de arte e fila Instagram de **@gutoexpress**, exclusivo por configuração à **Pizzaria Guto Express**. Validação técnica local em 16/11/2026. **Ainda não homologado para operação pública, nem conectado ao ChatGPT/Meta reais.**

## Entrega atual

- Perfil fixo: Guto Express, Colombo/PR, www.gutoexpress.com.br.
- Sete modelos de conteúdo para engajamento, alternados conforme temas recentes informados ao plugin. Sem promessa de resultado ou variedade ilimitada.
- Montagem JPEG 1080×1350 com fotos reais e logo oficial fornecidas e revisadas. Não gera fotos de pizzaria com IA, não substitui logo e não inventa bastidores.
- Política textual de marca: rejeita ausência de identificação Guto Express, menções a outras contas, links externos, WhatsApp, alegações selecionadas e ofertas/preços. Revisão humana ainda obrigatória, sem OCR ou reconhecimento automático de autenticidade.
- Fila SQLite com auditoria, aprovação, cancelamento, pausa e proteção contra tentativa duplicada.
- Revisão visual exige nome do revisor e SHA-256 do JPEG. Verificação online antes do envio compara os bytes revisados, resolução e formato.
- Adaptador Meta com Instagram Login, criação de container, consulta e publicação; testado somente com Meta simulada.
- Worker executável por agendador: uma publicação por janela de 24 horas, atraso máximo de duas horas.

## Ferramentas MCP (11)

`status_integracao`, `listar_posts`, `regras_da_marca`, `preparar_conteudo`, `montar_arte`, `criar_rascunho`, `registrar_revisao_visual`, `aprovar_e_agendar`, `pausar_publicacoes`, `cancelar_post`, `verificar_conta_meta`.

## Instalação e testes locais

Python 3.11+; testado com 3.12.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
python tests/check_mcp.py
python server.py
```

O servidor padrão usa stdio privado. Para HTTP apenas no mesmo computador:

```bash
MCP_TRANSPORT=streamable-http python server.py
```

Endpoint: `http://127.0.0.1:8765/mcp`. Não expor na internet sem autenticação. Esse endereço local não instala o plugin no ChatGPT em nuvem. Não há OAuth remoto implementado.

As variáveis de `.env.example` devem ser injetadas no ambiente/gerenciador de segredos; não são carregadas automaticamente. Não envie tokens no chat. `LIVE_PUBLISH` começa desativado e a fila começa pausada.

## Materiais e montagem

Provisionar arquivos reais e um manifesto em `ASSETS_ROOT`. O plugin recebe um identificador simples, como `campanha01`, que aponta para `campanha01.json` nessa pasta. Saídas vão a `ARTIFACTS_ROOT`, com nome único. O usuário responsável precisa revisar os materiais; um campo `reviewed` não autentica sua origem sozinho.

```json
{
  "brand": "gutoexpress",
  "reviewer": "Responsável que conferiu os materiais",
  "caption": "Qual sabor tem lugar no seu pedido da Guto Express? 🍕",
  "headline": "Seu sabor favorito",
  "photo": {"file": "pizza-real.jpg", "reviewed": true, "sha256": "HASH_REAL_DA_FOTO"},
  "logo": {"file": "logo-oficial.png", "reviewed": true, "sha256": "HASH_REAL_DA_LOGO"}
}
```

Substituir os marcadores por hashes reais obtidos com `sha256sum arquivo`. Foto: lado menor >= 800 px. Logo: lado menor >= 200 px. A arte mantém proporções e inclui site oficial. A fonte DejaVu e licença estão incluídas em `assets`.

CLI alternativa:

```bash
python render_post.py /caminho/campanha01.json /caminho/post.jpg
```

Produz JPEG e JSON com hashes dos materiais e da saída. Revisar o JPEG final. Hospedá-lo em objeto imutável sob domínio controlado pela pizzaria e permitido em `MEDIA_ALLOWED_HOSTS`. A ferramenta de montagem não hospeda arquivos automaticamente.

## Fluxo completo

1. Preparar tema e legenda; selecionar foto real e logo oficial.
2. Montar arte; conferir imagem e legenda.
3. Hospedar JPEG imutável e salvar rascunho com legenda, URL e descrição acessível.
4. Registrar revisão visual com revisor e hash do JPEG.
5. Aprovar/agendar data ISO com fuso, por exemplo `2026-11-20T18:00:00-03:00`.
6. Após implantação autenticada e conta verificada, ativar envio real e retomar a fila.
7. Agendador externo executa `python worker.py` a cada minuto. O worker envia apenas itens aprovados vencidos dentro da janela permitida.

`preparar_conteudo` não consulta histórico por conta própria: o chamador fornece temas recentes. Modelos são determinísticos; adaptação criativa adicional pode ser feita pelo ChatGPT. Não há uso da OpenAI API no backend.

## Estados e falhas

- `draft`: rascunho; `approved`: revisado e agendado; `canceled`: cancelado.
- `expired`: passou mais de duas horas do horário; não publica conteúdo antigo automaticamente.
- `publishing`: tentativa em andamento; se o processo parar, não reenvia automaticamente.
- `blocked`: conta/conteúdo/mídia falhou antes da criação do container.
- `failed`: falha na preparação do container, antes de solicitar publicação.
- `unknown`: publicação solicitada sem confirmação suficiente; conferir na Meta antes de qualquer reenvio.
- `published`: resposta da Meta com media ID registrada.

Não existe interface de reconciliação nesta edição. Estados de falha exigem intervenção administrativa. Pausar impede novas tentativas, sem desfazer requisições já enviadas. Não há garantia absoluta de exactly-once por rede; o bloqueio de tentativa incerta evita reenvio cego.

## Integridade e infraestrutura

A validação da mídia exige HTTPS, host autorizado, IP público, sem redirecionamento, até 10 MiB, JPEG 1080×1350 e hash idêntico ao revisado. O token Meta nunca deve seguir para o host da imagem.

A checagem DNS não substitui egress isolado contra DNS rebinding. Só permitir domínios CDN controlados pela pizzaria. O objeto deve ser imutável: a Meta busca a imagem depois da checagem e um servidor mutável pode fornecer bytes diferentes posteriormente.

SQLite exige volume persistente e servidor/worker no mesmo host. Não usar réplicas com discos independentes. Migrar a PostgreSQL para múltiplos hosts. Credenciais ficam fora do banco. Autenticação e identidade do operador devem ser implementadas antes de expor o serviço.

## Validação e limitações

29 testes passaram. O teste de protocolo MCP passou com 11 ferramentas, preparação de conteúdo, rascunho, bloqueio sem revisão, revisão, aprovação, cancelamento e montagem real de JPEG. As imagens de QA são sintéticas, claramente identificadas e não fazem parte de campanhas comerciais. Houve inspeção visual do layout de teste.

Teste do adaptador Meta e downloads usa transporte simulado. Nenhuma conta real ou publicação real foi validada. Aviso não fatal MCP/Pydantic sobre `lifespan` permanece para revisar na homologação.

Pendências de produção: OAuth Meta/MCP, hospedagem persistente, CDN, materiais oficiais revisados, backup/restauração, alertas, recuperação de falha, instalação no ChatGPT e primeiro post autorizado confirmado. Facebook, Reels, carrosséis, métricas e catálogo de preços/ofertas não foram implementados.

Ver `AUDITORIA_v0_2.md` para achados, correções e critérios de homologação. A rotina diária de propostas criada no ChatGPT continua separada da publicação: não substitui o worker nem o acesso autorizado à Meta.

## Fontes oficiais consultadas

- https://developers.openai.com/plugins/build/mcp-server
- https://developers.openai.com/plugins/deploy/connect-chatgpt
- https://developers.facebook.com/documentation/instagram-platform/content-publishing

## Versão v0.3 — autenticação e pacote de hospedagem

Esta versão adiciona OAuth MCP, login oficial Instagram com tokens cifrados/renovação e configuração Docker/Railway. Consulte **DEPLOY_v0_3.md**, que substitui as indicações anteriores de OAuth ainda não implementado. Nenhum serviço foi implantado; o funcionamento no ChatGPT, domínio público e conta real ainda não foi homologado. São 38 testes de domínio/adaptadores, um teste MCP stdio e um teste HTTP OAuth/PKCE. A quantidade de ferramentas permanece 11.
