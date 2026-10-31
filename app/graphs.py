"""ComfyUI API-format graphs for Open Cinema Studio.

Every graph uses only core ComfyUI nodes and permissively licensed open-weights models:
HiDream-O1-Image (MIT) for keyframes and cast portraits, Qwen-Image-Edit-2511 (Apache-2.0)
for multi-reference coverage that keeps the cast and set consistent, LTX 2.5 for
image-to-video with native audio, and SeedVR2 (Apache-2.0) for the 1080p master.
"""

from __future__ import annotations

from typing import Any

MODELS = {
    "hidream": "hidream_o1_image_fp8_scaled.safetensors",
    "qwen_edit": "qwen_image_edit_2511_int8_convrot.safetensors",
    "qwen_te": "qwen_2.5_vl_7b_fp8_scaled.safetensors",
    "qwen_vae": "qwen_image_vae.safetensors",
    "qwen_lightning": "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors",
    "ltx": "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors",
    "ltx_te": "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors",
    "ltx_vae": "ltx-2.5-video-vae-bf16.safetensors",
    "ltx_audio_vae": "ltx-2.5-audio-vae-bf16.safetensors",
    "ltx_upscaler": "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors",
    "writer": "gemma4_e4b_it_fp8_scaled.safetensors",  # Gemma 4 E4B-it (Apache-2.0), text + image understanding
}

# Distilled two-stage schedule: base pass at half resolution, x2 latent
# upscale, short refine pass at full resolution.
BASE_SIGMAS = "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"
REFINE_SIGMAS = "0.85, 0.725, 0.4219, 0.0"

KEYFRAME_NEGATIVE = ("illustration, painting, cartoon, anime, 3d render, CGI, video game, oversaturated, HDR, "
                     "low quality, blurry, deformed, extra limbs, extra fingers, plastic skin, readable text, "
                     "caption, subtitles, watermark, logo, frame border, split screen, collage, "
                     "film camera, camera rig, film crew, lighting equipment")
SHOT_NEGATIVE = ("warped anatomy, duplicate limbs, melted face, identity drift, morphing, "
                 "flicker, jump cut, scene change, text, caption, subtitle, watermark, logo")

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


def node(class_type: str, **inputs: Any) -> dict[str, Any]:
    return {"class_type": class_type, "inputs": inputs}


def keyframe_graph(prompt: str, seed: int, aspect: str, prefix: str,
                   size: tuple[int, int] | None = None) -> dict[str, Any]:
    """HiDream-O1-Image text-to-image, official Full recipe: 40 steps, cfg 5, seam smoothing."""
    width, height = size or ASPECTS[aspect][:2]
    return {
        "1": node("CheckpointLoaderSimple", ckpt_name=MODELS["hidream"]),
        "2": node("ModelNoiseScale", model=["1", 0], noise_scale=8.0),
        "3": node("HiDreamO1PatchSeamSmoothing", model=["2", 0], start_percent=0.8, end_percent=1.0,
                  pattern="single_shift", passes="ramp_2_4", blend="median", strength=1.0),
        "4": node("CLIPTextEncode", clip=["1", 1], text=prompt),
        "5": node("CLIPTextEncode", clip=["1", 1], text=KEYFRAME_NEGATIVE),
        "6": node("EmptyHiDreamO1LatentImage", width=width, height=height, batch_size=1),
        "7": node("BasicScheduler", model=["2", 0], scheduler="normal", steps=40, denoise=1.0),
        "8": node("KSamplerSelect", sampler_name="dpmpp_2m_sde_gpu"),
        "9": node("SamplerCustom", model=["3", 0], add_noise=True, noise_seed=seed, cfg=5.0, positive=["4", 0],
                  negative=["5", 0], sampler=["8", 0], sigmas=["7", 0], latent_image=["6", 0]),
        "10": node("VAEDecode", samples=["9", 0], vae=["1", 2]),
        "11": node("SaveImage", images=["10", 0], filename_prefix=prefix),
    }


def coverage_graph(prompt: str, seed: int, reference: str, prefix: str, aspect: str,
                   second_reference: str | None = None, keep_layout: bool = False) -> dict[str, Any]:
    """New camera setup of the same film with Qwen-Image-Edit-2511 + 4-step Lightning.

    Picture 1 is the world, Picture 2 (optional) the cast. It samples onto an empty canvas at
    the film's aspect rather than re-noising the reference, so the references steer identity
    and world but not the composition.
    """
    width, height = COVERAGE_SIZES[aspect]
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
    return graph


def people_check_graph(image: str, question: str) -> dict[str, Any]:
    """Gemma 4 E4B looks at an image and answers YES or NO (used to keep the world plate empty)."""
    return {
        "1": node("CLIPLoader", clip_name=MODELS["writer"], type="stable_diffusion", device="default"),
        "2": node("LoadImage", image=image),
        "3": node("TextGenerate", clip=["1", 0], prompt=question, image=["2", 0], max_length=8, sampling_mode="off"),
        "answer": node("PreviewAny", source=["3", 0]),
    }


def frames_for(seconds: float, fps: int) -> int:
    """LTX wants 8n+1 frames."""
    return max(9, round(seconds * fps / 8) * 8 + 1)


def shot_graph(start_image: str, prompt: str, seed: int, aspect: str, seconds: float, prefix: str,
               end_image: str | None = None, fps: int = 24, start_strength: float = 1.0,
               end_strength: float = 1.0, size: tuple[int, int] | None = None) -> dict[str, Any]:
    """Image-to-video shot with synchronized audio, two-stage distilled LTX 2.5."""
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
        "10": node("CLIPTextEncode", text=SHOT_NEGATIVE, clip=["6", 0]),
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
    """A continuous LTX 2.5 soundtrack for the trailer: one long, small render whose audio is the score."""
    return shot_graph(start_image, prompt, seed, "16:9", seconds, prefix, size=SCORE_SIZE)


def lead_writer_graph(mode: str, title: str, world: str, look: str, draft: str = "", photo: str | None = None,
                      seed: int = 1) -> dict[str, Any]:
    """Gemma 4 E4B writes the lead (and continuity notes) through ComfyUI's native TextGenerate."""
    graph = {
        "1": node("CLIPLoader", clip_name=MODELS["writer"], type="stable_diffusion", device="default"),
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


def story_writer_graph(target: str, idea: str, title: str, logline: str, world: str, look: str, lead: str,
                       seed: int = 1) -> dict[str, Any]:
    """Gemma 4 E4B develops the story page (or one field of it) through ComfyUI's native TextGenerate."""
    graph = {
        "1": node("CLIPLoader", clip_name=MODELS["writer"], type="stable_diffusion", device="default"),
        "2": node("OpenCinemaStoryBrief", target=target, idea=idea, title=title, logline=logline, world=world,
                  look=look, lead=lead),
        "3": node("TextGenerate", clip=["1", 0], prompt=["2", 0], max_length=900 if target == "everything" else 320,
                  sampling_mode="on",
                  **{"sampling_mode.temperature": 0.8 if target == "everything" else 0.75, "sampling_mode.top_k": 64,
                     "sampling_mode.top_p": 0.95, "sampling_mode.min_p": 0.05,
                     "sampling_mode.repetition_penalty": 1.05, "sampling_mode.seed": seed}),
        "4": node("OpenCinemaParseStory", text=["3", 0], target=target),
    }
    for index, field in enumerate(("title", "logline", "world", "look", "palette", "lead", "continuity", "trailer")):
        graph[field] = node("PreviewAny", source=["4", index])
    return graph
