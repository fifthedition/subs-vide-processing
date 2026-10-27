# Verification — 0.5.0

Local verification uses macOS, Python 3.14, Pillow 13, FFmpeg/ffprobe and Node. GitHub Actions repeats the tests on Linux, builds the image, and checks an empty protected container. CI results are recorded in the pull request.

## Interface

Six DOM integration tests exercise the real HTML and JavaScript with synthetic API fixtures:

- Slovak default, English preference, static labels, placeholders, accessible names, export stages and validation messages.
- Repeated SK/EN switches with dirty subtitle edits and an unfinished invalid time; no project mutation, save request, lost selection or audio reload.
- Session names, source/reference text, music names, usernames and entered API keys stay intact.
- Settings and account dialogs, empty-workspace import, sign-in and first-owner setup.
- SVG favicon and the Full HD output control.

JavaScript syntax checks include the shared translation module. These are DOM tests, not a real-browser visual or playback test; the responsive layout and fullscreen still need a deployed browser check.

## Rendering and queue

Thirty Python tests cover editing, imports, persistence, revision conflicts, account/CSRF/role boundaries, provider mocks, resumable uploads and durable claims/recovery. One private archive regression is intentionally skipped without the private archive.

Real FFmpeg tests verify:

- New output is 1920 × 1080 H.264 with two audio channels, including legacy 720p projects and mono sources.
- 44.1 kHz stereo is retained, and independent 440/880 Hz tones stay in the correct left/right channels.
- Stereo AAC source and MP4 output have identical audio packet hashes.
- Mono is duplicated at its original level into both channels.
- Fixed previous/current/next areas, timers, countdowns, gaps and offset boundaries match decoded frames at Full HD.
- The supplied music remains the sole audible source.
- A real eight-second HTTP queue → Mac worker → FFmpeg → upload → download round trip completes, then the foreground worker exits on an empty queue.
- Export download names retain dates, saved revisions, timezone offsets and IDs; range downloads work.
- Favicon and translations are available before sign-in while project APIs remain protected.

No paid provider request or full-length render benchmark was performed. Automated tests use isolated synthetic data and never modify the NAS, the existing private archive, service keys or Mac Keychain. Public Docker copies use the existing source allowlist; data, subtitles, music, databases and credentials stay excluded.

## Deployment

Update the NAS image and Mac checkout together to 0.5.0; existing accounts, private data and renderer pairing remain valid. Drain the previous queue first, or cancel and send older queued exports again afterward. Retain the current NAS data volume. Existing completed exports are unchanged.

The NAS was already running 0.4.1 with working HTTPS, owner/editor accounts and a paired Mac render round trip. This release's browser appearance, full-length music and large proxy transfers need a check after the image update.
