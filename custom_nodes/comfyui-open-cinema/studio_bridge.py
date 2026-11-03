"""Local Studio companion lifecycle; never fail ComfyUI node loading."""
import importlib.util
import logging
import os
import ipaddress
from pathlib import Path
import threading


MODEL_CATEGORIES = ('checkpoints', 'diffusion_models', 'text_encoders', 'vae', 'loras', 'latent_upscale_models')


def scanned_model_roots(folder_paths):
    """Return existing roots whose category folders are all scanned by ComfyUI."""
    common = None
    for category in MODEL_CATEGORIES:
        roots = set()
        for value in folder_paths.get_folder_paths(category):
            path = Path(value).resolve()
            if path.name == category and path.parent.is_dir():
                roots.add(os.path.normcase(str(path.parent)))
        common = roots if common is None else common & roots
    return sorted(common or ())


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

    @PromptServer.instance.routes.get('/open-cinema/model-roots')
    async def model_roots(request):
        try:
            peer = request.transport.get_extra_info('peername')
            if not peer or not ipaddress.ip_address(peer[0]).is_loopback:
                raise ValueError('not loopback')
        except (ValueError, AttributeError):
            return web.json_response({'error': 'Local access only'}, status=403)
        import folder_paths
        return web.json_response({'roots': scanned_model_roots(folder_paths)})

    @PromptServer.instance.routes.post('/open-cinema/start')
    async def retry(request):
        threading.Thread(target=start, daemon=True).start()
        return web.json_response(dict(state))

    @PromptServer.instance.routes.post('/open-cinema/setup/{action}')
    async def setup_action(request):
        # Same-origin browser access; never proxy arbitrary destinations or paths.
        try:
            peer = request.transport.get_extra_info('peername')
            if not peer or not ipaddress.ip_address(peer[0]).is_loopback:
                return web.json_response({'error': 'Model setup is available on the local computer.'}, status=403)
            action = request.match_info['action']
            if action not in ('workflow', 'download'):
                return web.json_response({'error': 'Unknown setup action'}, status=404)
            from aiohttp import ClientSession, ClientTimeout
            body = await request.json()
            async with ClientSession(timeout=ClientTimeout(total=20)) as session:
                async with session.post(f"http://127.0.0.1:{state['port']}/api/setup/{action}", json=body) as response:
                    return web.json_response(await response.json(), status=response.status)
        except Exception:
            return web.json_response({'error': 'Studio setup is unavailable. Start Studio and try again.'}, status=503)

    if os.environ.get('OPEN_CINEMA_AUTOSTART', '1') != '0':
        threading.Thread(target=start, daemon=True, name='open-cinema-startup').start()
    else:
        state.update(state='stopped', message='Open Studio to start your film workspace.')
