# Demo video script (about 2.5 minutes)

The judges look at the work, not the editing. Keep it as a screen recording with voice-over.
Hero film: `docs/media/the-colossus-pass.mp4` (6 shots, about 30 s, 1080p master). Second sample: `night-courier.mp4`.

**0:00 – 0:12 · Hook.** Play the first 12 seconds of *The Colossus Pass* with sound: the drone push between the stone kings, then the rope bridge.
> "A lone ranger, two colossal stone kings and a storm. Six shots with camera moves and sound, made from a shot list on one laptop GPU, with open models only. This is Open Cinema Studio."

**0:12 – 0:30 · The idea.**
> "Cinema-studio apps let you direct AI shots, but they're closed. Open Cinema rebuilds that on ComfyUI with HiDream-O1, Qwen-Image-Edit-2511, LTX 2.5 and SeedVR2. Every model is open and permissively licensed, there are no partner nodes or APIs, and the code is MIT."

Show the studio: the world, the lead character, the *70mm epic* look.

**0:30 – 0:50 · Casting.** Show the ranger's cast portrait.
> "First we cast the lead. HiDream-O1 renders a reference portrait from the description: crimson cloak, braid, silver circlet. Or you drop in a photo of a real actor."

**0:50 – 1:20 · Directing.** Scroll the shot list. Change a camera move and point out the live viewfinder animation. Untick **Lead** on the stone-king shot.
> "Every shot is a size, a camera move, an action and a sound. A keyframe is the first frame of its camera move, so a drone shot starts as an aerial view. Shots without the lead, like this stone king, are kept free of people."

**1:20 – 1:40 · Consistency.** Show `docs/media/the-colossus-pass-keyframes.jpg`.
> "Every keyframe after the first is Qwen-Image-Edit-2511 working from two references: the establishing frame for the world and light, and the cast portrait for her face and wardrobe. It renders onto a blank canvas, so we get new camera setups instead of copies."

**1:40 – 2:00 · Motion, sound and camera paths.** Play the bridge shot and the beacon lighting. Briefly show `03_shot_ltx25_i2v_audio.json` in ComfyUI.
> "LTX 2.5 animates each keyframe and generates the audio in the same pass. For forward moves like drone shots and dollies, the studio builds a camera-path guide, a zoomed end frame, so the camera really travels instead of drifting."

**2:00 – 2:15 · Takes and mastering.** Click between the takes on the opening drone shot, then press **Master in 1080p**.
> "Nothing gets overwritten. Every re-roll is a take you can pick from, like on set. SeedVR2 then masters each shot to 1080p and re-cuts the film."

**2:15 – 2:35 · Titles & Motion.** Open the **Titles & Motion** panel. Switch the main title to **In-world (AI)** and show the title carved into the canyon, then toggle stamps and credits, press **Cut trailer** and play it.
> "The title can be kinetic type in the film's look, or built into the world itself: here it's carved in stone by Qwen-Image-Edit, spelled right because our type sheet node hands it the exact lettering. The trailer cut puts tagline cards between shots, and every cut lands on a sound hit in the film's own audio."

**2:35 – 2:45 · Close.** Play the beacon finale and credits of the 1080p master, then show the GitHub repo.
> "Fork it, add camera moves, add looks. It's all open."
