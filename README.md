# Breathwork Studio

Edit Slovak meditation prompts in a browser, synchronize them with a separate music-only track, and export a teleprompter video. The video shows fixed previous/current/next text, elapsed time, remaining music time and a prompt countdown. The guide speaks live; no narrator voice is added.

The NAS hosts the editor and stores projects, audio, exports and the persistent queue. An editor clicks **Send for export**. The owner later launches **Render-Queued-Videos.command** on a Mac. The Mac connects to the NAS over HTTPS, renders queued jobs one at a time, uploads the MP4s, and exits when the queue is empty. There is no daemon, login item, inbound Mac port or scheduled poll.

- [Deploy on Synology and configure Nginx Proxy Manager](docs/NAS-SETUP.md)
- [Pair and run the Mac renderer](docs/MAC-RENDERER.md)
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

## Editing and drafts

The editor supports timed cue editing, split/merge, undo, automatic saving with revision conflict detection, SRT/VTT/JSON imports, subtitle downloads, project backups, reference text/audio, music upload, waveform seeking, prompt offsets, theme/font/resolution selection and fullscreen presentation. New JSON imports create a separate session.

Optional ElevenLabs and DeepL keys are configured by the owner in **Services & API keys**. Creating an audio draft sends the source recording to ElevenLabs for timed transcription and sends text to DeepL for Slovak translation. Charges can apply. No provider call is made just by saving keys. Review drafts before guiding live. Source recordings remain available for review and cannot be selected as the final music track.

## Development

```sh
.venv/bin/python -m unittest discover -s tests -v
node --check static/app.js
node --check static/login.js
```

CI runs the suite, builds the Linux image and checks its startup/authentication defaults. A private archive regression runs only when `STUDIO_CATALOG` points to that archive. Synthetic archive tests run publicly.

Version: **0.4.0**. Server and worker versions must match. The open Inter font is included with its OFL license in `static/assets/Inter-OFL.txt`.
