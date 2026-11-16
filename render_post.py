"""Create branded JPEG from explicitly reviewed real photo and official logo.
No generated or downloaded substitute assets. Run via CLI, not remote arbitrary paths.
"""
import argparse
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
from brand import validate_caption

FONT=Path(__file__).parent/'assets'/'DejaVuSans-Bold.ttf'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def render(manifest_path, output):
    manifest_path=Path(manifest_path).resolve()
    data=json.loads(manifest_path.read_text())
    if data.get('brand')!='gutoexpress':
        raise ValueError('Manifesto não pertence à Guto Express.')
    if not data.get('reviewer','').strip():
        raise ValueError('Identifique o responsável pela revisão dos materiais.')
    inputs={}
    for kind in ['photo','logo']:
        item=data[kind]
        p=(manifest_path.parent/item['file']).resolve()
        if not p.is_relative_to(manifest_path.parent):
            raise ValueError('Arquivo fora da pasta de materiais.')
        if item.get('reviewed') is not True or digest(p)!=item.get('sha256'):
            raise ValueError('Material não revisado ou alterado após revisão.')
        inputs[kind]=p
    validate_caption(data['caption'])
    headline=data['headline'].strip()
    if not headline or len(headline)>65 or '\n' in headline:
        raise ValueError('Título precisa ter de 1 a 65 caracteres em uma linha.')
    # Apply the same editorial restrictions to visible copy.
    validate_caption('Guto Express '+headline)
    with Image.open(inputs['photo']) as p:
        photo=ImageOps.exif_transpose(p).convert('RGB')
        if min(photo.size)<800:
            raise ValueError('Foto insuficiente: mínimo de 800 pixels no lado menor.')
    with Image.open(inputs['logo']) as l:
        logo=ImageOps.exif_transpose(l).convert('RGBA')
        if min(logo.size)<200:
            raise ValueError('Logo insuficiente: mínimo de 200 pixels no lado menor.')
    canvas=Image.new('RGB',(1080,1350),'#151515')
    # Contain preserves pizza and logo geometry without cropping or stretching.
    photo=ImageOps.contain(photo,(1080,880))
    canvas.paste(photo,((1080-photo.width)//2,160+(880-photo.height)//2))
    logo=ImageOps.contain(logo,(132,132))
    canvas.paste(logo,(42,14),logo)
    draw=ImageDraw.Draw(canvas)
    draw.text((200,58),'GUTO EXPRESS',font=ImageFont.truetype(str(FONT),42),fill='white')
    draw.rectangle((0,1040,1080,1350),fill='#a91724')
    words=headline.split(); lines=[]; line=''
    font=ImageFont.truetype(str(FONT),56)
    for word in words:
        attempt=(line+' '+word).strip()
        if draw.textlength(attempt,font=font)>984:
            if not line:
                raise ValueError('Palavra longa demais para o layout.')
            lines.append(line); line=word
        else:
            line=attempt
    if line: lines.append(line)
    if len(lines)>2 or any(draw.textlength(x,font=font)>984 for x in lines):
        raise ValueError('Título não cabe com legibilidade.')
    for i,text in enumerate(lines): draw.text((48,1072+i*70),text,font=font,fill='white')
    draw.text((48,1260),'www.gutoexpress.com.br',font=ImageFont.truetype(str(FONT),34),fill='white')
    output=Path(output)
    if output.suffix.lower() not in {'.jpg','.jpeg'}:
        raise ValueError('Saída precisa ser JPEG.')
    if output.resolve() in inputs.values() or output.resolve()==manifest_path:
        raise ValueError('Não sobrescreva materiais de origem.')
    canvas.save(output,'JPEG',quality=94,subsampling=0)
    report={'brand':'gutoexpress','reviewer':data['reviewer'],'caption':data['caption'],
            'headline':headline,'width':1080,'height':1350,'sha256':digest(output),
            'inputs':{k:digest(v) for k,v in inputs.items()},'visual_review_required':True}
    output.with_suffix('.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('manifest'); parser.add_argument('output')
    args=parser.parse_args()
    print(json.dumps(render(args.manifest,args.output),ensure_ascii=False))
