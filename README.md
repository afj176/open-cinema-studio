# Open Cinema Studio

**Write a shot list. Get a film.** An open-source, open-weights take on "cinema studio" apps, built on ComfyUI.

You describe the world and the lead character, then plan shots like a director: shot size, camera move (dolly, crane, orbit, whip pan, dolly zoom and more), film look, duration and sound. Open Cinema Studio then:

1. **Casts the lead.** The selected image engine (FLUX.2 Klein in Fast, HiDream-O1 in Standard) renders a studio reference portrait from your character description. You can also upload a photo of a real actor instead.
2. **Plans the frames.** The selected image engine paints an empty world plate and independently composes monochrome storyboard drawings from each shot's first-frame staging, cast descriptions and continuity notes.
3. **Shoots coverage.** The selected frame editor (FLUX.2 Klein in Fast, Qwen-Image-Edit-2511 in Standard) finishes each drawing in the film's look. New storyboards use the lead portrait's recorded appearance when available. *Picture 1* is the storyboard composition, *Picture 2* is the lead portrait when present. Wide shots also receive the world plate for materials, palette and light; tighter shots omit it to avoid inheriting the same wide composition. Recurring supporting characters can also use reusable portrait references. References improve consistency but do not guarantee identity, prop or action fidelity; inspect the results before accepting a cut.
4. **Rolls camera.** LTX 2.5 animates each keyframe with the camera move you picked: 1280×704 in Standard or 640×352 in Fast for 16:9. Each keyframe is composed as the *first frame* of its move (a drone shot starts aerial). Forward moves on empty wide views can use a **camera-path guide**, a zoomed end frame that pulls the shot forward. It **generates synchronized audio in the same pass**, so ambience, footsteps and effects come from the model itself.
5. **Does one-takes.** Set a shot to *Continue* and it starts on the exact last frame of the previous shot. Chains of these become one unbroken camera move, and the duplicated seam frame is dropped in the edit.
6. **Cuts the film.** Shots are joined with hard cuts or dissolves. Audio gets de-click fades and the whole film is loudness-normalized to −16 LUFS. An optional film finish adds grain, a soft vignette and crisper edges.
7. **Masters in 1080p.** SeedVR2 3B restores and upscales the final cut to 1920×1056 in one diffusion step, keeping the audio.

Everything runs locally on open weights, with no partner nodes and no closed APIs.

**Sample films:** [The Colossus Pass](docs/media/the-colossus-pass.mp4) (6 shots, epic fantasy, in-world title carved by AI, credits, 1080p SeedVR2 master), its [trailer cut](docs/media/the-colossus-pass-trailer.mp4) and [Night Courier](docs/media/night-courier.mp4) (6 shots, 25 s, neon chase).

![Cast portrait and keyframes from The Colossus Pass](docs/media/the-colossus-pass-keyframes.jpg)

![In-world title carved into the canyon](docs/media/the-colossus-pass-inworld-title.jpg)

> Entry for Comfy's [Open Source Higgsfield](https://comfy.org/open-source-higgsfield) challenge. Target category: **Open Weights Only**, plus the **LTX** bonus (LTX 2.5 is the core video model).

## How it works

```
 lead description ──► HiDream-O1 ──► cast portrait ───────────────────┐   (or upload a photo)
 world ────────────► HiDream-O1 ──► empty world plate ──────────────┤
 shot staging ─────► HiDream-O1 ──► monochrome storyboard ──────────┤
                                                                        ▼
 storyboard + cast + world ──► Qwen-Image-Edit-2511 + Lightning ──► keyframes
 keyframe + action + end state + camera + sound ──► LTX 2.5 (2-stage distilled, x2 latent upscale, audio) ──► shot.mp4
 "Continue" shots ──► last frame of previous shot ──► LTX 2.5
 all shots ──► cuts / dissolves / one-take seams + de-click + loudnorm (+ film finish) ──► film.mp4
 film.mp4 ──► SeedVR2 3B (1 step, x1.5) ──► 1920×1056 master
```

| Piece | What it is |
| --- | --- |
| `app/` | Web studio: a Python HTTP server, a GPU job queue and the UI, all driving ComfyUI over its HTTP API |
| `app/graphs.py` | The ComfyUI graphs (core nodes only): keyframe, coverage, and LTX shot with audio |
| `custom_nodes/comfyui-open-cinema/` | **Open Cinema** node pack: camera-direction vocabulary as ComfyUI nodes. *Open Cinema Shot* turns scene, action, shot size, camera move, look and sound into keyframe, coverage and motion prompts. *Open Cinema Shot Length* converts seconds to LTX-valid frame counts |
| `workflows/` | The same graphs as laid-out ComfyUI canvases (groups, titles, notes), plus `api/` JSON and example `inputs/` |

The camera language is the core of the app. `director.py` maps 22 camera moves, 12 shot sizes and 12 film looks to generation prompts for LTX 2.5 and the frame editors. Camera movement and action fidelity depend on the generated result; review each take. In the UI, each camera move also has a tiny animated viewfinder preview.

## Titles & Motion

Kinetic typography and motion graphics, built into the cut. **They take on each film's look.** *70mm epic* gets gold Fraunces serif on charcoal, *Neon cyberpunk* gets Barlow with magenta and cyan, and *None* gets black and orange. Everything is rendered by the Open Cinema node pack, so it runs inside ComfyUI and is usable in any workflow.

| Option | What it does |
| --- | --- |
| **Main title** | The film's title slams in over the opening shot. The glowing line streaks through, a starburst flashes, and the subtitle is typed out underneath. |
| **In-world title (AI)** | Instead of overlaid type, the title **becomes part of the world**. Qwen-Image-Edit-2511 builds it into the establishing frame in a material that suits the look: carved stone for *70mm epic*, a neon sign for *Neon cyberpunk*, brush calligraphy for *Anime*, or your own words. LTX 2.5 then brings the scene alive around the steady lettering, using a gentle push-in camera path. To guide spelling, the exact lettering is first set in the film's typeface by the **Open Cinema Type Sheet** node and handed to the editor as Picture 2. It opens the film and dissolves into shot 1, with its own frame and motion takes. |
| **Shot stamps** | A HUD slate on each later shot, e.g. `SHOT 03 · LOW ANGLE · TILT UP`, with the camera move highlighted. |
| **End credits** | Kinetic credit cards, one per line (`LABEL | TEXT`), scored with the last shot's own LTX sound echoing out. |
| **Trailer cut** | An alternate cut: your tagline cards between the strongest stretch of each shot. Its soundtrack is **one continuous score composed by LTX 2.5**, generated from the film's dark title card so the model writes music rather than scene ambience, in a style matched to the look (an orchestral epic, synthwave, a horror sting…). Every cut snaps to a hit in that score, and the trailer ends on a title card. **New score** re-rolls the music. **✨ Write cards** has Gemma 4 12B (8-bit) write the tagline cards from your story; every card gets a beat, and shots come round again when there are more cards than shots. |

Each option is a switch in the cut room's **Titles & Motion** panel. The 1080p master re-renders the graphics at full resolution. Rendered graphics are cached by content, so re-cutting only redraws what changed.

Nodes: *Open Cinema Title Overlay*, *Open Cinema Shot Stamp*, *Open Cinema Cards (kinetic type)*, *Open Cinema Title Preview* and *Open Cinema Type Sheet*. Fonts are bundled under the SIL Open Font License: Barlow Condensed, Fraunces, Manrope and JetBrains Mono.

## Requirements

- ComfyUI v0.43 or newer (Desktop or portable is fine). LTX 2.5 and Qwen-Image nodes are part of core ComfyUI.
- An NVIDIA GPU with 24 GB of VRAM. Developed on an RTX 5090 Laptop GPU (24 GB) with 64 GB of system RAM.
- Python 3.10+ for Studio. Install `requirements.txt` for WebSocket notifications; HTTP fallback works without it. ComfyUI has its own Python and PyTorch requirements.
- `ffmpeg` and `ffprobe` on your PATH (used for assembly, probing, and continuations).

### Models and licenses

The **Studio settings** side panel combines generation mode, image settings, and model setup. It separates writing readiness from rendering readiness. **Required for your current settings** follows the film's performance, image generator and frame editor; **Install required models** downloads only missing files in that set. Alternate engines and 1080p mastering are under **Optional capabilities**. Fast video does not require the Standard refinement upscaler. Qwen remains part of full-film setup for repairs, ending frames and storyboard tracing, including films using Klein opening frames. Casting and world painting require only the selected image engine and writer.

In ComfyUI, open the **Open Cinema** sidebar and choose **Check workflow setup**. It checks the open canvas, including the writer node's selected model, and offers installation only for missing models from the Open Cinema catalog. Other model filenames are identified for manual checking. Choose the download folder in Studio's **Installation details** if needed. Neither interface downloads models until you choose an install action.

Code and weights have separate licenses. LTX uses its community license, including revenue-dependent commercial terms; consult the linked model license before use. Weights are downloaded separately and are not redistributed in this repository.

| ComfyUI folder | File | Source | License |
| --- | --- | --- | --- |
| `diffusion_models` | `flux-2-klein-4b.safetensors` | [Comfy-Org/Flux-2-Klein-4B](https://huggingface.co/Comfy-Org/Flux-2-Klein-4B) | Apache-2.0 |
| `text_encoders` | `qwen_3_4b.safetensors` | [Comfy-Org/Flux-2-Klein-4B](https://huggingface.co/Comfy-Org/Flux-2-Klein-4B) | Apache-2.0 |
| `vae` | `flux2-vae.safetensors` | [Comfy-Org/Flux-2-Klein-4B](https://huggingface.co/Comfy-Org/Flux-2-Klein-4B) | Apache-2.0 |
| `checkpoints` | `hidream_o1_image_fp8_scaled.safetensors` | [Comfy-Org/HiDream-O1-Image](https://huggingface.co/Comfy-Org/HiDream-O1-Image) | MIT |
| `diffusion_models` | `qwen_image_edit_2511_int8_convrot.safetensors` | [Comfy-Org/Qwen-Image-Edit](https://huggingface.co/Comfy-Org/Qwen-Image-Edit) | Apache-2.0 |
| `text_encoders` | `qwen_2.5_vl_7b_fp8_scaled.safetensors` | [Comfy-Org/Qwen-Image](https://huggingface.co/Comfy-Org/Qwen-Image) | Apache-2.0 |
| `vae` | `qwen_image_vae.safetensors` | [Comfy-Org/Qwen-Image](https://huggingface.co/Comfy-Org/Qwen-Image) | Apache-2.0 |
| `loras` | `Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors` | [lightx2v/Qwen-Image-Edit-2511-Lightning](https://huggingface.co/lightx2v/Qwen-Image-Edit-2511-Lightning) | Apache-2.0 |
| `diffusion_models` | `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` | [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) | [LTX-2.x Community License](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x) (free under $10M revenue) |
| `text_encoders` | `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` | [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) | LTX-2.x Community License |
| `vae` | `ltx-2.5-video-vae-bf16.safetensors`, `ltx-2.5-audio-vae-bf16.safetensors` | [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) | LTX-2.x Community License |
| `latent_upscale_models` | `ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors` | [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) | LTX-2.x Community License |
| `diffusion_models` | `seedvr2_3b_int8_convrot.safetensors` (1080p master) | [Comfy-Org/SeedVR2](https://huggingface.co/Comfy-Org/SeedVR2) | Apache-2.0 |
| `vae` | `seedvr2_ema_vae_fp16.safetensors` (1080p master) | [Comfy-Org/SeedVR2](https://huggingface.co/Comfy-Org/SeedVR2) | Apache-2.0 |
| `text_encoders` | `gemma4_12b_int8_convrot.safetensors` (AI lead writer) | [Comfy-Org/gemma-4](https://huggingface.co/Comfy-Org/gemma-4) | Apache-2.0 |
| `text_encoders` | `gemma4_e4b_it_fp8_scaled.safetensors` (Fast writer) | [Comfy-Org/gemma-4](https://huggingface.co/Comfy-Org/gemma-4) | Apache-2.0 |

The LTX 2.5 repo is gated: accept its terms on Hugging Face before downloading. Studio shows the missing download size for the selected configuration; requirements vary by mode and enabled capabilities. Allow additional disk space for temporary downloads, generated media, and optional models.

**Fast is the default for new films.** Existing films retain their saved mode. Changing modes applies these presets:

| Studio setting | Fast | Standard |
| --- | --- | --- |
| Story and review model | Gemma 4 E4B | Gemma 4 12B (8-bit) |
| Image generator | FLUX.2 Klein 4B | HiDream-O1 |
| Frame editor | FLUX.2 Klein 4B | Qwen-Image-Edit-2511 |
| Image quality | Fast previews | Detailed images |
| 16:9 video | LTX 2.5, single stage, 640×352 | LTX 2.5, two stages, 1280×704 |

You can customize image settings after choosing a mode. Queued jobs retain their selected mode; existing takes are kept and must be rendered again to change their quality. Scaling a Fast clip in the final cut does not restore missing detail. Missing weights are shown in Studio settings without a silent fallback. In ComfyUI, choose the mode on **Open Cinema Writer** and use workflow 24 or 25 for Fast video.

HiDream and Klein generate images, Qwen and Klein edit reference-based frames, and LTX generates video with audio. These roles are available in both the Studio orchestration and standalone ComfyUI workflows.

## Setup

Start with a working [ComfyUI installation](https://docs.comfy.org/installation/overview), Python 3.10+, and FFmpeg/ffprobe on PATH. Clone the complete repository into a writable folder:

```sh
git clone https://github.com/afj176/open-cinema-studio.git
cd open-cinema-studio
python -m pip install -r requirements.txt
python app/launcher.py --comfy-dir /path/to/ComfyUI --comfy-python /path/to/ComfyUI/python
```

Use `python3` on macOS/Linux and replace the example paths with your installation. For a ComfyUI virtual environment, the interpreter is typically `.venv/bin/python` on macOS/Linux or `.venv/Scripts/python.exe` on Windows. The launcher starts missing services, waits for readiness, and opens Studio. Platform-specific shortcuts and configuration are below.

1. Put the models in your ComfyUI `models/` folders, or point ComfyUI at wherever they live using [`extra_model_paths.example.yaml`](extra_model_paths.example.yaml).
2. Use the platform launcher described below to register this checkout's nodes and start both services (ComfyUI on port 8288, Studio on 8420). For independent ComfyUI startup, add this repository's `custom_nodes` directory to its extra paths configuration or symlink the node pack. Keep the full repository; copying only the node directory provides nodes but cannot locate the Studio companion.
3. If managing services manually, start ComfyUI (its usual default is `http://127.0.0.1:8188`). The companion starts Studio automatically when the node pack loads.
4. Setup can discover local model folders scanned by ComfyUI and let you select one for downloads. Alternatively, supply a ComfyUI-scanned models folder to the launcher with `--models-dir /absolute/path/to/ComfyUI/models`, or set `OPEN_CINEMA_MODELS_DIR` before starting either the launcher or ComfyUI; these settings take precedence over the selection. The companion inherits that setting when ComfyUI starts Studio. For manual Studio startup, disable companion autostart using `OPEN_CINEMA_AUTOSTART=0` and run:

   ```bash
   python app/server.py --comfy http://127.0.0.1:8188 --models-dir /absolute/path/to/ComfyUI/models --open
   ```

5. Open `http://127.0.0.1:8420`. **Studio settings** opens automatically when required models, nodes, ComfyUI or FFmpeg are missing. It shows exact files, sizes, publisher links and readiness by stage. Select a discovered folder, then choose missing models to install; nothing downloads automatically. The choice is saved locally and checked against ComfyUI again before installation. Downloads resume from `.part` files and verify publisher SHA-256 hashes before installation. The folder must be one ComfyUI scans for all required model categories. Folder discovery requires the Open Cinema node pack and a local ComfyUI; restart ComfyUI after installing or updating the pack. For remote ComfyUI, configure the folder on its host or install manually. For gated files, accept the publisher's terms yourself and set `HF_TOKEN` in the server environment before retrying. Tokens never enter browser storage. Check readiness again after installation, then write the world and render. Existing projects remain editable while generation is unavailable.

### Optional local dialogue check

Studio can compare a speech-recognition transcript with the scripted line during video review. Install the optional packages in the **Python environment that runs Studio**:

```bash
python -m pip install "faster-whisper>=1.1.1,<2" huggingface_hub
```

Download a CTranslate2 Whisper model such as [Systran/faster-whisper-small](https://huggingface.co/Systran/faster-whisper-small) into a local directory. The directory must contain the model files, including `model.bin` and `tokenizer.json`. For example:

```bash
python -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-small', local_dir='whisper-small')"
```

Set `OPEN_CINEMA_WHISPER_MODEL` to the absolute path of that directory in the environment that starts Studio, then restart Studio. In PowerShell use `$env:OPEN_CINEMA_WHISPER_MODEL = 'C:\path\to\whisper-small'`; in macOS or Linux shells use `export OPEN_CINEMA_WHISPER_MODEL=/path/to/whisper-small`. If ComfyUI starts Studio, set it before starting ComfyUI. Speech checking uses CPU and only local files; Studio does not download the dependency or model. Without both, dialogue checking is unavailable and rendering continues.

If faster-whisper encounters the `metadata_errors` incompatibility with its installed PyAV audio decoder, Studio uses FFmpeg to decode the shot for the local speech check. FFmpeg must be available to Studio; no PyAV downgrade is needed in ComfyUI's Python environment. If decoding fails, the check is marked unavailable and the shot remains playable.

The check is a word-match heuristic, not an approval: speech recognition can miss or invent words, and it cannot establish the correct speaker, performance, or lip sync. Listen to the finished shot. Results are kept with their video take and the dialogue they checked; changing either invalidates the displayed result.

## Using it

- **✨ Generate the whole story:** type a spark (or nothing) and Gemma 4 12B (8-bit) writes the whole Story page: title, logline, world, an original film look, graphics colours, the lead, continuity notes, any other characters the story needs and 5 to 7 beats. With an empty spark and no established story, each seed supplies different loose starting points for the writer; these are inspiration rather than a closed list, and an explicit spark takes precedence. Sampling and prompting encourage variety but cannot guarantee originality. Then it casts the lead, paints the world, writes a shot for every beat and draws the storyboard. Each field also has its own ✨. **Undo AI change** reverts only what the AI touched. In ComfyUI, the *Open Cinema Story Brief* and *Open Cinema Parse Story* nodes wrap `TextGenerate` (workflow `11_ai_story_writer_gemma4.json`); change `creative_seed` to vary blank-spark inspiration.
- A complete story needs a title, logline, world, lead and at least three beats. If the full reply omits beats, the studio asks the writer for them separately before saving or queuing renders; an incomplete retry fails visibly. In the standalone ComfyUI workflow, inspect the parser's `beats` output and rerun the Story Brief with target `beats` if it is empty. Generated text and images still need editorial review.
- Title generation checks repeated distinctive words in recent local film titles for both blank and typed sparks. A separate title pass proposes eight grounded alternatives and rejects recurring words (including singular/plural forms). Words explicitly requested in the spark are permitted. Scratch films do not pollute this history. ComfyUI offers the same `avoid_title_words` input and candidate selection nodes; no project history leaves the local runtime.
- **Prop references and guided endings:** Scene continuity can bind a recurring object's design to a changing fact. Generate and inspect references for its states, choose the prop in each shot's Scene state, and enable a reviewed end frame for actions with a precise result. The exact prop reference overrides approximate storyboard details; the end frame edits the opening composition and conditions LTX's final frame. When a named supporting character enters during a shot, a generated ending can also use their available portrait; this is opt-in through the guided ending and requires the planned start/end cast. Uploaded ending frames remain independent of those portraits. Changing a prop design invalidates its references and affected shots. These controls improve constraints; the generated performance still needs visual review.

  In Draft, the first ending candidate is reviewed and kept with any findings so a playable shot can be made without automatic repair attempts. Strict mode retains its repair and review requirements.
- **Image quality:** Fast previews use smaller HiDream portraits and world plates, skip the costly seam-smoothing pass on HiDream previews, and use four-step Qwen Lightning for finished frames. Detailed uses full-size HiDream images with seam smoothing and the full Qwen editor at 40 steps, CFG 4, following the [publisher's inference settings](https://huggingface.co/Qwen/Qwen-Image-Edit-2511). Image quality is independent of Standard and Fast performance. Draft first queues opening-frame checks after the playable draft and offers explicit repairs; Strict continuity checks before dependent work and can automatically repair confirmed defects up to twice. Uncertain evidence and malformed reviewer output never trigger an automatic repaint. A repair that introduces a new defect or fails to improve the result stays inspectable without replacing the better candidate.
- **Image generator and shot-frame editor:** The Look panel can optionally use FLUX.2 Klein 4B for new portraits, world plates and independently drawn storyboards, in either performance mode. The separate **Shot-frame editor** can opt into experimental Klein reference editing; Qwen remains the default. Install the three Klein models from Setup first. Klein can be faster, but its multi-reference cast and composition can differ from Qwen; inspect results before relying on them for continuity. Existing takes are kept when changing an editor, and the choice applies to new frames.
- **Camera continuity:** the shot writer chooses independent compositions, reframed cuts or one-take continuations to suit the story. In the shot inspector, **Starting frame** lets you choose a new composition, a new angle from the preceding shot, or a continuation of its action. For a new angle, describe the camera position and who is seen face-on, from behind, partly in the foreground, or offscreen in **First frame**; include only visible people in the shot's cast. Reframing uses the preceding clip's final frame as a reference and follows the new shot's staging; one take starts directly from that frame. If two cast checks agree that a countable linked frame has extra people, Studio tries one alternate and keeps both frames. Inspect the alternate before using it: a correct cast count does not guarantee the requested viewpoint. These shots render in sequence, and replacing a preceding clip invalidates dependent work. AI-generated continuity is approximate, so inspect the resulting performance. For a new location, use a new composition. Global look clauses naming a light source are omitted while that source's tracked state is unlit; the state ledger controls when it lights.
- **The story, beat by beat:** the bottom of the Story page shows the whole film in order: each beat with its shots (the storyboard drawing, then → the rendered frame), and any shot that isn't in the story yet where it sits in the film, with **✨ Add to story** to write its beat. When a shot goes past the last beat (✨ Next shot, ✨ Continue the story), Gemma writes the new beat with it, so the story grows with the film. Once there are beats, **✨ Beats** and **+ Add beat** open *Continue the story*: Gemma adds 1, 2, 3 or 5 beats after the last one, following on from the story so far, and with Auto-render on they get their shots and videos too (rewriting every beat, or writing one yourself, are in the same menu). The **Strip** view shows just the storyboard drawings in film order, like a comic strip, and the **Script** view lays the film out as a screenplay: each beat a scene, each shot its action, and every spoken line under the character who says it. Beats guide the shots but never bind them: a shot can tell any beat or none, and you can add, delete, reorder and hand-write shots freely.
- **✨ Write shots:** on the Shots page, Gemma 4 12B (8-bit) writes one shot per beat (or 3 to 8 shots from the logline if there are no beats), each with its beat, action, shot size, camera move, length, sound and whether the lead is in it. Shots you wrote or edited and shots with a frame always stay; Gemma's own unrendered drafts (marked ✨) are replaced, so writing again gives a new draft. The button says what it will do: *Write shots*, *Redraft shots*, *Fill in the story* (beats no kept shot tells yet) or *Continue the film*. **✨ Next shot** writes the moment that follows, and **✨ Rewrite** writes one shot again. Every write can be undone, and text jobs jump ahead of queued renders. In ComfyUI: *Open Cinema Shots Brief* and *Open Cinema Parse Shots* (workflow `13_ai_shot_writer_gemma4.json`).
- **The storyboard:** The selected image generator composes each drawing independently from text: first-frame staging, shot size, everyone present, prop positions and continuity notes. It sees neither the world plate nor the preceding panel, avoiding repeated establishing compositions. `OpenCinemaMonochrome` guarantees grayscale output. The finished frame uses this drawing as Picture 1. Workflow `14_storyboard_sketch_qwen_image_edit_2511.json` retains its published filename for compatibility and uses the HiDream graph.
- **Editable script and dependencies:** the Script view edits action, dialogue, first-frame staging and end state inline. Autosave stores edits without launching GPU jobs on every keystroke. Render film rebuilds affected assets: staging/cast/world/look changes invalidate drawings, frames and videos; dialogue, sound, duration and end-state changes invalidate video. Beat changes flag attached shots for review: Rewrite for changed beat, or Still tells this beat. Old takes remain available. Generated assets record their inputs, so an edit during rendering leaves the older result visibly out of date. Auto-render applies to AI writing and pause/resume; it does not silently rewrite manually edited scripts.
- **Scene continuity:** before rendering, Gemma plans permanent design separately from changing state: object location, holder, light, damage, and any other story-specific facts. Story exposes the initial state; Script and Shot settings expose each shot's inherited state, result, visible cast at each end, and which facts can actually be checked in the image. Results flow into subsequent shots. Editing a result invalidates its video and affected downstream images; script edits require replanning or an explicit review of the existing state plan. These controls are open-ended, with no fixed prop vocabulary.

  The planner rechecks named people mentioned in the opening direction against the opening roster. Clear physical staging may add an omitted person; ambiguous mentions are flagged instead and suspend automatic count judgments for that opening. Review the people in Shot settings and use the reviewed plan when satisfied.
- **Review approach:** **Draft first** is the default, independent of generation mode and frame quality. It keeps flagged candidates available for animation and assembles a playable draft while preserving their findings. Video generation batches ahead of its queued video checks, reducing model switching. **Strict continuity** requires current passing reviews or explicit director acceptance before dependent work and assembly. Each queued job retains its selected review policy. Both approaches stop on missing, stale, or unreadable required media.
- **Visual review:** frames are checked against visible state, cast and film look. Video checks sample the start, one third, two thirds and end. Observers receive appearance descriptions rather than expecting names or story labels to be printed in the image. Confirmed defects, uncertainty, and reviewer failures are separate outcomes. Broken review output gets one review retry; it does not become a visual defect or an approval. Exact content and review contracts can reuse definitive cached evidence; changing the relevant inputs or reviewer version invalidates it. Four samples can miss transient defects, so inspect the complete clip before delivery.
- **Polish after playback:** Edit and Screen collect findings in one panel, with shot inspection, explicit repair/regeneration, and a short review reel of flagged clips. Draft exports with unresolved checks carry a visible **DRAFT - REVIEW PENDING** label. Once checks pass or you explicitly keep the relevant takes, **Update clean cut** assembles a new export without that label. Draft acceptance notes are optional; strict overrides require a reason. Automated findings stay attached to the take in either case. A flagged new candidate never silently replaces a current approved take.
- **Shot-plan and cast checks:** the shared shot-writing graph runs a second script-supervision pass for beat coverage, first/last states, prop continuity and purposeful framing. Proper lead names are normalized to the lead portrait. Explicit rosters receive a count check as part of visual review. A linked reframe with a known cast also gets an early count check; an apparent extra person triggers a full review before any alternate is attempted. Planning drawings are retained with their findings; Draft first can continue from them, while Strict continuity requires acceptance or a replacement. Crowds without a fixed roster skip the numerical check. Counts check presence, not identity or successful acting; the vision model can miscount.
- **Recover without starting over:** Activity puts running steps and unresolved problems first, with Inspect shot and Retry step actions; earlier activity is collapsed. A failed shot blocks its own dependent work, linked continuations and the final cut, while independent shots continue. Resume missing work queues missing or outdated assets and keeps finished work. Stop generation affects only the selected film. History survives a server restart; interrupted work requires an explicit retry.
- **The Edit page keeps the last cut** and says when it's out of date and why ("Out of date: shot 3 re-rendered, transitions changed"). With Auto-render on it re-cuts itself once every shot has its video; otherwise **Re-cut film** does it, and the button reads *Up to date* when nothing changed. The timeline shows the story's beats above the shots and the cut's real sound, and a paused shot is called out instead of the film quietly not being cut. **Cut trailer** writes its cards from the story first when you haven't, and composes the score as sound only.
- **Auto-render and pause:** with *Auto-render* on (the default, on the Shots page), shots Gemma writes go straight on to frames, videos and the final cut, so Generate the whole story ends in a film. Any shot can be paused from its card or inspector: its waiting work leaves the queue and, if it's rendering, it stops, while the other shots carry on. Change it while it's paused, press ▶ Resume, and it's rebuilt from whatever is out of date (drawing, frame, video); the film is cut once no shot is paused. **Render film** also redoes frames that no longer match their shot.
- **Film look** is an editable, open-ended direction for medium, light, colour, texture and camera style. It goes into casting, the world, frames and LTX motion; the presets are optional starting points. State the medium explicitly (for example, “2D animation” or “live action”) so the rest of the pipeline can match it. **Titles & graphics colours** control the studio, titles, cards and HUD overlays independently; changing the film look preserves them. **Use preset colours** explicitly applies the chosen preset's palette. In ComfyUI, `custom_look` on *Open Cinema Shot* overrides its preset.
- **Lead character**: describe your lead, then press **Cast from description**, or let **Render film** cast them automatically. You can drop a photo instead. The portrait establishes identity for storyboard-based frames. When carrying a scene forward, the accepted preceding frame supplies identity and materials without a competing portrait reference:
  - Gemma 4 12B (8-bit) looks at the portrait and writes the lead's identity notes (skin tone, face shape, eyes, hair, age). Storyboard-based frames and motion prompts use them; following frames preserve the existing face directly.
- **The world plate**: under the World text, the selected image model paints an empty location and the vision model checks for people, retrying confirmed positive results up to three times. Continuity planning can extract verbatim setting phrases from your world description so character actions do not compete with the empty-location instruction; if the extraction is missing or invalid, the original description is used. The plate is flagged when its world, look, aspect or extracted direction changes, and every re-paint is kept as a take. Check that the plate retains the details and style you intended.
- **Other characters and dialogue:** besides the lead, a film can have other characters (the Story page's *Other characters*, one `Name: what they look like` per line, written by Gemma or by you), crowds and passers-by. Recurring named individuals can receive reusable portraits automatically; cast or upload one in the Story page to control it. Uploaded portraits are never silently replaced. Shot frames use the available auxiliary picture slots for the lead, explicitly selected props and visible supporting portraits; scene continuations keep their previous performance as the reference. Choose **Automatic**, **Minimal**, **Dialogue-rich** or **No dialogue** to guide newly written shots; existing and manually edited shots stay yours. Each shot can carry a spoken line (`Mara: "We should go."`), shown on its card and in Script. LTX is prompted to generate the speech with the video; listen to the result to check the words, voices and synchronization.
- **Looks guide their medium:** *Noir* requests black and white, *Anime* requests drawing and *Claymation* requests plasticine: the portrait, the world plate, the frames and the negative prompt follow the look instead of forcing live action.
- **Each shot has its own composition**: initial storyboards plan independent compositions from text. Once an opening frame has a current passing review, redrawing its board traces that frame into deterministic monochrome (workflow 23), preserving the accepted cast, prop and pose. Replacing the source frame makes its traced drawing stale; drawing a trace does not invalidate the source performance. Storyboard-based finished frames use the drawing as Picture 1 and the lead portrait as Picture 2 when present. Only wide shots also receive the world plate; tighter shots omit it because its establishing layout can overwhelm the drawing.
  - The lead card shows which shots the lead is in, and flags any whose frame was made with an older portrait.
- **How it was made**: every shot's inspector shows the exact inputs of its current frame (the world plate, the portrait and the storyboard drawing), what the lead was described as, the model steps and the prompts. Before a frame exists, it shows what the next one will be made from. Storyboard cards show the lead's face and flag frames that no longer match (LEAD CHANGED, WORLD CHANGED, ACTION CHANGED) with a one-click New frame.
- **Continuity notes** are the few details that must never change, such as a prop or a scar.
- **✨ AI lead writer:** a local open LLM, **Gemma 4 12B-it (8-bit)** (Apache-2.0) running through ComfyUI's native `TextGenerate` node, writes the lead and the continuity notes. It has three modes:
  - **Write with AI** invents a lead who belongs to your world, era and look.
  - **Refine** keeps every detail you wrote and makes it camera-ready.
  - **Describe photo** describes your cast photo exactly.

  **✨ From the lead** distills the continuity notes from the lead. Every change can be undone. In ComfyUI, the *Open Cinema Lead Brief* and *Open Cinema Parse Lead* nodes wrap `TextGenerate` (workflow `10_ai_lead_writer_gemma4.json`).
- **Lead** (per shot): untick it when the lead is not visible. List the other characters or groups needed in the shot in **Who else**; they can appear with or without the lead. An empty cast produces a deserted shot, and a lead with no other cast is alone.
- **Shots**: each shot has an action, a size, a camera move (shown live in the little viewfinder), its length in seconds, and sound.
  - **New keyframe** re-rolls only that shot's frame. **Upload** uses your own frame. **Render shot** animates it.
  - **Cut to** starts from a fresh coverage keyframe. **Dissolve** crossfades picture and sound. **Continue (one take)** starts on the previous shot's last frame.
  - A linked new camera angle uses the previous shot's final frame for continuity. With Qwen, a known returning supporting character may also use their saved portrait as an identity reference when they were absent from that frame; their appearance is still guided by the written staging.
- **Takes**: **New keyframe** and **Render shot** never overwrite. Every attempt becomes a numbered take (K1, K2… for frames, S1, S2… for shots) that you can switch between under the frame. Each take gets its own reproducible seed.
- **Film finish** (optional) adds fine animated grain, a soft vignette and gentle sharpening to the cut.
- **Master in 1080p** runs SeedVR2 on each shot (cached per take), then re-cuts the film at 1920×1056 with the same transitions and audio.
- **Render film** queues missing or outdated casting, world, storyboard drawings, keyframes, videos and the final cut. Drawings run before finished frames; cast-count checks add vision-model passes. Uploaded portraits remain unchanged; generated portraits follow changes to the casting description and film look.

Approximate timings on an RTX 5090 Laptop GPU (24 GB):

| Step | Time |
| --- | --- |
| Cast portrait or establishing keyframe (HiDream-O1, 40 steps, 2560×1440) | about 1.5–2 min |
| Planning storyboard (HiDream-O1, 1280×704 landscape + grayscale + cast check) | about 20–23 s in the two-shot local pilot; cold loads vary |
| Coverage keyframe (4-step Qwen Lightning, up to three references; Detailed uses 40 steps and takes longer) | about 25 s plus cast check |
| 4-second shot with audio at 1280×704 | about 45 s |
| 1080p master (SeedVR2 3B), per 4-second shot | about 4.5 min |

A six-shot film also needs six storyboard drawings before its finished frames. Planning drawings use roughly one megapixel. In one warm three-second sample on the same RTX 5090 Laptop, the single-stage video pass took 10.1 seconds versus 25.3 seconds for two-stage; this is not an end-to-end film benchmark. Additional review and redraws affect total time. Mastering six 4-second shots in 1080p adds about 27 minutes.

New jobs record queue time and ComfyUI submission, wait, upload and download wall time in the local job history. Run `python tools/performance_report.py` to summarize completed jobs by type and mode. Execution time starts when the Studio worker begins; queue time comes before it. The report calculates queue plus execution for each job with both values and shows how many jobs contributed to each median. ComfyUI wait includes its own queue, model loading, inference and polling; optional node observations are partial and do not measure GPU utilization. Compare like-for-like shots and record cold versus warm runs separately. Existing jobs without timing are excluded.

Studio uses ComfyUI's `/ws` events for execution notifications and serves `/api/events` as an SSE stream to the browser. Each browser connection reconciles current HTTP snapshots, with 15-second stream heartbeats, 5-second fallback polling while disconnected, and 30-second reconciliation while connected. ComfyUI history remains authoritative for success and failure; the backend checks it after events and at least every five seconds while connected. Install `requirements.txt` into your Python environment, or use `python -m pip install --target runtime/python-packages -r requirements.txt`. Without the optional WebSocket dependency, the backend falls back to HTTP history polling. Restart Studio and reload the browser after updating.

## Running single steps in ComfyUI

### One launcher, two workspaces

| Platform | Launcher |
| --- | --- |
| Windows | Double-click **Start Open Cinema.cmd** |
| macOS | Run `chmod +x "Start Open Cinema.command"` once, then double-click it |
| Linux | Run `sh start-open-cinema.sh`; optionally generate a desktop entry with `python3 tools/create_linux_shortcut.py` |

Each launcher reuses healthy services, starts missing services, waits for readiness, and opens Studio. Errors remain visible in the terminal; logs are in `runtime/comfy-launch.log` and `runtime/studio-launch.log`. Closing the launcher leaves services running.

For an explicit installation, run `python app/launcher.py --comfy-dir /path/to/ComfyUI --comfy-python /path/to/python` (use `python3` on macOS/Linux). Both options have environment equivalents: `COMFYUI_PATH` and `COMFYUI_PYTHON`. The launcher discovers common checkout locations and `.venv`/`venv` environments, Windows portable Python, or an activated virtual/Conda environment. Ambiguous installations require an explicit path. When starting ComfyUI, the launcher registers this checkout's custom nodes through generated extra-path configuration. Copying only the node directory does not install the Studio app.

When the node pack loads in ComfyUI, it starts the local Studio companion automatically after ComfyUI becomes ready. The **Open Cinema** sidebar provides readiness feedback, a start/retry action, and **Open Studio**. Studio's **ComfyUI ↗** link returns to its configured backend in another tab. Existing canvases remain open. Studio is a separate full film workspace; the sidebar does not embed or synchronize a film with the current graph.

Set `OPEN_CINEMA_AUTOSTART=0` to start Studio only from the sidebar or launcher. Set `OPEN_CINEMA_PORT` to change the companion port (match the launcher's `--port`). A Studio connected to another ComfyUI backend is never silently reused. These launch and navigation features target a local desktop installation; remote hosting, reverse proxies, and HTTPS require deployment-specific configuration.

### Platform setup and configuration

1. Clone the complete repository into a writable folder. Studio stores projects and runtime files beside the code, so read-only system installation locations are unsuitable.
2. Install ComfyUI with its supported Python/PyTorch environment and the required models listed in the README. The launcher does not install ComfyUI, GPU drivers, or model weights.
3. Install Python 3.10+ for the launcher, and install `requirements.txt` into that environment for WebSocket support. ComfyUI's companion uses ComfyUI's own Python; install the requirements there too, or allow HTTP fallback.
4. Install FFmpeg including FFprobe and make both visible on the PATH inherited by the launcher. Finder and desktop launchers may have a different PATH from your terminal.
5. Set `COMFYUI_PATH` to the directory containing `main.py` if discovery is insufficient. Set `COMFYUI_PYTHON` to the Python executable with ComfyUI's dependencies if using a custom environment. CLI arguments override environment values.

Example for Linux or macOS:

```sh
export COMFYUI_PATH="$HOME/apps/ComfyUI"
export COMFYUI_PYTHON="$HOME/apps/ComfyUI/.venv/bin/python"
sh start-open-cinema.sh
```

Python discovery checks `.venv`, then `venv`, then Windows portable `python_embeded`, then an activated virtual/Conda environment. An explicitly selected Python takes precedence. The environment must already contain ComfyUI's dependencies; an active environment is not proof of compatibility. `OPEN_CINEMA_PYTHON` selects the Python running the Unix launcher itself. `--comfy-python` selects the separate ComfyUI interpreter.

## Desktop entry points

- Windows: double-click `Start Open Cinema.cmd`; Python must be available as `python` on PATH.
- macOS: run `chmod +x "Start Open Cinema.command"` once, then open it in Finder. Errors remain visible until Return is pressed. If your GUI environment lacks Python or FFmpeg, launch from a configured terminal instead. There is no signed or notarized app bundle.
- Linux: use `sh start-open-cinema.sh`. To create a menu/desktop entry, run `python3 tools/create_linux_shortcut.py`; it writes `runtime/Open Cinema.desktop` with this checkout's absolute paths. Copy that file to `~/.local/share/applications/` or your desktop. Your desktop environment may require marking it trusted/allowing launch. Regenerate it if the checkout moves. For environments not inherited by desktop apps, invoke the shell launcher from your configured terminal.

All launchers accept `--comfy-dir`, `--comfy-python`, `--comfy-port`, `--models-dir`, `--port`, and `--no-browser`. `--models-dir` and `OPEN_CINEMA_MODELS_DIR` select a ComfyUI-scanned destination for optional downloads; restart an existing Studio if its download folder differs. Without a graphical session, use `--no-browser` and open Studio manually on the same machine. Closing the launcher does not stop services. Stop them through your process manager after confirming generation is idle.

## ComfyUI integration

When starting ComfyUI, the launcher writes a generated extra-path file registering this checkout's custom nodes; it also loads `runtime/extra_model_paths.yaml` if supplied. That optional file must contain paths valid on the current machine. Model files stay in your ComfyUI model folders or configured external model locations.

If you start ComfyUI independently, register this checkout's `custom_nodes` directory with ComfyUI. Keep the complete repository in place: the node pack locates Studio relative to itself. Its sidebar and automatic companion startup then work without running the launcher. `OPEN_CINEMA_AUTOSTART=0` disables automatic startup. `OPEN_CINEMA_PORT` changes the companion's Studio port; the launcher propagates its selected port when it starts ComfyUI.

Services bind to loopback. This is a local desktop experience; remote browsers, reverse proxies, authentication, TLS, multi-user storage, and shared-network deployment need additional design. Multiple ComfyUI installations cannot share one Studio port when they use different backends; select distinct ports explicitly.

### Canvas workflows

`workflows/` holds the shared graphs as **laid-out canvases**: nodes flow left to right in colour-coded groups, inputs are titled, and a note explains the recipe and reference order. `workflows/api/` has the same graphs as API JSON for scripting, and `workflows/inputs/` has example images (copy them into ComfyUI's `input` folder). Cast checks save the candidate and report mismatches for inspection rather than silently discarding it.

Regenerate with `python tools/export_workflows.py` while the studio's ComfyUI runs on :8288. It also installs the canvases into that ComfyUI's **Workflows** sidebar (`open-cinema/`) and the example inputs into its input folder.

- `00_cast_portrait_hidream_o1.json`: the lead's casting portrait
- `01_world_plate_hidream_o1.json`: the film's world as an empty location
- `12_world_plate_people_check_gemma4.json`: Gemma checks the world plate has nobody in it (YES / NO)
- `02_shot_frame_qwen_image_edit_2511.json`: a tighter shot from its storyboard (Picture 1) and the lead (Picture 2); wide shots may also use the world plate (Picture 3)
- `03_shot_ltx25_i2v_audio.json`: image-to-video with audio and camera direction
- `04_shot_ltx25_keyframe_to_keyframe.json`: lands the shot on a chosen end frame
- `05_director_node_keyframe_to_keyframe.json`: the same shot, with its motion prompt written by the **Open Cinema Shot** node (requires the node pack)
- `06_master_1080p_seedvr2.json`: SeedVR2 1080p master of a finished film (input `oc_example_film.mp4`, the opening of Glass Eye), audio kept
- `07_motion_title_over_shot.json`: main title over a shot (input `oc_example_shot.mp4`, a Glass Eye shot), audio kept
- `08_motion_kinetic_cards.json`: kinetic type cards (`LABEL | TEXT` per line)
- `09_inworld_title_frame.json`: an in-world title built into a frame (input `oc_world_plate.jpg`), with the type sheet as Picture 2
- `10_ai_lead_writer_gemma4.json`: Gemma 4 12B (8-bit) writes a lead and continuity notes from a world (Lead Brief → TextGenerate → Parse Lead)
- `11_ai_story_writer_gemma4.json`: Gemma 4 12B (8-bit) writes a whole story page (title, logline, world, look, palette, lead, continuity) from a spark (Story Brief → TextGenerate → Parse Story)
- `13_ai_shot_writer_gemma4.json`: Gemma 4 12B (8-bit) turns beats into staged shots, including participants, dialogue, first frame and end state (Shots Brief → draft → script-supervision review → Parse Shots)
- `14_storyboard_sketch_qwen_image_edit_2511.json`: independent HiDream storyboard composition plus deterministic grayscale (legacy filename); its output is Picture 1 in 02
- `15_trailer_score_ltx25.json`: the trailer's music: one long, small LTX 2.5 render from the dark title card (`oc_title_card.jpg`), keeping only its sound
- `16_scene_state_gemma4.json`: plan the film's state ledger and extract any shot's inherited state, changes, visible cast, visible fact checks and permanent design with *Open Cinema State Ledger*. Connect those outputs to the optional state inputs on *Open Cinema Shot*. The checks also scope image direction so an offscreen character's state does not accidentally introduce them into the composition.
- `17_frame_state_review_gemma4.json`: inspect a frame against explicit state, cast-count and look requirements, returning structured evidence and a pass flag.
- `18_video_continuity_review_gemma4.json`: inspect four samples of a short shot against opening, invariant and ending requirements. The web app uses these same nodes, prompts and graphs; candidate promotion and cut gating are studio orchestration, while ComfyUI exposes the review result for your workflow.

## License

The code is MIT licensed (see [LICENSE](LICENSE)). The model weights keep their own licenses, listed above.

## Developer tools and validation

Run `python -m unittest discover -s tests` for the automated suite. Developer tools use `COMFYUI_URL` (default `http://127.0.0.1:8288`) and `OPEN_CINEMA_URL` (default `http://127.0.0.1:8420`) to target another local service. These are tool settings, separate from launcher port arguments. Workflow export installs examples into this checkout's runtime folders by default. Set `COMFYUI_INPUT_DIR` and `COMFYUI_USER_DIR` to install into an independently configured ComfyUI's input and user directories.

`python tools/performance_report.py --project PROJECT_ID` summarizes retained job timings for one film. New render requests record the time from the render request to its first selected playable shot; this excludes earlier story writing and only covers jobs still in the local history. ComfyUI node-class timings use observed WebSocket node transitions and are partial: cached nodes, disconnected or missed events, and unfinished spans need not appear. They do not include graph inputs, prompts or image contents. The report does not infer missing timing from older jobs.

The `tools/qa_*.py` scripts are opt-in scratch-film helpers, not runtime dependencies. They require Pillow for contact sheets and existing project assets; `qa_continuity.py fixture --source-project ID` and `production --source-project ID` use a source film with the documented lantern fixture assets. `calibrate` uses the scratch fixture previously created. They can queue GPU work and create scratch projects. Inspect their CLI and inputs before running them.

`tests/fixtures/film_evaluation_cases.json` contains repeatable live-action, cartoon, shadow-puppet and dialogue-ensemble briefs. For an existing storyboard-based shot with a recorded frame prompt and complete reference provenance, `python tools/compare_frame_editors.py PROJECT_ID --shot 1 --seed 1101 --seed 1102 --output runtime/frame-comparison` renders matched Qwen and Klein candidates without changing the film. It reuses the recorded storyboard and auxiliary references in their original order; it refuses incomplete recipes and linked-shot reframes rather than silently omitting a picture. It writes images and `results.json`; model loading and cache state can affect timings and are not verified by the tool. Add human `scores` (0–5 for `identity`, `style`, `continuity`, `action`, or `dialogue`) only after inspecting the outputs, then run `python tools/film_evaluation.py runtime/frame-comparison/results.json --baseline qwen --candidate klein`. The report compares matching case/seed pairs and leaves unscored dimensions absent; it does not claim automatic quality verification or extrapolate a frame benchmark to an entire film.

To generate the four supplied briefs without using an existing film, run `python tools/benchmark_film_cases.py --output runtime/film-case-comparison`, then compare the results with `python tools/film_evaluation.py runtime/film-case-comparison/results.json --baseline qwen --candidate klein`. This is a GPU-intensive, opening-frame-only comparison: the editors currently output different image sizes, and it does not test motion, spoken dialogue, or continuity across shots. Both comparison tools require an empty output directory and do not change Studio projects.

For a small pipeline check, `python tools/benchmark_film_pipeline.py --output runtime/pipeline-check --mode fast` renders a two-shot scratch project with dialogue and a linked second shot; use `--mode normal` for Standard, and optionally `--viewpoint "Over Mira's shoulder, facing Noah"` to change the second shot's opening description. It submits GPU work to ComfyUI, checks that Studio and ComfyUI queues are idle first, and writes its scratch project, clips and report only into the new or empty output directory. To retry missing or stale work in an existing evaluation, add `--resume` and use that same output directory; the original report and takes are kept. It starts from a prepared script rather than testing story writing, and completing the run does not prove dialogue, motion or consistency quality; inspect the clips and listen to the audio. Changes to prompts, generated references, or system state make runs imperfect comparisons.

Use `--case character_reentry` to exercise a character leaving and returning; `--seed-offset 100` with any named case creates a repeatable second shot-seed sample. The fixture fingerprint records the resulting directions and seeds. Casting and planning can still vary between runs.

`tools/benchmark_entrance_guidance.py --help` compares unguided and portrait-guided endings from an existing scratch shot; `tools/benchmark_reframe_strategy.py --help` compares a previous-frame edit with a storyboard and two portrait references. Both submit GPU work and require a new empty output folder. `tools/benchmark_video_cache.py --help` compares a video after a requested model unload with a subsequent run in both modes. It changes ComfyUI's shared model cache; it cannot control disk caches or prove the model was cold. All comparisons need visual inspection and are not proof of full-film quality.

Add `--case live_action_keys`, `--case cel_animation_bus_stop`, or `--case stop_motion_parcel` to run the supplied scripted styles in `tests/fixtures/film_pipeline_cases.json`; the report records a fixture hash so altered prompts are identifiable. For a narrower scheduling comparison, run `python tools/benchmark_first_shot.py PATH_TO_PROJECT_JSON --output runtime/first-world --mode fast --variant world-first --seed 1701`, then repeat with `--output runtime/first-deferred --variant deferred`, the same mode and seed. Repeat in `normal` mode for Standard. Each run uses a scratch copy of the first shot, existing cast references and continuity plan, with fresh generated media and a fixed world seed. `world-first` simulates earlier ordering using current code; it is not the historical build. Match the recorded input and working-tree hashes before comparing, record the model/cache state, and repeat in reversed order: model loading and ComfyUI caches can strongly influence one-shot timings. This measures the render request to its first playable shot and excludes prior writing, planning and casting. It skips its own queued scratch assembly and reviews after the preview, while allowing running work and the world job to finish.

For an existing linked-shot frame, `python tools/compare_reframe_editors.py projects/PROJECT_ID/project.json --shot 2 --seed 1702 --expected-cast 2 --output runtime/reframe-comparison` renders Qwen and Klein from the same saved previous-shot end image, recorded frame prompt and seed, appending the same cast-count instruction to both. It does not change the project. Inspect the outputs for the requested viewpoint, cast count and identity; matching prompts and seeds do not guarantee equivalent output sizes or comparable model warm-up.

After a scratch pipeline run, `python tools/inspect_film_pipeline.py runtime/pipeline-check/report.json --output runtime/pipeline-inspection` produces a four-sample contact sheet and a review template with clip hashes, timing and audio-stream details. Add `--speech` to use the separately configured local dialogue checker described above. The tool rejects a report whose selected takes have changed and never changes the project. Its review dimensions remain unscored until a person examines the clips: watch the full action and cuts, inspect character identity and camera viewpoint, and listen for the words, speaker and lip sync. Sampled frames, audio levels and speech recognition cannot independently establish those qualities.

For repeatable coverage across films, run `python tools/benchmark_film_matrix.py --output runtime/film-matrix` to preview the planned cases, Fast/Standard modes, and seed offsets. Add `--run` to render them serially into isolated scratch folders, with a log, report and inspection evidence for each completed film. Narrow the run with repeatable `--case`, `--mode`, or `--seed-offset` options; `--frame-backend klein` selects Klein and `--speech` enables the configured local speech checker. A timeout stops the matrix before another film is submitted. `matrix.json` distinguishes pipeline completion from unassessed visual/audio quality. Evaluation comparisons keep performance modes and fixture revisions separate and support `viewpoint` and `audio_quality` scores alongside the existing dimensions.

For a specific over-the-shoulder view, name the foreground character in the opening direction—for example, “Over Mira's shoulder, facing Noah.” Studio expands that into camera placement and checks the foreground character's visible orientation separately from headcount. Explicit photographic scenes containing both humans and cloth puppets also get separate character-material checks. When both cast portraits are available for a two-character independent shot without a prop reference, Studio composes directly from those identities to avoid carrying the storyboard's drawn material into the photographed human. The opening direction still supplies staging, and the frame's ingredients show the references actually used. Material-only objections are advisory and do not trigger automatic repainting. These checks run through the existing review policy; ambiguous evidence remains unverified and does not automatically approve an alternate take.
