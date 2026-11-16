# Guto Express Social v0.3 — instalação e autorização

## Situação verificada em 16/11/2026

Código preparado para serviço remoto autenticado e executado em testes HTTP locais. Nenhum serviço público foi criado nesta etapa. A conta Railway está acessível pelo conector. O envio local de código pela CLI não foi possível: a instalação tentou baixar o binário oficial e falhou por bloqueio de rede. O GitHub CLI local não está autenticado, e o conector GitHub não oferece criação de repositório. A alternativa é criar um repositório privado pela interface oficial e enviar os arquivos pelo conector.

## Implementado nesta versão

- OAuth do plugin com SDK MCP oficial, PKCE S256, consentimento administrativo, recurso vinculado a `/mcp`, tokens de acesso e refresh rotativos.
- Registro de clientes somente com callbacks HTTPS exatos cadastrados. O administrador fornece a URL exata mostrada no ChatGPT; não há callback inventado no código.
- Senha administrativa com scrypt. Cinco tentativas globais em 15 minutos; credenciais erradas não revelam detalhes.
- Estado de autorização expirável e código de uso único. Banco de autenticação cifrado por Fernet; chave de cifragem fora do banco.
- Revogação compatível com clientes públicos. Contorna exigência indevida de `client_secret` no modelo de revogação do SDK MCP 1.29, mantendo autenticação de cliente pelo SDK e conferência de titularidade do token.
- Login oficial do Instagram, troca por token longo e renovação quando restam menos de sete dias, com token antigo há pelo menos 24 horas.
- Exige ambas permissões de leitura básica/publicação e rejeita conta diferente de @gutoexpress.
- Corrigida distinção entre `id` app-scoped e `user_id` profissional na consulta `/me`.
- Docker sem usuário root, configuração Railway, endpoint `/health` e worker supervisionado em processo único.
- Logs de acesso HTTP desativados para não registrar códigos OAuth na URL; logs HTTP de bibliotecas em nível warning. Nunca ativar logs completos de requisições de token na hospedagem/proxy.

## Preparar hospedagem

1. Criar repositório **privado** exclusivo e copiar o conteúdo de `guto-social` para a raiz. Não incluir tokens, `.env` real, banco ou `deployment-secrets.env`.
2. Criar serviço Railway a partir desse repositório, um único replica, Dockerfile da raiz. Montar volume em `/data`, garantir escrita pelo UID 10001. Não compartilhar o volume com serviços sem relação com o plugin.
3. Gerar um domínio HTTPS e definir `PUBLIC_BASE_URL` com sua origem exata, sem barra final.
4. Executar `python setup_secrets.py` em ambiente privado. O arquivo gerado tem permissão 0600 e não é exibido. Subir somente `TOKEN_ENCRYPTION_KEY` e `OWNER_PASSWORD_HASH` como segredos do serviço. Guardar `OWNER_LOGIN_PASSWORD` em gerenciador de senhas; não enviar pelo chat nem adicionar ao ambiente do servidor.
5. Definir `REMOTE_MODE=true`, `DATABASE_PATH=/data/guto-social.sqlite3`, `ASSETS_ROOT=/data/reviewed-assets`, `ARTIFACTS_ROOT=/data/generated-posts`, `LIVE_PUBLISH=false`.
6. Definir `MCP_ALLOWED_REDIRECT_URIS` com as URLs exatas mostradas na configuração OAuth do plugin no ChatGPT, separadas por vírgula. As URLs de teste dos arquivos de QA não servem para produção.
7. Selecionar no painel Meta uma versão suportada e definir `META_GRAPH_VERSION`. Não presumir a versão usada nos testes como escolhida para sua conta.

O processo não inicia sem configurações de autenticação corretas. O serviço de saúde só é bem-sucedido após validar configurações básicas. Verifique o deploy Railway em estado terminal SUCCESS; fila continua pausada.

## Autorizar a Meta

1. Criar/configurar o app próprio no Meta for Developers e adicionar Instagram Login. Para conta própria/administrada, confirmar a configuração de Standard Access e papel da conta no painel, conforme requisitos da Meta.
2. Obter **Instagram App ID e Instagram App Secret** na seção Instagram Login; não confundir com outro ID do painel. Configurar `META_APP_ID` e `META_APP_SECRET` diretamente nos segredos da hospedagem.
3. Cadastrar o callback exato `PUBLIC_BASE_URL/meta/callback` e a política de privacidade `PUBLIC_BASE_URL/privacy`, após revisar esse texto com o responsável pela operação.
4. Abrir `PUBLIC_BASE_URL/setup`; usar a senha administrativa própria da integração. Essa tela não pede senha do Instagram.
5. O sistema redireciona ao site oficial Instagram/Meta, onde o proprietário autentica e autoriza as permissões. Cookies seguros e state vinculam o retorno ao navegador que iniciou a autorização.
6. A conta autorizada precisa ser @gutoexpress; o token cifrado fica no volume persistente. O worker lê esse token sem colocá-lo nas respostas do plugin.

A renovação acontece no uso das credenciais. Se a fila permanecer pausada por mais que a validade do token, será necessária nova autorização. Não há renovação incondicional em segundo plano nem aviso automático de expiração nesta edição.

## Conectar ao ChatGPT

Adicionar a URL HTTPS `/mcp` como plugin próprio nas opções disponíveis da conta. Escolher DCR, suportado por este servidor. A interface e disponibilidade dependem do plano/workspace e ainda precisam ser conferidas no ambiente real. Não anunciar compatibilidade de conta antes dessa verificação.

O login pede a senha administrativa da integração e mostra consentimento para gerenciar conteúdo da Guto Express. A autorização do plugin é diferente da autorização do Instagram. Uma vincula o ChatGPT ao servidor; a outra vincula o servidor à conta Meta.

## Antes de ativar publicação

Configurar CDN/objetos imutáveis com os JPEGs aprovados, materiais oficiais, backup/restauração, monitoramento e acesso administrativo. Validar volume, healthcheck, proteção sem token e OAuth no domínio real. Revisar um primeiro post e verificar sua publicação na conta real. Somente depois ativar `LIVE_PUBLISH=true` e retomar a fila.

Testes locais cobrem autenticação, mas não substituem teste do Docker, infraestrutura, TLS, CDN e conta real. Não foi realizado build de imagem ou deploy nesta etapa. A proteção contra abuso deve incluir limites de requisição/tamanho no proxy antes de exposição pública. O banco limita clientes a 20 e autorizações pendentes a 100; isso não é proteção DDoS completa.

## Evidência de testes

38 testes de domínio/adaptadores passaram. Fluxo MCP stdio com 11 ferramentas passou. Fluxo HTTP real com SDK passou: discovery → DCR → consentimento → bloqueio CSRF → bloqueio PKCE incorreto → token válido → MCP protegido → rejeição de replay → revogação → bloqueio após revogação. Chamadas da Meta foram simuladas, incluindo permissões, conta errada, state repetido e refresh.

Há avisos não fatais de dependências MCP/Pydantic e de depreciação do TestClient HTTPX. Reavaliar as versões em homologação; não foram ocultados no teste.

## Documentação oficial

- https://developers.openai.com/plugins/build/auth
- https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login
- https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/get-started

### Inicialização bloqueada para vinculação

`MCP_ALLOWED_REDIRECT_URIS` pode iniciar vazio: o servidor fica saudável, mas rejeita todos os registros de clientes. Isso permite obter um domínio e informar a URL `/mcp` ao ChatGPT antes de copiar o callback exato apresentado pela interface. Não colocar callbacks genéricos ou de QA em produção.

### Volume Railway

Railway monta volumes como root. O entrypoint inicia somente a criação/atribuição de `/data/app` ao UID/GID 10001 e então descarta grupos e privilégios antes de importar o servidor. O processo da aplicação roda como UID 10001. Não há chown recursivo nem alterações em volumes de outros serviços. Os caminhos desta instalação usam `/data/app`.
