"""One web process, one supervised worker loop; persistent SQLite on a single host."""
import asyncio
import logging
import os
import uvicorn

async def work():
    from worker import main
    while True:
        try:
            await asyncio.to_thread(main)
        except Exception:
            logging.error('Worker falhou; confira a configuração e a fila.')
        await asyncio.sleep(60)

async def main():
    import remote
    task=asyncio.create_task(work())
    config=uvicorn.Config(remote.app,host='0.0.0.0',port=int(os.getenv('PORT','8080')),
                          access_log=False,log_level='warning',proxy_headers=False)
    try:
        await uvicorn.Server(config).serve()
    finally:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass

if __name__=='__main__': asyncio.run(main())
