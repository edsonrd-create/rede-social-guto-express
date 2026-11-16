# Auditoria técnica — Guto Express Social v0.2

Data: 16/11/2026. Escopo: código local, ferramentas MCP, criação editorial, montagem JPEG, persistência, validação de mídia e caminho de publicação. Não foi acessada conta real da Meta.

## Parecer

**Criação técnica local aprovada nos testes. Operação pública ainda pendente.** A primeira versão era uma fila de publicação com adaptador Meta, não um sistema completo de criação exclusiva. A versão v0.2 adiciona criação editorial baseada em modelos da Guto Express e composição real de arte com materiais revisados. A aprovação comercial de uma arte depende de fotos e logo oficiais efetivamente conferidas.

## Achados e correções

| Achado | Impacto | Correção / situação |
|---|---|---|
| Sem gerador editorial | Só armazenava legendas fornecidas | Sete temas próprios, perfil da marca e ferramenta de briefing |
| Sem montagem da arte | Não criava o post visual | Renderer JPEG 1080×1350, fonte incluída e validação dos materiais |
| Regras apenas em instruções | Podia salvar conteúdo sem marca ou com ofertas erradas | Política executável na criação e antes de publicar |
| Aprovação sem evidência da arte revisada | Podia agendar sem revisar imagem | Revisor e hash obrigatórios |
| URL não garantia imagem válida | PNG, dimensões erradas ou arquivo trocado | Validação dos bytes, formato, tamanho e integridade antes do envio |
| Conteúdo antigo saía após downtime | Post fora de contexto | Expiração após duas horas de atraso |
| Qualquer falha era marcada incerta | Dificultava diagnóstico | Estados separados por etapa, sem reenvio cego |
| Status mostrava conta como falsa sem consulta | Confundia ausência de verificação com reprovação | Status desconhecido e indicação de verificação online separada |
| Datas com precisão variável | Comparações textuais inconsistentes | Normalização UTC com microssegundos |
| Acesso a arquivos para montagem | Risco de caminhos arbitrários | Identificador restrito e pastas autorizadas, hashes e isolamento dos materiais |
| OAuth ausente | Não instalável como serviço público autenticado | Continua pendente; HTTP restrito ao loopback |
| Sem recuperação assistida e alertas | Pode exigir intervenção após falha | Continua pendente antes de produção |

## Evidências

- 29 testes de conteúdo, aprovação, agendamento, mídia, renderer, fila, concorrência e adaptador Meta.
- Teste do protocolo MCP com 11 ferramentas e fluxo: tema → rascunho → aprovação negada sem revisão → revisão → aprovação → cancelamento → montagem JPEG.
- Inspeção visual de layout usando foto e logo sintéticas claramente identificadas como testes. Sem corte ou sobreposição observados no título inspecionado.
- API Meta e downloads de mídia testados com transporte simulado; não equivalem a publicação real.
- Aviso não fatal da dependência MCP/Pydantic sobre anotação `lifespan` observado no início do teste. O handshake e as chamadas passaram; isso deve ser revisado na homologação da hospedagem.

## Restrições para a marca

Conta-alvo fixa @gutoexpress, domínio www.gutoexpress.com.br, app/site como canais de pedido, logo e fotos reais. Esta edição bloqueia preços e promoções em vez de presumir validade de ofertas antigas. Alterações de preço exigirão catálogo de ofertas com fonte, aprovação e validade.

A política não compreende toda linguagem natural, não faz OCR e não detecta automaticamente se uma foto é autêntica. A revisão humana e a implantação autenticada são parte necessária do controle. Os modelos editoriais são limitados; não há alegação de criação ilimitada ou garantia de engajamento.

## Critérios ainda necessários para produção

1. OAuth da Meta e do servidor MCP; armazenamento e renovação de tokens.
2. Hospedagem persistente, acesso restrito, backup e restauração verificados.
3. Materiais oficiais aprovados e CDN imutável sob controle da pizzaria.
4. Recuperação auditável, alertas de falha e expiração de token.
5. Instalação real no ChatGPT, conta @gutoexpress verificada e primeiro post autorizado confirmado no Instagram.
6. Operação do worker em agendador. A automação de propostas do ChatGPT existente não substitui esse serviço.

Não houve publicação em Instagram/Facebook, uso de credenciais reais, alteração de páginas, instalação remota ou implantação nesta auditoria. Facebook, Reels, carrosséis e métricas permanecem fora desta implementação.
