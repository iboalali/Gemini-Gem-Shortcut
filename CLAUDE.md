# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project shape

A GTK4 launcher window for Ubuntu GNOME (Wayland) that streams replies from the
official Google Gemini API. `PLAN.md` is the authoritative design doc — read it
before making structural changes. `README.md` is the user-facing setup.

Three Python modules + a shell wrapper + a stylesheet:

- `main.py` — `Gtk.Application` (single-instance via app-id
  `com.iboalali.GeminiGemShortcut`), `MainWindow` (input, two `Gtk.DropDown`s,
  expanding response area, multi-turn conversation), `SettingsWindow`
  (API key + models + Gem notebook tabs). Both windows live here.
- `gemini_client.py` — `stream_generate()` generator that POSTs to
  `…/v1beta/models/{MODEL}:streamGenerateContent?alt=sse` and yields text
  deltas. Raises `GeminiError` for any failure with a human-friendly message.
- `config.py` — load/save `~/.config/gemini-gem-shortcut/config.json` (chmod
  0600), default bootstrap, `find_gem()` helper.
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

**Conversation rollback on errors.** `_show_error` pops the trailing user
turn off `self.history` so a failed request doesn't poison the next turn's
context.

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

**Per-Gem clipboard auto-paste has a Wayland timing gotcha.** Per-Gem
`auto_paste_clipboard: bool` prefills `input_view` with the clipboard text
when the window opens (`_maybe_autopaste_clipboard`, scheduled from
`__init__` via `GLib.idle_add`), then selects all so Enter sends it as-is.
The non-obvious part: a freshly-mapped Wayland window has NOT negotiated the
clipboard data-offer yet at the first idle tick, so an immediate
`read_text_async` fails with "No compatible transfer format found" /
"Cannot read from empty clipboard" — the offer only lands shortly after the
surface gains keyboard focus. `_read_clipboard_into_input(attempt)` therefore
RETRIES on a 50 ms `GLib.timeout_add` (up to `_AUTOPASTE_MAX_ATTEMPTS`, ~1 s
total) until the read succeeds. Do NOT collapse this back to a single
immediate read — it will silently paste nothing. The callback also bails if
`buf.get_char_count() > 0` so a retry that lands late never clobbers text the
user already started typing.

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

## Commit / push

- Per the user's global instructions, **never add `Co-Authored-By` to
  commits**.
- The repo is `git@github.com:iboalali/Gemini-Gem-Shortcut.git`, default
  branch `main`.
