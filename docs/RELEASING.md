# Public Docker image

Source repository: <https://github.com/fifthedition/subs-vide-processing>

Docker Hub image: `sixthedition/subs-video-processor`

The DS1522+ needs `linux/amd64`, which is the configured build platform. The Mac renders natively using Python/FFmpeg; it does not need an image.

## One-time GitHub setup

Create a Docker Hub access token for `sixthedition` with permission to write this repository. In GitHub repository **Settings → Secrets and variables → Actions**, add it as the repository secret **DOCKERHUB_TOKEN**. Keep the token out of issues, chat, `.env`, source files and Docker build arguments.

Make the Docker Hub repository public so Container Manager can pull without a login. The workflow logs in only during publishing using the Actions secret. It does not embed that credential in the image.

## Review, test, release

The **Test and build** workflow runs on pull requests and main. It runs Python/rendering/HTTP integration checks, builds the Docker image, and boots a fresh container to verify its protected default. The actual NAS/proxy and Mac Keychain pairing still need the first deployment acceptance check.

After the code is reviewed, CI passes, and changes are merged to `main`, create and push a version tag, for example:

```sh
git switch main
git pull --ff-only
git tag v0.7.0
git push origin v0.7.0
```

**Publish Docker image** verifies the commit belongs to main and publishes `0.7.0`, `latest`, and a commit SHA tag. Do not tag an unreviewed feature branch. A manual workflow run publishes a SHA tag; a version tag creates the version used in Compose. The workflow does not deploy to the NAS or change its reverse proxy.

The image uses explicit source-file copies plus a Docker build-context allowlist. It contains code and the licensed font. Private archives, databases, uploaded music, exports, service credentials, worker tokens and configuration are excluded. Public examples are synthetic.

Use a fixed version in the NAS `.env` so it updates when you choose. Update the Mac code when the renderer compatibility version changes: queued snapshots retain their requested renderer version and cannot be silently rendered by a different release. Drain an existing queue before a future renderer-version upgrade, or cancel and resubmit those queued jobs after reviewing the upgrade.

Release 0.6.0 adds independent microphone check, durable browser narration with range replacement/undo, timeline WAV masters, enhanced-audio alignment and a final Mac mix. Both app and renderer compatibility are 0.6.0. Update the Mac checkout and NAS image; keep the existing private data volume and Keychain pairing. Existing completed Full HD guide videos can be narrated; older queued jobs must be drained before upgrading or cancelled/resubmitted afterward.

Release 0.6.1 handles TERM/INT, drains HTTP requests, cancels queued background tasks and bounds NAS cleanup to 20 seconds. CI verifies normal Docker stop/restart with/without init and idle sockets, retaining a synthetic owner/project. Renderer compatibility stays 0.6.0; no worker or queue migration is needed from 0.6.0. This hardening does not establish or fix a Synology UI/runtime cause when stop requests are not delivered.

Release 0.6.2 stabilizes narration preview while WAV metadata, play promises or network seeks are pending. Volume changes and session polls no longer force seeks. A direct Play preview control starts both tracks from the user gesture; blocked playback pauses the music and shows a persistent translated message in the studio. Decode/network failures are visible there too. Renderer compatibility stays 0.6.0; no data, worker or queue migration is needed. Actual Firefox playback remains an on-device acceptance check.

Release 0.7.0 applies the design research to Script/Narration/Exports views, clearer SVG controls, comfortable/compact bilingual editing, per-cue review and ready handoff, subtitle version history and private browser drafts, favorites/archive, complete export history, direct take audition, preview mute/solo, range timelines/looping, count-in/lead-in, enhanced alignment helpers and owner storage information. History tables and project metadata are additive; no media is deleted. Existing 0.6.0 workers and queues remain compatible. Recording still requires a completed guide; the browser-only pre-render recording proposal is excluded. Verify a short real microphone/preview session after updating the NAS before a long recording.
