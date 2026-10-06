"""
Модуль ExploValue: подсчёт стоимости картографических (исследовательских) данных.

Источники данных:
  * события Scan / SAAScanComplete / SellExplorationData / MultiSellExplorationData / Died,
    которые приходят через JournalEntryProcessor плагина;
  * при старте дочитываются журналы прошлых сессий (modules.journal_history).

В журнале нет стоимости отдельных тел, поэтому оценка считается по формуле сообщества
(константы ниже приблизительные и правятся в таблицах K_*). Реальные суммы продаж
берутся из SellExplorationData, а при продаже показывается сравнение "факт / оценка".
"""
import tkinter as tk
from tkinter import ttk
from threading import RLock

from modules.debug import debug
from modules.lib.journal import JournalEntry
from modules.lib.module import Module
from modules.lib.thread import BasicThread
from modules import journal_history
from modules.lib.conf import config as plugin_config
from modules.value_ui import configure_styles

BOUNDARY_EVENTS = ("SellExplorationData", "MultiSellExplorationData", "Died")
SALE_EVENTS = ("SellExplorationData", "MultiSellExplorationData")
SCAN_TYPES = ("AutoScan", "Detailed", "Basic", "NavBeacon", "NavBeaconDetail")

# ---- константы формулы (приблизительные, можно править) ----
Q = 0.56591828
MAP_MULT = 3.3333333333          # обычное картографирование
MAP_MULT_FIRST_BOTH = 3.699622554  # первым открыл и первым закартографировал
MAP_MULT_FIRST_MAP = 8.0956      # закартографировал первым то, что уже открыто другими
EFFICIENCY_MULT = 1.25           # бонус эффективности DSS
ODYSSEY_MAP_MULT = 0.30          # Odyssey: дополнительный бонус к стоимости картографии
ODYSSEY_MAP_MIN_BONUS = 555       # минимальный Odyssey-бонус картографии
FIRST_DISCOVERY_MULT = 2.6       # First Discoverer
MIN_VALUE = 500

K_STAR_DEFAULT = 1200
K_STAR_NEUTRON_BH = 22628
K_STAR_WHITE_DWARF = 14057

# (обычная, терраформируемая)
K_PLANET = {
    "Metal rich body": (21790, 21790),
    "High metal content body": (9654, 100677),
    "Rocky body": (300, 93328),
    "Icy body": (1721, 1721),
    "Rocky ice body": (1721, 1721),
    "Earthlike body": (116295, 116295),
    "Water world": (64831, 116295),
    "Ammonia world": (96932, 96932),
    "Water giant": (667, 667),
    "Sudarsky class I gas giant": (1656, 1656),
    "Sudarsky class II gas giant": (9654, 9654),
    "Sudarsky class III gas giant": (1000, 1000),
    "Sudarsky class IV gas giant": (1119, 1119),
    "Sudarsky class V gas giant": (2000, 2000),
    "Helium rich gas giant": (900, 900),
    "Helium gas giant": (900, 900),
    "Gas giant with water based life": (883, 883),
    "Gas giant with ammonia based life": (774, 774),
}
K_PLANET_DEFAULT = 300


def fmt(n) -> str:
    return f"{int(n):,}".replace(",", " ")


def body_value(ev: dict, mapped: bool = False, efficient: bool = False, odyssey: bool = True):
    """Оценка стоимости одного тела по событию Scan. None - тело не оценивается."""
    star = ev.get("StarType")
    planet = ev.get("PlanetClass")
    if star:
        if star == "SupermassiveBlackHole":
            return None                      # формулу не знаю - считаем как "без цены"
        if star in ("H", "N"):
            k = K_STAR_NEUTRON_BH
        elif star.startswith("D"):
            k = K_STAR_WHITE_DWARF
        else:
            k = K_STAR_DEFAULT
        value = k + ev.get("StellarMass", 0) * k / 66.25
        if not ev.get("WasDiscovered", True):
            value *= FIRST_DISCOVERY_MULT
        return max(MIN_VALUE, int(value))
    if not planet:
        return 0                             # пояса, кольца и т.п.
    normal, terra = K_PLANET.get(planet, (K_PLANET_DEFAULT, K_PLANET_DEFAULT))
    terraformable = ev.get("TerraformState") in ("Terraformable", "Terraforming", "Terraformed")
    k = terra if terraformable else normal
    base = k + k * Q * (ev.get("MassEM", 1) ** 0.2)
    if mapped:
        first_disc = not ev.get("WasDiscovered", True)
        first_map = not ev.get("WasMapped", True)
        if first_disc and first_map:
            mult = MAP_MULT_FIRST_BOTH
        elif first_map:
            mult = MAP_MULT_FIRST_MAP
        else:
            mult = MAP_MULT
        value = base * mult
        if odyssey:
            value += max(value * ODYSSEY_MAP_MULT, ODYSSEY_MAP_MIN_BONUS)
        if efficient:
            value *= EFFICIENCY_MULT
        return max(MIN_VALUE, int(value))
    value = base
    if not ev.get("WasDiscovered", True):
        value *= FIRST_DISCOVERY_MULT
    return max(MIN_VALUE, int(value))


def body_value_reason(ev: dict, value):
    """Explain missing or approximate valuations in the details view."""
    if value is None:
        if ev.get("StarType") == "SupermassiveBlackHole":
            return "Для сверхмассивной чёрной дыры нет формулы оценки"
        if not ev.get("PlanetClass") and not ev.get("StarType"):
            return "В журнале отсутствует класс тела"
        return "Не удалось рассчитать стоимость по данным журнала"
    if value == 0:
        return "Для этого объекта нет выплаты за картографию"
    planet = ev.get("PlanetClass")
    if planet and planet not in K_PLANET:
        return "Класс отсутствует в таблице; использована базовая оценка"
    return ""


def _read_display_option(key):
    try:
        value = plugin_config.get(f"ExploValue.{key}")
        return 1 if value is None else int(bool(int(value)))
    except (TypeError, ValueError):
        return 1


def body_key(ev: dict):
    """Journal identity for a body; don't merge entries with missing IDs."""
    system_address = ev.get("SystemAddress")
    body_id = ev.get("BodyID")
    if system_address is None or body_id is None:
        return None
    return system_address, body_id


class ExploValue(tk.Frame, Module):
    def __init__(self, parent, gridrow):
        super().__init__(parent)
        self._lock = RLock()
        self.bodies = {}        # ключ тела -> {"ev", "mapped", "efficient"}
        self.last_sale = None   # (факт, оценка)
        self._multi_sell_active = False
        self._rebuilding = True
        self._history_error = False
        self._buffer = []
        self.current_star_type = None
        self.current_system_address = None

        configure_styles(self)
        self.card = ttk.LabelFrame(
            self, text="Картография", padding=(10, 7), style="Triumvirate.Card.TLabelframe"
        )
        self.card.grid(sticky="ew")
        self.card.columnconfigure(0, weight=1)
        metrics = ttk.Frame(self.card, style="Triumvirate.Card.TFrame")
        metrics.grid(row=1, column=0, sticky="ew")
        for column in range(3):
            metrics.columnconfigure(column, weight=1, uniform="exploration_metric")
        pending_tile = ttk.LabelFrame(metrics, text="Не сдано", padding=(7, 5), style="Triumvirate.Card.TLabelframe")
        value_tile = ttk.LabelFrame(metrics, text="Оценка", padding=(7, 5), style="Triumvirate.Card.TLabelframe")
        mapped_tile = ttk.LabelFrame(metrics, text="DSS", padding=(7, 5), style="Triumvirate.Card.TLabelframe")
        for column, tile in enumerate((pending_tile, value_tile, mapped_tile)):
            tile.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 3, 0))
            tile.columnconfigure(0, weight=1)
        self.label_pending = ttk.Label(pending_tile, anchor="w", font=("TkDefaultFont", 10, "bold"), style="Triumvirate.Accent.TLabel")
        self.label_value = ttk.Label(value_tile, anchor="w", font=("TkDefaultFont", 10, "bold"), style="Triumvirate.Accent.TLabel")
        self.label_progress = ttk.Label(mapped_tile, anchor="w", font=("TkDefaultFont", 10, "bold"), style="Triumvirate.Accent.TLabel")
        self.label_sale = ttk.Label(self.card, anchor="w", justify="left", style="Triumvirate.Card.TLabel")
        self.label_status = ttk.Label(self.card, anchor="w", justify="left", style="Triumvirate.Muted.TLabel")
        self.label_star_warning = ttk.Label(
            self.card, anchor="w", justify="left", style="Triumvirate.Warning.TLabel"
        )
        self.label_star_warning.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        self.label_pending.grid(row=0, column=0, sticky="ew")
        self.label_value.grid(row=0, column=0, sticky="ew")
        self.label_progress.grid(row=0, column=0, sticky="ew")
        self.label_sale.grid(row=2, column=0, sticky="ew", pady=(6, 2))
        self.label_status.grid(row=3, column=0, sticky="ew", pady=(2, 4))
        self.details_button = ttk.Button(self.card, text="Подробности по телам…", command=self._show_details)
        self.details_button.grid(row=4, column=0, sticky="w", pady=(2, 0))
        self.columnconfigure(0, weight=1)
        self.grid(column=0, row=gridrow, sticky="ew", pady=(4, 0))
        self._refresh()

    # ---------- хуки Module ----------
    def on_start(self, plugin_dir):
        BasicThread(name="ExploValueHistory", target=self._read_history).start()

    def on_journal_entry(self, entry: JournalEntry):
        ev = entry.data
        if ev.get("event") not in ("Scan", "SAAScanComplete", "Died", "FSDJump", "Location") + SALE_EVENTS:
            return
        with self._lock:
            if self._rebuilding:
                self._buffer.append(ev)
                return
            changed = self._apply(ev)
        if changed:
            self.after(0, self._refresh)

    # ---------- история ----------
    def _read_history(self):
        try:
            # Cartography is an expedition history: earlier scans remain relevant
            # even when the commander sold data partway through the trip.
            history_dir = journal_history.journal_dir()
            if history_dir is None:
                self._history_error = True
                events = []
            else:
                events = journal_history.all_events(directory=history_dir)
        except Exception:
            self._history_error = True
            debug("ExploValue: ошибка чтения истории журналов")
            events = []
        self.after(0, self._finish_history, events)

    def _finish_history(self, events):
        with self._lock:
            for ev in events:
                self._apply(ev)
            self._rebuilding = False
            buffered, self._buffer = self._buffer, []
            for ev in buffered:
                self._apply(ev)
        self._refresh()

    # ---------- обработка события ----------
    def _apply(self, ev) -> bool:
        t = ev.get("event")
        if t != "MultiSellExplorationData":
            self._multi_sell_active = False
        if t in ("FSDJump", "Location"):
            self.current_system_address = ev.get("SystemAddress")
            self.current_star_type = ev.get("StarClass") or ev.get("StarType")
            return True
        if t == "Scan":
            system_address = ev.get("SystemAddress")
            star_updated = False
            if ev.get("StarType") and (
                self.current_system_address is None
                or system_address == self.current_system_address
            ):
                self.current_system_address = system_address
                self.current_star_type = ev.get("StarType")
                star_updated = True
            if ev.get("ScanType") not in SCAN_TYPES:
                return star_updated
            key = body_key(ev)
            if key is None:
                return False
            rec = self.bodies.get(key)
            if rec is None:
                self.bodies[key] = {"ev": ev, "mapped": False, "efficient": False}
                return True
            # Later journal scans can contain more complete information. Preserve
            # DSS data already associated with this body while refreshing its scan.
            rec["ev"] = ev
            return True
        if t == "SAAScanComplete":
            key = body_key(ev)
            rec = self.bodies.get(key) if key is not None else None
            if rec is None:
                return False     # скан этого тела в просмотренном окне не найден
            rec["mapped"] = True
            probes_used = ev.get("ProbesUsed")
            efficiency_target = ev.get("EfficiencyTarget")
            rec["efficient"] = (
                probes_used is not None and efficiency_target is not None
                and probes_used <= efficiency_target
            )
            return True
        if t in SALE_EVENTS:
            actual = ev.get("TotalEarnings")
            if actual is None:
                actual = ev.get("BaseValue", 0) + ev.get("Bonus", 0)
            if t == "MultiSellExplorationData" and self._multi_sell_active and self.last_sale:
                # MultiSellExplorationData is emitted once per page. Keep the
                # first page's pre-sale estimate and aggregate the sale total.
                self.last_sale = (self.last_sale[0] + actual, self.last_sale[1])
            else:
                estimate, _, _ = self.pending_value()
                self.last_sale = (actual, estimate)
            self._multi_sell_active = t == "MultiSellExplorationData"
            self.bodies.clear()
            return True
        if t == "Died" and self.bodies:
            self.bodies.clear()
            return True
        return False

    # ---------- расчёт ----------
    def pending_value(self):
        total, unknown = 0, 0
        with self._lock:
            for rec in self.bodies.values():
                v = body_value(rec["ev"], rec["mapped"], rec["efficient"])
                if v is None:
                    unknown += 1
                else:
                    total += v
            return total, unknown, len(self.bodies)

    def _refresh(self):
        total, unknown, count = self.pending_value()
        mapped = efficient = 0
        with self._lock:
            for rec in self.bodies.values():
                if rec["mapped"]:
                    mapped += 1
                    efficient += bool(rec["efficient"])
            sale = self.last_sale
            rebuilding = self._rebuilding

        self.label_pending["text"] = f"{count} тел"
        self.label_value["text"] = f"~{fmt(total)} CR"
        self.label_progress["text"] = f"{mapped}/{count} · эффективно {efficient}"
        if self.current_star_type and self.current_star_type.startswith("D"):
            self.label_star_warning["text"] = (
                f"⚠ Белый карлик ({self.current_star_type}) · опасный конус — держись на расстоянии"
            )
            self.label_star_warning.grid()
        else:
            self.label_star_warning["text"] = ""
            self.label_star_warning.grid_remove()
        if unknown:
            self.label_value["text"] += f"* ({unknown} без цены)"
        if sale:
            self.label_sale["text"] = f"Последняя сдача: {fmt(sale[0])} CR · оценка до сдачи: ~{fmt(sale[1])} CR"
        else:
            self.label_sale["text"] = "Продаж картографических данных в истории пока нет"
        if rebuilding:
            status = "Читаю историю журналов…"
        elif self._history_error:
            status = "История не загружена полностью · новые события учитываются"
        else:
            status = "История журналов загружена"
        if unknown:
            status += " · * есть тела без оценки"
        self.label_status["text"] = status

    def _show_details(self):
        with self._lock:
            rows = []
            for rec in self.bodies.values():
                ev = rec["ev"]
                value = body_value(ev, rec["mapped"], rec["efficient"])
                body = ev.get("BodyName") or f"Тело {ev.get('BodyID', '—')}"
                system = ev.get("StarSystem") or ev.get("System") or "—"
                if value is None:
                    value_text = "нет оценки"
                else:
                    value_text = f"~{fmt(value)} CR"
                reason = body_value_reason(ev, value)
                if rec["mapped"]:
                    map_text = "DSS · эффективно" if rec["efficient"] else "DSS"
                else:
                    map_text = "не картировано"
                rows.append((system, body, map_text, value_text, reason, bool(ev.get("StarType")), value))

        window = tk.Toplevel(self)
        window.title("Непроданная картография")
        window.transient(self.winfo_toplevel())
        window.minsize(760, 320)
        configure_styles(window)
        container = ttk.Frame(window, padding=10, style="Triumvirate.Card.TFrame")
        container.grid(sticky="nsew")
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        filters = ttk.Frame(container, style="Triumvirate.Card.TFrame")
        filters.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        flags = {
            "stars": tk.IntVar(window, value=_read_display_option("show_stars")),
            "zero": tk.IntVar(window, value=_read_display_option("show_zero")),
            "unknown": tk.IntVar(window, value=_read_display_option("show_unknown")),
        }
        for column, (key, title) in enumerate((
            ("stars", "Показывать звёзды"),
            ("zero", "Показывать нулевые оценки"),
            ("unknown", "Показывать без оценки"),
        )):
            ttk.Checkbutton(
                filters,
                text=title,
                variable=flags[key],
                style="Triumvirate.Card.TCheckbutton",
                command=lambda: refresh_rows(),
            ).grid(row=0, column=column, sticky="w", padx=(0, 12))

        columns = ("system", "body", "mapping", "value", "reason")
        tree = ttk.Treeview(
            container, columns=columns, show="headings", height=12,
            style="Triumvirate.Treeview",
        )
        for key, title in (("system", "Система"), ("body", "Тело"), ("mapping", "DSS"),
                           ("value", "Оценка"), ("reason", "Пояснение")):
            tree.heading(key, text=title)
        tree.column("system", width=155, anchor="w")
        tree.column("body", width=155, anchor="w")
        tree.column("mapping", width=105, anchor="w")
        tree.column("value", width=105, anchor="e")
        tree.column("reason", width=260, anchor="w")
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")

        def refresh_rows():
            for item in tree.get_children():
                tree.delete(item)
            for row in sorted(rows):
                system, body, map_text, value_text, reason, is_star, value in row
                if is_star and not flags["stars"].get():
                    continue
                if value == 0 and not flags["zero"].get():
                    continue
                if value is None and not flags["unknown"].get():
                    continue
                tree.insert("", "end", values=(system, body, map_text, value_text, reason))

        for key, variable in flags.items():
            variable.trace_add("write", lambda *_args, k=key, v=variable: plugin_config.set(
                f"ExploValue.show_{k}", v.get()
            ))
        refresh_rows()
        ttk.Button(container, text="Закрыть", command=window.destroy).grid(
            row=2, column=0, sticky="e", pady=(8, 0)
        )
