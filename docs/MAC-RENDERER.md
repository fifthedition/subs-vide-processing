# Manual Mac renderer

The Mac initiates HTTPS connections to the NAS. There is no inbound Mac server, login item, LaunchAgent, scheduled task or idle poller.

## Pair once

1. Install Python 3.11+ and FFmpeg (`brew install ffmpeg` if using Homebrew).
2. Keep a checkout/download of this repository on the Mac, matching the NAS renderer compatibility version. App 0.7.0 uses renderer 0.6.0 for guide and final narration exports; this patch does not require an update to an existing 0.6.0 worker. Updating the code does not require a new token or pairing.
3. Sign in to the NAS app as owner. Open **People & Mac renderers**, enter a name, and create a renderer token. Copy it while shown; the app stores only its hash.
4. Double-click **Configure-Mac-Renderer.command** in Finder. It prepares the Python environment, asks for the app HTTPS address and prompts for the token without showing typed characters. It checks the connection and stores the token in macOS Keychain. The token is sent over stdin to the Keychain tool, not placed in process arguments or a shell history command.

Only the URL is stored in `~/Library/Application Support/BreathworkStudio/renderer.json`. Do not put a token in this Git checkout or in Docker variables.

## Render when needed

The editor saves the session and clicks **Send for export**, then contacts you. Double-click **Render-Queued-Videos.command**.

Terminal shows the session/revision and download/render/upload progress. The worker claims queued exports in order, downloads music when not already cached, renders with the same teleprompter code used for preview frames, uploads the MP4, and continues to the next queued export. When there is no queued job it prints **Queue empty … Renderer stopped** and exits. Terminal can stay open showing that message without a worker running; close the window whenever convenient.

`caffeinate` prevents idle sleep only while a job is active. It does not keep the display lit or override closing the laptop lid. When the job finishes or is stopped, the keep-awake process is terminated. Keep the Mac connected to power/network with its lid open while rendering.

Press **Control-C** to stop. The worker terminates its FFmpeg process and tries to return unfinished work to the queue. Terminal-close/termination signals also trigger cleanup. If the Mac loses power or the network before it can release a claim, that claim expires after three minutes and the NAS returns the job to the queue. Start the worker again afterward. No video rendering resumes by itself.

A failed job does not block later queued jobs. It appears as failed in the app; fix the problem and click **Retry this export**, or edit the project and send a new export. Retry uses that original frozen subtitle revision. A new submission uses the newly saved revision. Only one active export per session is allowed; cancel a queued export before submitting a replacement.

The same launcher processes both music/subtitle guide jobs and final narration mixes. A final mix downloads the existing guide MP4 plus the enhanced voice, copies the video stream and mixes the audio. No separate Mac app or permanent process is added. See [NARRATION.md](NARRATION.md).

## Storage and connectivity

Music is cached by SHA-256 under `~/Library/Caches/BreathworkStudio/media`, with a 5 GB limit after a successful job. A rendered MP4 is retained in the local exports cache if uploading fails so a retry can reuse it. After confirmed upload, the local completed MP4 is deleted. The NAS keeps the downloadable copy. Cache files can be deleted while the worker is stopped; they are regenerated/downloaded as needed.

Transfers use HTTPS, 4 MB upload chunks, resumed audio downloads, and integrity checks. Brief transient failures are retried a bounded number of times. The worker exits on a sustained connection failure; it does not become a background reconnecting process.

A lock prevents two worker instances sharing this Mac cache. The owner can revoke a token in the app at any time. A replacement token requires pairing again. Worker credentials are limited to claiming queued render jobs, their assigned music and render status/results; they cannot edit sessions or manage people/API keys.

When the renderer compatibility version changes, replace/update the checkout, then run the launcher again. Interface-only app releases can keep the same renderer version. It checks the installed Pillow version. No re-pairing is necessary if the URL and token remain valid.
