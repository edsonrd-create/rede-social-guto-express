"""Deterministic Guto-only editorial policy; does not claim AI authorship or performance."""
import re
import unicodedata

BRAND = {'name':'Pizzaria Guto Express','instagram':'gutoexpress',
         'site':'www.gutoexpress.com.br','city':'Colombo/PR',
         'format':{'width':1080,'height':1350},
         'rules':['Logo oficial','Fotos reais','Sem preço ou promoção não confirmados',
                  'Pedidos pelo app ou site','Sem alegações de forno a lenha']}


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',value.lower()) if not unicodedata.combining(c))


def validate_caption(caption):
    text=normalized(caption)
    if 'guto express' not in text and '@gutoexpress' not in text:
        raise ValueError('O conteúdo precisa identificar a Guto Express.')
    for phrase in ['whatsapp','whats app','forno a lenha','melhor de colombo','premiada','depoimento']:
        if phrase in text:
            raise ValueError('Texto contém chamada ou alegação não autorizada para a marca.')
    # This edition intentionally supports evergreen engagement only.
    if re.search(r'r\$|\b\d+[,.]\d{2}\b|\b(gratis|gratuita|promocao|desconto|cupom|off)\b|\d+\s*%',text):
        raise ValueError('Ofertas e preços exigem cadastro validado; não suportados nesta edição.')
    for handle in re.findall(r'@([\w.]+)',caption):
        if handle.lower()!='gutoexpress':
            raise ValueError('Menção a outra conta não autorizada.')
    # Avoid turning a Guto caption into advertising for arbitrary sites.
    urls=re.findall(r'(?:https?://|www\.)[^\s]+',caption)
    for url in urls:
        from urllib.parse import urlsplit
        host=urlsplit(url if '://' in url else 'https://'+url).hostname
        if host not in {'gutoexpress.com.br','www.gutoexpress.com.br'}:
            raise ValueError('Link fora do domínio oficial da Guto Express.')
    return True


THEMES = [
 ('duelo','Qual ganha hoje?','Calabresa ou frango com catupiry? 🍕 Qual você escolheria na Guto Express?', 'Fotos reais dos dois sabores lado a lado.'),
 ('preferencia','A sua combinação','Se pudesse montar sua pizza agora, quais sabores escolheria? Conta pra Guto Express! 🍕','Foto real de uma pizza de dois sabores.'),
 ('ocasiao','Hoje combina com pizza','Filme, conversa ou jogo? Qual é a sua companhia perfeita para uma pizza da Guto Express? 🍕','Foto real da pizza sobre fundo simples.'),
 ('borda','Até a última mordida','Você começa pela ponta ou pela borda? 🍕 A Guto Express quer saber!','Close real de uma borda, sem afirmar recheio não confirmado.'),
 ('compartilhar','Pizza e boa companhia','Na hora de dividir uma pizza da Guto Express, sempre tem alguém de olho na última fatia. Quem é essa pessoa na sua turma? 🍕','Foto real da pizza cortada, sem pessoas inventadas.'),
 ('sabores','Seu sabor favorito','Qual sabor tem lugar garantido no seu pedido da Guto Express? 🍕','Foto real do sabor correspondente, sem adicionar ingredientes.'),
 ('ritual','O momento da pizza','Qual é a melhor parte: abrir a caixa ou pegar a primeira fatia? 🍕 Aqui é Guto Express!','Foto real da pizza na caixa oficial.')]


def prepare_post(day, recent_themes=None):
    from datetime import date
    parsed=date.fromisoformat(day)
    recent=set(recent_themes or [])
    start=parsed.toordinal()%len(THEMES)
    ordered=THEMES[start:]+THEMES[:start]
    theme=next((t for t in ordered if t[0] not in recent),ordered[0])
    key,headline,caption,visual=theme
    validate_caption(caption)
    return {'brand':BRAND['name'],'account':'@gutoexpress','date':day,
            'theme':key,'headline':headline,'caption':caption,'visual_brief':visual,
            'format':BRAND['format'],'state':'brief_needs_real_assets',
            'requires':['Foto real revisada','Logo oficial revisada','Revisão final da arte'],
            'note':'Legenda editorial baseada em modelos próprios; sem garantia de engajamento.'}
