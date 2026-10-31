# Brag plan — industrial equipment identification backend demo

## Nine-question inspection rubric
1. App: local nameplate detection/OCR feeding a factory asset/evidence workflow.
2. Grounded claim: the trained ONNX export matched its reference and returned regions on four public photos; warm CPU detector time was 72–75 ms.
3. Visual hook: the actual current-transformer photo with its actual detected rectangle.
4. Actual material: photo, ROI, raw OCR text, detector score, insufficient-evidence status. No finished frontend exists; every result panel is a presentation view.
5. Shortest satisfying film: 22 seconds, landscape 1920×1080 at 30 fps.
6. Tone: polished; restrained industrial documentation brought into motion.
7. Audio: low vol-12 Sascha Ende music bed and three quiet action accents. No narration.
8. Caption: A real nameplate photo through local detection and OCR; identity confirmation stays human. Backend demo, web interface in progress.
9. Flow: photo → region detection → raw OCR → human confirmation required.

## Angle and look
Hook: "Read the plate. Keep the evidence." No invented product name or finished frontend claim.
LOOK: #111C22 steel ground, #F4F1E9 text, #F2C14E amber, #B8C5CB secondary text; DejaVu Sans Bold display 78–88px, DejaVu Sans body 30–36px, DejaVu Sans Mono labels 28px; 2px rules, 18px panel corners. These are presentation tokens; no frontend brand spec exists.
BANNED: approval ticks, fabricated serial matches, field-accuracy claims, generic effects, floating titles and voiceover.

## Storyboard — total 22s
- 0–4.39: actual photo arrives beside the hook. Hold the copy. Label "Backend demo / presentation view". Photo handoff on beat grid.
- 4.39–10.93: enlarge photo into review canvas. Draw actual [357.219,212.375,1529.691,838.521] box in 1600×900 coordinates; class nameplate, score 0.926. Outline lands on global 8.74s strong cue. Measured music bands affect only border opacity.
- 10.93–17.47: actual crop and two actual low-confidence raw OCR lines arrive separately, then "Needs human confirmation / No verified tag or serial". Hold text for readability. No success cue.
- 17.47–22: "Photo → plate → evidence", scoped "72–75 ms / warm CPU detector / 4 public-image smoke cases", final "Identity confirmation stays human". Show frontend-in-progress disclosure and image/music credits. Final title holds over 2 seconds.

## Audio and cue guidance
Sascha Ende, Happy Beats / Business Moves vol-12, CC BY 4.0, 0.20 gain, fade in 0.4s / out 1.5s. Kenney CC0 quiet click and soft impacts. 109.96 BPM preset read. Strong cues at 8.74s and 17.47s; 4.39s scene handoff on beat grid. Natural timing wins for legibility. No voiceover. Audio-reactive extraction uses Hyperframes media-use's official extract-audio-data.py at 30fps; no audio or private data is uploaded.
