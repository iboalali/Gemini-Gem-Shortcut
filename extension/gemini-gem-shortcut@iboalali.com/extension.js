// GNOME Shell extension that positions the Gemini Gem Shortcut launcher
// window at bottom-center of the work area when it opens. Runs inside
// Mutter, so it bypasses the Wayland client-side "no toplevel positioning"
// restriction — `MetaWindow.move_frame()` operates on compositor-internal
// geometry.
//
// The window is matched by GTK application id (`com.iboalali.GeminiGemShortcut`),
// so no other windows are affected. If the launcher app changes its app-id,
// update TARGET_APP_ID below.
//
// Timing: we place on the window-manager `map` signal, NOT on
// `display::window-created`. At window-created a Wayland GTK window has no
// real frame size yet (often 0x0) and its GTK app-id may not be set, and a
// `move_frame()` issued before the window is mapped does not stick — the
// window ends up at Mutter's default (top-left for an undecorated toplevel).
// By `map`, the frame rect and app-id are both reliable and the move sticks.
// The target monitor is captured earlier, at window-created, because by map
// time our own window has grabbed focus.

import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';

const TARGET_APP_ID = 'com.iboalali.GeminiGemShortcut';

export default class GeminiGemShortcutPositioner extends Extension {
    enable() {
        this._settings = this.getSettings();

        // win -> monitor index of whatever was focused when `win` was
        // created (i.e. before our launcher maps and steals focus).
        this._monitorForWindow = new Map();

        this._windowCreatedId = global.display.connect(
            'window-created',
            (_display, win) => this._onWindowCreated(win),
        );

        // `map` fires once, when a window is first shown. The launcher only
        // maps once, so this is naturally single-shot: later size changes
        // (the response area appearing on first submit) and user drags don't
        // re-trigger placement.
        this._mapId = global.window_manager.connect(
            'map',
            (_wm, actor) => this._onMap(actor.meta_window),
        );
    }

    disable() {
        if (this._windowCreatedId) {
            global.display.disconnect(this._windowCreatedId);
            this._windowCreatedId = 0;
        }
        if (this._mapId) {
            global.window_manager.disconnect(this._mapId);
            this._mapId = 0;
        }
        this._monitorForWindow = null;
        this._settings = null;
    }

    _onWindowCreated(win) {
        if (!win) return;

        // Capture the intended monitor now: at window-created the previously
        // focused window is still focused, so its monitor is the one the user
        // is working on. Fall back to the primary monitor. We record this for
        // every new window (cheap) and only act on the matching one at map.
        const focused = global.display.get_focus_window();
        let monitorIdx = global.display.get_primary_monitor();
        if (focused && focused !== win) {
            const idx = focused.get_monitor();
            if (idx >= 0) monitorIdx = idx;
        }
        this._monitorForWindow.set(win, monitorIdx);
        win.connect('unmanaged', () => {
            if (this._monitorForWindow) this._monitorForWindow.delete(win);
        });
    }

    _onMap(win) {
        // Guard against disable() racing with a queued map signal.
        if (!this._settings || !win) return;
        if (typeof win.get_gtk_application_id !== 'function') return;
        if (win.get_gtk_application_id() !== TARGET_APP_ID) return;

        const monitorIdx =
            this._monitorForWindow.get(win) ??
            global.display.get_primary_monitor();
        const workspace = global.workspace_manager.get_active_workspace();
        const work = workspace.get_work_area_for_monitor(monitorIdx);
        const rect = win.get_frame_rect();

        const pct = this._settings.get_int('bottom-offset-percent');
        const bottomOffset = Math.round(work.height * (pct / 100));

        const targetX = work.x + Math.round((work.width - rect.width) / 2);
        const targetY = work.y + work.height - rect.height - bottomOffset;

        // user_op=false so Mutter doesn't mark the window "user-placed".
        win.move_frame(false, targetX, targetY);
    }
}
