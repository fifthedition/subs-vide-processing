# Breathwork Studio

Edit Slovak meditation prompts in a browser, synchronize them with a separate music-only track, and export a teleprompter video. The video shows fixed previous/current/next text, elapsed time, remaining music time and a prompt countdown. The guide speaks live; no narrator voice is added.

The NAS hosts the editor and stores projects, audio, exports and the persistent queue. An editor clicks **Send for export**. The owner later launches **Render-Queued-Videos.command** on a Mac. The Mac connects to the NAS over HTTPS, renders queued jobs one at a time, uploads the MP4s, and exits when the queue is empty. There is no daemon, login item, inbound Mac port or scheduled poll.

- [Deploy on Synology and configure Nginx Proxy Manager](docs/NAS-SETUP.md)
- [Pair and run the Mac renderer](docs/MAC-RENDERER.md)
- [Microphone check, narration, Adobe processing and final mix](docs/NARRATION.md)
- [Publish the public Docker image](docs/RELEASING.md)
- [Architecture, recovery and access controls](docs/ARCHITECTURE.md)
- [Verification and remaining deployment checks](VERIFICATION.md)

## Local editing

Requires Python 3.11+, Pillow and FFmpeg/ffprobe. Double-click **Start-Breathwork-Studio.command**, or run:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py --open
```

Open <http://127.0.0.1:8787>. Local mode binds to localhost and renders on the same computer. Use authenticated server mode for NAS hosting.

A clean installation starts empty. Import `examples/sample-session.json`, add `examples/synthetic-test-audio.wav`, and export an eight-second test. The longer sample is `examples/teleprompter-session.json` with `examples/teleprompter-test-audio.wav`. These files contain original synthetic test material.

Private subtitle archives are deliberately excluded from this repository and the public image. To migrate the existing app with all preserved English/Slovak documents and corrections, follow the NAS guide. Existing archives can also be mounted privately as `data/subtitles.json`.

Completed exports show their full date, time and timezone. Downloads include the saved revision, export timestamp with UTC offset, and a short export ID in the filename. Dates use the browser’s timezone, including for older migrated exports.

## Narration

Completed guides are playable in the app. Editors can independently check their microphone, record a high-quality WAV while watching a guide, pause/resume, replace sections and undo. Original takes and a full-timeline master WAV remain on the NAS. After manual Adobe Podcast enhancement, upload the processed voice, check alignment and levels, then queue a final Mac mix. Final exports copy the existing subtitle video and retain stereo music. See [the narration guide](docs/NARRATION.md).

## Editing and drafts

The Clear light editor uses a navy sidebar, white panels, blue actions, larger subtitle text and visible input borders. The interface defaults to Slovak; the SK/EN switch on the editor and sign-in page remembers the language on that browser. Interface language does not alter session titles, subtitle/reference text, audio or the Slovak labels in the exported video.

The editor supports timed cue editing, split/merge, undo, automatic saving with revision conflict detection, SRT/VTT/JSON imports, subtitle downloads, project backups, reference text/audio, music upload, waveform seeking, prompt offsets, video theme/font selection and fullscreen presentation. New JSON imports create a separate session.

All new exports are **1920 × 1080**, H.264 at CRF 16. Older 720p projects open and export in Full HD without changing cue text, timing or revision. Already completed files remain available as originally rendered.

Exports always have **two audio channels**. Stereo AAC is copied unchanged, preserving the original audio quality and sample rate. Other formats are encoded to AAC at a 320 kb/s target, retaining the source sample rate where AAC supports it (otherwise the nearest supported rate). Stereo left/right channels remain separate; no normalization or voice is added. Mono is duplicated into both channels at the original level; it cannot create a spatial stereo recording. Multichannel sources use FFmpeg's stereo downmix. Lossless WAV/FLAC bit depth cannot be inherited by lossy AAC. Actual AAC bitrate depends on content.

Optional ElevenLabs and DeepL keys are configured by the owner in **Services & API keys**. Creating an audio draft sends the source recording to ElevenLabs for timed transcription and sends text to DeepL for Slovak translation. Charges can apply. No provider call is made just by saving keys. Review drafts before guiding live. Source recordings remain available for review and cannot be selected as the final music track.

## Development

```sh
.venv/bin/python -m unittest discover -s tests -v
node --check static/app.js
node --check static/login.js
node --check static/i18n.js
npm ci --ignore-scripts
npm test
```

CI runs the suite, builds the Linux image and checks its startup/authentication defaults. A private archive regression runs only when `STUDIO_CATALOG` points to that archive. Synthetic archive tests run publicly.

App and renderer compatibility version: **0.6.0**, protocol 1. Update both the NAS image and Mac checkout for the narration and final-mix jobs; the existing Keychain pairing stays valid. Drain old queued exports before updating, or cancel and send them again afterward. The open Inter font is included with its OFL license in `static/assets/Inter-OFL.txt`. Node/jsdom are development test dependencies only; the NAS and Mac renderer do not require Node.
