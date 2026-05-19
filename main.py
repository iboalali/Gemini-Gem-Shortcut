"""Gemini Gem Shortcut — small launcher window backed by the Gemini API."""
from __future__ import annotations

import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, GObject, Gio, Gtk  # noqa: E402

import config  # noqa: E402
from gemini_client import GeminiError, stream_generate  # noqa: E402

APP_ID = "de.blueworld.GeminiGemShortcut"
WINDOW_WIDTH = 640


def _make_dropdown() -> Gtk.DropDown:
    dd = Gtk.DropDown()
    dd.set_model(Gtk.StringList.new([]))
    return dd


def _dropdown_set_items(dd: Gtk.DropDown, items: list[str]) -> None:
    dd.set_model(Gtk.StringList.new(items))


def _dropdown_get_text(dd: Gtk.DropDown) -> str | None:
    idx = dd.get_selected()
    if idx == Gtk.INVALID_LIST_POSITION:
        return None
    model = dd.get_model()
    if model is None:
        return None
    item = model.get_item(idx)
    return item.get_string() if item is not None else None


def _dropdown_index_of(dd: Gtk.DropDown, text: str) -> int:
    model = dd.get_model()
    if model is None:
        return -1
    for i in range(model.get_n_items()):
        item = model.get_item(i)
        if item is not None and item.get_string() == text:
            return i
    return -1


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app: "GeminiGemApp") -> None:
        super().__init__(application=app, title="Gemini")
        self.app = app
        self.cfg = config.load()
        self.history: list[dict] = []
        self.current_assistant_buf: list[str] = []
        self.cancel_flag = threading.Event()
        self._thinking_mark = None
        self._settings_open = False
        self._close_timeout_id: int | None = None

        self.set_default_size(WINDOW_WIDTH, -1)

        # Window-level key handling (Esc, Ctrl+,).
        win_keys = Gtk.EventControllerKey()
        win_keys.connect("key-pressed", self._on_window_key_pressed)
        self.add_controller(win_keys)

        # Auto-close on focus-out, but debounce so that a Gtk.DropDown
        # popover closing (focus is briefly orphaned before returning to the
        # dropdown widget) doesn't trip the close. The `enter` event cancels
        # any pending close.
        focus_ctrl = Gtk.EventControllerFocus()
        focus_ctrl.connect("leave", self._on_focus_leave)
        focus_ctrl.connect("enter", self._on_focus_enter)
        self.add_controller(focus_ctrl)

        self.connect("close-request", self._on_close_request)

        self._build_ui()
        self._populate_gem_combo()
        self._populate_model_combo()
        self._apply_defaults()

        GLib.idle_add(self.input_view.grab_focus)

    # ── layout ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.set_margin_top(10)
        outer.set_margin_bottom(10)
        outer.set_margin_start(10)
        outer.set_margin_end(10)
        self.set_child(outer)

        # Top row: gem combo, model combo, gear button.
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        outer.append(header)

        self.gem_combo = _make_dropdown()
        self.gem_combo.set_tooltip_text("Gem (system instruction preset)")
        self.gem_combo.set_hexpand(True)
        self.gem_combo.connect("notify::selected", lambda d, _p: self._on_gem_changed(d))
        header.append(self.gem_combo)

        self.model_combo = _make_dropdown()
        self.model_combo.set_tooltip_text("Model")
        self.model_combo.set_hexpand(True)
        header.append(self.model_combo)

        gear = Gtk.Button(label="⚙")
        gear.set_tooltip_text("Settings (Ctrl+,)")
        gear.set_has_frame(False)
        gear.connect("clicked", lambda *_: self._open_settings())
        header.append(gear)

        # Input area: TextView wrapped in a ScrolledWindow.
        input_frame = Gtk.Frame()
        outer.append(input_frame)

        input_scroll = Gtk.ScrolledWindow()
        input_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        input_scroll.set_min_content_height(70)
        input_scroll.set_max_content_height(180)
        input_scroll.set_propagate_natural_height(True)
        input_frame.set_child(input_scroll)

        self.input_view = Gtk.TextView()
        self.input_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.input_view.set_left_margin(8)
        self.input_view.set_right_margin(8)
        self.input_view.set_top_margin(6)
        self.input_view.set_bottom_margin(6)

        # Key handling on the input TextView (Enter to submit, Shift+Enter for newline).
        input_keys = Gtk.EventControllerKey()
        input_keys.connect("key-pressed", self._on_input_key_pressed)
        self.input_view.add_controller(input_keys)
        input_scroll.set_child(self.input_view)

        # Response area, hidden until first submit.
        self.response_frame = Gtk.Frame()
        self.response_frame.set_vexpand(True)
        self.response_frame.set_visible(False)
        outer.append(self.response_frame)

        response_scroll = Gtk.ScrolledWindow()
        response_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        response_scroll.set_min_content_height(220)
        response_scroll.set_vexpand(True)
        self.response_frame.set_child(response_scroll)

        self.response_view = Gtk.TextView()
        self.response_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.response_view.set_editable(False)
        self.response_view.set_cursor_visible(False)
        self.response_view.set_left_margin(8)
        self.response_view.set_right_margin(8)
        self.response_view.set_top_margin(6)
        self.response_view.set_bottom_margin(6)
        response_scroll.set_child(self.response_view)

        buf = self.response_view.get_buffer()
        buf.create_tag("user", weight=700)
        buf.create_tag("error", foreground="#c01c28", style=2)  # italic
        buf.create_tag("dim", foreground="#888888")

    # ── helpers ─────────────────────────────────────────────────────────

    def _populate_gem_combo(self) -> None:
        _dropdown_set_items(self.gem_combo, [g["name"] for g in self.cfg.get("gems", [])])

    def _populate_model_combo(self) -> None:
        _dropdown_set_items(self.model_combo, list(self.cfg.get("models", [])))

    def _apply_defaults(self) -> None:
        gems = [g["name"] for g in self.cfg.get("gems", [])]
        default_gem = self.cfg.get("default_gem")
        if default_gem in gems:
            self.gem_combo.set_selected(gems.index(default_gem))
        elif gems:
            self.gem_combo.set_selected(0)

        if self.model_combo.get_selected() == Gtk.INVALID_LIST_POSITION:
            models = self.cfg.get("models", [])
            default_model = self.cfg.get("default_model")
            if default_model in models:
                self.model_combo.set_selected(models.index(default_model))
            elif models:
                self.model_combo.set_selected(0)

    def _on_gem_changed(self, _dd: Gtk.DropDown) -> None:
        name = _dropdown_get_text(self.gem_combo)
        if not name:
            return
        gem = config.find_gem(self.cfg, name)
        if not gem:
            return
        gem_default = gem.get("default_model")
        models = self.cfg.get("models", [])
        target = gem_default if gem_default in models else self.cfg.get("default_model")
        if target in models:
            self.model_combo.set_selected(models.index(target))

    # ── key handling ────────────────────────────────────────────────────

    def _on_window_key_pressed(
        self,
        _ctrl: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        if ctrl and keyval == Gdk.KEY_comma:
            self._open_settings()
            return True
        if ctrl and keyval in (Gdk.KEY_c, Gdk.KEY_C):
            # If the response view has a selection, copy it to the clipboard.
            # response_view isn't keyboard-focusable (no cursor, not editable),
            # so without this the native Ctrl+C in the focused input_view runs
            # against an empty selection.
            if self._copy_response_selection():
                return True
        return False

    def _copy_response_selection(self) -> bool:
        buf = self.response_view.get_buffer()
        bounds = buf.get_selection_bounds()
        if not bounds:
            return False
        start, end = bounds
        text = buf.get_text(start, end, False)
        if not text:
            return False
        self.get_clipboard().set(text)
        return True

    def _on_input_key_pressed(
        self,
        _ctrl: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if state & Gdk.ModifierType.SHIFT_MASK:
                return False  # let TextView insert newline
            self._submit()
            return True
        return False

    def _on_close_request(self, *_: object) -> bool:
        # Stop the in-flight stream.
        self.cancel_flag.set()
        # Cancel any pending deferred-close timer — its GLib source holds a
        # strong ref to our bound method (and therefore this window), which
        # keeps the C widget alive past destroy and prevents the application
        # from reaching hold-count 0. Without this, repeated open+close
        # leaves zombie processes piling up.
        if self._close_timeout_id is not None:
            GLib.source_remove(self._close_timeout_id)
            self._close_timeout_id = None
        # Drop the app's reference to us so a subsequent activation builds
        # a fresh window instead of presenting a destroyed one.
        if self.app.window is self:
            self.app.window = None
        # Belt-and-braces: explicitly quit the GApplication. Window-tracking
        # alone is unreliable when GLib sources have held refs to widgets.
        self.app.quit()
        return False

    def _on_focus_leave(self, *_: object) -> None:
        # Schedule a deferred close (spotlight-style) but let the next
        # `enter` cancel it. This filters out transient focus losses caused
        # by Gtk.DropDown popovers closing.
        if self._settings_open:
            return
        if self._close_timeout_id is not None:
            return
        self._close_timeout_id = GLib.timeout_add(200, self._do_deferred_close)

    def _on_focus_enter(self, *_: object) -> None:
        if self._close_timeout_id is not None:
            GLib.source_remove(self._close_timeout_id)
            self._close_timeout_id = None

    def _do_deferred_close(self) -> bool:
        self._close_timeout_id = None
        if self._settings_open:
            return False
        self.close()
        return False

    # ── submit / stream ─────────────────────────────────────────────────

    def _submit(self) -> None:
        buf = self.input_view.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
        if not text:
            return
        if not self.input_view.get_editable():
            return  # already streaming

        gem_name = _dropdown_get_text(self.gem_combo) or ""
        gem = config.find_gem(self.cfg, gem_name) or {}
        system_instruction = gem.get("system_instruction", "")
        model = _dropdown_get_text(self.model_combo) or self.cfg.get("default_model", "")
        api_key = self.cfg.get("api_key", "")
        # Snapshot the gem's auto-copy preference at submit time so editing
        # the gem mid-stream doesn't change behavior for the in-flight reply.
        self._current_auto_copy = bool(gem.get("auto_copy", False))

        self.history.append({"role": "user", "parts": [{"text": text}]})

        # Lock input (editable=False blocks typing). We deliberately leave
        # sensitive=True so the input keeps focus — turning the focused widget
        # insensitive would force GTK to move focus away, briefly dropping it
        # out of the window's focus tree and tripping the auto-close.
        self.input_view.set_editable(False)
        buf.set_text("")
        self.response_frame.set_visible(True)
        self._append_user_echo(text)
        self._append_thinking()
        self.current_assistant_buf = []
        self.cancel_flag = threading.Event()

        contents_snapshot = [dict(c) for c in self.history]
        threading.Thread(
            target=self._worker,
            args=(api_key, model, system_instruction, contents_snapshot),
            daemon=True,
        ).start()

    def _worker(self, api_key: str, model: str, system_instruction: str, contents: list[dict]) -> None:
        try:
            first = True
            for delta in stream_generate(api_key, model, system_instruction, contents):
                if self.cancel_flag.is_set():
                    break
                if first:
                    GLib.idle_add(self._clear_thinking_marker)
                    first = False
                GLib.idle_add(self._append_assistant_delta, delta)
            GLib.idle_add(self._finish_stream)
        except GeminiError as e:
            GLib.idle_add(self._show_error, str(e))
        except Exception as e:  # noqa: BLE001
            GLib.idle_add(self._show_error, f"Unexpected error: {e}")

    # ── response UI updates (main thread) ───────────────────────────────

    def _append_user_echo(self, text: str) -> None:
        buf = self.response_view.get_buffer()
        end = buf.get_end_iter()
        buf.insert_with_tags_by_name(end, f"> {text}\n\n", "user")
        self._scroll_to_end()

    def _append_thinking(self) -> None:
        buf = self.response_view.get_buffer()
        end = buf.get_end_iter()
        mark = buf.create_mark("thinking-start", end, True)
        buf.insert_with_tags_by_name(end, "  …thinking\n\n", "dim")
        self._thinking_mark = mark
        self._scroll_to_end()

    def _clear_thinking_marker(self) -> bool:
        buf = self.response_view.get_buffer()
        if self._thinking_mark is None:
            return False
        start = buf.get_iter_at_mark(self._thinking_mark)
        end = buf.get_end_iter()
        buf.delete(start, end)
        buf.delete_mark(self._thinking_mark)
        self._thinking_mark = None
        return False

    def _append_assistant_delta(self, text: str) -> bool:
        self.current_assistant_buf.append(text)
        buf = self.response_view.get_buffer()
        buf.insert(buf.get_end_iter(), text)
        self._scroll_to_end()
        return False

    def _finish_stream(self) -> bool:
        full = "".join(self.current_assistant_buf)
        if full:
            self.history.append({"role": "model", "parts": [{"text": full}]})
            buf = self.response_view.get_buffer()
            if getattr(self, "_current_auto_copy", False):
                self.get_clipboard().set(full)
                end = buf.get_end_iter()
                buf.insert_with_tags_by_name(end, "\n  (copied to clipboard)", "dim")
            buf.insert(buf.get_end_iter(), "\n\n")
        else:
            if self.history and self.history[-1].get("role") == "user":
                self.history.pop()
        self._scroll_to_end()
        self.input_view.set_editable(True)
        self.input_view.grab_focus()
        return False

    def _show_error(self, msg: str) -> bool:
        self._clear_thinking_marker()
        buf = self.response_view.get_buffer()
        end = buf.get_end_iter()
        buf.insert_with_tags_by_name(end, f"  {msg}\n\n", "error")
        if self.history and self.history[-1].get("role") == "user":
            self.history.pop()
        self._scroll_to_end()
        self.input_view.set_editable(True)
        self.input_view.grab_focus()
        return False

    def _scroll_to_end(self) -> None:
        buf = self.response_view.get_buffer()
        mark = buf.create_mark(None, buf.get_end_iter(), False)
        self.response_view.scroll_mark_onscreen(mark)
        buf.delete_mark(mark)

    # ── settings ────────────────────────────────────────────────────────

    def _open_settings(self) -> None:
        self._settings_open = True
        win = SettingsWindow(self, self.cfg)
        win.connect("saved", self._on_settings_saved)
        win.connect("close-request", self._on_settings_closed)
        win.present()

    def _on_settings_closed(self, *_: object) -> bool:
        self._settings_open = False
        return False  # allow the close to proceed

    def _on_settings_saved(self, _w: "SettingsWindow", new_cfg: dict) -> None:
        self.cfg = new_cfg
        prev_gem = _dropdown_get_text(self.gem_combo)
        prev_model = _dropdown_get_text(self.model_combo)
        self._populate_gem_combo()
        self._populate_model_combo()

        gems = [g["name"] for g in self.cfg.get("gems", [])]
        if prev_gem in gems:
            self.gem_combo.set_selected(gems.index(prev_gem))
        else:
            self._apply_defaults()

        models = self.cfg.get("models", [])
        if prev_model in models:
            self.model_combo.set_selected(models.index(prev_model))


class SettingsWindow(Gtk.Window):
    __gsignals__ = {
        "saved": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, parent: Gtk.Window, cfg: dict) -> None:
        super().__init__(title="Gemini Gem Shortcut — Settings")
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_default_size(600, 560)
        self.cfg = {
            **cfg,
            "models": list(cfg.get("models", [])),
            "gems": [dict(g) for g in cfg.get("gems", [])],
        }
        self._build_ui()

    def _build_ui(self) -> None:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        outer.set_margin_start(12)
        outer.set_margin_end(12)
        self.set_child(outer)

        # API key.
        outer.append(self._label("API key"))
        self.api_entry = Gtk.Entry()
        self.api_entry.set_visibility(False)
        self.api_entry.set_text(self.cfg.get("api_key", ""))
        self.api_entry.set_placeholder_text("AIza…")
        outer.append(self.api_entry)

        # Models (one per line).
        outer.append(self._label("Models (one per line)"))
        models_scroll = Gtk.ScrolledWindow()
        models_scroll.set_min_content_height(80)
        self.models_view = Gtk.TextView()
        self.models_view.set_wrap_mode(Gtk.WrapMode.NONE)
        self.models_view.get_buffer().set_text("\n".join(self.cfg.get("models", [])))
        models_scroll.set_child(self.models_view)
        outer.append(models_scroll)

        # Default model.
        outer.append(self._label("Default model"))
        self.default_model_entry = Gtk.Entry()
        self.default_model_entry.set_text(self.cfg.get("default_model", ""))
        outer.append(self.default_model_entry)

        # Gems (notebook with one tab per gem).
        outer.append(self._label("Gems"))
        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        self.notebook.set_vexpand(True)
        outer.append(self.notebook)
        for gem in self.cfg.get("gems", []):
            self._add_gem_tab(gem)
        if self.notebook.get_n_pages() == 0:
            self._add_gem_tab({"name": "General", "system_instruction": "", "default_model": None})

        gem_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        add_btn = Gtk.Button(label="+ Add Gem")
        add_btn.connect(
            "clicked",
            lambda *_: self._add_gem_tab(
                {
                    "name": f"Gem {self.notebook.get_n_pages() + 1}",
                    "system_instruction": "",
                    "default_model": None,
                }
            ),
        )
        del_btn = Gtk.Button(label="– Remove current")
        del_btn.connect("clicked", self._on_remove_gem)
        gem_buttons.append(add_btn)
        gem_buttons.append(del_btn)
        outer.append(gem_buttons)

        # Default gem.
        outer.append(self._label("Default gem (name)"))
        self.default_gem_entry = Gtk.Entry()
        self.default_gem_entry.set_text(self.cfg.get("default_gem", ""))
        outer.append(self.default_gem_entry)

        # Save / Cancel.
        action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        action_row.set_halign(Gtk.Align.END)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        save = Gtk.Button(label="Save")
        save.add_css_class("suggested-action")
        save.connect("clicked", self._on_save)
        action_row.append(cancel)
        action_row.append(save)
        outer.append(action_row)

    @staticmethod
    def _label(text: str) -> Gtk.Label:
        lbl = Gtk.Label(label=text)
        lbl.set_xalign(0)
        lbl.add_css_class("dim-label")
        return lbl

    def _add_gem_tab(self, gem: dict) -> None:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        page.set_margin_top(8)
        page.set_margin_bottom(8)
        page.set_margin_start(8)
        page.set_margin_end(8)

        page.append(self._label("Name"))
        name_entry = Gtk.Entry()
        name_entry.set_text(gem.get("name", ""))
        page.append(name_entry)

        page.append(self._label("System instruction"))
        instr_scroll = Gtk.ScrolledWindow()
        instr_scroll.set_min_content_height(140)
        instr_scroll.set_vexpand(True)
        instr_view = Gtk.TextView()
        instr_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        instr_view.get_buffer().set_text(gem.get("system_instruction", "") or "")
        instr_scroll.set_child(instr_view)
        page.append(instr_scroll)

        page.append(self._label("Default model (optional — blank uses the global default)"))
        default_model_entry = Gtk.Entry()
        default_model_entry.set_text(gem.get("default_model") or "")
        page.append(default_model_entry)

        auto_copy_check = Gtk.CheckButton(label="Copy response to clipboard automatically")
        auto_copy_check.set_active(bool(gem.get("auto_copy", False)))
        page.append(auto_copy_check)

        page._gem_name_entry = name_entry  # type: ignore[attr-defined]
        page._gem_instr_view = instr_view  # type: ignore[attr-defined]
        page._gem_default_model_entry = default_model_entry  # type: ignore[attr-defined]
        page._gem_auto_copy_check = auto_copy_check  # type: ignore[attr-defined]

        label_text = gem.get("name", "Gem") or "Gem"
        tab_label = Gtk.Label(label=label_text)
        self.notebook.append_page(page, tab_label)
        name_entry.connect(
            "changed",
            lambda e, lbl=tab_label: lbl.set_text(e.get_text() or "Gem"),
        )
        self.notebook.set_current_page(self.notebook.get_n_pages() - 1)

    def _on_remove_gem(self, *_: object) -> None:
        if self.notebook.get_n_pages() <= 1:
            return
        idx = self.notebook.get_current_page()
        if idx >= 0:
            self.notebook.remove_page(idx)

    def _on_save(self, *_: object) -> None:
        api_key = self.api_entry.get_text().strip()
        models_buf = self.models_view.get_buffer()
        models_text = models_buf.get_text(models_buf.get_start_iter(), models_buf.get_end_iter(), False)
        models = [ln.strip() for ln in models_text.splitlines() if ln.strip()]

        gems: list[dict] = []
        for i in range(self.notebook.get_n_pages()):
            page = self.notebook.get_nth_page(i)
            name = page._gem_name_entry.get_text().strip() or f"Gem {i+1}"  # type: ignore[attr-defined]
            ibuf = page._gem_instr_view.get_buffer()  # type: ignore[attr-defined]
            instr = ibuf.get_text(ibuf.get_start_iter(), ibuf.get_end_iter(), False)
            dm = page._gem_default_model_entry.get_text().strip() or None  # type: ignore[attr-defined]
            auto_copy = page._gem_auto_copy_check.get_active()  # type: ignore[attr-defined]
            gems.append({
                "name": name,
                "system_instruction": instr,
                "default_model": dm,
                "auto_copy": auto_copy,
            })

        new_cfg = {
            "api_key": api_key,
            "default_model": self.default_model_entry.get_text().strip() or (models[0] if models else ""),
            "default_gem": self.default_gem_entry.get_text().strip() or (gems[0]["name"] if gems else ""),
            "models": models,
            "gems": gems,
        }
        config.save(new_cfg)
        self.emit("saved", new_cfg)
        self.close()


class GeminiGemApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window: MainWindow | None = None

    def do_activate(self) -> None:  # noqa: N802 (GObject vtable name)
        if self.window is None:
            self.window = MainWindow(self)
        self.window.present()


def main() -> int:
    app = GeminiGemApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
