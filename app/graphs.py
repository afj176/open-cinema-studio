"""ComfyUI API-format graphs for Open Cinema Studio.

Graphs use core ComfyUI nodes, the shared Open Cinema nodes and open-weight models:
HiDream-O1-Image (MIT) for keyframes and cast portraits, Qwen-Image-Edit-2511 (Apache-2.0)
for multi-reference coverage that keeps the cast and set consistent, LTX 2.5 for
image-to-video with native audio, and SeedVR2 (Apache-2.0) for the 1080p master.
"""

from __future__ import annotations

from typing import Any
from contextlib import contextmanager
from contextvars import ContextVar
import json

_writer_mode = ContextVar("writer_mode", default="normal")

@contextmanager
def using_writer(mode: str):
    if mode not in ("normal", "fast"):
        raise ValueError("Choose Normal or Fast AI mode")
    token = _writer_mode.set(mode)
    try:
        yield
    finally:
        _writer_mode.reset(token)

def writer_node():
    return node("OpenCinemaWriter", mode=_writer_mode.get())

MODELS = {
    "hidream": "hidream_o1_image_fp8_scaled.safetensors",
    "klein": "flux-2-klein-4b.safetensors",
    "klein_te": "qwen_3_4b.safetensors",
    "klein_vae": "flux2-vae.safetensors",
    "qwen_edit": "qwen_image_edit_2511_int8_convrot.safetensors",
    "qwen_te": "qwen_2.5_vl_7b_fp8_scaled.safetensors",
    "qwen_vae": "qwen_image_vae.safetensors",
    "qwen_lightning": "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors",
    "ltx": "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors",
    "ltx_te": "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors",
    "ltx_vae": "ltx-2.5-video-vae-bf16.safetensors",
    "ltx_audio_vae": "ltx-2.5-audio-vae-bf16.safetensors",
    "ltx_upscaler": "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors",
    "writer": "gemma4_12b_int8_convrot.safetensors",  # Gemma 4 12B-it (8-bit) (Apache-2.0), text + image understanding
}

# Distilled two-stage schedule: base pass at half resolution, x2 latent
# upscale, short refine pass at full resolution.
BASE_SIGMAS = "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"
REFINE_SIGMAS = "0.85, 0.725, 0.4219, 0.0"

ASPECTS = {
    # name: (keyframe w, h, video w, h). Keyframes use HiDream-O1's trained sizes; video dims are multiples of 64.
    "16:9": (2560, 1440, 1280, 704),
    "2.39:1": (3104, 1312, 1536, 640),
    "9:16": (1440, 2560, 704, 1280),
    "1:1": (2048, 2048, 960, 960),
}
# Qwen-Image-Edit works best around 1.5 MP; coverage canvases at the film's aspect.
COVERAGE_SIZES = {"16:9": (1664, 928), "2.39:1": (1792, 768), "9:16": (928, 1664), "1:1": (1328, 1328)}
CAST_SIZE = (1728, 2304)  # 3:4 portrait, a HiDream-O1 trained size
# Klein targets an interactive draft: around one megapixel, preserving each film aspect.
KLEIN_IMAGE_SIZES = {"16:9": (1280, 704), "2.39:1": (1536, 640), "9:16": (704, 1280), "1:1": (1024, 1024)}
KLEIN_SKETCH_SIZES = {"16:9": (1024, 576), "2.39:1": (1152, 480), "9:16": (576, 1024), "1:1": (768, 768)}
KLEIN_CAST_SIZE = (768, 1024)


def node(class_type: str, **inputs: Any) -> dict[str, Any]:
    return {"class_type": class_type, "inputs": inputs}


def keyframe_graph(prompt: str, seed: int, aspect: str, prefix: str,
                   size: tuple[int, int] | None = None, negative: str = "", backend: str = "hidream",
                   preview: bool = False) -> dict[str, Any]:
    """HiDream-O1-Image text-to-image, official Full recipe: 40 steps, cfg 5, seam smoothing."""
    if backend == "klein":
        # Portrait callers request CAST_SIZE, the full-resolution HiDream shape.
        # Other explicit dimensions (e.g. storyboard size) are honored.
        width, height = KLEIN_CAST_SIZE if size == CAST_SIZE else size or KLEIN_IMAGE_SIZES[aspect]
        return klein_graph(prompt, seed, prefix, width, height)
    if backend != "hidream":
        raise ValueError("Choose a supported image backend")
    width, height = (KLEIN_CAST_SIZE if size == CAST_SIZE else size or KLEIN_IMAGE_SIZES[aspect]) if preview else (size or ASPECTS[aspect][:2])
    graph = {
        "1": node("CheckpointLoaderSimple", ckpt_name=MODELS["hidream"]),
        "2": node("ModelNoiseScale", model=["1", 0], noise_scale=8.0),
        "3": node("HiDreamO1PatchSeamSmoothing", model=["2", 0], start_percent=0.8, end_percent=1.0,
                  pattern="single_shift", passes="ramp_2_4", blend="median", strength=1.0),
        "4": node("CLIPTextEncode", clip=["1", 1], text=prompt),
        "5": node("CLIPTextEncode", clip=["1", 1], text=negative),  # director.image_negative(look)
        "6": node("EmptyHiDreamO1LatentImage", width=width, height=height, batch_size=1),
        "7": node("BasicScheduler", model=["2", 0], scheduler="normal", steps=40, denoise=1.0),
        "8": node("KSamplerSelect", sampler_name="dpmpp_2m_sde_gpu"),
        "9": node("SamplerCustom", model=["3", 0], add_noise=True, noise_seed=seed, cfg=5.0, positive=["4", 0],
                  negative=["5", 0], sampler=["8", 0], sigmas=["7", 0], latent_image=["6", 0]),
        "10": node("VAEDecode", samples=["9", 0], vae=["1", 2]),
        "11": node("SaveImage", images=["10", 0], filename_prefix=prefix),
    }
    if preview:
        # The seam-smoothing patch performs extra model passes near the end.
        # Keep it for full-resolution work; small previews favor responsiveness.
        graph["9"]["inputs"]["model"] = ["2", 0]
        graph.pop("3")
    return graph


def klein_graph(prompt: str, seed: int, prefix: str, width: int, height: int) -> dict[str, Any]:
    """FLUX.2 Klein 4B distilled: the publisher's four-step Euler graph."""
    return {
        "1": node("UNETLoader", unet_name=MODELS["klein"], weight_dtype="default"),
        "2": node("CLIPLoader", clip_name=MODELS["klein_te"], type="flux2", device="default"),
        "3": node("VAELoader", vae_name=MODELS["klein_vae"]),
        "4": node("CLIPTextEncode", clip=["2", 0], text=prompt),
        "5": node("ConditioningZeroOut", conditioning=["4", 0]),
        "6": node("EmptyFlux2LatentImage", width=width, height=height, batch_size=1),
        "7": node("Flux2Scheduler", steps=4, width=width, height=height),
        "8": node("KSamplerSelect", sampler_name="euler"),
        "8n": node("RandomNoise", noise_seed=seed),
        "8g": node("CFGGuider", model=["1", 0], positive=["4", 0], negative=["5", 0], cfg=1.0),
        "9": node("SamplerCustomAdvanced", noise=["8n", 0], guider=["8g", 0], sampler=["8", 0],
                  sigmas=["7", 0], latent_image=["6", 0]),
        "10": node("VAEDecode", samples=["9", 0], vae=["3", 0]),
        "11": node("SaveImage", images=["10", 0], filename_prefix=prefix),
    }


def klein_coverage_graph(prompt: str, seed: int, reference: str, prefix: str, aspect: str,
                         second_reference: str | None = None, third_reference: str | None = None) -> dict[str, Any]:
    """Four-step FLUX.2 Klein multi-reference frame using ComfyUI's reference latents.

    Each supplied image is encoded separately and appended in order to both
    conditioning branches. The output canvas uses the film's target aspect,
    rather than inheriting the dimensions of a portrait reference.
    """
    if not reference:
        raise ValueError("A composition reference is required")
    if third_reference and not second_reference:
        raise ValueError("A third reference requires the second reference")
    graph = klein_graph(prompt, seed, prefix, *KLEIN_IMAGE_SIZES[aspect])
    positive, negative = ["4", 0], ["5", 0]
    for index, image in enumerate((reference, second_reference, third_reference), start=1):
        if not image:
            continue
        load, scale, latent = f"ref{index}", f"scale{index}", f"latent{index}"
        pos, neg = f"positive{index}", f"negative{index}"
        graph[load] = node("LoadImage", image=image)
        graph[scale] = node("ImageScaleToTotalPixels", image=[load, 0], upscale_method="nearest-exact",
                            megapixels=1.0, resolution_steps=1)
        graph[latent] = node("VAEEncode", pixels=[scale, 0], vae=["3", 0])
        graph[pos] = node("ReferenceLatent", conditioning=positive, latent=[latent, 0])
        graph[neg] = node("ReferenceLatent", conditioning=negative, latent=[latent, 0])
        positive, negative = [pos, 0], [neg, 0]
    graph["8g"]["inputs"].update(positive=positive, negative=negative)
    return graph


def coverage_graph(prompt: str, seed: int, reference: str, prefix: str, aspect: str,
                   second_reference: str | None = None, keep_layout: bool = False,
                   third_reference: str | None = None, scale: float = 1.0, detailed: bool = False) -> dict[str, Any]:
    """New camera setup of the same film with Qwen-Image-Edit-2511 + 4-step Lightning.

    Picture 1 is the world, Picture 2 (optional) the cast, Picture 3 (optional) the storyboard drawing that
    sets the composition. It samples onto an empty canvas at the film's aspect rather than re-noising the
    reference. `scale` makes smaller canvases (storyboard sketches are drawn at half size).
    """
    width, height = (int(v * scale) // 16 * 16 for v in COVERAGE_SIZES[aspect])
    graph: dict[str, Any] = {
        "1": node("UNETLoader", unet_name=MODELS["qwen_edit"], weight_dtype="default"),
        "1l": node("LoraLoaderModelOnly", model=["1", 0], lora_name=MODELS["qwen_lightning"], strength_model=1.0),
        "2": node("ModelSamplingAuraFlow", model=["1l", 0], shift=3.1),
        "3": node("CFGNorm", model=["2", 0], strength=1.0),
        "4": node("CLIPLoader", clip_name=MODELS["qwen_te"], type="qwen_image", device="default"),
        "5": node("VAELoader", vae_name=MODELS["qwen_vae"]),
        "6": node("LoadImage", image=reference),
        "7": node("FluxKontextImageScale", image=["6", 0]),
        "8": node("TextEncodeQwenImageEditPlus", clip=["4", 0], vae=["5", 0], image1=["7", 0], prompt=prompt),
        "9": node("FluxKontextMultiReferenceLatentMethod", conditioning=["8", 0],
                  reference_latents_method="index_timestep_zero"),
        "10": node("TextEncodeQwenImageEditPlus", clip=["4", 0], vae=["5", 0], image1=["7", 0], prompt=""),
        "11": node("FluxKontextMultiReferenceLatentMethod", conditioning=["10", 0],
                   reference_latents_method="index_timestep_zero"),
        # an edit keeps Picture 1's layout (start from it); a new setup starts from an empty canvas
        "12": node("VAEEncode", pixels=["7", 0], vae=["5", 0]) if keep_layout else
        node("EmptySD3LatentImage", width=width, height=height, batch_size=1),
        "13": node("KSampler", model=["3", 0], positive=["9", 0], negative=["11", 0], latent_image=["12", 0],
                   seed=seed, steps=4, cfg=1.0, sampler_name="euler", scheduler="simple", denoise=1.0),
        "14": node("VAEDecode", samples=["13", 0], vae=["5", 0]),
        "15": node("SaveImage", images=["14", 0], filename_prefix=prefix),
    }
    if second_reference:
        graph["16"] = node("LoadImage", image=second_reference)
        graph["17"] = node("FluxKontextImageScale", image=["16", 0])
        for encoder in ("8", "10"):
            graph[encoder]["inputs"]["image2"] = ["17", 0]
    if third_reference:
        graph["18"] = node("LoadImage", image=third_reference)
        graph["19"] = node("FluxKontextImageScale", image=["18", 0])
        for encoder in ("8", "10"):
            graph[encoder]["inputs"]["image3"] = ["19", 0]
    if detailed:
        graph.pop("1l")
        graph["2"]["inputs"]["model"] = ["1", 0]
        graph["13"]["inputs"].update(steps=40, cfg=4.0)
    return graph


def verify_cast(graph: dict[str, Any], save: str, expected: int | None) -> dict[str, Any]:
    """Save inspectable candidates and report cast evidence; promotion belongs to the studio/director."""
    if expected is None:
        return graph
    from director import CAST_COUNT_CHECK
    image = graph[save]["inputs"]["images"]
    graph["count_model"] = writer_node()
    graph["count"] = node("TextGenerate", clip=["count_model", 0], image=image, prompt=CAST_COUNT_CHECK,
                          max_length=8, sampling_mode="off")
    graph["checked"] = node("OpenCinemaCastReview", observed=["count", 0], expected=expected)
    graph["cast_review"] = node("PreviewAny", source=["checked", 0])
    return graph


def storyboard_graph(prompt: str, seed: int, aspect: str, prefix: str, expected_cast: int | None = None,
                     backend: str = "hidream", preview: bool = False) -> dict[str, Any]:
    """Independent composition, then deterministic grayscale in both the app and exported canvas."""
    from director import SKETCH_NEGATIVE
    size = KLEIN_SKETCH_SIZES[aspect] if backend == "klein" else KLEIN_IMAGE_SIZES[aspect]
    graph = keyframe_graph(prompt, seed, aspect, prefix, size=size, negative=SKETCH_NEGATIVE, backend=backend, preview=preview)
    graph["mono"] = node("OpenCinemaMonochrome", images=["10", 0])
    graph["11"]["inputs"]["images"] = ["mono", 0]
    return verify_cast(graph, "11", expected_cast)


def frame_storyboard_graph(image: str, seed: int, aspect: str, prefix: str,
                           expected_cast: int | None = None) -> dict[str, Any]:
    from director import sketch_from_frame_prompt
    graph = coverage_graph(sketch_from_frame_prompt(), seed, image, prefix, aspect, keep_layout=True)
    graph["mono"] = node("OpenCinemaMonochrome", images=["14", 0])
    graph["15"]["inputs"]["images"] = ["mono", 0]
    return verify_cast(graph, "15", expected_cast)


def people_check_graph(image: str, question: str) -> dict[str, Any]:
    """Gemma 4 12B (8-bit) looks at an image and answers YES or NO (used to keep the world plate empty)."""
    return {
        "1": writer_node(),
        "2": node("LoadImage", image=image),
        "3": node("TextGenerate", clip=["1", 0], prompt=question, image=["2", 0], max_length=8, sampling_mode="off"),
        "answer": node("PreviewAny", source=["3", 0]),
    }


def memory_comparison_graph(source: str, plate: str, state: dict | None = None) -> dict[str, Any]:
    """Ask separate bounded visual questions about the source and prepared location."""
    location = ('Two pictures side by side: original on the left, prepared location on the right. '
                'Ignoring people and objects, are the visible room architecture, window, and materials '
                'clearly inconsistent? Answer only YES, NO, or UNKNOWN.')
    state_prompt = ('Inspect this prepared location by itself. Search for each tracked object, including small '
                    'objects on tables, counters and the floor. Does a visible object clearly contradict its '
                    'tracked location or state? Do not assume that an unseen object is correct. '
                    'Answer only YES, NO, or UNKNOWN. Facts: '
                    + json.dumps(state or {}, ensure_ascii=False))
    graph = {'model': writer_node(), 'left': node('LoadImage', image=source),
             'right': node('LoadImage', image=plate),
             'pair': node('ImageStitch', image1=['left', 0], image2=['right', 0], direction='right',
                          match_image_size=True, spacing_width=16, spacing_color='white'),
             'compare': node('TextGenerate', clip=['model', 0], image=['pair', 0], prompt=location,
                             max_length=8, sampling_mode='off'),
             'location_result': node('PreviewAny', source=['compare', 0])}
    if state:
        graph['state_compare'] = node('TextGenerate', clip=['model', 0], image=['right', 0],
                                      prompt=state_prompt, max_length=8, sampling_mode='off')
        graph['state_result'] = node('PreviewAny', source=['state_compare', 0])
    return graph


def frames_for(seconds: float, fps: int) -> int:
    """LTX wants 8n+1 frames."""
    return max(9, round(seconds * fps / 8) * 8 + 1)


def continuity_graph(context_json: str, shot_count: int) -> dict[str, Any]:
    return {
        "1": writer_node(),
        "2": node("OpenCinemaContinuityBrief", context_json=context_json),
        "3": node("TextGenerate", clip=["1", 0], prompt=["2", 0], max_length=min(6000, 500 + 450 * shot_count), sampling_mode="off"),
        "repair_brief": node("OpenCinemaContinuityRepairBrief", text=["3", 0], context_json=context_json, shot_count=shot_count),
        "repair": node("TextGenerate", clip=["1", 0], prompt=["repair_brief", 0], max_length=min(8000, 800 + 500 * shot_count), sampling_mode="off"),
        "4": node("OpenCinemaParseContinuity", text=["repair", 0], shot_count=shot_count),
        "plan": node("PreviewAny", source=["4", 0]),
        "ledger": node("OpenCinemaStateLedger", plan_json=["4", 0], shot_index=1),
        "state_before": node("PreviewAny", source=["ledger", 0]),
        "state_changes": node("PreviewAny", source=["ledger", 1]),
    }


def _review_nodes(graph: dict, prefix: str, image: list, expected_json: str, look: str, phase: str, optimize: bool = True):
    from director import CAST_COUNT_CHECK
    required = json.loads(expected_json)
    graph[prefix + "requirements"] = node("OpenCinemaReviewRequirements", expected_json=expected_json)
    expected_json = [prefix + "requirements", 0]
    graph[prefix + "brief"] = node("OpenCinemaVisualReviewBrief", expected_json=expected_json, look=look, phase=phase, style_only=True)
    graph[prefix + "vision"] = node("TextGenerate", clip=["review_model", 0], image=image,
                                    prompt=[prefix + "brief", 0], max_length=1200, sampling_mode="off")
    graph[prefix + "count"] = node("TextGenerate", clip=["review_model", 0], image=image,
                                   prompt=CAST_COUNT_CHECK, max_length=8, sampling_mode="off")
    if optimize and not required.get('state'):
        graph[prefix + 'parsed'] = node('OpenCinemaParseVisualReview', text=[prefix + 'vision', 0],
            expected_json=expected_json, observed_count=[prefix + 'count', 0])
        return  # no state facts means no fact-observation or comparison inference
    graph[prefix + "fact_briefs"] = node("OpenCinemaFactBrief", expected_json=expected_json)
    graph[prefix + "fact_observations"] = node("TextGenerate", clip=["review_model", 0], image=image,
                                               prompt=[prefix + "fact_briefs", 1], max_length=140, sampling_mode="off")
    graph[prefix + "observations"] = node("OpenCinemaAppendObservation", text=[prefix + "vision", 0],
                                          key=[prefix + "fact_briefs", 0], observation=[prefix + "fact_observations", 0])
    observations = [prefix + "observations", 0]
    graph[prefix + "compare_brief"] = node("OpenCinemaStateEvidenceBrief", text=observations, expected_json=expected_json)
    graph[prefix + "compare"] = node("TextGenerate", clip=["review_model", 0], prompt=[prefix + "compare_brief", 0],
                                     max_length=min(4096, max(1200, 220 * len(required['state']))), sampling_mode="off")
    graph[prefix + "parsed"] = node("OpenCinemaParseVisualReview", text=observations, expected_json=expected_json,
                                    observed_count=[prefix + "count", 0], state_audit=[prefix + "compare", 0])


def visual_review_graph(image: str, expected_json: str, look: str, optimize: bool = True) -> dict[str, Any]:
    graph = {"review_model": writer_node(),
             "image": node("LoadImage", image=image)}
    _review_nodes(graph, "", ["image", 0], expected_json, look, "start", optimize)
    graph["review"] = node("PreviewAny", source=["parsed", 0])
    return graph


def video_review_graph(video: str, start_json: str, middle_json: str, end_json: str, look: str, optimize: bool = True) -> dict[str, Any]:
    """Four independent visual inspections share one loaded vision model; no contact-sheet counting ambiguity."""
    graph = {"review_model": writer_node(),
             "video": node("LoadVideo", file=video), "components": node("GetVideoComponents", video=["video", 0]),
             "samples": node("OpenCinemaReviewSamples", images=["components", 0])}
    for i, (expected, phase) in enumerate(((start_json, "start"), (middle_json, "middle"),
                                          (middle_json, "middle"), (end_json, "end"))):
        _review_nodes(graph, str(i), ["samples", i], expected, look, phase, optimize)
    graph["combined"] = node("OpenCinemaCombineReviews", **{f"review_{i + 1}": [str(i) + "parsed", 0] for i in range(4)})
    graph["review"] = node("PreviewAny", source=["combined", 0])
    return graph


def shot_graph(start_image: str, prompt: str, seed: int, aspect: str, seconds: float, prefix: str,
               end_image: str | None = None, fps: int = 24, start_strength: float = 1.0,
               end_strength: float = 1.0, size: tuple[int, int] | None = None,
               performance: str = "normal") -> dict[str, Any]:
    """Image-to-video with synchronized audio; Fast decodes the single-stage draft."""
    if performance not in ("normal", "fast"):
        raise ValueError("Choose Normal or Fast performance")
    width, height = size or ASPECTS[aspect][2:]
    frames = frames_for(seconds, fps)
    graph: dict[str, Any] = {
        "1": node("LoadImage", image=start_image),
        "3": node("ImageScale", image=["1", 0], upscale_method="lanczos", width=width * 2, height=height * 2,
                  crop="center"),
        "4": node("LTXVPreprocess", image=["3", 0], img_compression=18),
        "5": node("UNETLoader", unet_name=MODELS["ltx"], weight_dtype="default"),
        "6": node("CLIPLoader", clip_name=MODELS["ltx_te"], type="ltxv", device="default"),
        "7": node("VAELoader", vae_name=MODELS["ltx_vae"]),
        "8": node("VAELoader", vae_name=MODELS["ltx_audio_vae"]),
        "9": node("CLIPTextEncode", text=prompt, clip=["6", 0]),
        "10": node("CLIPTextEncode", text="", clip=["6", 0]),  # unused: LTX samples at cfg 1
        "11": node("LTXVConditioning", positive=["9", 0], negative=["10", 0], frame_rate=float(fps)),
        "12": node("EmptyLTXVLatentVideo", width=width // 2, height=height // 2, length=frames, batch_size=1),
        "13": node("LTXVImgToVideoInplace", vae=["7", 0], image=["4", 0], latent=["12", 0],
                   strength=start_strength, bypass=False),
        "15": node("LTXVEmptyLatentAudio", frames_number=frames, frame_rate=fps, batch_size=1, audio_vae=["8", 0]),
        "18": node("RandomNoise", noise_seed=seed),
        "19": node("KSamplerSelect", sampler_name="euler_ancestral"),
        "20": node("ManualSigmas", sigmas=BASE_SIGMAS),
        "23": node("LatentUpscaleModelLoader", model_name=MODELS["ltx_upscaler"]),
        "29": node("RandomNoise", noise_seed=seed + 1),
        "30": node("KSamplerSelect", sampler_name="euler_ancestral"),
        "31": node("ManualSigmas", sigmas=REFINE_SIGMAS),
    }
    if end_image:
        # Keyframe-to-keyframe: guide the last frame so the shot lands on an exact composition.
        graph["2"] = node("LoadImage", image=end_image)
        graph["2s"] = node("ImageScale", image=["2", 0], upscale_method="lanczos", width=width * 2,
                           height=height * 2, crop="center")
        graph["2p"] = node("LTXVPreprocess", image=["2s", 0], img_compression=18)
        graph["14"] = node("LTXVAddGuide", positive=["11", 0], negative=["11", 1], vae=["7", 0], latent=["13", 0],
                           image=["2p", 0], frame_idx=-1, strength=end_strength)
        base_pos, base_neg, base_latent = ["14", 0], ["14", 1], ["14", 2]
    else:
        base_pos, base_neg, base_latent = ["11", 0], ["11", 1], ["13", 0]

    graph["16"] = node("LTXVConcatAVLatent", video_latent=base_latent, audio_latent=["15", 0])
    graph["17"] = node("LTXVDualCFGGuider", model=["5", 0], positive=base_pos, negative=base_neg,
                       video_cfg=1.0, audio_cfg=1.0)
    graph["21"] = node("SamplerCustomAdvanced", noise=["18", 0], guider=["17", 0], sampler=["19", 0],
                       sigmas=["20", 0], latent_image=["16", 0])
    graph["22"] = node("LTXVSeparateAVLatent", av_latent=["21", 0])

    if end_image:
        graph["24"] = node("LTXVCropGuides", positive=base_pos, negative=base_neg, latent=["22", 0])
        up_source, ref_pos, ref_neg = ["24", 2], ["24", 0], ["24", 1]
    else:
        up_source, ref_pos, ref_neg = ["22", 0], base_pos, base_neg
    if performance == "fast":
        graph["3"]["inputs"].update(width=width // 2, height=height // 2)
        if end_image:
            graph["2s"]["inputs"].update(width=width // 2, height=height // 2)
        for key in ("23", "29", "30", "31"):
            graph.pop(key)
        graph["34"] = node("VAEDecodeTiled", samples=up_source, vae=["7", 0], tile_size=768, overlap=64,
                           temporal_size=max(96, frames), temporal_overlap=8)
        graph["35"] = node("LTXVAudioVAEDecode", samples=["22", 1], audio_vae=["8", 0])
        graph["36"] = node("CreateVideo", images=["34", 0], fps=float(fps), audio=["35", 0])
        graph["37"] = node("SaveVideo", video=["36", 0], filename_prefix=prefix, format="mp4", codec="h264")
        return graph
    graph["24u"] = node("LTXVLatentUpsampler", samples=up_source, upscale_model=["23", 0], vae=["7", 0])
    graph["25"] = node("LTXVImgToVideoInplace", vae=["7", 0], image=["4", 0], latent=["24u", 0],
                       strength=start_strength, bypass=False)
    if end_image:
        graph["26"] = node("LTXVAddGuide", positive=ref_pos, negative=ref_neg, vae=["7", 0], latent=["25", 0],
                           image=["2p", 0], frame_idx=-1, strength=end_strength)
        refine_pos, refine_neg, refine_latent = ["26", 0], ["26", 1], ["26", 2]
    else:
        refine_pos, refine_neg, refine_latent = ref_pos, ref_neg, ["25", 0]

    graph["27"] = node("LTXVConcatAVLatent", video_latent=refine_latent, audio_latent=["22", 1])
    graph["28"] = node("LTXVDualCFGGuider", model=["5", 0], positive=refine_pos, negative=refine_neg,
                       video_cfg=1.0, audio_cfg=1.0)
    graph["32"] = node("SamplerCustomAdvanced", noise=["29", 0], guider=["28", 0], sampler=["30", 0],
                       sigmas=["31", 0], latent_image=["27", 0])
    graph["33"] = node("LTXVSeparateAVLatent", av_latent=["32", 0])
    if end_image:
        graph["33c"] = node("LTXVCropGuides", positive=refine_pos, negative=refine_neg, latent=["33", 0])
        video_latent = ["33c", 2]
    else:
        video_latent = ["33", 0]
    graph["34"] = node("VAEDecodeTiled", samples=video_latent, vae=["7", 0], tile_size=768, overlap=64,
                       temporal_size=max(96, frames), temporal_overlap=8)
    graph["35"] = node("LTXVAudioVAEDecode", samples=["33", 1], audio_vae=["8", 0])
    graph["36"] = node("CreateVideo", images=["34", 0], fps=float(fps), audio=["35", 0])
    graph["37"] = node("SaveVideo", video=["36", 0], filename_prefix=prefix, format="mp4", codec="h264")
    return graph


def master_graph(video: str, prefix: str, aspect: str = "16:9", seed: int = 42) -> dict[str, Any]:
    """SeedVR2 3B one-step restoration upscale to 1.5x the shot size (1280x704 -> 1920x1056), audio kept."""
    _, _, width, height = ASPECTS[aspect]
    return {
        "1": node("LoadVideo", file=video),
        "2": node("GetVideoComponents", video=["1", 0]),
        "3": node("ResizeImageMaskNode", input=["2", 0], scale_method="lanczos",
                  **{"resize_type": "scale dimensions", "resize_type.width": width * 3 // 2,
                     "resize_type.height": height * 3 // 2, "resize_type.crop": "disabled"}),
        "4": node("SeedVR2Preprocess", resized_images=["3", 0]),
        "5": node("UNETLoader", unet_name="seedvr2_3b_int8_convrot.safetensors", weight_dtype="default"),
        "6": node("VAELoader", vae_name="seedvr2_ema_vae_fp16.safetensors"),
        "7": node("VAEEncodeTiled", pixels=["4", 0], vae=["6", 0], tile_size=512, overlap=128,
                  temporal_size=64, temporal_overlap=8),
        # chunk in time so long films fit in VRAM; auto sizes chunks to free memory
        "8": node("SeedVR2TemporalChunk", latent=["7", 0], temporal_overlap=2, chunking_mode="auto"),
        "9": node("SeedVR2Conditioning", model=["5", 0], vae_conditioning=["8", 0]),
        "10": node("KSampler", model=["5", 0], positive=["9", 0], negative=["9", 1], latent_image=["8", 0],
                   seed=seed, steps=1, cfg=1.0, sampler_name="euler", scheduler="simple", denoise=1.0),
        "11": node("SeedVR2TemporalMerge", latents=["10", 0], temporal_overlap=["8", 1]),
        "12": node("VAEDecodeTiled", samples=["11", 0], vae=["6", 0], tile_size=512, overlap=128,
                   temporal_size=64, temporal_overlap=8),
        "13": node("SeedVR2PostProcessing", images=["12", 0], original_resized_images=["3", 0],
                   color_correction_method="lab"),
        "14": node("CreateVideo", images=["13", 0], audio=["2", 1], fps=["2", 2]),
        "15": node("SaveVideo", video=["14", 0], filename_prefix=prefix, format="mp4", codec="h264"),
    }


def motion_overlay_graph(video: str, prefix: str, node_class: str, **params: Any) -> dict[str, Any]:
    """Run one Open Cinema motion node over a clip's frames, keeping its audio and frame rate."""
    return {
        "1": node("LoadVideo", file=video),
        "2": node("GetVideoComponents", video=["1", 0]),
        "3": node(node_class, images=["2", 0], fps=["2", 2], **params),
        "4": node("CreateVideo", images=["3", 0], audio=["2", 1], fps=["2", 2]),
        "5": node("SaveVideo", video=["4", 0], filename_prefix=prefix, format="mp4", codec="h264"),
    }


def cards_graph(lines: str, look: str, width: int, height: int, prefix: str, seconds_per_card: float = 1.1,
                fps: float = 24.0, seed: int = 5, palette: str = "") -> dict[str, Any]:
    """Full-frame kinetic type cards (trailer lines, title card, credits) as a silent clip."""
    return {
        "1": node("OpenCinemaCards", lines=lines, look=look, width=width, height=height, fps=fps,
                  seconds_per_card=seconds_per_card, seed=seed, palette=palette),
        "2": node("CreateVideo", images=["1", 0], fps=fps),
        "3": node("SaveVideo", video=["2", 0], filename_prefix=prefix, format="mp4", codec="h264"),
    }


def title_preview_graph(title: str, look: str, prefix: str, width: int = 1280, height: int = 704,
                        palette: str = "") -> dict[str, Any]:
    return {
        "1": node("OpenCinemaTitlePreview", title=title, look=look, width=width, height=height, palette=palette),
        "2": node("SaveImage", images=["1", 0], filename_prefix=prefix),
    }


def title_frame_graph(prompt: str, seed: int, frame: str, prefix: str, title: str, look: str) -> dict[str, Any]:
    """In-world title: Qwen-Image-Edit-2511 + Lightning edits the establishing frame itself (latent from the
    frame, unlike coverage) so the scene is kept. Picture 2 is the title set in the film's typeface by the
    Open Cinema Type Sheet node: copying letterforms is far more reliable than spelling from a prompt."""
    graph = coverage_graph(prompt, seed, frame, prefix, "16:9")
    graph["12"] = node("VAEEncode", pixels=["7", 0], vae=["5", 0])
    graph["13"]["inputs"]["steps"] = 6  # a couple of extra steps sharpen the lettering
    graph["16"] = node("OpenCinemaTypeSheet", title=title, look=look, width=1344, height=768)
    for encoder in ("8", "10"):
        graph[encoder]["inputs"]["image2"] = ["16", 0]
    return graph


SCORE_SIZE = (768, 448)  # the trailer score only needs LTX's audio, so the picture is rendered small


def score_graph(start_image: str, prompt: str, seed: int, seconds: float, prefix: str) -> dict[str, Any]:
    """A continuous LTX 2.5 soundtrack for the trailer: one long, small render whose audio is the score. Only
    the sound is decoded and saved: decoding a trailer's worth of frames in one tile overflows the GPU."""
    graph = shot_graph(start_image, prompt, seed, "16:9", seconds, prefix, size=SCORE_SIZE)
    for key in ("34", "36", "37"):  # the picture decode, and the video it would have made
        del graph[key]
    graph["37"] = node("SaveAudio", audio=["35", 0], filename_prefix=prefix)
    return graph


def lead_writer_graph(mode: str, title: str, world: str, look: str, draft: str = "", photo: str | None = None,
                      seed: int = 1) -> dict[str, Any]:
    """Gemma 4 12B (8-bit) writes the lead (and continuity notes) through ComfyUI's native TextGenerate."""
    graph = {
        "1": writer_node(),
        "2": node("OpenCinemaLeadBrief", mode=mode, title=title, world=world, look=look, draft=draft),
        "3": node("TextGenerate", clip=["1", 0], prompt=["2", 0], max_length=320, sampling_mode="on",
                  **{"sampling_mode.temperature": 0.65, "sampling_mode.top_k": 64, "sampling_mode.top_p": 0.95,
                     "sampling_mode.min_p": 0.05, "sampling_mode.repetition_penalty": 1.05,
                     "sampling_mode.seed": seed}),
        "4": node("OpenCinemaParseLead", text=["3", 0]),
        "lead": node("PreviewAny", source=["4", 0]),
        "continuity": node("PreviewAny", source=["4", 1]),
    }
    if photo:
        graph["5"] = node("LoadImage", image=photo)
        graph["3"]["inputs"]["image"] = ["5", 0]
    return graph


def shot_writer_graph(mode: str, title: str, logline: str, world: str, look: str, lead: str, continuity: str,
                      shots: str, index: int = 1, count: int = 5, seed: int = 1, beats: str = "",
                      write_beats: str = "", characters: str = "", dialogue_mode: str = "auto", idea: str = "") -> dict[str, Any]:
    """Gemma 4 12B (8-bit) writes the storyboard (or the next shot, or one shot again) through ComfyUI's TextGenerate."""
    graph = {
        "1": writer_node(),
        "2": node("OpenCinemaShotsBrief", mode=mode, count=count, index=index, title=title, logline=logline,
                  world=world, look=look, lead=lead, continuity=continuity, beats=beats, shots=shots,
                  write_beats=write_beats, characters=characters, dialogue_mode=dialogue_mode, idea=idea),
        "3": node("TextGenerate", clip=["1", 0], prompt=["2", 0], max_length=320 * count if mode == "board" else 400,
                  sampling_mode="on",
                  **{"sampling_mode.temperature": 0.75, "sampling_mode.top_k": 64, "sampling_mode.top_p": 0.95,
                     "sampling_mode.min_p": 0.05, "sampling_mode.repetition_penalty": 1.05,
                     "sampling_mode.seed": seed}),
        "4": node("OpenCinemaParseShots", text=["3", 0], lead_description=lead),
        "shots": node("PreviewAny", source=["4", 0]),
        "storyboard": node("PreviewAny", source=["4", 1]),
        "new_beats": node("PreviewAny", source=["4", 2]),
    }
    if mode != "beat":
        graph["review_brief"] = node("OpenCinemaReviewShotsBrief", brief=["2", 0], draft=["3", 0])
        graph["review"] = node("TextGenerate", **{**graph["3"]["inputs"], "prompt": ["review_brief", 0],
                                                  "sampling_mode.temperature": 0.35})
        graph["4"]["inputs"]["text"] = ["review", 0]
    return graph


def story_writer_graph(target: str, idea: str, title: str, logline: str, world: str, look: str, lead: str,
                       seed: int = 1, beats: str = "", count: int = 3, characters: str = "",
                       avoid_title_words: str = "") -> dict[str, Any]:
    """Gemma 4 12B (8-bit) develops the story page (or one field of it) through ComfyUI's native TextGenerate."""
    graph = {
        "1": writer_node(),
        "2": node("OpenCinemaStoryBrief", target=target, idea=idea, title=title, logline=logline, world=world,
                  look=look, lead=lead, beats=beats, count=count, characters=characters, creative_seed=seed,
                  avoid_title_words=avoid_title_words),
        "3": node("TextGenerate", clip=["1", 0], prompt=["2", 0], max_length=1500 if target == "everything" else 360,
                  sampling_mode="on",
                  **{"sampling_mode.temperature": 0.8 if target == "everything" else 0.75, "sampling_mode.top_k": 64,
                     "sampling_mode.top_p": 0.95, "sampling_mode.min_p": 0.05,
                     "sampling_mode.repetition_penalty": 1.05, "sampling_mode.seed": seed}),
        "4": node("OpenCinemaParseStory", text=["3", 0], target=target, idea=["2", 1]),
    }
    for index, field in enumerate(("title", "logline", "world", "look", "palette", "lead", "continuity", "trailer",
                                   "beats", "characters")):
        graph[field] = node("PreviewAny", source=["4", index])
    if target in ("everything", "title"):
        graph["title_brief"] = node("OpenCinemaTitleBrief", idea=idea,
                                    story=["3", 0] if target == "everything" else "\n".join((logline, world, beats)),
                                    avoid_words=avoid_title_words)
        graph["title_candidates"] = node("TextGenerate", **{**graph["3"]["inputs"], "prompt": ["title_brief", 0], "max_length": 300})
        graph["title_selected"] = node("OpenCinemaSelectTitle", text=["title_candidates", 0], avoid_words=avoid_title_words, idea=idea)
        graph["title"]["inputs"]["source"] = ["title_selected", 0]
    return graph
