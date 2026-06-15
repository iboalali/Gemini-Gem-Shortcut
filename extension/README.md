# Gemini Gem Shortcut Positioner

An **optional** GNOME Shell extension that places the Gemini Gem Shortcut
launcher window at bottom-center of the screen when it opens.

The app itself works without this extension — it just appears wherever
Mutter decides (usually centered). Install the extension if you want
Spotlight-style bottom anchoring.

## Why a separate extension?

Pure Wayland clients can't position their own toplevels. The Wayland
`xdg-shell` protocol has no "place this window at (x, y)" message; only
the compositor (Mutter, on GNOME) can move windows. A small GNOME Shell
extension runs *inside* Mutter and uses `MetaWindow.move_frame()` to
position the launcher before its first frame is composited.

The extension matches windows by GTK application id
(`com.iboalali.GeminiGemShortcut`), so no other apps are touched.

## Install

```bash
./install.sh
```

That copies the extension into
`~/.local/share/gnome-shell/extensions/gemini-gem-shortcut@iboalali.com/`,
compiles the gsettings schema, and runs `gnome-extensions enable`. On
Wayland (GNOME's default on Ubuntu) you must then **log out and back in**
for GNOME Shell to load the extension — there's no `Alt+F2` + `r`
restart on Wayland.

## Preferences

Open the dialog from the terminal:

```bash
gnome-extensions prefs gemini-gem-shortcut@iboalali.com
```

Or via the Extensions app (`gnome-extensions-app`).

One setting:

- **Distance from bottom (%)** — where the window's bottom edge sits,
  measured from the bottom of the work area (i.e. excluding the top bar
  and dock). Default: `20`. Changes take effect on the next launch of
  the app.

## Multi-monitor

The extension picks the monitor of the **currently focused window** at
the moment the launcher opens. If nothing is focused (or it's
ambiguous), it falls back to the GNOME-configured primary monitor.

## Limitations

- **Single-shot placement.** The window is positioned once, when it is
  first shown (on the window-manager `map` signal).
  After the first submit the response area appears and the window grows
  downward — if the bottom of the screen is reached, the response area
  is already scrollable so the input stays visible, but you may want to
  drag the window up. Re-anchoring on every size change would fight
  user drags, so it's deferred to a v2 if it proves annoying.
- **GNOME version.** `metadata.json` declares `shell-version: ["46"]`.
  If you upgrade GNOME, add the new major version to the array (and
  test). The extension uses the standard GNOME 45+ ESM API and shouldn't
  break on minor positioning APIs across versions.
- **Wayland session restart required to install/upgrade.** GNOME Shell
  on Wayland can't be reloaded in place. After every change to the
  extension files, log out and back in.

## Uninstall

```bash
gnome-extensions disable gemini-gem-shortcut@iboalali.com
rm -rf ~/.local/share/gnome-shell/extensions/gemini-gem-shortcut@iboalali.com
```

Log out + back in to release the GNOME Shell hooks.
