---
name: ordinal-batch
description: >
  Queue a batch of video posts to X and LinkedIn through the Ordinal web
  app (no API on the basic plan, so everything runs through the browser).
  Use when the user says "schedule posts", "queue the batch", "N videos
  today and N Monday", or names Ordinal. Covers picking the lineup,
  writing the batch doc, and the click-by-click Ordinal flow with its
  traps: the 10MB upload cap, the P shortcut, AM/PM parsing, and channel
  switching.
---

# Ordinal posting batch

YOU are the orchestrator. Ordinal has no API on the basic plan. The whole
flow runs through the browser extension against
`https://app.tryordinal.com/<workspace>` (fill in the workspace slug; the
user's session is already logged in).

Cadence: 2 to 3 videos per posting day, 5 days a week. One concept = one
Ordinal post carrying an X channel and a LinkedIn channel, same day. Usual
slots: 8:20 AM, 10:20 AM, 12:20 PM local. Evening slots only when the user
asks for same-day posting.

## Step 1: the lineup (judgment work)

Propose the batch, get the user's yes, then build. Rules of thumb:

- Lead each day with the strongest idea clip (talking head), then mix in
  a how-to or a product demo. Never two interchangeable how-tos the same
  day.
- Track runway: say how many posting days of finished assets remain.
- Prefer assets that are render-final in `Projects/*/exports/`. A concept
  whose video is missing a format is a production task, not a post.

## Step 2: the batch doc

Write `_social/YYYY-MM-DD-ordinal-batch.md`. Per post: title, day and
time, X video path, LinkedIn video path, X copy, LinkedIn copy. The
previous batch doc in `_social/` is the model.

Copy constraints:

- Zero errors from the prose linter, if one is configured.
- X copy stays under 280 characters. Count it.
- X video over 2:20 needs X Premium on the posting account. Note it in
  the doc when a video crosses that line.
- Video lengths and copy claims must match the actual cut (a "4-minute
  walkthrough" line on a 2:24 cut is a bug).

## Step 3: build each post in Ordinal

Per-post loop:

1. Click **New Post** in the sidebar. In the quick-create modal: type the
   title, click the date field and pick the day on the calendar, click
   the time field and type 12-hour time ("8:20 AM"). Zoom the field and
   verify the AM/PM chip before moving on. Leave "Open Post Page" on,
   click CREATE.
2. On the post page, X channel first: click the copy area, type the X
   copy. Check the character counter (280 cap).
3. Attach the X video if it is 10MB or under: `find` "file input element
   for uploading media", then `file_upload` by ref. Wait ~5s and
   screenshot; the attachment is real when the player renders under the
   copy. (An upload with no player after ~10s did not take; re-upload to
   the same ref.)
4. Click **+ Cross-Post**, tick LinkedIn, Escape.
5. Switch channels by URL, not by clicking the chip:
   append `?channel=LinkedIn` (or `?channel=Twitter`) to the post URL.
6. On the LinkedIn channel: click the copy area, cmd+A, type the
   LinkedIn copy. If the LinkedIn video differs from the X video, hover
   the inherited media and click the trash icon, then attach the right
   file.
7. Verify both channels by flipping the URL param. Only then click
   **Schedule Post**: a dialog lists both channels and the date/time. It
   runs an AI review ("Thinking") that re-renders and moves the SCHEDULE
   button; click SCHEDULE, wait ~3s, screenshot, click SCHEDULE again if
   the dialog is still up. Done when STATUS reads SCHEDULED and the
   sidebar shows the date, time, and both channel handles.

## Traps (each one has cost real time)

- **Bare letter keys fire global shortcuts.** "p" opens New Post from
  anywhere. Never send single letters unless a text input is focused. To
  flip AM/PM: click the chip, press ArrowUp.
- **Verify focus with a one-character test before typing anywhere.**
  Click the field, type a single character, zoom to confirm it landed,
  then type the rest. Typing blind into the quick-create modal turned
  half a title into shortcuts and flipped the modal to CREATE CAMPAIGN
  (the X resets it); typing blind into a fresh post page's copy area
  fired the "p" shortcut mid-sentence and opened a stray New Post modal
  over the page. A just-created post page needs ~3s plus a verified
  click before it accepts text.
- **The Cross-Post dropdown often ignores the first click.** Worse: the
  menu closes between separate extension tool calls, so
  click-then-click-LinkedIn across two calls almost never lands.
  The reliable recipe is one javascript_tool execution that does the
  whole thing: dispatch pointer events on the Cross-Post button, await
  ~600ms, re-dispatch if `input[placeholder*="Search channels"]` is
  absent, then dispatch pointer events on the element whose trimmed
  text is exactly "LinkedIn" (closest `[role="option"]`), await
  ~800ms, and confirm the LinkedIn channel chip exists before
  returning. Verify the chip in the channel bar with a zoom afterward
  regardless.
- **The time field wants 12-hour.** "17:45" parses as 1:45 PM. Type
  "5:45 PM" style, then verify the chip.
- **Cross-Post copies the current channel's text and media once, at add
  time.** Same video on both channels: attach media before Cross-Post.
  Different videos: Cross-Post, then replace media on LinkedIn.
- **Check the URL channel param before cmd+A.** Retyping copy on the
  wrong channel destroys it. The chip click silently fails to switch.
- **Never click the image/upload icons.** They open the native macOS
  picker, which the extension cannot drive. Always `file_upload` to the
  hidden input.
- **file_upload hard-caps at 10MB per call.** For bigger files, test
  AppleScript control first:
  `osascript -e 'tell application "System Events" to count processes'`.
  Error -1743 means the terminal app lacks Automation permission (System
  Settings, Privacy & Security, Automation, enable System Events). With
  permission: click the upload icon, then drive the picker via osascript
  (cmd+shift+G, type the absolute path, Return, Return). Without it:
  leave the post in TO DO with title, copy, date, and time all set, and
  give the user a drag list (post name, file path). **Never schedule a
  post with missing media.**
- **Leave any default post automations** (e.g. "Share to a Slack
  Channel after posting") in place on every post.
- **Stray post cleanup:** top-right ⋮ menu, Delete Post, MOVE TO TRASH
  (restorable for 30 days).

## Step 4: verify the batch

Open `/<workspace>/calendar` and screenshot the week. Every post sits at
its slot. Report per post: SCHEDULED, or TO DO plus exactly what is
missing and what the user must do. Then commit the batch doc and any
skill edits to git.
