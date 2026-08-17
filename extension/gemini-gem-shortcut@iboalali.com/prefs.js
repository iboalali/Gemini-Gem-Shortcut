// Preferences dialog for the Gemini Gem Shortcut Positioner extension.
// Exposes `bottom-offset-percent` via a single Adw.SpinRow, bound to the
// gsettings key with Gio.SettingsBindFlags.DEFAULT so writes are immediate.
// Changes take effect on the *next* launch of the app (the extension
// places windows at window-created time; it doesn't move already-open ones).

import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import Gtk from 'gi://Gtk';

// NOTE the capitalisation and the extra `js/` segment: prefs run in a separate
// gjs process backed by the org.gnome.Shell.Extensions resource bundle, whose
// path is `/org/gnome/Shell/Extensions/js/extensions/prefs.js`. The lowercase
// `resource:///org/gnome/shell/extensions/…` form used by extension.js only
// exists inside the gnome-shell process — importing it here fails with
// "The resource … does not exist" and Extension Manager shows a bare
// "Something's gone wrong" dialog.
import { ExtensionPreferences } from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

export default class GeminiGemShortcutPrefs extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();

        const page = new Adw.PreferencesPage();
        const group = new Adw.PreferencesGroup({
            title: 'Position',
            description: 'How the launcher window is placed when it opens.',
        });

        const row = new Adw.SpinRow({
            title: 'Distance from bottom (%)',
            subtitle: "Bottom edge of the window, measured from the bottom of the work area.",
            adjustment: new Gtk.Adjustment({
                lower: 0,
                upper: 50,
                step_increment: 1,
                page_increment: 5,
            }),
        });
        settings.bind(
            'bottom-offset-percent',
            row,
            'value',
            Gio.SettingsBindFlags.DEFAULT,
        );
        group.add(row);

        page.add(group);
        window.add(page);
    }
}
