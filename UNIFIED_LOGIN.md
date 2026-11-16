# Login unificado Guto Express Social

App: 4841713669443386. Configuração: 2135916773978596. Portfólio esperado: 1375878014056924. Nenhum desses identificadores é segredo.

META_LOGIN_MODE=unified seleciona Facebook Login para Empresas com config_id. O callback troca o código em graph.facebook.com, inspeciona validade, app e permissões com debug_token, confirma client_business_id e encontra exclusivamente gutoexpress em /me/assigned_instagram_accounts, com paginação limitada e sem seguir URLs externas.

Token e metadados ficam cifrados no volume. Esta configuração aceita somente token com expiração futura de até 61 dias, rejeita token sem expiração e exige instagram_basic e instagram_content_publish. Sem business_management, não há promessa de refresh automático SUAT: uma nova autorização é necessária antes de vencer. Não utiliza graph.instagram.com/refresh_access_token nesse modo.

O adaptador publica em graph.facebook.com usando o ID profissional da conta, não o ID do usuário de sistema. A publicação permanece desativada (LIVE_PUBLISH=false) até autorização e aprovação real da arte.

META_APP_SECRET ainda precisa ser preenchido diretamente no serviço Railway pelo proprietário. Nunca enviar por chat, GitHub ou logs. Confirmar também no painel Meta a URI de callback exata: https://guto-social-plugin-production.up.railway.app/meta/callback . A autorização da conta somente deve ocorrer após configurar isso e o segredo.

Validação local: 45 testes e fluxos MCP stdio/OAuth HTTP aprovados. Testes Meta são simulados. Isso não confirma autorização ou publicação real. O modo legado continua disponível apenas quando META_LOGIN_MODE não é unified.
