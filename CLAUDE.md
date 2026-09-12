# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project shape

A GTK4 launcher window for Ubuntu GNOME (Wayland) that streams replies from the
official Google Gemini API. `README.md` is the user-facing setup; the design
constraints live in this file (see "Locked-in constraints" below).

Four Python modules + a shell wrapper + a stylesheet:

- `main.py` — `Gtk.Application` (single-instance via app-id
  `com.iboalali.GeminiGemShortcut`), `MainWindow` (input, two `Gtk.DropDown`s,
  expanding response area, multi-turn conversation), `SettingsWindow`
  (API key + models + Gem notebook tabs). Both windows live here.
- `gemini_client.py` — `stream_generate()` generator that POSTs to
  `…/v1beta/models/{MODEL}:streamGenerateContent?alt=sse` and yields text
  deltas. Raises `GeminiError` for any failure with a human-friendly message.
- `config.py` — load/save `~/.config/gemini-gem-shortcut/config.json` (chmod
  0600), default bootstrap, `find_gem()` helper.
- `usage.py` holds the local token accounting in
  `~/.config/gemini-gem-shortcut/usage.json` (chmod 0600), bucketed by day and
  model, pruned to `RETENTION_DAYS`. Also owns the display formatting
  (`format_tokens`, `format_response`, `summary`) so `main.py` stays UI-only.
- `run.sh` — what the GNOME keyboard shortcut binds to. `exec`s
  `.venv/bin/python main.py`.
- `style.css` — dark Spotlight-style theme. Loaded once at app activation
  via `Gtk.CssProvider` (`GeminiGemApp._load_css`) at
  `STYLE_PROVIDER_PRIORITY_APPLICATION`. Edit and relaunch to iterate.
- `extension/gemini-gem-shortcut@iboalali.com/` — optional GNOME Shell
  extension that bottom-anchors the launcher window (GJS, GNOME 45+ ESM
  API). Self-contained; the Python app has no knowledge of it. See
  `extension/README.md` for install and `extension/install.sh` for the
  one-shot installer. Matching is by GTK app-id, so the rename of
  `APP_ID` in `main.py` must stay in sync with `TARGET_APP_ID` in
  `extension.js`. Placement happens on the window-manager `map` signal,
  NOT `display::window-created`: at creation a Wayland GTK window has no
  real frame size yet (and a `move_frame()` issued before the window is
  mapped doesn't stick — the window lands top-left). The target monitor
  *is* captured at `window-created` though, before the launcher steals
  focus. Don't move placement back to `window-created`.

## Run / develop

```bash
# System deps (one-time)
sudo apt install python3-gi gir1.2-gtk-4.0 python3-venv

# Venv — MUST use --system-site-packages so PyGObject (gi) is importable
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt

# Launch (or bind ./run.sh to a GNOME custom shortcut)
./run.sh

# Headless import smoke test (catches syntax / GTK4 API mistakes
# without popping a window)
.venv/bin/python -c "import config, gemini_client, main; print('ok')"

# Brief GUI smoke test (window pops for 2 s, exits 0 if clean)
timeout --preserve-status 2 ./run.sh
```

No test suite, no linter config. Smoke tests above are the verification path.

## Architecture notes that aren't obvious from the code

**Threading model.** The GTK main loop owns all UI updates. On submit,
`MainWindow._submit` spawns a daemon thread that iterates
`stream_generate(...)` and pushes each delta back via `GLib.idle_add`. The
worker checks `self.cancel_flag` between tokens so closing the window mid-
stream stops the loop on the next yield. Never touch GTK widgets from the
worker thread.

**"Gems" are mimicked, not real.** Google has no official API for the Gems on
gemini.google.com. Each named Gem in config is just a `system_instruction`
preset that gets injected into a normal `generateContent` call. Do not add
code that pretends otherwise (no reverse-engineered web RPC, no
clipboard+ydotool tricks) without the user's explicit go-ahead — those paths
were considered and rejected.

**Focus-out close has three gotchas.** The window auto-closes when focus
leaves it (spotlight-launcher behavior). Implementation:

1. Uses `Gtk.EventControllerFocus` on the window, not `notify::is-active` —
   the latter fires when a child `Gtk.DropDown` opens its popover, which
   would close the window the moment you click a dropdown.
2. The `leave` handler schedules a 200 ms deferred close instead of closing
   immediately. The paired `enter` handler cancels the pending close. This
   filters out the transient focus loss when a dropdown popover closes
   (focus is briefly orphaned before returning to the dropdown widget) —
   without the debounce, selecting from a dropdown would close the window.
3. The settings window is a separate toplevel, so opening it fires `leave`.
   The `_settings_open` flag suppresses the deferred close in that case.
   `_open_settings` sets the flag; the settings window's `close-request`
   handler clears it.
4. Interactive window moves on Wayland (`xdg_toplevel_move`) grab BOTH
   pointer and keyboard for the duration of the drag — the focus
   controller fires `leave` and the window becomes inactive, so neither
   `is_active()` nor `notify::is-active` can be used to distinguish a
   move from a real click-outside. The drag *is* preceded by a button
   press on this window, though, so `MainWindow` registers a CAPTURE-phase
   `Gtk.GestureClick` (`_on_window_press`) that records
   `_last_press_time`. When `_on_focus_leave` fires within 1 s of a press,
   it picks a 5 s deferred-close delay (long enough for a typical drag to
   complete and `_on_focus_enter` to cancel the timer); otherwise it uses
   the original 200 ms. CAPTURE phase is required so we observe the press
   before the body-level `Gtk.WindowHandle` (the one wrapping `outer` in
   `_build_ui` — added when the CSD titlebar was dropped via
   `set_decorated(False)`) claims it. Do NOT replace the press-tracking
   with `notify::is-active` (gotcha 1) or with checking `is_active()` at
   deferred-close time (the move makes us inactive, so the check returns
   False and the close fires anyway).

**Per-Gem thinking is a fallback ladder, not a single value.** The `thinking`
bool on each Gem maps to `generationConfig.thinkingConfig.thinkingLevel` in
`gemini_client.stream_generate`. On tries `"high"`; off tries `"minimal"`, then
`"low"`; both end with "no thinkingConfig at all". A level the model refuses
comes back as HTTP 400 with "Thinking level ... is not supported" in the body,
which `_stream_once` turns into `_UnsupportedThinkingLevel` so the loop moves to
the next rung. The retry is safe because the status check happens before any
token is yielded. Measured against the API (2026-09): `"minimal"` gives 0
thought tokens on the Flash-Lite line, 3.5-flash and 3.6-flash, but 3.7-flash
and 3.8-flash reject it and only go down to `"low"` (still ~50-70 thought
tokens). Gemma models reject `"low"` with "Thinking level is not supported"
and return HTTP 500 on `"high"`; the 500 is deliberately not treated as a
fallback trigger so real server errors stay visible. `thinkingBudget` is not
used: 3.x models reject `thinkingBudget: 0` with a generic "invalid argument"
that carries no thinking hint, so it can't drive the ladder. Like `auto_copy`,
the flag is snapshotted in `_submit` and passed to the worker, so editing the
Gem mid-stream doesn't affect the in-flight request.

**Conversation rollback on errors.** `_show_error` pops the trailing user
turn off `self.history` so a failed request doesn't poison the next turn's
context.

**Token usage is counted locally because the API cannot report it.** There is
no usage or quota endpoint on `generativelanguage.googleapis.com`. That is
verified against the full v1beta discovery document, which has no such method,
and successful responses carry no `x-ratelimit-*` headers either. A 429 names the
quota you exceeded (`QuotaFailure` violations plus a `RetryInfo`) but never how
much of it you had used. Those violation names are also where the free tier's
actual meters show up: `generate_content_free_tier_requests` and
`generate_content_free_tier_input_token_count`, per model, per minute and per
day. Only *input* tokens are metered, which is why `usage.summary` puts the
input count before the total. `totalTokenCount` is the billing figure
(input + output + thinking), not the quota figure. The aggregate lives in Cloud Monitoring / Service
Usage, and both reject an API key outright ("API keys are not supported by this
API"), so reading it needs OAuth credentials and the project id, which an API
key does not reveal. Don't go looking for a usage endpoint again; accumulate
client-side instead.

How the accumulation works:

1. **Every SSE chunk carries a `usageMetadata`, and the counts are cumulative**
   for the reply so far (`candidatesTokenCount` grows chunk by chunk,
   `promptTokenCount` holds steady). So `_stream_once` keeps only the newest and
   reports it once. Summing every chunk would multiply-count the same tokens.
2. `stream_generate(..., on_usage=cb)` fires the callback from a `finally`, on
   the **caller's thread**, which is the streaming worker, not the GTK main
   loop. It fires on `GeneratorExit` too, when the window closes mid-stream.
   The callback must therefore never touch a GTK widget.
   `MainWindow._worker` passes `usage_meta.update`, so the dict just fills in
   place, then travels to the main thread as an argument of the `GLib.idle_add`
   that calls `_finish_stream`.
3. The thinking-level retry ladder calls `_stream_once` more than once, but a
   rejected level fails on the status check before any chunk arrives, so the
   callback still fires exactly once per reply.
4. `_record_usage` swallows `OSError`: an unwritable store must never break a
   reply.

**Clipboard paths are two-tier.** `Ctrl+C` is handled at the window level
(`_copy_response_selection`) so a mouse-selection in the read-only response
view copies even though the focused widget is the input. The window's key
controller MUST run on `Gtk.PropagationPhase.CAPTURE`, not the default
BUBBLE — otherwise `input_view` (which owns focus after streaming finishes)
consumes Ctrl+C with an empty selection before our handler sees it, and the
response-view selection is never copied. If `_copy_response_selection`
returns False (no selection), the handler returns False to let the native
Ctrl+C on the input proceed. Per-Gem `auto_copy: bool` triggers a clipboard
write in `_finish_stream` with an inline "(copied to clipboard)"
confirmation. The flag is snapshotted at `_submit` time
(`self._current_auto_copy`) so editing the Gem mid-stream doesn't change
behavior for the in-flight reply.

**Per-Gem auto-paste has a Wayland timing gotcha.** Two per-Gem flags
prefill `input_view` when the window opens (`_maybe_autopaste_clipboard`,
scheduled from `__init__` via `GLib.idle_add`), then select-all so Enter
sends it as-is: `auto_paste_clipboard: bool` reads the regular CLIPBOARD
(`get_clipboard()`, last Ctrl+C) and `auto_paste_selection: bool` reads the
PRIMARY selection (`get_primary_clipboard()`, whatever text is currently
highlighted in any app — the middle-click-paste buffer). Both are just
`Gdk.Clipboard`s, read identically. The non-obvious part: a freshly-mapped
Wayland window has NOT negotiated the data-offer yet at the first idle tick,
so an immediate `read_text_async` fails with "No compatible transfer format
found" / "Cannot read from empty clipboard" — the offer only lands shortly
after the surface gains keyboard focus. `_read_clipboard_into_input(sources,
source_idx, attempt)` therefore RETRIES on a 50 ms `GLib.timeout_add` (up to
`_AUTOPASTE_MAX_ATTEMPTS`, ~1 s total) until the read succeeds. Do NOT
collapse this back to a single immediate read — it will silently paste
nothing. The callback also bails if `buf.get_char_count() > 0` so a retry
that lands late never clobbers text the user already started typing.
`_maybe_autopaste_clipboard` builds a priority-ordered `sources` list
(PRIMARY before CLIPBOARD); when both flags are on, the selection is read
first and the clipboard is tried as a fallback only after the selection
source exhausts its retry budget with no text. This means "both enabled +
nothing highlighted" pays the full ~1 s retry budget before falling back —
acceptable since it's the rare combination. Note PRIMARY only holds text
*highlighted* in an app that supports the selection protocol (most
GTK/Qt/GNOME apps, terminals, browsers do); there is no Wayland way to read
arbitrary unselected text fields — client isolation forbids it.

**Don't disable input via `set_sensitive(False)`.** Use `set_editable(False)`
instead. Turning the focused widget insensitive forces GTK to move focus
away, and during the transition `contains_focus` on the window briefly goes
false — tripping the auto-close deferred timer. This was a real regression
that took a round to find.

**Rounded corners need a transparent toplevel.** `MainWindow` is undecorated
(`set_decorated(False)`), and the rounded dark fill is painted on the
body-level `Gtk.WindowHandle`, not the toplevel. The `window.spotlight-window`
rule in `style.css` therefore sets the toplevel `background-color:
transparent` — otherwise the compositor draws an opaque rectangle behind the
`border-radius` and the corners stay square. The `.spotlight-window` CSS
class (added in `MainWindow.__init__`) scopes this to the main window so
`SettingsWindow` keeps its native decorated chrome. If you add a second
spotlight-style toplevel, give it the same class; if you make the main
window decorated again, drop the class and the transparency rule together.

**Close-request must cancel the deferred-close timer and call
`app.quit()`.** A pending `GLib.timeout_add` source holds a strong ref to
the bound method (and therefore the window), which keeps the C widget alive
past destroy. The GApplication's hold count never reaches 0, `app.run()`
never returns, and zombie processes accumulate every shortcut press. The
`_on_close_request` handler explicitly removes the source, drops
`self.app.window`, and calls `self.app.quit()` as belt-and-braces. Don't
remove any of those three steps.

**The extension's two GNOME resource imports use DIFFERENT paths.** They look
like they should match and they don't:

```js
// extension.js — runs inside the gnome-shell process
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';
// prefs.js — runs in a separate gjs process
import { ExtensionPreferences } from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';
```

Note the capital `S`/`E` and the extra `js/` segment in the prefs one. Prefs are
hosted by `gjs -m /usr/share/gnome-shell/org.gnome.Shell.Extensions`, a
different process backed by the `org.gnome.Shell.Extensions.src.gresource`
bundle; the lowercase `…/org/gnome/shell/…` tree only exists inside
gnome-shell itself. Getting it wrong throws `ImportError: … The resource at
"/org/gnome/shell/extensions/prefs.js" does not exist`, and both Extension
Manager and the Extensions app swallow it into a bare **"Something's gone
wrong"** dialog with no detail. Verify the real path rather than trusting
memory:

```bash
gresource list /usr/share/gnome-shell/org.gnome.Shell.Extensions.src.gresource | grep prefs
journalctl --user -b --grep "JS ERROR"   # where the swallowed error actually lands
```

**Only `extension.js` needs a logout; `prefs.js` does not.** The prefs process
is spawned fresh per dialog and reads `prefs.js` off disk each time, so
re-running `install.sh` + reopening prefs is enough to test a prefs change.
`extension.js` and `metadata.json` are loaded once into the running shell, and
GNOME Shell on Wayland can't be reloaded in place — those do require a log
out/in. Note the shell refuses a second dialog with "Already showing a prefs
dialog", so a stale broken one has to be closed (or its gjs pid killed) before
retrying.

## Locked-in constraints (do not regress without asking)

- **Pure Wayland + latest GTK.** Do not reintroduce `GDK_BACKEND=x11`. Do not
  downgrade to GTK3. The user explicitly chose this.
- **No client-side window positioning.** GTK4 dropped `move()`, and Wayland
  doesn't let clients position themselves on Mutter. Bottom-anchored
  positioning lives in the optional GNOME Shell extension at
  `extension/gemini-gem-shortcut@iboalali.com/` — that runs *inside*
  Mutter and uses `MetaWindow.move_frame()`, which is the only legitimate
  path on stock GNOME. Do not reintroduce client-side positioning
  attempts (XWayland fallback, layer-shell, etc.) — those were
  considered and rejected.
- **No deprecated widgets.** Use `Gtk.DropDown` + `Gtk.StringList`, not
  `Gtk.ComboBoxText`. The migration was done to silence GTK4 deprecation
  warnings; don't undo it.
- **Always-on-top / skip-taskbar.** Dropped in GTK4. The window is a normal
  window. Don't try to fake these via hacks.

## Config and secrets

- `~/.config/gemini-gem-shortcut/config.json` (mode 0600) holds the API key
  in plaintext. Migrating to GNOME Keyring via `libsecret` is on the future
  list but not started.
- `.gitignore` excludes `config.json` from the repo root defensively — even
  though the real config lives under `~/.config`, this prevents accidental
  commits if someone drops a copy at the project root.

## Updating the model list

Model IDs are duplicated in two places — change both together:
`DEFAULT_CONFIG` in `config.py` (the source of truth) and the config example in
`README.md`.

**Bumping `DEFAULT_CONFIG["models"]` does not migrate an existing config.**
`config.load()` merges defaults with `setdefault`, which only fills in *missing*
top-level keys — a user who already has a `models` list keeps their old one
forever. Editing the default list alone changes nothing for anyone but fresh
installs; the live `~/.config/.../config.json` has to be rewritten separately
(via settings, or a one-off `config.load()` → overwrite `models` →
`config.save()`, which preserves the key, gems and 0600 perms). Also check each
Gem's `default_model` override for IDs that no longer exist.

**Verify against the API, not against docs or memory.** `GET
…/v1beta/models?key=$KEY` lists exactly what a given key can address, which is
the only reliable source for what's current. Then actually stream one token
through `gemini_client.stream_generate` for each ID — presence in `ListModels`
is necessary but not sufficient:

- **Pro models are unavailable on the free tier.** Every `*-pro*` ID (including
  `gemini-pro-latest` and `gemini-2.5-pro`) returns `HTTP 429 … limit: 0` on a
  free key. `limit: 0` is a hard zero allowance, not a transient throttle —
  retrying never helps, so don't diagnose it as rate-limiting. Keeping a Pro
  entry in the list is a deliberate choice (it starts working the moment
  billing is enabled), not an oversight.
- Unversioned aliases (`gemini-flash-latest`, `gemini-pro-latest`) float to the
  newest model in their tier. Prefer pinned IDs in the default list so a
  silent upstream swap can't change behavior mid-release.

## Commit / push

- Per the user's global instructions, **never add `Co-Authored-By` to
  commits**.
- The repo is `git@github.com:iboalali/Gemini-Gem-Shortcut.git`, default
  branch `main`.
