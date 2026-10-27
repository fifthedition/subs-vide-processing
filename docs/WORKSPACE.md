# Workspace, review and recovery

App 0.7.0 keeps the Clear light theme and offers three session views: **Script / Text**, **Narration / Hlas** and **Exports / Exporty**. Expand the progress summary to choose live guidance or a narrated session. Live guidance finishes with the music/subtitle guide. Narrated sessions continue through recording, manual Adobe processing and a final mix.

## Translate and review

The original reference is read-only beside the Slovak text on wide screens, and stacks above it on narrower screens. A merged subtitle can show all overlapping reference text. Choose Comfortable or Compact; this changes the editor display only.

Use each subtitle's play, scissors, merge and bin controls. The action group supports arrow-key focus. Preview plays the selected subtitle range when music is present. Previous/next subtitle, a jump field and 0.1-second timing nudges help navigate long sessions. Time jumps can land in intentional music-only intervals. Open Shortcuts for the keyboard reference; ordinary typing is preserved.

Mark each subtitle Reviewed. A change to its wording or timing clears that mark. Filter unfinished subtitles, or explicitly mark the shown subtitles reviewed after checking them. Mark script ready records the reviewed revision. It does not silently queue a render; Send for export remains the explicit handoff. Existing scripts and guide exports remain available without retrospectively forcing all review flags to be checked.

The latest guide and final mix are shown in Exports, with their dates and revisions. Show all exports reveals older files. A label identifies when the script or appearance differs from a completed export. Metadata-only changes such as favorites do not change a guide's render fingerprint. Waiting for the Mac renderer is normal: start the foreground Mac launcher when ready.

## Check recordings

Open a completed guide from Narration or Exports. Microphone check remains independent. Recording still follows the immutable rendered guide, including its original subtitle version and music.

- Enable the optional three-second count-in and choose a lead-in duration if useful. During lead-in, music/video plays without capturing microphone audio. Recording starts at the selected range boundary. Cancel preparation before capture if needed.
- Pause and save a take, then use Play last take or Listen to this take. A take can be auditioned before preparing a full-length WAV. After a range replacement, playback uses the retained source offsets.
- Saved narration and music can play the saved timeline directly while a master is unavailable; preparing a master is still required for the full WAV download used with Adobe Podcast.
- Play/pause icon buttons control the preview. Music/voice mute and solo are temporary preview controls. Saving mix levels does not persist mute/solo.
- Expand Timeline and range playback for music, subtitles, recorded ranges and optional enhanced voice. Click to seek, drag empty space to select a range, or use the numerical start/end fields. Play and loop the selected interval. Quiet gaps do not automatically indicate a missing recording.
- Waveform thumbnails are generated privately on the NAS when the timeline is opened and are cached. A failed or slow thumbnail does not block playback or numeric range selection.
- Focus recording view makes the guide and recording controls prominent. Upload/recovery status remains visible. Confirm that a take has saved before leaving.

Prepare the full-length WAV, enhance it manually in Adobe Podcast, and upload the matching version. Offset nudges, beginning/end check buttons and the enhanced waveform help align it. A duration difference is a reason to check both ends, not proof the audio is wrong. One fixed offset cannot repair changing drift. Final rendering continues through the manually started Mac worker; the guide video is copied and the stereo music retained.

## Saved versions and local drafts

Version history lists saved subtitle versions with dates and editor names where known. Preview differences before restoring. Restoration creates a new revision and preserves the current script in history. Session favorites, archive state and workflow type are not rolled back. Existing queue snapshots, recordings and MP4s keep their original versions.

The latest 200 routine version entries are retained, along with explicit created/ready/restored milestones. Undo remains available for immediate edits; saved versions provide recovery across browser sessions.

Unsaved subtitle drafts are also kept in this browser's IndexedDB, scoped to the account and session. If a draft is found after reopening, review it, download it, or save it as a separate session. A concurrent save conflict exposes these same recovery choices. Opening the saved NAS version leaves the recovered draft available until subsequent work replaces it. The app does not silently overwrite either person's saved text.

Browser storage can be unavailable or full; the interface explains when local draft recovery is unavailable. Invalid typed time values are retained with a local draft and restored for correction in a recovered copy; a downloaded recovery JSON includes them as `recoveredInputs`. Private browsing/site-data clearing can remove local-only drafts. Completed NAS recordings and server-side saved versions are separate from browser recovery.

## Organize the studio

Use favorites and the Active, Favorites, Ready scripts, Archived and All sessions filters. Archive hides a session from the active list; Restore session returns it. The media remains on the NAS.

The owner can open Storage usage to inspect free volume space, category sizes and private media files. Original takes, undo references and older exports are retained. This view does not delete files or replace a NAS backup.

## Upgrade

Set the NAS image to `sixthedition/subs-video-processor:0.7.0` using the same private data volume. App 0.7.0 uses renderer compatibility 0.6.0, so an existing 0.6.0 Mac worker and pairing remain valid. The database additions are automatic and additive. Recording without a previously rendered guide is not part of this release.

After updating, refresh the browser and verify one short recording, direct take playback, a replacement range, WAV download, enhanced alignment and final export in the browsers actually used by the studio. Automated media-element fixtures do not replace real microphone and long-session timing checks.
