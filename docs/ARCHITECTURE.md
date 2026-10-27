# Architecture and recovery

The browser talks to the NAS HTTPS hostname through Nginx Proxy Manager. The NAS stores the SQLite database and files in its private `/data` volume. The manually launched Mac worker connects outbound to the same HTTPS hostname; all coordination is over the API, never a shared SQLite/SMB database.

## Export contract

- Submission validates saved revision, music-only purpose, file availability, cue bounds, nonempty text and text fitting. The job persists its project snapshot and music metadata/content hash. Subsequent editing does not change it.
- One active export per project is enforced inside a SQLite immediate transaction. Failed jobs can be explicitly retried; queued jobs can be cancelled.
- Claim is atomic and uses a unique client request ID so a retried claim response does not consume another job. Protocol and renderer version must match. One active claim per worker token is allowed.
- Each attempt has an unpredictable token and a 180-second lease. The worker heartbeats every 10 seconds, independently of frame preparation, FFmpeg and transfers. Progress is polled by the browser.
- Expired claims return to the queue when the queue is inspected/claimed. Old attempt IDs cannot update, upload or complete replacement attempts. NAS restarts preserve queued snapshots and live lease information.
- Music is downloaded with HTTP Range and verified against its SHA-256. The worker caches by hash. Render output is uploaded in sequential chunks; repeated identical chunks are accepted, mismatched chunks are rejected. A lost response can be retried safely.
- Completed uploads are checked for declared size, SHA-256, audio/video streams, duration, 1920 × 1080 dimensions and two audio channels before the final MP4 is made downloadable. Completion is idempotent.
- Normal shutdown/Control-C releases the job. A crash relies on lease expiry. A worker failure records an error and moves on to later queued jobs. There is no automatic paid provider retry.

The app and renderer compatibility versions are 0.5.0; protocol is 1. App and renderer versions remain separate so future interface-only updates can use paired existing workers. Update both ends for this release's new audio/video behavior; Keychain tokens remain valid. Drain the old queue before upgrading, or cancel and resubmit queued jobs. Old queue entries from local-only versions cannot be rendered remotely because their in-memory snapshots were never persisted; their old downloadable completed exports remain available.

The renderer produces Full HD H.264 at CRF 16. Stereo AAC uses packet copy; other sources use AAC at a 320 kb/s target and a source-compatible sample rate. Stereo channels are not mixed together. Mono duplicates at unity gain; multichannel sources use FFmpeg's stereo downmix. Browser language is a local preference and is excluded from export snapshots; the video remains Slovak.

Export history displays the full completion date/time in the browser’s timezone (using creation time for legacy exports without a completion timestamp). Pending/failed entries show their request date. Download names include the saved revision, that timestamp with its UTC offset and a short job ID. Direct download URLs without a timezone use UTC. Stored MP4 paths and project revisions remain unchanged.

## Access

Server mode requires an HTTPS public URL and exact Host checking. It binds on the container network behind the proxy. Local mode binds only to localhost and has no remote worker/admin endpoints.

Owner/editor passwords use scrypt with independent random salts. Browser sessions use random tokens stored as hashes with a 12-hour expiry. Cookies are Secure, HttpOnly, SameSite=Strict, with Origin checks and a separate CSRF header for authenticated mutations. Login/setup attempts have a bounded per-peer rate limit. The app does not trust arbitrary forwarded client headers. User disabling and password recovery invalidate sessions.

A one-time random first-owner code is generated in a private file and shown in container startup logs. It is consumed atomically. Renderer credentials are separate random tokens stored as hashes and can be revoked. Raw tokens are shown once and saved in Mac Keychain during pairing. Browser session tokens cannot call worker APIs; worker credentials cannot call editor/admin APIs. Only the owner saves provider keys and manages people/renderers.

All editors share this small studio's sessions/media; this is not multi-tenant hosting. Nginx, NAS access controls and valid HTTPS remain part of the deployment. The Python HTTP server is intentionally behind the reverse proxy rather than exposed directly to the public internet.

## Data and operations

SQLite uses bounded connections and transactions on the NAS's local volume, not a remote filesystem mounted by the Mac. Browser audio uploads are persisted with offsets and expire after seven days when upload cleanup runs at app startup. Media and MP4 transfers are bounded per request; large outputs are not loaded into server memory. Completed media and exports remain until the owner removes them at the filesystem level; there is no automatic deletion of user projects.

Back up the private data folder while the container is stopped, including the database, `subtitles.json`, media, transcripts, exports and provider settings. The supplied migration helper makes a new private folder and uses SQLite's backup API. Stop local editing first so copied media and the database represent a consistent session state.

No renderer daemon, queue broker, Redis, third-party storage service, email notification, webhook or remote Mac shell is required. Editor-to-owner communication is manual as requested.
