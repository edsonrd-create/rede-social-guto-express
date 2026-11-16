"""Execute once from a scheduler every minute. Does not generate content."""
import json
import os
from core import Queue, MetaPublisher

def main():
    queue=Queue(os.getenv('DATABASE_PATH','guto-social.sqlite3'))
    if os.getenv('LIVE_PUBLISH')!='true' or queue.status()['paused']:
        print(json.dumps(queue.status()))
        return
    try:
        result=queue.run_due(MetaPublisher())
    except Exception:
        result={'error':'Configuração Meta ausente ou inválida; nenhum envio iniciado.'}
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    main()
