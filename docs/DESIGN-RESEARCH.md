# Design research and implementation direction

Research date: 2026-10-27. Baseline: Breathwork Studio 0.6.2.

The user approved the improvements while excluding recording against a browser teleprompter before a guide video has been rendered. The existing rendered-guide recording workflow remains the basis of this work.

## Method and limits

Reviewed official product documentation for five relevant web applications, their published interface descriptions, and primary usability/accessibility guidance. Compared their patterns with this app's source and the supplied screenshot. This is a comparative design review, not a controlled usability study or a hands-on test inside paid accounts. Product documentation establishes how a feature works; it does not prove that adopting it improves this app. The recommendations below are design judgments to validate with realistic editing and recording tasks.

## What the comparable tools demonstrate

| Product and primary source | Observed pattern | Application to Breathwork Studio |
| --- | --- | --- |
| [Happy Scribe: subtitle editor](https://help.happyscribe.com/en/articles/8548885-subtitle-editor-101) | Text, start/end codes, preview and a waveform timeline support different levels of timing precision. Save state, proofreading progress and playback controls are visible. | Keep text correction quick and central. Make precise timing available without requiring every edit to happen on a timeline. |
| [Happy Scribe: translation view](https://help.happyscribe.com/en/articles/6115876-how-to-enable-the-translation-editor) and [proofreading progress](https://help.happyscribe.com/en/articles/6380919-how-can-i-mark-my-transcript-as-reviewed-proofread) | Original and translated text can appear side by side. A section can be marked reviewed, and reviewed work contributes to progress. | Offer a read-only English reference next to editable Slovak. Track reviewed subtitles and provide a filter for unfinished work. |
| [Descript: editor](https://help.descript.com/descript-tour/the-editor-interface) and [timeline](https://help.descript.com/timeline/timeline-overview) | Script, preview, properties and timeline are distinct areas. The timeline can be revealed and expanded for detailed work. | Use clear Script, Narration and Exports views, with an expandable timeline and secondary settings panels. |
| [Descript: recorder](https://help.descript.com/record/editor-recorder) | Recording has explicit input selection, range replacement, pause/stop controls, a countdown option and visible background upload progress. | Give the recording view a clear state, count-in, microphone meter, selected replacement range and upload state. Make playback of a saved take immediately available. |
| [Riverside: upload completion](https://support.riverside.com/hc/en-us/articles/5460933431453-Has-my-recording-finished-uploading) and [record in the editor](https://support.riverside.com/hc/en-us/articles/22727113815965-Record-in-the-editor) | Recording, uploading and returning to editing are explicit parts of the workflow. Upload completion can be checked per take. | Distinguish recording stopped, uploading and saved on NAS. Show recovery actions near the affected take. |
| [VEED: timeline](https://support.veed.io/en/articles/10804541-what-you-need-to-know-about-veeds-timeline) | A common playhead connects preview and track elements. Zoom, selection and split controls provide timing precision. | Use a shared ruler, playhead, range selection and zoom for subtitle and voice review. Preserve numeric timing controls as an alternative to dragging. |
| [Frame.io: versioning](https://help.frame.io/en/articles/9101068-versioning-in-frame-io) | Revisions are grouped into version stacks; the newest opens first, with older versions available through history and comparison. | Clearly present the latest guide and final mix, retain full export history, and identify subtitle revisions and dates. |
| [Descript: version history](https://help.descript.com/working-in-projects/version-history) | Older project versions can be previewed before restoration. Conflict recovery is explicit. | Add readable saved versions and a restore preview; protect unsaved local edits when another window has changed the project. |

The tools above also include editing behaviors that do not fit a meditation workflow. For example, VEED documents closing timeline gaps and Descript supports editing media through a transcript. In this app, a text correction must preserve the music timeline. Intentional silence and breathing pauses remain intact. Range replacement stays bounded to its selected interval. These are requirements specific to this product, not claims about the other tools.

## Design decisions

### 1. Keep the Clear light visual language

Retain the navy session navigation, white work surfaces, dark readable type and blue primary actions. Use one consistent SVG icon style, aligned to a common box. Replace the ambiguous split, merge and delete glyphs with scissors, a join symbol and a bin. Give icon buttons accessible names and Slovak/English explanations.

Aim for 44 by 44 CSS-pixel main controls, using the [W3C enhanced target-size guidance](https://www.w3.org/WAI/WCAG22/Understanding/target-size-enhanced.html) as a design target rather than a claim that every current control violates a requirement. Keep essential control boundaries and states distinguishable; [W3C non-text contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html) specifies 3:1 for relevant visual information. Use words and shapes as well as color for recording, review and failure states.

### 2. Organize by the task the user is doing

Provide three views within a session:

- **Script:** translate, review, adjust timing and send the guide for export.
- **Narration:** record against a completed guide, review takes and prepare/attach enhanced voice.
- **Exports:** see queued work, current guide/final downloads and their history.

A short workflow summary communicates progress without forcing users through a rigid wizard. A live-guidance session can finish with the music/subtitle guide. A recorded session continues through narration, Adobe processing and the final mix. Waiting for the manually started Mac is an expected state with a plain explanation.

Keep one primary next action prominent. Appearance settings, enhancement details and historical files should be available through clearly labeled secondary areas. This follows the [progressive disclosure principle](https://www.nngroup.com/articles/progressive-disclosure/), while preserving access to completed stages and original media.

### 3. Make long subtitle sessions practical

Use text fields that grow with their content, plus comfortable/compact density preferences. Keep font size readable while reducing unused row height. Put timing, review status and a consistent action group on each subtitle. Preserve the insertion point, selection and scroll position during status updates.

Offer side-by-side reference and translation where space permits, and stack them on narrower screens. Keep the reference read-only. Provide reviewed/unreviewed filters, next/previous subtitle, jump to subtitle/time and small timing nudges. Editing reviewed wording or timing should make that subtitle require review again. Marking a script ready records the reviewed revision; later edits make the handoff out of date.

### 4. Make saved audio easy to verify

Show the selected voice source explicitly: music only, saved voice or enhanced voice. Use recognizable play/pause icons and separate music/voice mute or solo controls. Preview-only mute/solo must not silently change the final export settings.

After saving, put **Play last take** next to the recording controls. Individual saved ranges also get playback and re-record actions. This audition should not depend on preparing a full-length master WAV. Playback must honor the current range's source offsets after replacement edits.

The recording view prioritizes guide video, elapsed/remaining time, microphone meter, record/pause and save state. Count-in and lead-in are optional. Microphone capture starts only at the recording boundary, after the count-in; listening through lead-in does not overwrite existing speech.

### 5. Show timing without turning the app into a general video editor

Add a focused timeline with music, subtitle and narration lanes. Include a common playhead, a selected range, zoom, play range and loop range. Keep numeric range inputs available for keyboard access. During recording, timing controls must not silently move or resize the active range.

Represent saved voice ranges and their waveforms using lightweight peak data. Keep long media streamed; do not require the browser to decode an entire hour-long WAV just to draw a timeline. Silence outside a take remains an understandable part of the session.

For enhanced voice, provide offset nudges and comparison points at the beginning and end. A duration difference invites review; it is not proof of a bad upload. A fixed offset cannot solve changing drift, and audio must not be silently stretched.

### 6. Give feedback where the action happened

Distinguish recording, saving/uploading, saved, preparing WAV, ready, blocked playback and recovery required. Keep important messages inside the active workspace or dialog. Use [accessible status messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html) without moving focus or announcing the clock every tick.

Refresh background master/export state even while mix controls contain unsaved changes. A status update must not reset those inputs, restart a seek or erase an error. When an action is disabled, explain the missing prerequisite nearby.

### 7. Make versions understandable

Show the newest guide and final mix prominently, together with their subtitle revision, full timestamp and purpose. Add a complete history view and a visible indication when the working script has changed since a guide was rendered. Historical files remain downloadable.

Add dated subtitle snapshots, preview/compare and restoration as a new current revision. Preserve queued-job snapshots and older recordings. On a save conflict, keep the local text available and offer recovery actions instead of silently overwriting either version. Local drafts must be scoped to the account and project.

### 8. Keep private storage manageable

Add favorites, session status filters and archive/restore. An owner-only storage view should explain media sizes and usage, including retained takes and older masters. No automatic deletion is part of the redesign. Existing private NAS storage and backups remain the basis of recovery.

## Implementation scope and order

The approved backlog is R01–R02, S01–S07 and L01–L07 in [ROADMAP.md](ROADMAP.md). L08, recording without a previously rendered guide, is explicitly excluded.

1. **Editor foundation:** consistent icons, compact/comfortable layout, workflow navigation, translation review, shortcuts and clear export history.
2. **Recording and review:** immediate take playback, mute/solo, count-in/lead-in, timeline, looped review, alignment controls and visible upload/error states.
3. **Recovery and organization:** saved subtitle versions, local draft/conflict recovery, favorites/archive and owner storage information.
4. **Verification and release:** integration checks, existing guide/final worker regression tests, and an actual-browser acceptance pass where a connected browser is available.

This order groups related changes for implementation; it does not remove any approved backlog item.

## Acceptance tasks

- Correct and review a long bilingual script without losing keyboard focus or repeatedly scrolling oversized empty rows. Check the same task in the comfortable layout.
- Mark the script ready, queue its guide, edit a subtitle and verify the revision difference is clear while the old queue entry remains immutable.
- Open a completed guide, check the microphone, record a short take with count-in, save it and immediately hear the saved range.
- Select a replacement range, listen through lead-in, replace only that interval and undo it. Verify original recordings remain intact.
- Play a selected range repeatedly, audition music and voice independently, and verify that temporary mute/solo does not alter the final queued mix.
- Prepare a WAV while changing mix controls; progress must continue and the input values must stay as entered.
- Upload enhanced voice and check the beginning and end with offset nudges. Final export must retain stereo music and the existing guide video.
- Restore a subtitle version, recover a local draft and handle a concurrent edit without silent loss.
- Check Slovak/English labels, keyboard operation, visible focus, smaller laptop viewports and page zoom. Apply [reflow guidance](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html) to text and controls; the timeline can have its own horizontal navigation.
- Test real microphone playback, media buffering and recording alignment in Firefox, Chrome and Safari. Simulated media-element tests alone cannot establish hardware or hour-long timing reliability.

## Product boundaries

Private data stays on the NAS. The Mac worker starts manually and exits after its queue. The app retains both live-guidance and narrated-video workflows, Full HD output, independent stereo music channels, fixed teleprompter text, manual Adobe processing and existing account controls. No new cloud dependency, third-party analytics, automatic publishing or background Mac service is introduced by these design choices.
