# Container shutdown and Synology troubleshooting

App 0.6.1 handles SIGTERM (Docker stop) and SIGINT (Control-C) explicitly. The handler only records the request; the main loop closes HTTP admission and the listening socket, drains application requests, cancels pending background tasks in every registered pool, then waits for running work. Idle browser sockets do not delay shutdown. The legacy upload waveform task uses a registered pool too.

Normal shutdown logs `Shutdown requested (SIGTERM)` and `Shutdown complete`, and exits with status **0**. Server mode has a **20-second** cleanup budget inside Docker's **30-second** grace period. If work remains stuck, it logs `Shutdown deadline reached` and exits **1**. This is a bounded fallback, not a claim that interrupted work completed. Keep `init: true` so Docker manages/reaps child processes. Local editing allows running exports to finish; the manual Mac worker and its compatibility version are unchanged.

Completed saves remain in the private data volume. An interrupted request may need retrying; unsaved browser changes cannot be recovered by server shutdown. Existing draft/take/upload/queue recovery rules still apply. A deadline may interrupt transcription or WAV preparation; review its status after restarting. No automatic paid provider request is made by this change.

## When Container Manager cannot stop the app

A healthy app plus a successful direct SSH stop suggests a problem in the management interface or its request handling. It does not establish the exact Synology cause. Improving app shutdown cannot repair a stop request that never reaches the container.

Before restarting the package, save the Container Manager error and note the time and DSM/package versions. Capture:

```sh
sudo docker inspect --format '{{json .State}}' breathwork-studio
sudo docker inspect --format 'Image={{.Config.Image}} Init={{.HostConfig.Init}} StopSignal={{.Config.StopSignal}}' breathwork-studio
sudo docker logs --tail 60 breathwork-studio
sudo docker events --since 10m --until 0s --filter container=breathwork-studio --filter event=kill --filter event=die --filter event=stop
```

The event history is limited, so capture it promptly. Application logs show whether its stop handler ran; Docker events show delivered signals and exits. If a direct stop succeeds while the UI action does not, retain both records for Synology troubleshooting. A package restart may interrupt other containers; it remains a recovery option when container-specific controls fail.

After saving edits and allowing active uploads/exports to finish, the SSH fallback is:

```sh
time sudo docker stop -t 30 breathwork-studio
sudo docker inspect --format 'Status={{.State.Status}} ExitCode={{.State.ExitCode}}' breathwork-studio
```

If it still blocks after about a minute, stop waiting in that terminal and capture Container Manager/DSM logs. Do not delete the persistent data folder to fix a stop problem. Keep the supplied `init: true`, `stop_signal: SIGTERM`, `stop_grace_period: 30s`, direct Python command, and a DSM/Container Manager release supported by the NAS model.

Docker normally sends SIGTERM and escalates to SIGKILL after the timeout. Exit 143 in an older app can be an expected signal termination; exit 137 can reflect SIGKILL and needs event/OOM evidence to interpret. For app 0.6.1, a normal handled stop should exit 0.

References: [Docker stop](https://docs.docker.com/reference/cli/docker/container/stop/), [Docker events](https://docs.docker.com/reference/cli/docker/system/events/), [Compose init and stop settings](https://docs.docker.com/reference/compose-file/services/).
