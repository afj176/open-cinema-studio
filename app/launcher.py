"""Start Open Cinema and its local ComfyUI backend with readiness checks."""
import argparse
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]


def health(url):
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=2) as response:
            return json.load(response)
    except (OSError, ValueError):
        return None


def wait_ready(url, process=None, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = health(url)
        if result is not None:
            return result
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"Service exited ({process.returncode}). See runtime launch logs.")
        time.sleep(0.5)
    raise RuntimeError(f"Service did not become ready: {url}. See runtime launch logs.")


def discover_comfy(directory=None):
    if directory:
        candidate = Path(directory).expanduser().resolve()
        if (candidate / 'main.py').is_file():
            return candidate
        raise RuntimeError(f'ComfyUI main.py not found in {candidate}')
    candidates = [ROOT.parent / 'ComfyUI', Path.home() / 'ComfyUI', Path.home() / 'Documents/ComfyUI']
    if os.name == 'nt' and os.environ.get('LOCALAPPDATA'):
        candidates.insert(0, Path(os.environ['LOCALAPPDATA']) / 'Comfy-Desktop/ComfyUI-Installs/ComfyUI/ComfyUI')
    found = list(dict.fromkeys(p.resolve() for p in candidates if (p / 'main.py').is_file()))
    if len(found) == 1:
        return found[0]
    raise RuntimeError('Supply --comfy-dir or COMFYUI_PATH: ComfyUI was not found, or multiple installations exist.')


def discover_python(directory, explicit=None, windows=None):
    windows = os.name == 'nt' if windows is None else windows
    if explicit:
        resolved = shutil.which(str(explicit)) or str(Path(explicit).expanduser().resolve())
        if Path(resolved).is_file():
            return Path(resolved)
        raise RuntimeError('ComfyUI Python not found. Check --comfy-python or COMFYUI_PYTHON.')
    relative = 'Scripts/python.exe' if windows else 'bin/python'
    for environment in ('.venv', 'venv'):
        candidate = directory / environment / relative
        if candidate.is_file():
            return candidate
    portable = directory.parent / 'python_embeded/python.exe'
    if windows and portable.is_file():
        return portable
    if os.environ.get('VIRTUAL_ENV') or os.environ.get('CONDA_PREFIX'):
        return Path(sys.executable)
    raise RuntimeError('No ComfyUI Python environment found. Supply --comfy-python or COMFYUI_PYTHON.')


def spawn(arguments, name, cwd=None):
    runtime = ROOT / 'runtime'
    runtime.mkdir(exist_ok=True)
    with (runtime / f'{name}-launch.log').open('ab') as log:
        return subprocess.Popen(arguments, cwd=cwd or ROOT, stdout=log, stderr=subprocess.STDOUT,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                                start_new_session=os.name != 'nt')


def ensure_studio(comfy_url, port=8420):
    url = f'http://127.0.0.1:{port}'
    status = health(url + '/api/health')
    if status:
        if status.get('service') != 'open-cinema' or status.get('comfy_url') != comfy_url:
            raise RuntimeError(f'Port {port} belongs to another service or a Studio using a different ComfyUI backend.')
        return url
    process = spawn([sys.executable, '-u', str(ROOT / 'app/server.py'), '--comfy', comfy_url, '--port', str(port)], 'studio')
    status = wait_ready(url + '/api/health', process, 30)
    if status.get('service') != 'open-cinema' or status.get('comfy_url') != comfy_url:
        raise RuntimeError('Studio identity or backend does not match.')
    return url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--comfy-dir', type=Path, default=os.environ.get('COMFYUI_PATH'))
    parser.add_argument('--comfy-port', type=int, default=8288)
    parser.add_argument('--comfy-python', default=os.environ.get('COMFYUI_PYTHON'))
    parser.add_argument('--port', type=int, default=int(os.environ.get('OPEN_CINEMA_PORT', '8420')))
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    comfy_url = f'http://127.0.0.1:{args.comfy_port}'
    if health(comfy_url + '/system_stats') is None:
        directory = discover_comfy(args.comfy_dir)
        python = discover_python(directory, args.comfy_python)
        command = [str(python), '-s', str(directory / 'main.py'), '--listen', '127.0.0.1', '--port', str(args.comfy_port), '--disable-auto-launch']
        config = ROOT / 'runtime/extra_model_paths.yaml'
        if config.is_file():
            command += ['--extra-model-paths-config', str(config)]
        bridge_config = ROOT / 'runtime/open-cinema-paths.json'
        bridge_config.parent.mkdir(parents=True, exist_ok=True)
        bridge_config.write_text(json.dumps({'open_cinema_plugin': {'custom_nodes': str(ROOT / 'custom_nodes')}}), encoding='utf-8')
        command += ['--extra-model-paths-config', str(bridge_config)]
        for flag, folder in [('input', 'comfy-input'), ('output', 'comfy-output'), ('user', 'comfy-user')]:
            target = ROOT / 'runtime' / folder
            target.mkdir(parents=True, exist_ok=True)
            command += [f'--{flag}-directory', str(target)]
        print('Starting ComfyUI…', flush=True)
        # The companion started by ComfyUI must use the same Studio port.
        os.environ['OPEN_CINEMA_PORT'] = str(args.port)
        wait_ready(comfy_url + '/system_stats', spawn(command, 'comfy', cwd=directory))
    print('ComfyUI ready. Starting Studio…', flush=True)
    url = ensure_studio(comfy_url, args.port)
    print(f'Open Cinema is ready: {url}', flush=True)
    if not args.no_browser:
        webbrowser.open(url)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
