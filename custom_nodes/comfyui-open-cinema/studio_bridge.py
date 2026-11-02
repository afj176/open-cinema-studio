"""Local Studio companion lifecycle; never fail ComfyUI node loading."""
import importlib.util
import logging
import os
from pathlib import Path
import threading


def install():
    import server
    if not hasattr(server, 'PromptServer'):
        return  # importing the nodes outside ComfyUI must not start a companion
    PromptServer = server.PromptServer
    from aiohttp import web
    from comfy.cli_args import args
    root = Path(__file__).resolve().parents[2]
    launcher_file = root / 'app/launcher.py'
    state = {'state': 'starting', 'message': 'Starting your film workspace…',
             'port': int(os.environ.get('OPEN_CINEMA_PORT', '8420'))}
    lock = threading.Lock()
    comfy_url = f'http://127.0.0.1:{args.port}'

    def start():
        if not lock.acquire(blocking=False):
            return
        try:
            state.update(state='starting', message='Waiting for ComfyUI…')
            if not launcher_file.is_file():
                raise RuntimeError('Install the complete Open Cinema repository to enable Studio.')
            spec = importlib.util.spec_from_file_location('open_cinema_launcher', launcher_file)
            launcher = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(launcher)
            launcher.wait_ready(comfy_url + '/system_stats')
            launcher.ensure_studio(comfy_url, state['port'])
            state.update(state='ready', message='Your film workspace is ready.')
        except Exception as error:
            state.update(state='error', message=str(error))
            logging.warning('Open Cinema Studio: %s', error)
        finally:
            lock.release()

    @PromptServer.instance.routes.get('/open-cinema/status')
    async def status(request):
        return web.json_response(dict(state))

    @PromptServer.instance.routes.post('/open-cinema/start')
    async def retry(request):
        threading.Thread(target=start, daemon=True).start()
        return web.json_response(dict(state))

    if os.environ.get('OPEN_CINEMA_AUTOSTART', '1') != '0':
        threading.Thread(target=start, daemon=True, name='open-cinema-startup').start()
    else:
        state.update(state='stopped', message='Open Studio to start your film workspace.')
