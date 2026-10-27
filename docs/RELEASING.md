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
git tag v0.4.1
git push origin v0.4.1
```

**Publish Docker image** verifies the commit belongs to main and publishes `0.4.1`, `latest`, and a commit SHA tag. Do not tag an unreviewed feature branch. A manual workflow run publishes a SHA tag; a version tag creates the version used in Compose. The workflow does not deploy to the NAS or change its reverse proxy.

The image uses explicit source-file copies plus a Docker build-context allowlist. It contains code and the licensed font. Private archives, databases, uploaded music, exports, service credentials, worker tokens and configuration are excluded. Public examples are synthetic.

Use a fixed version in the NAS `.env` so it updates when you choose. Update the Mac code when the renderer compatibility version changes: queued snapshots retain their requested renderer version and cannot be silently rendered by a different release. Drain an existing queue before a future renderer-version upgrade, or cancel and resubmit those queued jobs after reviewing the upgrade.

App 0.4.1 adds export dates and timestamped download names. Its `APP_VERSION` is 0.4.1 and its `RENDERER_VERSION` remains 0.4.0; existing 0.4.0 workers and queued jobs stay compatible.
