# Open Cinema Studio

An AI film studio built on ComfyUI, for Comfy's "Open Source Higgsfield" challenge (Open Weights category + LTX bonus).
A web app (Story → Shots → Edit → Screen) drives a headless ComfyUI; every step also ships as a ComfyUI canvas workflow.
`README.md` describes the features and models; this file is how to work on it.

## Where things live

- `custom_nodes/comfyui-open-cinema/director.py`: **every prompt and every Gemma instruction** (story, lead, beats, shots,
  world plate, frames, storyboard drawings, motion, titles, score) and their parsers. Shared by the web app and ComfyUI.
- `custom_nodes/comfyui-open-cinema/__init__.py`: the Open Cinema ComfyUI nodes (briefs, parsers, motion graphics).
- `app/graphs.py`: the ComfyUI API graphs. `app/studio.py`: projects, the job queue and the pipeline.
  `app/server.py`: HTTP routes. `app/static/`: the web app (plain JS/CSS, no build step).
- `tools/export_workflows.py`: writes `workflows/*.json` (canvases), `workflows/api/*.json` and installs them, plus
  `workflows/inputs/*`, into the runtime ComfyUI. `tools/canvas.py`: API graph → laid-out canvas.
- `projects/<id>/`: one folder per film (`project.json` + media). Not in git. `runtime/`: ComfyUI's input, output and
  user folders and logs. Not in git.

## Running it

Start both services using the portable launcher:

```bash
python app/launcher.py --comfy-dir /path/to/ComfyUI --comfy-python /path/to/python --no-browser
```

Use `python3` on macOS/Linux. See the root `README.md`. Before restarting, inspect the queue and identify the exact owned process; do not stop unrelated ComfyUI instances. Studio alone (port 8420):

```bash
python -u app/server.py --comfy http://127.0.0.1:8288 --port 8420
```

**What needs a restart:** changes to `director.py` or the nodes need **both** (the Gemma briefs and parsers run inside
ComfyUI's nodes; the studio builds the image and video prompts). Changes to `app/*.py` need the studio. `app/static/`
only needs a page reload. Studio preserves job history; queued/running jobs become interrupted on restart and require explicit retry.

## Changing prompts or graphs

- After any change to a prompt, graph or node, run `python tools/export_workflows.py` (ComfyUI must be up: it reads
  `/object_info`) so the canvases match the app.
- Check a canvas the way ComfyUI will load it: in ComfyUI's frontend, `app.loadGraphData(canvas)` then
  `app.graphToPrompt()`, and compare with `workflows/api/<name>.json`. Extra inputs at their default values are expected.
- Prompts are part of the product. Don't leak one film's details into shared prompts (examples like "lantern room"
  ended up in every film once), and keep each look's medium consistent (`LOOK_MEDIUM` in `director.py`).
- Only HiDream-O1 samples with real guidance, so only its negative prompt (`image_negative`) does anything. LTX and
  Qwen-Image-Edit run at cfg 1: say what to avoid in the positive prompt.

## Checking results

Look at what was made, not just whether the job finished: pull frames from videos with ffmpeg (start, a third, two
thirds, end) and view them. A finished job can still be a zooming still, a duplicated title or a colour leak.
Test on a scratch film (create one through the API), never on the user's films, and say which films you created.

## Rules from the user

- Permissively licensed models only (MIT / Apache-style); use the standard ComfyUI model folders.
- Beautiful, considered UX; talk big UX or design changes through before building them.
- Ask before pushing to GitHub. Commit when asked.
- Look before deleting anything: list it in one step, read the list, then delete. Never `ls && rm` in one command.

## Gotchas

- Bash heredocs mangle `\n`, `\\` and quotes in Python patch scripts. Use the Edit tool, or write the script to a file
  first and run it.
- The app's browser pane answers `confirm()` with "no" without showing it: confirm inline (click twice) instead.
- An open page autosaves its in-memory project. After changing a project through the API, reload the page, or the page
  can write its stale copy back.
- Videos over ~20 s must not be decoded in one temporal tile (the trailer score once filled 24 GB of VRAM). The score
  graph saves audio only.
