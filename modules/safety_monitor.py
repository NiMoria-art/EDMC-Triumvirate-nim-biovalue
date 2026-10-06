"""Compact landing and ship status warnings for the plugin panel."""
import tkinter as tk
from queue import Empty, Queue
from tkinter import ttk

from modules.lib.module import Module
from modules.value_ui import configure_styles


G = 9.80665
HIGH_GRAVITY_G = 2.0
SEVERE_GRAVITY_G = 3.0


class SafetyMonitor(tk.Frame, Module):
    """Show high-gravity, fuel, heat, and on-foot survival warnings."""

    def __init__(self, parent, gridrow):
        super().__init__(parent)
        configure_styles(self)
        self._queue = Queue()
        self._poll_id = None
        self._closed = False
        self._status = {}
        self._body_name = None
        self._body_gravity = None
        self._gravity_body = None

        self.card = ttk.LabelFrame(
            self, text="Безопасность", padding=(10, 7),
            style="Triumvirate.Card.TLabelframe",
        )
        self.card.grid(sticky="ew")
        self.card.columnconfigure(0, weight=1)
        self.gravity_label = ttk.Label(
            self.card, text="Гравитация: ожидание данных",
            style="Triumvirate.Muted.TLabel", wraplength=500,
        )
        self.gravity_label.grid(row=0, column=0, sticky="ew")
        self.ship_label = ttk.Label(
            self.card, text="Состояние корабля: ожидание данных",
            style="Triumvirate.Muted.TLabel", wraplength=500,
        )
        self.ship_label.grid(row=1, column=0, sticky="ew", pady=(3, 0))
        self.columnconfigure(0, weight=1)
        self.grid(column=0, row=gridrow, sticky="ew", pady=(4, 0))

    def on_start(self, plugin_dir):
        # Start the timer on Tk's thread; callbacks only place data in the queue.
        self._poll_id = self.after(150, self._drain_queue)

    def on_dashboard_entry(self, cmdr, is_beta, entry):
        self._queue.put(("dashboard", dict(entry)))

    def on_journal_entry(self, entry):
        event = entry.data
        kind = event.get("event")
        if kind in {"Scan", "Touchdown", "Liftoff", "FSDJump", "StartUp", "Location"}:
            self._queue.put(("journal", (kind, dict(event))))

    def _drain_queue(self):
        self._poll_id = None
        if self._closed:
            return
        changed = False
        while True:
            try:
                kind, payload = self._queue.get_nowait()
            except Empty:
                break
            if kind == "dashboard":
                self._status = payload
                if "BodyName" in payload:
                    self._body_name = payload.get("BodyName") or None
                changed = True
            else:
                event_name, event = payload
                changed = self._apply_journal_event(event_name, event) or changed
        if changed:
            self._refresh()
        self._poll_id = self.after(150, self._drain_queue)

    def _apply_journal_event(self, kind, event):
        if kind == "Scan":
            scan_body = event.get("BodyName")
            if scan_body:
                self._body_name = scan_body
            self._gravity_body = None
            self._body_gravity = None
            if event.get("Landable") and event.get("SurfaceGravity") is not None:
                try:
                    self._body_gravity = float(event["SurfaceGravity"]) / G
                    self._gravity_body = scan_body
                except (TypeError, ValueError):
                    self._body_gravity = None
            return True
        elif kind in {"FSDJump", "StartUp", "Location"}:
            self._body_name = event.get("Body") or None
            self._body_gravity = None
            self._gravity_body = None
            return True
        elif kind == "Touchdown":
            self._body_name = event.get("Body") or self._body_name
            return True
        elif kind == "Liftoff":
            return True
        return False

    def _refresh(self):
        status = self._status
        body = status.get("BodyName") or self._body_name
        gravity = self._body_gravity
        if self._gravity_body and body and self._gravity_body != body:
            gravity = None
        # Status.json gives gravity directly in G while on foot.
        if status.get("BodyName") == body and status.get("Gravity") is not None:
            try:
                gravity = float(status["Gravity"])
            except (TypeError, ValueError):
                pass

        if gravity is None:
            self.gravity_label.configure(
                text="Гравитация: сканируй планету для оценки риска посадки",
                style="Triumvirate.Muted.TLabel",
            )
        elif gravity >= HIGH_GRAVITY_G:
            severity = "ОПАСНО" if gravity >= SEVERE_GRAVITY_G else "ВНИМАНИЕ"
            body_text = f" · {body}" if body else ""
            self.gravity_label.configure(
                text=f"⚠ {severity}: {gravity:.2f} g{body_text} — осторожно при посадке",
                style="Triumvirate.Warning.TLabel",
            )
        else:
            body_text = f" · {body}" if body else ""
            self.gravity_label.configure(
                text=f"Гравитация: {gravity:.2f} g{body_text}",
                style="Triumvirate.Muted.TLabel",
            )

        flags = int(status.get("Flags", 0) or 0)
        flags2 = int(status.get("Flags2", 0) or 0)
        alerts = []
        if flags & (1 << 19):
            alerts.append("низкий запас топлива")
        if flags & (1 << 20):
            alerts.append("перегрев корабля")
        if flags2 & (1 << 6):
            alerts.append("мало кислорода")
        if flags2 & (1 << 7):
            alerts.append("низкое здоровье")

        fuel = status.get("Fuel") or {}
        if isinstance(fuel, dict) and fuel.get("FuelMain") is not None:
            try:
                fuel_text = f"Топливо: {float(fuel['FuelMain']):.1f} т"
            except (TypeError, ValueError):
                fuel_text = None
        else:
            fuel_text = None

        if alerts:
            details = ", ".join(alerts)
            if fuel_text:
                details += f" · {fuel_text}"
            self.ship_label.configure(
                text=f"⚠ {details}", style="Triumvirate.Warning.TLabel",
            )
        else:
            text = "Состояние: предупреждений нет"
            if fuel_text:
                text += f" · {fuel_text}"
            self.ship_label.configure(
                text=text, style="Triumvirate.Muted.TLabel",
            )

    def close(self):
        self._closed = True
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except tk.TclError:
                pass
            self._poll_id = None
