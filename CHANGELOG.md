# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- **Command-line mode** (`cli.sh`, `cli.py`): send one prompt without opening a window and stream the reply to stdout. Gem mode uses a Gem from the config. `ask MODEL SYSTEM QUESTION` calls the Gemini API with only the API key, with the system instruction as an argument or from a file (`--system-file`). `models` lists the models the key can use, cached for 24 h. Prompts come from arguments or stdin, and replies can be copied to the clipboard. `--version` prints the CLI's version. `--json` prints the reply, token usage or error as one JSON object, and `--timeout SECONDS` limits the whole request (exit 124).
- **App icon** for the dash: a gem in the Gemini colors with the Gemini sparkle. `data/install.sh` installs it with a launcher entry.
- The app icon in the top-left corner of the main window, left of the Gem dropdown. The window is 40 px wider (680 px) to make room.
- A 500 ms shine sweeps diagonally across the header icon once the window has fully appeared (100 ms after GNOME Shell's open animation ends), and again on each click of the icon.
- Per-Gem **Thinking** checkbox (`thinking`). On requests the model's highest
  thinking level, off requests the lowest it allows. Levels a model rejects
  fall back automatically, so the checkbox works across models with
  different support.
- Per-Gem **auto-paste of the selected text into the input on open**
  (`auto_paste_selection`), toggled per Gem in settings. Grabs the primary
  selection (text highlighted in any app) so you can highlight, press the
  shortcut, and send it straight to the Gem. Takes priority over the
  clipboard paste, falling back to it when nothing is highlighted.
- Per-Gem **auto-paste of clipboard into the input on open** (`auto_paste_clipboard`),
  toggled per Gem in settings. The pasted text is pre-selected so `Enter` sends it
  as-is or the first keystroke replaces it.
- Optional companion **GNOME Shell extension** that bottom-anchors the launcher
  window Spotlight-style (`extension/`).
- Per-Gem **automatic copy-to-clipboard** of the full response (`auto_copy`).
- `Ctrl+C` copies the current mouse selection in the response area.
- Dark Spotlight-style theme via `style.css`, with rounded window corners.
- Focus-out auto-close (spotlight-launcher behavior) with drag-aware debounce.

### Changed
- Added `gemini-4-hydrogen` and `gemini-4-carbon` to the default models. `gemini-4-carbon`, like `gemini-4-argon`, needs a paid tier.
- Refreshed the default model list to the current Gemini lineup, including
  `gemini-3.7-flash` and `gemini-3.8-flash`.

### Removed
- `PLAN.md`. Setup lives in `README.md`, design constraints in `CLAUDE.md`.
- Dropped the CSD titlebar; the window is dragged via a body-level `Gtk.WindowHandle`.

### Fixed
- GNOME Shell extension preferences failing with "Something's gone wrong":
  `prefs.js` imported `ExtensionPreferences` from the gnome-shell resource tree
  instead of the `org.gnome.Shell.Extensions` one that hosts the prefs process.
- Zombie processes piling up after the window closed.
