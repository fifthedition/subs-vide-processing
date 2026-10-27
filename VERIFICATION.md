# Verification — 0.6.0

Local checks use macOS, Python 3.14, Pillow 13, FFmpeg/ffprobe and Node. GitHub Actions repeats the suite on Linux, builds the public image, and checks first boot and authenticated empty defaults. CI results are recorded in the pull request.

## Results

- 37 Python tests, with the optional private archive regression skipped when its archive is absent.
- 13 JavaScript DOM/audio-worklet/storage tests.
- JavaScript/Python syntax and Git diff checks.
- All fixtures are synthetic and isolated from the actual NAS and Keychain.

The original import/editing, account/CSRF/role, provider mocks, resumable upload, immutable queue/recovery and guide-render checks remain in place. No paid provider request is made.

## Narration

Tests cover:

- Private chunked 24-bit mono PCM upload, account scope, repeated/mismatched chunks, exact byte count, restart recovery and idempotent finish.
- Non-destructive punch-in: old left/right portions retain their source sample offsets, silence remains in place, and undo restores the earlier timeline.
- A full-duration 48 kHz/24-bit WAV master, including gaps; 44.1 kHz browser input is resampled without changing its timeline.
- Conflict handling retains audio. Retakes invalidate enhanced audio; saving levels cannot silently make an older enhancement current.
- Final jobs freeze the guide subtitle revision, enhanced-audio hash, offset and levels. Changed settings cannot replace an already queued snapshot.
- A real HTTP editor recording → private WAV master → enhanced upload → final queue → native Mac worker → chunked upload → authenticated final MP4 download round trip.
- Final mixing copies video packet hashes unchanged, retains independent left/right music, places mono voice in both channels, applies its offset and preserves video duration.
- Browser PCM encoding/clamping, pause flush, silent microphone output, actual sample-rate settings and processing constraints.
- Permission denial and an independent mic test that never creates a narration or uploads its audio.
- IndexedDB persistence across recorder instances, removal of acknowledged chunks and in-memory retention when a storage write fails.
- Pause/resume, language switching during capture, network failure/retry, buffering and playback-speed interruptions.

## Browser and deployment acceptance

The implementation uses standard APIs available in current desktop Chrome, Safari and Firefox: getUserMedia, AudioWorklet, Web Audio, IndexedDB, WAV and native video. Sources checked include [MDN microphone permissions](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia), [AudioWorkletNode](https://developer.mozilla.org/en-US/docs/Web/API/AudioWorkletNode), [device enumeration](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/enumerateDevices) and [reported track settings](https://developer.mozilla.org/en-US/docs/Web/API/MediaStreamTrack/getSettings).

DOM/worklet fixtures exercise the application code; physical microphone permissions, browser real-time clocks, hardware playback and the visual layout need an actual-device check in each browser. No hour-long microphone benchmark or live Adobe processing was performed.

Update NAS and Mac code together to **0.6.0**. Retain the current private data volume and existing renderer pairing. Completed Full HD guides remain usable; older queued jobs must be cancelled/resubmitted after upgrading (or drained before the upgrade). First verify a short take, pause/resume, a replacement range, WAV download, enhanced upload and final mix; then test a complete session.

The public image uses explicit code/static copies and the existing context allowlist. Original subtitles, databases, microphone audio, masters, enhanced files, exports, API keys and worker credentials are runtime private data, never image or source contents. Automated tests do not alter the deployed NAS, proxy or user Keychain.
