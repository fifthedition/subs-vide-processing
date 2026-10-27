# Next build and improvement ideas

Updated: 2026-10-27. Reviewed against app 0.6.2 source and the supplied editor screenshot.

The user approved the improvements on 2026-10-27, with research before implementation, and explicitly excluded recording without a rendered guide (L08; number 6 in the conversation). R01–R02, S01–S07 and L01–L07 are in scope. Effort is relative scope, not a delivery estimate. See [the design research and implementation direction](DESIGN-RESEARCH.md).

## Requested for the next build

| ID | Change | Details |
| --- | --- | --- |
| R01 | Play/pause icons in Listen and align | Replace the text-only preview controls with recognizable, consistently sized play and pause icon buttons. Preserve accessible names, keyboard focus and Slovak/English tooltips. |
| R02 | Clearer subtitle-row controls | Align and center the four controls with consistent dimensions and spacing. Use recognizable icons for preview, split at cursor, merge with next, and delete. Explain each action in Slovak and English. Keep destructive actions visually distinct. |

## Suggested next-build additions

| ID | Improvement | Effort | Why it helps and what to check |
| --- | --- | --- | --- |
| S01 | Listen to the last saved take immediately | Medium | Put a Play button beside each saved take and offer Play last take after saving. Audition that recorded range directly without preparing the entire timeline WAV first. Make voice-only playback and playback with music explicit; stop at the range end. Respect the current replacement timeline and authenticated access. |
| S02 | Comfortable and compact subtitle layouts | Small–medium | Short prompts currently occupy tall rows, with four vertically stacked tools. Offer compact rows with text fields that grow with their content, keep a comfortable layout available, and retain readable text. Remember the preference in that browser without altering exported video typography. |
| S03 | Independent music/voice mute and solo | Small–medium | A reader can check the voice without repeatedly dragging music to zero. Show clearly whether saved or enhanced voice is selected. Preview mute/solo should be temporary; saved export levels remain explicit. |
| S04 | Keep background status updating while adjusting the mix | Small–medium | `refreshSession()` currently skips refresh while `mixDirty` is true. Separate background master/export status from unsaved input values so changing a slider cannot stop progress updates. Preserve local settings and conflict checks. |
| S05 | Clear feedback in every dialog | Small–medium | Extend the preview's inline error approach to microphone permission/device failures, take upload/recovery and guide playback. Messages must remain visible inside the active dialog and explain the next action. Preserve recovery details until the problem is resolved. |
| S06 | Cue navigation and timing shortcuts | Medium | Add next/previous subtitle, jump to subtitle number or time, play selected range, and small timing nudges. Offer a shortcut help panel and prevent shortcuts from intercepting normal typing or microphone controls. |
| S07 | Separate guide and final exports | Small–medium | Clearly label the newest guide and newest final mix, add a View all exports list, and visibly distinguish exports based on an older subtitle revision. Preserve the existing dates, timezone, unique download IDs, retries and immutable jobs. |

## Larger improvements

| ID | Improvement | Effort | Intended outcome |
| --- | --- | --- | --- |
| L01 | A clear session workflow | Medium–large | Show a short progress strip: subtitles, guide, recording, enhancement, final export. Bring the next useful action forward and collapse later settings. A live-guidance session can finish at the guide; narrated sessions continue through voice and final mix. |
| L02 | Translation review and owner handoff | Medium–large | Show English and Slovak side by side, add Needs review / Reviewed per subtitle, filter unfinished items, and display review progress. Editing reviewed text marks it for another check. Marking the script ready should identify the reviewed revision and connect clearly to queuing its guide for the owner. Keep the manually started Mac worker. |
| L03 | A visual recording timeline | Large | Display subtitle blocks, recorded voice ranges, a voice waveform, and the playhead together. Select a range, loop it, and replace it from the same view. Make intentional silent sections understandable rather than treating every quiet interval as an error. Keep the actual teleprompter text fixed rather than scrolling. |
| L04 | A focused recording view | Medium–large | Prioritize the video, current recording state, microphone meter, countdown, elapsed/remaining time and record/pause controls. Add an optional three-second count-in, a configurable lead-in before replacing a range, and a Play last take action. Preserve accurate clock-based capture and pause on interruptions. |
| L05 | Saved versions and recovery for subtitle edits | Large | Add dated server-side versions with compare/restore and recoverable local text drafts. Show a useful conflict screen when another window edits the same session. Existing optimistic revision checks and recording-chunk recovery remain in place; this extends recovery to subtitle text. Scope local drafts to the signed-in account. |
| L06 | Easier enhanced-audio alignment | Medium–large | Add a voice waveform, small offset nudge buttons and repeatable comparison points near the beginning and end. Surface duration differences as a reason to check alignment, not proof that the file is wrong. If drift differs between the beginning and end, explain that one offset cannot correct a changed playback speed; avoid silently stretching audio. |
| L07 | Project organization and storage management | Medium–large | Add session status filters, favorites and archive/restore. Give the owner a private storage view with file sizes, free space, project assets and export history. Show what depends on an asset before any optional deletion; protect active takes, undo history and queued exports. Preserve intentional manual backups. |
| L08 | EXCLUDED: narrate before rendering a guide | Out of scope | The user explicitly excluded this architectural change. Continue recording against an existing rendered guide and retain the existing two-export workflow. |

## Implementation status

Implemented in the 0.7.0 source: R01–R02, S01–S07 and L01–L07. The workflow uses collapsible progress/settings and separate Script, Narration and Exports views. Asset management is a read-only owner storage report plus reversible session archive/favorites; there is no media deletion. L08 is excluded. Automated verification is recorded in [VERIFICATION.md](../VERIFICATION.md); real microphone/browser acceptance remains a deployment check.

## Suggested order

1. R01 and R02, plus S01 and S02: clearer controls, faster reading and immediate take review.
2. S03–S05: easier audio checks, reliable progress and visible recovery feedback.
3. S06–S07: faster subtitle editing and clearer export selection.
4. L01–L02: workflow and translation handoff.
5. L03–L06: recording, alignment and recovery improvements, selected according to real usage.
6. L07 as the media library grows. L08 remains out of scope.

## Constraints to retain

- The NAS owns private subtitles, source audio, takes, enhanced files and exports; public Git and Docker contain code and synthetic examples only. Do not add private screenshots or subtitle content to this document.
- The Mac renderer starts manually, drains its queue and exits. Waiting for the Mac is an expected queue state, not an application failure.
- Preserve both music-and-text guides for live narration and completed mixes with recorded narration.
- Preserve Full HD output and independent left/right music channels. Display-only preferences must not change a queued export.
- Keep Slovak and English interface copy, keyboard access and useful accessible names. Important messages should be visible inside their dialogs and announced without repeatedly interrupting the reader.
- Current behavior already includes basic undo, revision conflict detection, immutable render snapshots, resumable uploads, recording recovery, waveform seeking, per-export timestamps and microphone checks. These suggestions extend those features rather than introducing them for the first time.

## Review basis

- Subtitle rows and controls: `static/app.js` (`renderCues`, `mutateCue`) and `static/styles.css`.
- Save/conflict behavior and export cards: `static/app.js` (`flushSave`, `loadJobs`).
- Saved takes, master preparation, mix refresh and playback: `static/narration.js` (`renderSession`, `refreshSession`, `pauseTake`, `playback`).
- Workflow and storage behavior: `docs/NARRATION.md` and `docs/ARCHITECTURE.md`.
- [W3C guidance on target size and spacing](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html).
- [W3C guidance on accessible status messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html).

This was a source and screenshot review, not a new interactive test of the deployed NAS app or its microphone playback.
