# Verification — 0.4.1

Tested on macOS with Python 3.14, Pillow 13, FFmpeg/ffprobe and Node. Public Linux/container checks are included in GitHub Actions; their result is recorded separately in the pull request.

The existing renderer tests cover fixed teleprompter areas, Slovak text, elapsed/remaining/countdown boundaries, cue gaps and offsets, encoded video duration/streams, decoded picture comparisons, and correlation with the sole supplied audio source. Editing tests cover imports, revision conflicts and persistence. Provider calls use mocked responses; no paid live API request was made.

New tests exercise:

- First-owner setup, hashed passwords, sessions, editor disabling and renderer token revocation.
- HTTP authentication, Secure/HttpOnly/SameSite cookie flags, CSRF and Origin rejection, exact Host checking, editor/admin boundaries and renderer credential scope.
- Frozen export revisions, duplicate submission handling, restart persistence, atomic concurrent claims, repeated claim requests, expiry/reassignment and stale-attempt rejection, retry/cancel and renderer-version mismatch.
- Audio upload offsets across restart, repeated chunks, mismatched chunks, account isolation and idempotent finalization.
- A real eight-second HTTP queue → native worker → FFmpeg → chunked MP4 upload → downloadable video round trip, followed by an empty-queue run that exits. Test data and caches are isolated; the existing app's database/audio were not modified.

Local launch scripts and JavaScript/Python syntax are checked. Private original website/subtitle content is excluded from Git and image copies. A separate optional private-archive regression verifies all 35 documents/7,627 cues when its private path is supplied. Synthetic archive tests run without those documents.

Still requires the user's deployment:

1. Publish the image using a Docker Hub Actions secret and deploy it on the NAS.
2. Check the existing Nginx Proxy Manager configuration/HTTPS certificate and private data permissions.
3. Manually check sign-in, empty-workspace import, editor workflow, browser playback/fullscreen and owner controls in the deployed browser. No automated live browser tool was available in this session.
4. Pair once with macOS Keychain and test a complete real journey. Keychain itself was not modified by automated tests; token files were used in an isolated loopback test.
5. Confirm large transfers through the actual proxy and rendering performance/space for a full-length session. No full-length benchmark has been run.

The old local `breathwork-studio` app and its saved projects remain separate from this deployment checkout. No NAS service, proxy setting, Docker Hub image or user Keychain entry was changed by local verification.

The 0.4.1 update adds full export timestamps in the browser and dated download filenames. The HTTP render/upload/download test checks Copenhagen timestamps, UTC fallback and range downloads. The renderer compatibility value stays at 0.4.0; no render engine, database schema, stored media or worker pairing changes are required.
