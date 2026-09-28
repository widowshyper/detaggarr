"""Detaggarr - bulk remove tags from Sonarr series / Radarr movies."""

import json
import os
import queue
import sys
import threading
import tkinter as tk
import urllib.error
import urllib.request
from tkinter import messagebox, ttk

APP_NAME = "Detaggarr"
_APPDATA = os.environ.get("APPDATA", os.path.expanduser("~"))
CONFIG_DIR = os.path.join(_APPDATA, APP_NAME)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
LEGACY_CONFIG_PATH = os.path.join(_APPDATA, "Taggarr", "config.json")  # pre-rename

# Bundled files live in sys._MEIPASS when running as a PyInstaller exe.
RESOURCE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
ICON_PATH = os.path.join(RESOURCE_DIR, "assets", "detaggarr.ico")

SERVICES = {
    "Sonarr": {
        "port": 8989,
        "items": "series",
        "editor": "series/editor",
        "ids_key": "seriesIds",
        "noun": "series",
        "one": "series",
    },
    "Radarr": {
        "port": 7878,
        "items": "movie",
        "editor": "movie/editor",
        "ids_key": "movieIds",
        "noun": "movies",
        "one": "movie",
    },
}


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def load_config():
    for path in (CONFIG_PATH, LEGACY_CONFIG_PATH):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            continue
    return {}


def save_config(cfg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# API client
# --------------------------------------------------------------------------- #
class ArrError(Exception):
    pass


class ArrClient:
    def __init__(self, service, url, api_key):
        self.service = SERVICES[service]
        url = url.strip().rstrip("/")
        if not url.lower().startswith(("http://", "https://")):
            url = "http://" + url
        self.base = url + "/api/v3/"
        self.api_key = api_key.strip()

    def _request(self, method, path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("X-Api-Key", self.api_key)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code == 401:
                raise ArrError("Unauthorized - check the API key.") from e
            raise ArrError(f"HTTP {e.code}: {detail or e.reason}") from e
        except urllib.error.URLError as e:
            raise ArrError(f"Could not connect: {e.reason}") from e
        except OSError as e:
            raise ArrError(f"Connection error: {e}") from e
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError as e:
            raise ArrError("Unexpected response (is this the right URL/app?).") from e

    def system_status(self):
        return self._request("GET", "system/status")

    def tags(self):
        return self._request("GET", "tag")

    def items(self):
        return self._request("GET", self.service["items"])

    def remove_tags(self, item_ids, tag_ids):
        body = {
            self.service["ids_key"]: list(item_ids),
            "tags": list(tag_ids),
            "applyTags": "remove",
        }
        return self._request("PUT", self.service["editor"], body)

    def delete_tag(self, tag_id):
        return self._request("DELETE", f"tag/{tag_id}")


# --------------------------------------------------------------------------- #
# GUI
# --------------------------------------------------------------------------- #
class DetaggarrApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        try:
            self.iconbitmap(default=ICON_PATH)
        except tk.TclError:
            pass  # icon missing; fall back to the default Tk icon
        self.geometry("900x620")
        self.minsize(760, 520)

        self.cfg = load_config()
        self.client = None
        self.tags = []  # [{id, label}]
        self.items = []  # raw series/movie dicts

        self.service_var = tk.StringVar(value=self.cfg.get("last_service", "Sonarr"))
        self.url_var = tk.StringVar()
        self.key_var = tk.StringVar()
        self.tag_input_var = tk.StringVar()
        self.delete_tags_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Not connected.")

        self._build_ui()
        self._load_service_fields()
        self.service_var.trace_add("write", lambda *_: self._on_service_change())

    # ---- layout ---------------------------------------------------------- #
    def _build_ui(self):
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")

        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        # Connection
        conn = ttk.LabelFrame(root, text="Connection", padding=8)
        conn.pack(fill="x")

        ttk.Label(conn, text="Service:").grid(row=0, column=0, sticky="w")
        svc = ttk.Frame(conn)
        svc.grid(row=0, column=1, sticky="w", pady=(0, 4))
        for name in SERVICES:
            ttk.Radiobutton(svc, text=name, value=name, variable=self.service_var).pack(
                side="left", padx=(0, 12)
            )

        ttk.Label(conn, text="URL:").grid(row=1, column=0, sticky="w")
        ttk.Entry(conn, textvariable=self.url_var).grid(row=1, column=1, sticky="ew", pady=2)

        ttk.Label(conn, text="API key:").grid(row=2, column=0, sticky="w")
        key_row = ttk.Frame(conn)
        key_row.grid(row=2, column=1, sticky="ew", pady=2)
        self.key_entry = ttk.Entry(key_row, textvariable=self.key_var, show="â€¢")
        self.key_entry.pack(side="left", fill="x", expand=True)
        self.show_key_btn = ttk.Button(key_row, text="Show", width=6, command=self._toggle_key)
        self.show_key_btn.pack(side="left", padx=(4, 0))

        self.connect_btn = ttk.Button(conn, text="Connect", command=self._connect)
        self.connect_btn.grid(row=1, column=2, rowspan=2, sticky="ns", padx=(8, 0))
        conn.columnconfigure(1, weight=1)

        # Body: tags (left) | affected items (right)
        body = ttk.PanedWindow(root, orient="horizontal")
        body.pack(fill="both", expand=True, pady=(10, 0))

        # Tags panel
        tag_frame = ttk.LabelFrame(body, text="Tags to remove", padding=8)
        body.add(tag_frame, weight=1)

        ttk.Label(
            tag_frame, text="Type tag names (comma separated) or pick from the list:"
        ).pack(anchor="w")
        entry = ttk.Entry(tag_frame, textvariable=self.tag_input_var)
        entry.pack(fill="x", pady=(2, 6))
        entry.bind("<Return>", lambda _e: self._apply_typed_tags())
        entry.bind("<KeyRelease>", lambda _e: self._apply_typed_tags())

        tag_list = ttk.Frame(tag_frame)
        tag_list.pack(fill="both", expand=True)
        self.tag_tree = ttk.Treeview(
            tag_list, columns=("label", "count"), show="headings", selectmode="extended"
        )
        self.tag_tree.heading("label", text="Tag")
        self.tag_tree.heading("count", text="Used by")
        self.tag_tree.column("label", width=160)
        self.tag_tree.column("count", width=70, anchor="center", stretch=False)
        sb = ttk.Scrollbar(tag_list, orient="vertical", command=self.tag_tree.yview)
        self.tag_tree.configure(yscrollcommand=sb.set)
        self.tag_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tag_tree.bind("<<TreeviewSelect>>", lambda _e: self._on_tag_select())

        # Items panel
        item_frame = ttk.LabelFrame(body, text="Affected items", padding=8)
        body.add(item_frame, weight=2)
        self.item_frame = item_frame

        ttk.Label(
            item_frame,
            text="Items with the selected tags. Deselect any you want to leave alone.",
        ).pack(anchor="w")
        items_list = ttk.Frame(item_frame)
        items_list.pack(fill="both", expand=True, pady=(4, 4))
        self.item_tree = ttk.Treeview(
            items_list, columns=("title", "year", "tags"), show="headings", selectmode="extended"
        )
        self.item_tree.heading("title", text="Title")
        self.item_tree.heading("year", text="Year")
        self.item_tree.heading("tags", text="Matching tags")
        self.item_tree.column("title", width=260)
        self.item_tree.column("year", width=60, anchor="center", stretch=False)
        self.item_tree.column("tags", width=160)
        sb2 = ttk.Scrollbar(items_list, orient="vertical", command=self.item_tree.yview)
        self.item_tree.configure(yscrollcommand=sb2.set)
        self.item_tree.pack(side="left", fill="both", expand=True)
        sb2.pack(side="right", fill="y")
        self.item_tree.bind("<<TreeviewSelect>>", lambda _e: self._update_action_state())

        sel_row = ttk.Frame(item_frame)
        sel_row.pack(fill="x")
        ttk.Button(sel_row, text="Select all", command=self._select_all_items).pack(side="left")
        ttk.Button(sel_row, text="Select none", command=self._select_no_items).pack(
            side="left", padx=(4, 0)
        )

        # Actions
        actions = ttk.Frame(root)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Checkbutton(
            actions,
            text="Also delete the tag from the server if no longer used",
            variable=self.delete_tags_var,
            command=self._update_action_state,
        ).pack(side="left")
        self.remove_btn = ttk.Button(
            actions, text="Remove tags", command=self._remove, state="disabled"
        )
        self.remove_btn.pack(side="right")
        self.refresh_btn = ttk.Button(
            actions, text="Refresh", command=self._connect, state="disabled"
        )
        self.refresh_btn.pack(side="right", padx=(0, 6))

        # Status bar
        ttk.Separator(root).pack(fill="x", pady=(8, 4))
        ttk.Label(root, textvariable=self.status_var, anchor="w").pack(fill="x")

    # ---- helpers --------------------------------------------------------- #
    def _toggle_key(self):
        if self.key_entry.cget("show"):
            self.key_entry.configure(show="")
            self.show_key_btn.configure(text="Hide")
        else:
            self.key_entry.configure(show="â€¢")
            self.show_key_btn.configure(text="Show")

    def _noun(self, count=2):
        svc = SERVICES[self.service_var.get()]
        return svc["one"] if count == 1 else svc["noun"]

    def _load_service_fields(self):
        svc = self.service_var.get()
        saved = self.cfg.get(svc, {})
        self.url_var.set(saved.get("url", f"http://localhost:{SERVICES[svc]['port']}"))
        self.key_var.set(saved.get("api_key", ""))

    def _on_service_change(self):
        self._load_service_fields()
        self.client = None
        self.tags, self.items = [], []
        self.tag_tree.delete(*self.tag_tree.get_children())
        self.item_tree.delete(*self.item_tree.get_children())
        self.refresh_btn.configure(state="disabled")
        self._update_action_state()
        self.status_var.set("Not connected.")

    def _set_busy(self, busy, msg=None):
        state = "disabled" if busy else "normal"
        self.connect_btn.configure(state=state)
        self.refresh_btn.configure(state="disabled" if busy or not self.client else "normal")
        if busy:
            self.remove_btn.configure(state="disabled")
        else:
            self._update_action_state()
        self.configure(cursor="watch" if busy else "")
        if msg:
            self.status_var.set(msg)

    def _run_bg(self, work, done, busy_msg):
        """Run work() in a thread, then done(result, error) on the UI thread."""
        self._set_busy(True, busy_msg)

        results = queue.Queue()

        def runner():
            try:
                results.put((work(), None))
            except Exception as e:  # noqa: BLE001 - surface any failure to the user
                results.put((None, e))

        def poll():
            try:
                result, err = results.get_nowait()
            except queue.Empty:
                self.after(50, poll)
                return
            self._set_busy(False)
            done(result, err)

        threading.Thread(target=runner, daemon=True).start()
        self.after(50, poll)

    # ---- connect / load -------------------------------------------------- #
    def _connect(self):
        svc = self.service_var.get()
        url, key = self.url_var.get().strip(), self.key_var.get().strip()
        if not url or not key:
            messagebox.showwarning(APP_NAME, "Please enter both a URL and an API key.")
            return
        client = ArrClient(svc, url, key)

        def work():
            status = client.system_status()
            if not isinstance(status, dict) or "version" not in status:
                raise ArrError("Unexpected response (is this the right URL/app?).")
            return status, client.tags(), client.items()

        def done(result, err):
            if err:
                self.status_var.set(f"Connection failed: {err}")
                messagebox.showerror(APP_NAME, f"Could not connect to {svc}.\n\n{err}")
                return
            status, tags, items = result
            app_name = status.get("appName", svc)
            if app_name and app_name.lower() != svc.lower():
                messagebox.showwarning(
                    APP_NAME, f"That URL looks like {app_name}, not {svc}."
                )
                self.status_var.set(f"Connected to {app_name}, expected {svc}.")
                return
            self.client = client
            self.cfg[svc] = {"url": url, "api_key": key}
            self.cfg["last_service"] = svc
            save_config(self.cfg)
            self.tags = sorted(tags or [], key=lambda t: t["label"].lower())
            self.items = items or []
            self._populate_tags()
            self.refresh_btn.configure(state="normal")
            self.status_var.set(
                f"Connected to {app_name} v{status.get('version', '?')} - "
                f"{len(self.tags)} tags, {len(self.items)} {self._noun()}."
            )

        self._run_bg(work, done, f"Connecting to {svc}...")

    def _populate_tags(self):
        prev_selected = {int(i) for i in self.tag_tree.selection()}
        self.tag_tree.delete(*self.tag_tree.get_children())
        counts = {}
        for item in self.items:
            for tid in item.get("tags", []):
                counts[tid] = counts.get(tid, 0) + 1
        for tag in self.tags:
            self.tag_tree.insert(
                "", "end", iid=str(tag["id"]), values=(tag["label"], counts.get(tag["id"], 0))
            )
        keep = [str(t) for t in prev_selected if self.tag_tree.exists(str(t))]
        if keep:
            self.tag_tree.selection_set(keep)
        self._on_tag_select()

    # ---- selection ------------------------------------------------------- #
    def _apply_typed_tags(self):
        names = [n.strip().lower() for n in self.tag_input_var.get().split(",") if n.strip()]
        if not self.tags:
            return
        ids = [str(t["id"]) for t in self.tags if t["label"].lower() in names]
        self.tag_tree.selection_set(ids)
        if ids:
            self.tag_tree.see(ids[0])

    def _selected_tag_ids(self):
        return {int(i) for i in self.tag_tree.selection()}

    def _on_tag_select(self):
        tag_ids = self._selected_tag_ids()
        labels = {t["id"]: t["label"] for t in self.tags}
        self.item_tree.delete(*self.item_tree.get_children())
        matches = [
            it for it in self.items if tag_ids.intersection(it.get("tags", []))
        ]
        matches.sort(key=lambda it: (it.get("sortTitle") or it.get("title") or "").lower())
        for it in matches:
            hit = sorted(labels[t] for t in tag_ids.intersection(it.get("tags", [])))
            self.item_tree.insert(
                "",
                "end",
                iid=str(it["id"]),
                values=(it.get("title", "?"), it.get("year") or "", ", ".join(hit)),
            )
        self.item_tree.selection_set(self.item_tree.get_children())
        self.item_frame.configure(text=f"Affected {self._noun()} ({len(matches)})")
        self._update_action_state()

    def _select_all_items(self):
        self.item_tree.selection_set(self.item_tree.get_children())

    def _select_no_items(self):
        self.item_tree.selection_set(())

    def _update_action_state(self):
        n_items = len(self.item_tree.selection())
        n_tags = len(self.tag_tree.selection())
        can_delete_only = self.delete_tags_var.get() and n_tags
        enabled = self.client and n_tags and (n_items or can_delete_only)
        self.remove_btn.configure(state="normal" if enabled else "disabled")
        if n_tags:
            self.remove_btn.configure(
                text=f"Remove {n_tags} tag{'s' if n_tags != 1 else ''} from "
                f"{n_items} {self._noun(n_items)}"
            )
        else:
            self.remove_btn.configure(text="Remove tags")

    # ---- remove ---------------------------------------------------------- #
    def _remove(self):
        if not self.client:
            return
        tag_ids = sorted(self._selected_tag_ids())
        item_ids = [int(i) for i in self.item_tree.selection()]
        delete_tags = self.delete_tags_var.get()
        labels = {t["id"]: t["label"] for t in self.tags}
        tag_names = ", ".join(labels[t] for t in tag_ids)

        msg = (
            f"Remove tag(s): {tag_names}\n"
            f"from {len(item_ids)} {self._noun(len(item_ids))}?"
        )
        if delete_tags:
            msg += "\n\nTags left unused afterwards will also be deleted from the server."
        if not messagebox.askyesno(APP_NAME, msg):
            return

        client = self.client
        selected = set(item_ids)

        def work():
            if item_ids:
                client.remove_tags(item_ids, tag_ids)
            deleted, skipped = [], []
            items = client.items()
            if delete_tags:
                in_use = {t for it in items for t in it.get("tags", [])}
                for tid in tag_ids:
                    if tid in in_use:
                        skipped.append(labels[tid])
                        continue
                    try:
                        client.delete_tag(tid)
                        deleted.append(labels[tid])
                    except ArrError as e:
                        # Tag may still be referenced by indexers, profiles, etc.
                        skipped.append(f"{labels[tid]} ({e})")
            return items, client.tags(), deleted, skipped

        def done(result, err):
            if err:
                self.status_var.set(f"Failed: {err}")
                messagebox.showerror(APP_NAME, f"Removing tags failed.\n\n{err}")
                return
            items, tags, deleted, skipped = result
            self.items = items or []
            self.tags = sorted(tags or [], key=lambda t: t["label"].lower())
            summary = f"Removed {tag_names} from {len(selected)} {self._noun(len(selected))}."
            if deleted:
                summary += f"\nDeleted tag(s): {', '.join(deleted)}."
            if skipped:
                summary += f"\nKept tag(s) still in use: {', '.join(skipped)}."
            self._populate_tags()
            self.status_var.set(summary.replace("\n", "  "))
            messagebox.showinfo(APP_NAME, summary)

        self._run_bg(work, done, "Removing tags...")


def main():
    app = DetaggarrApp()
    app.mainloop()


if __name__ == "__main__":
    main()
