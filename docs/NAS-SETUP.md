# Synology deployment

Target: DS1522+ Container Manager, HTTPS through Nginx Proxy Manager at <https://breathworkers.nasforlife.eu>. Nginx forwards traffic; the app supplies owner/editor authentication. NAS setup and proxy changes have not been applied automatically.

## 1. Publish the image

Complete [RELEASING.md](RELEASING.md) first. The prepared image reference is `sixthedition/subs-video-processor:0.6.2`. It becomes available after the release workflow succeeds; preparing this source does not itself publish an image.

## 2. Prepare the private data folder

Create a NAS project folder, for example `/volume1/docker/breathwork-studio`, and a `data` subfolder. Copy `compose.yaml` into the project folder and `.env.example` as `.env`.

To bring the existing sessions and preserved subtitle documents across, stop the old local app with Control-C first. From the new repository folder on the Mac run:

```sh
python3 prepare_nas_data.py ../breathwork-studio ../nas-data-copy
```

This creates a separate private copy; it preserves the old app. Copy the **contents** of `nas-data-copy` into the NAS project's `data` folder. It includes the SQLite backup, uploaded music, saved exports, transcripts/service settings when present, and all original subtitle documents as `subtitles.json`. This folder contains private content and credentials: keep it outside Git and the image build.

For a fresh installation leave `data` empty. A private archive placed at `data/subtitles.json` before startup is loaded into the catalog. On an unseeded database it creates editable Slovak sessions. A restarted database preserves existing corrections and does not create duplicates.

Set `STUDIO_UID` and `STUDIO_GID` in `.env` to the numeric NAS user/group that owns `data`, with read/write access. If using an NAS terminal, `id USERNAME` shows those numbers. Do not assume they match the Mac. The container runs as that user, not root. Restrict this folder's NAS permissions to its owner and administrators.

## 3. Choose the proxy connection

`STUDIO_LISTEN_IP` controls the NAS-side listening address. It is not the public hostname.

- If Nginx runs directly on the NAS host, use `127.0.0.1` and forward to `127.0.0.1:8787`.
- If Nginx Proxy Manager is a separate container, its `127.0.0.1` belongs to that container. Set `STUDIO_LISTEN_IP` to the NAS LAN IP, and forward NPM to that same NAS IP, port `8787`, scheme `http`. Restrict that port to the proxy/LAN in the NAS firewall; the public router forwards HTTPS to NPM only.

The supplied Compose file assumes the second option can use a NAS LAN address; it does not assume the name of an existing Docker network. A shared Docker network is another option, using service name `studio` port `8787` and removing the published port.

In Container Manager, create a **Project** from this project folder and start it. The data volume persists when the image/container is replaced. Start one app container for this database.

## 4. Nginx Proxy Manager

Configure the proxy host:

| Setting | Value |
| --- | --- |
| Domain | `breathworkers.nasforlife.eu` |
| Scheme to app | `http` |
| Forward host | NAS LAN IP or shared-network service name, as chosen above |
| Forward port | `8787` |
| SSL | Valid certificate for this hostname; Force SSL |
| Host header | Preserve the public host, `breathworkers.nasforlife.eu` |
| Access list | App provides sign-in; worker API must accept its Bearer token |

The app uses its explicit `STUDIO_PUBLIC_URL` and does not trust arbitrary forwarded host/protocol headers. Preserve `Authorization`, cookies, `Range`, `X-CSRF-Token`, `X-Render-Attempt` and `X-Upload-Offset`. Standard proxying normally preserves these.

The following limits are suitable in the proxy host's **Advanced** configuration (avoid duplicate directives already set elsewhere):

```nginx
client_max_body_size 32m;
client_body_timeout 300s;
proxy_read_timeout 300s;
proxy_send_timeout 300s;
```

Audio and rendered video upload in application-level 4 MB pieces. JSON subtitle imports are limited to 25 MB, audio files to 4 GB and rendered outputs to 32 GB. No WebSocket or extra Mac hostname is required. Keep Range support for playback, resumed music downloads and large MP4 downloads.

If NPM also has HTTP Basic Auth or a separate access-login screen, worker requests will need a deliberate exception or integration. Do not give the Mac your owner password. App-level accounts work with a forwarding-only proxy.

## 5. First owner and editor

Open the HTTPS hostname. On first startup the Container Manager log shows **First-time setup code**. Enter that code on the setup screen, choose the owner username, and create a password of at least 12 characters. The code is single-use and its private file is removed after setup. Old startup logs may retain the now-invalid code.

In **People & Mac renderers**, create an editor account. Give its username/password to the editor privately. Editors can edit shared projects, upload music, create drafts and queue/download exports. Only the owner manages accounts, renderer tokens and cloud API keys. Disabled editor accounts lose existing sessions.

Create a renderer token and follow [MAC-RENDERER.md](MAC-RENDERER.md).

## 6. Acceptance check

1. Sign out: direct project, music and video URLs should require sign-in.
2. Sign in as editor and import the synthetic sample project/music.
3. Click **Send for export** with the Mac renderer stopped. Confirm **Queued — waiting for renderer**.
4. Restart the NAS container. Confirm the job is still queued.
5. Launch the Mac worker, let it finish, and download/play the MP4 in the browser.
6. Confirm the Mac launcher exits, and no renderer starts when you log in later.
7. Test a real journey/music track to check timing, Slovak diacritics, previous/current/next areas and both clocks.

## Updates and backups

Before an app update, stop the container and back up the entire private `data` folder. Keep the old image version. Set `STUDIO_VERSION` to the new tested version, download/pull it in Container Manager, and recreate the project/container using the same data volume. App 0.6.2 uses renderer compatibility 0.6.0; workers and queued jobs from 0.6.0 need no changes. When upgrading from 0.5.x, drain the old export queue first or cancel/resubmit it after updating the Mac checkout. Existing pairing stays valid. Retain the existing private data volume rather than reimporting an older installation snapshot.

Keep `init: true`, `stop_signal: SIGTERM` and `stop_grace_period: 30s`. Normal shutdown now logs the signal and completion and exits 0. See [shutdown troubleshooting](SHUTDOWN.md) if the Container Manager UI cannot stop the container.

Container Manager UI wording varies by DSM release. The terminal equivalent from the NAS project folder is:

```sh
docker compose pull
docker compose up -d
```

Updates are intentional, not an always-on updater. Roll back by selecting the earlier image and restoring the backup if a later release changes its data format. Never delete the persistent `data` folder to update the app.

To recover an account password, open an interactive terminal for the container:

```sh
python manage.py reset-password owner
```

Substitute the actual username. The password is prompted, not passed in a command. Existing sessions for that account are invalidated. This requires NAS administrative access.
