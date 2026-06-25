# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
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
- Refreshed the default model list to the current Gemini lineup.
- Dropped the CSD titlebar; the window is dragged via a body-level `Gtk.WindowHandle`.

### Fixed
- Zombie processes piling up after the window closed.
