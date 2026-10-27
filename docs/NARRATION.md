# Record narration and make a final mix

The workflow uses two manually started Mac exports. First render the music/subtitle guide; later render the final mix after Adobe processing. All project data, original takes and finished files stay in the private NAS volume.

## Microphone check

Open **Microphone check / Kontrola mikrofónu** in the sidebar, independently of any session or rendered video. Click Enable microphone and allow the browser's microphone prompt. Choose the laptop/USB microphone, refresh the device list, watch the input meter and clipping indicator, adjust recording gain, and record/play a 10-second test. Use headphones.

Capture requests echo cancellation, noise suppression and automatic gain control off. The app displays the settings reported by the device/browser; unsupported or unreported settings are not presented as guaranteed. Gain is a digital recording control; hardware input level is adjusted in macOS Sound settings.

The test WAV stays in the current browser unless downloaded. Closing the mic-check dialog stops capture and releases the microphone. No microphone permission is requested on page load.

## Editor: record to the rendered guide

1. Translate/correct the English source into Slovak and send the guide for export.
2. The owner runs **Render-Queued-Videos.command**; the completed card gains **Play video** and **Open narration studio**.
3. Open the studio. Its video selector identifies the rendered subtitle revision and date. Recording belongs to that immutable guide, even when the live editor's subtitles change afterward.
4. Check the microphone. Set a start/end time or choose a subtitle range from the rendered snapshot. Record the selected range.
5. **Pause and save take** stops both recording and video and saves that take. **Resume from playhead** continues from the current video position within the chosen range.
6. To replace speech, choose an earlier range and record again. Only the newly covered interval is replaced; the rest of the old recording stays in place. **Undo last recording** restores up to 20 timeline edits. Original take files are retained.
7. Use **Play last take / Vypočuť poslednú nahrávku** to check the saved voice immediately. Each recorded range also has a Listen action. Prepare the full-length WAV when ready for Adobe processing, then download the master with its version in the filename.

The WAV master is **48 kHz, 24-bit mono**, with silence in all unrecorded areas and the same timeline length as the guide. Capture uses the browser's native audio clock (often 44.1 or 48 kHz); the NAS resamples to 48 kHz if necessary. File precision cannot create detail absent from the microphone/hardware.

A take is limited to two hours. Pause/resume permits longer guides; full masters are limited by ordinary WAV's 4 GB size (about eight hours at this format). A one-hour master is about 518 MB. Original takes, masters, enhanced files and retakes require additional NAS space.

## Interruptions and recovery

During recording, small PCM chunks are saved in IndexedDB and sent to the NAS with idempotent offsets. A long take is never accumulated as a single in-memory browser buffer. A network/storage failure, video buffering/seeking/speed change, hidden tab, microphone interruption or excessive clock drift pauses capture for review.

**Recover recordings** reopens the matching video after an interruption. In the original browser, **Retry upload and save** sends pending chunks and finishes the take. From another browser/device, **Recover received audio only** explicitly saves just the portion already on the NAS. Review a recovered take before continuing. A sudden crash can lose the last fraction of audio not yet delivered from the audio thread; recovery cannot reconstruct samples that were never persisted.

Keep the original tab open until uploads finish. Browser-private storage must be available; clearing site data removes its unsent chunks. The app warns before leaving while capture/pending uploads remain. In-flight takes are scoped to their recording account; finished takes are part of the shared studio.

## Owner: enhance, check, queue final mix

1. Download the master and process it manually in Adobe Podcast. Preserve timing and silence; no Adobe API integration or account access is used.
2. Upload the enhanced audio in the studio. Explicitly identify the WAV version it came from. A later retake makes the previous enhancement stale.
3. Select saved/enhanced narration plus music, seek the video to a recorded section, then click **Play preview / Prehrať náhľad** in Listen and align. Use **Pause preview / Pozastaviť náhľad** to stop both tracks. Adjust voice offset (positive plays later), music level and voice level. The full WAV is silent outside recorded sections. Playback/loading errors appear directly in this panel; if the browser blocks voice playback, click Play preview to retry with an explicit user gesture.
4. Check synchronization near both the beginning and end, confirm it, and save the mix settings.
5. Send the final mix to the Mac renderer. The owner runs the same manual launcher again. The immutable job downloads the guide and enhanced voice, copies the video stream unchanged, mixes stereo audio and uploads the final MP4.
6. Play or download the final file in the app. Final filenames include `_final`; guide and final exports remain separate.

The final audio is 48 kHz stereo AAC at a 320 kb/s target, with independent music/voice levels and a peak limiter. Mono narration is placed in both channels at unity gain; the original music's left/right channels remain separate. The existing H.264 subtitle video is not re-encoded. Changes made after queueing cannot change that queued mix; cancel it in Exports before resubmitting changed settings.

Check [Adobe's current upload and duration limits](https://podcast.adobe.com/en/plans) against the master before processing a long session. A one-hour 24-bit WAV is about 518 MB; Adobe's free Enhance Speech tier is limited to 30 minutes per file, while Premium currently permits files up to 1 GB. The app does not split or recombine Adobe uploads automatically.

## Browser acceptance

Use current desktop Chrome, Safari or Firefox on macOS over the existing HTTPS hostname. The implementation uses getUserMedia, AudioWorklet, Web Audio, IndexedDB, WAV and native video playback, with feature detection and permission/device error handling. If playback is blocked by browser autoplay policy, press Play once in the video player, pause it, then start recording.

Automated tests cover audio-thread PCM output, mocked device/permission/rate fallbacks, IndexedDB persistence, recording transport/recovery, pauses and final mixing. They do not substitute for testing the actual microphone and real-time playback in each browser. Before a full session, record a short take, pause/resume, replace a range, download it and verify the complete enhanced/final path. Physical-microphone tests in the three browsers and a full-length recording remain deployment checks.


See [workspace controls](WORKSPACE.md) for count-in/lead-in, timeline/range playback, preview mute/solo, alignment helpers and subtitle recovery.
