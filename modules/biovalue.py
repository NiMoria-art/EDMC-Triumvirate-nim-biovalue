"""
Модуль BioValue: подсчёт стоимости биологических образцов (экзобиология).

Использует данные самого плагина:
  * словари названий видов из modules.bio_dicts;
  * журнальные события, которые уже приходят через JournalEntryProcessor;
  * при старте дочитывает журналы прошлых сессий (modules.journal_history);
Недостающих данных (цены видов) в плагине нет, поэтому таблица цен лежит здесь.
"""
import tkinter as tk
from tkinter import ttk
from threading import RLock

from modules.bio_dicts import codex_to_english_variants, codex_to_english_genuses
from modules.debug import debug
from modules.lib.journal import JournalEntry
from modules.lib.module import Module
from modules.lib.thread import BasicThread
from modules import journal_history
from modules.value_ui import configure_styles

# Приблизительная базовая стоимость видов (кредиты). Можно править.
SPECIES_VALUES = {
    "Aleoida Arcus": 7252500, "Aleoida Coronamus": 6284600, "Aleoida Gravis": 12934900,
    "Aleoida Laminiae": 3385200, "Aleoida Spica": 3385200,
    "Amphora Plant": 1628800,
    "Bacterium Acies": 1000000, "Bacterium Alcyoneum": 1658500, "Bacterium Aurasus": 1000000,
    "Bacterium Bullaris": 1152500, "Bacterium Cerbrus": 1689800, "Bacterium Informem": 8418000,
    "Bacterium Nebulus": 5289900, "Bacterium Omentum": 4638900, "Bacterium Scopulum": 4934500,
    "Bacterium Tela": 1949000, "Bacterium Verrata": 3897000, "Bacterium Vesicula": 1000000,
    "Bacterium Volu": 7774700,
    "Cactoida Cortexum": 3667600, "Cactoida Lapis": 2483600, "Cactoida Peperatis": 2483600,
    "Cactoida Pullulanta": 3667600, "Cactoida Vermis": 16202800,
    "Clypeus Lacrimam": 8418000, "Clypeus Margaritus": 11873200, "Clypeus Speculumi": 16202800,
    "Concha Aureolas": 7774700, "Concha Biconcavis": 19010800, "Concha Labiata": 2352400,
    "Concha Renibus": 4572400,
    "Electricae Pluma": 6284600, "Electricae Radialem": 6284600,
    "Fonticulua Campestris": 1000000, "Fonticulua Digitos": 1804100, "Fonticulua Fluctus": 20000000,
    "Fonticulua Lapida": 3111000, "Fonticulua Segmentatus": 19010800, "Fonticulua Upupam": 5727600,
    "Frutexa Acus": 7774700, "Frutexa Collum": 1639800, "Frutexa Fera": 1632500,
    "Frutexa Flabellum": 1808900, "Frutexa Flammasis": 10326000, "Frutexa Metallicum": 1632500,
    "Frutexa Sponsae": 5988000,
    "Fumerola Aquatis": 6284600, "Fumerola Carbosis": 6284600, "Fumerola Extremus": 16202800,
    "Fumerola Nitris": 7500900,
    "Fungoida Bullarum": 3703200, "Fungoida Gelata": 3330300, "Fungoida Setisis": 1670100,
    "Fungoida Stabitis": 2680300,
    "Osseus Cornibus": 1483000, "Osseus Discus": 12934900, "Osseus Fractus": 4029700,
    "Osseus Pellebantus": 9739000, "Osseus Pumice": 3156300, "Osseus Spiralis": 2404700,
    "Recepta Conditivus": 14313700, "Recepta Deltahedronix": 16202800, "Recepta Umbrux": 12934900,
    "Stratum Araneamus": 2448900, "Stratum Cucumisis": 16202800, "Stratum Excutitus": 2448900,
    "Stratum Frigus": 2637500, "Stratum Laminamus": 2788300, "Stratum Limaxus": 1362000,
    "Stratum Paleas": 1362000, "Stratum Tectonicas": 19010800,
    "Tubus Cavas": 11873200, "Tubus Compagibus": 7774700, "Tubus Conifer": 2415500,
    "Tubus Rosarium": 2637500, "Tubus Sororibus": 5727600,
    "Tussock Albata": 3252500, "Tussock Capillum": 7025800, "Tussock Caputus": 3472400,
    "Tussock Catena": 1766600, "Tussock Cultro": 1766600, "Tussock Divisa": 1766600,
    "Tussock Ignis": 1849000, "Tussock Pennata": 5853800, "Tussock Pennatis": 1000000,
    "Tussock Propagito": 1000000, "Tussock Serrati": 4447100, "Tussock Stigmasis": 19010800,
    "Tussock Triticum": 7774700, "Tussock Ventusa": 3277700, "Tussock Virgam": 14313700,
    # Виды без названия рода в словаре bio_dicts (приблизительно)
    "Amphora Plant": 1628800, "Bark Mounds": 1471900,
    "Roseum Brain Tree": 1593700, "Gypseeum Brain Tree": 1593700, "Ovatum Brain Tree": 3565100,
    "Puniceum Brain Tree": 1593700, "Lindigoticum Brain Tree": 1593700, "Viride Brain Tree": 1593700,
    "Puniceum Anemone": 1499900, "Prasinum Bioluminescent Anemone": 1499900,
    "Luteolum Anemone": 1499900, "Croceum Anemone": 3399800, "Roseum Anemone": 1499900,
    "Blatteum Bioluminescent Anemone": 1499900, "Rubeum Bioluminescent Anemone": 1499900,
    "Roseum Bioluminescent Anemone": 1499900, "Prasinum Anemone": 1499900,
}

FIRST_BONUS = 5          # итоговый множитель First Logged
def fmt(n) -> str:
    return f"{int(n):,}".replace(",", " ")


def resolve_species(data: dict):
    """Возвращает каноническое английское имя вида для поиска цены.

    Species_Localised зависит от языка игры, поэтому его нельзя использовать
    как ключ SPECIES_VALUES. Сначала используем Variant/Species из журнала,
    затем словари BioPatrol, а локализованное имя оставляем только как fallback.
    """
    for key in (data.get("Variant"), data.get("Species")):
        if key:
            mapped = codex_to_english_variants.get(key)
            if mapped:
                return mapped.split(" - ")[0]
            if key in SPECIES_VALUES:
                return key

    name = data.get("Species_Localised")
    if name and name in SPECIES_VALUES:
        return name

    genus = data.get("Genus")
    if genus:
        return codex_to_english_genuses.get(genus, genus)
    return name or "Unknown"


class BioValue(tk.Frame, Module):
    def __init__(self, parent, gridrow):
        super().__init__(parent)
        self._lock = RLock()
        self.pending = {}      # уникальный ключ события -> {"name", "variant", "body"}
        self.sold = {}         # timestamp продажи -> сумма (защита от повторов)
        self._rebuilding = True
        self._buffer = []      # живые события, пришедшие пока читается история

        configure_styles(self)
        self.card = ttk.LabelFrame(
            self, text="Экзобиология", padding=(10, 7), style="Triumvirate.Card.TLabelframe"
        )
        self.card.grid(sticky="ew")
        self.card.columnconfigure(0, weight=1)
        metrics = ttk.Frame(self.card, style="Triumvirate.Card.TFrame")
        metrics.grid(row=0, column=0, sticky="ew")
        for column in range(3):
            metrics.columnconfigure(column, weight=1, uniform="bio_metric")
        pending_tile = ttk.LabelFrame(metrics, text="Не сдано", padding=(7, 5), style="Triumvirate.Card.TLabelframe")
        sold_tile = ttk.LabelFrame(metrics, text="Продано", padding=(7, 5), style="Triumvirate.Card.TLabelframe")
        bonus_tile = ttk.LabelFrame(metrics, text="Возможный бонус ×5", padding=(7, 5), style="Triumvirate.Card.TLabelframe")
        for column, tile in enumerate((pending_tile, sold_tile, bonus_tile)):
            tile.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 3, 0))
            tile.columnconfigure(0, weight=1)
        self.label_pending = ttk.Label(pending_tile, anchor="w", font=("TkDefaultFont", 10, "bold"), style="Triumvirate.Accent.TLabel")
        self.label_pending_value = ttk.Label(pending_tile, anchor="w", style="Triumvirate.Card.TLabel")
        self.label_sold = ttk.Label(sold_tile, anchor="w", font=("TkDefaultFont", 10, "bold"), style="Triumvirate.Accent.TLabel")
        self.label_first = ttk.Label(bonus_tile, anchor="w", font=("TkDefaultFont", 10, "bold"), style="Triumvirate.Accent.TLabel")
        self.label_bio_status = ttk.Label(self.card, anchor="w", style="Triumvirate.Muted.TLabel")
        self.label_pending.grid(row=0, column=0, sticky="ew")
        self.label_pending_value.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        self.label_sold.grid(row=0, column=0, sticky="ew")
        self.label_first.grid(row=0, column=0, sticky="ew")
        self.label_bio_status.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        self.columnconfigure(0, weight=1)
        self.grid(column=0, row=gridrow, sticky="ew", pady=(4, 0))
        self._refresh()

    # ---------- хуки Module ----------
    def on_start(self, plugin_dir):
        BasicThread(name="BioValueHistory", target=self._read_history).start()

    def on_journal_entry(self, entry: JournalEntry):
        ev = entry.data
        if ev.get("event") not in ("ScanOrganic", "SellOrganicData", "Died"):
            return
        with self._lock:
            if self._rebuilding:
                self._buffer.append((ev, entry.body))
                return
            changed = self._apply(ev, entry.body)
        if changed:
            self.after(0, self._refresh)

    # ---------- история ----------
    def _read_history(self):
        try:
            # Replay sales as well as scans so the sold total survives restarts.
            events = journal_history.all_events(max_files=300)
        except Exception:
            debug("BioValue: ошибка чтения истории журналов")
            events = []
        self.after(0, self._finish_history, events)

    def _finish_history(self, events):
        with self._lock:
            for ev in events:
                self._apply(ev, None)       # название тела в старых записях недоступно
            self._rebuilding = False
            buffered, self._buffer = self._buffer, []
            for ev, body in buffered:
                self._apply(ev, body)
        self._refresh()

    # ---------- обработка события ----------
    def _apply(self, ev, body) -> bool:
        t = ev.get("event")
        if t == "ScanOrganic" and ev.get("ScanType") == "Analyse":
            ts = ev.get("timestamp")
            key = (ts, ev.get("SystemAddress"), ev.get("Body"), ev.get("Variant"), ev.get("Species"))
            if key in self.pending:
                return False
            name = resolve_species(ev)
            self.pending[key] = {
                "name": name,
                "variant": ev.get("Variant_Localised", ""),
                "body": body,
            }
            return True
        if t == "SellOrganicData":
            sale_key = ev.get("timestamp")
            self.sold[sale_key] = sum(i.get("Value", 0) + i.get("Bonus", 0)
                                      for i in ev.get("BioData", []))
            self.pending.clear()
            return True
        if t == "Died" and self.pending:
            self.pending.clear()
            return True
        return False

    # ---------- расчёт ----------
    def pending_value(self):
        total, first_total, unknown = 0, 0, 0
        with self._lock:
            for p in self.pending.values():
                base = SPECIES_VALUES.get(p["name"])
                if base is None:
                    unknown += 1
                    continue
                total += base
                # Journal ScanOrganic does not tell us whether this sample will
                # receive the First Logged bonus. BioPatrol priority is a location
                # hint, not proof that we are first to sell the sample.
                first_total += base * FIRST_BONUS
            return total, first_total, unknown, len(self.pending)

    def _refresh(self):
        total, first_total, unknown, count = self.pending_value()
        self.label_pending["text"] = f"{count} образцов"
        self.label_pending_value["text"] = f"~{fmt(total)} CR"
        self.label_first["text"] = f"~{fmt(first_total)} CR"
        with self._lock:
            sold = sum(self.sold.values())
        self.label_sold["text"] = f"{fmt(sold)} CR"
        self.label_bio_status["text"] = (
            f"{unknown} образцов без цены · бонус зависит от факта первой сдачи"
            if unknown else "Оценка примерная · бонус зависит от факта первой сдачи"
        )
