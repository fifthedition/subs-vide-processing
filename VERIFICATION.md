# Verification — 0.7.0

Local checks use macOS, Python 3.14, Pillow 13, FFmpeg/ffprobe and Node. GitHub Actions repeats the suite on Linux, builds the public image, and checks first boot and authenticated empty defaults. CI results are recorded in the pull request.

## Results

- 52 Python tests, with the optional private archive regression skipped when its archive is absent.
- 31 JavaScript DOM/audio-worklet/storage/workspace tests.
- JavaScript/Python syntax and Git diff checks.
- All fixtures are synthetic and isolated from the actual NAS and Keychain.

The original import/editing, account/CSRF/role, provider mocks, resumable upload, immutable queue/recovery and guide-render checks remain in place. No paid provider request is made.

## Shutdown

Five new process-level tests exercise TERM/INT exit 0, idle sockets, in-flight request completion and 503 for late admission, cancellation of pending work across all three pools, and a logged non-zero deadline for a deliberately stalled task followed by restart with the project retained. All use synthetic data in isolated temporary directories.

The Docker smoke test runs the actual entry point, asserts SIGTERM exits 0 before Docker's forced-kill deadline, restarts and signs in to the existing synthetic owner/project, tests incomplete headers, and repeats stop with Python as PID 1 without Docker init. CI uses init for the primary container to match NAS Compose. These checks do not reproduce or prove a Synology management-interface defect.

## Narration

Tests cover:

- Private chunked 24-bit mono PCM upload, account scope, repeated/mismatched chunks, exact byte count, restart recovery and idempotent finish.
- Non-destructive punch-in: old left/right portions retain their source sample offsets, silence remains in place, and undo restores the earlier timeline.
- A full-duration 48 kHz/24-bit WAV master, including gaps; 44.1 kHz browser input is resampled without changing its timeline.
- Conflict handling retains audio. Retakes invalidate enhanced audio; saving levels cannot silently make an older enhancement current.
- Final jobs freeze the guide subtitle revision, enhanced-audio hash, offset and levels. Changed settings cannot replace an already queued snapshot.
- A real HTTP editor recording → private WAV master → enhanced upload → final queue → native Mac worker → chunked upload → authenticated final MP4 download round trip.
- Final mixing copies video packet hashes unchanged, retains independent left/right music through the final audio tail, places mono voice in both channels, applies its offset and preserves guide duration even when its video packets end earlier than its music.
- Browser PCM encoding/clamping, pause flush, silent microphone output, actual sample-rate settings and processing constraints.
- Permission denial and an independent mic test that never creates a narration or uploads its audio.
- IndexedDB persistence across recorder instances, removal of acknowledged chunks and in-memory retention when a storage write fails.
- Pause/resume, language switching during capture, network failure/retry, buffering and playback-speed interruptions.
- Preview levels without repeated decoder seeks; late WAV metadata, pending playback/seek, direct user-gesture retry after autoplay rejection, inline decode/network errors, source changes and enhanced offsets. These are simulated media-element tests, not actual Firefox audio decoding.

## Workspace and recording review

New integration/DOM checks cover bilingual row actions and keyboard toolbar focus, display-only density, review invalidation and explicit handoff, account-scoped local drafts, save conflicts, version preview/restore, archive/favorites, exact time jumps and background master progress with unsaved mix settings. Recording fixtures cover source-offset take playback without a master, temporary mute/solo, cancellable count-in, lead-in without capture, range selection, keyboard seeking and looped playback. Python checks exercise additive history migration, current-revision restore, immutable queued snapshots, review approval rules, safe recovery copies, cached scalar waveforms and owner-only storage/history HTTP access.

The existing HTTP guide and final Mac worker round trips still run, including stereo channel separation and unchanged copied video packets. CSS is parsed locally, but DOM fixtures do not establish visual rendering in real browsers. No physical microphone or full-session timing acceptance is claimed for this release.

## Browser and deployment acceptance

The implementation uses standard APIs available in current desktop Chrome, Safari and Firefox: getUserMedia, AudioWorklet, Web Audio, IndexedDB, WAV and native video. Sources checked include [MDN microphone permissions](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia), [AudioWorkletNode](https://developer.mozilla.org/en-US/docs/Web/API/AudioWorkletNode), [device enumeration](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/enumerateDevices) and [reported track settings](https://developer.mozilla.org/en-US/docs/Web/API/MediaStreamTrack/getSettings).

DOM/worklet fixtures exercise the application code; physical microphone permissions, browser real-time clocks, hardware playback and the visual layout need an actual-device check in each browser. No hour-long microphone benchmark or live Adobe processing was performed.

App **0.7.0** retains renderer compatibility **0.6.0**. Existing 0.6.0 workers, pairing and queued jobs remain valid. When upgrading from 0.5.x, update the Mac checkout and drain or cancel/resubmit old queued jobs. Retain the private data volume. Completed Full HD guides remain usable. First verify a short take, pause/resume, a replacement range, WAV download, enhanced upload and final mix; then test a complete session. Verify the handled stop in Container Manager on the actual NAS too.

The public image uses explicit code/static copies and the existing context allowlist. Original subtitles, databases, microphone audio, masters, enhanced files, exports, API keys and worker credentials are runtime private data, never image or source contents. Automated tests do not alter the deployed NAS, proxy or user Keychain.
