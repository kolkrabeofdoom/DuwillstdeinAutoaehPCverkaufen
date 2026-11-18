import concurrent.futures
import csv
import html
import json
import math
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

MARKET = "https://www.heise.de/preisvergleich/"
HISTORY_URL = "https://preisvergleich.heise.de/api/gh0/price_history"
CPU_BENCH = "https://www.notebookcheck.net/Mobile-Processors-Benchmark-List.2436.0.html"
# G3D Mark, Stand 18.11.2026, für ausgewählte Desktop-Chips.
# Quelle: https://www.videocardbenchmark.net/common_gpus.html
DESKTOP_GPU = {
    "GeForce RTX 4090": 38014, "GeForce RTX 5080": 35652,
    "GeForce RTX 5070 Ti": 32336, "GeForce RTX 4070 Ti": 31514,
    "GeForce RTX 4070 SUPER": 29938, "GeForce RTX 5070": 28684,
    "Radeon RX 9070 XT": 26926, "GeForce RTX 4070": 26852,
    "GeForce RTX 3080 Ti": 26723, "GeForce RTX 3090": 26456,
    "GeForce RTX 3080": 24969, "GeForce RTX 5060 Ti 16GB": 22635,
}
RAM_TYPES = {17: "SDRAM", 18: "SGRAM", 19: "RDRAM", 20: "DDR",
             21: "DDR2", 24: "DDR3", 26: "DDR4", 27: "LPDDR",
             28: "LPDDR2", 29: "LPDDR3", 30: "LPDDR4", 34: "DDR5",
             35: "LPDDR5"}
FORMS = {8: "DIMM", 12: "SO-DIMM"}
COLUMNS = ("Kategorie", "Installierte Hardware", "Technische Daten",
           "Vergleichsprodukt", "Vergleich", "Preis pro Stück", "Quelle", "Abruf")


@dataclass(frozen=True)
class PriceChoice:
    label: str
    title: str
    note: str
    price: Decimal | None
    url: str

    def columns(self):
        if self.price is not None:
            return self.title, self.note, f"ab {euros(self.price)}", "heise Preisvergleich"
        return self.title, self.note, "", "heise-Suche" if self.url else ""


@dataclass(frozen=True)
class HistoryProduct:
    title: str
    url: str
    reference: bool = False
    current_price: Decimal | None = None


@dataclass(frozen=True)
class HistoryLine:
    label: str
    points: dict[date, Decimal]
    color: str
    current_price: Decimal | None = None
    dashed: bool = False


POWERSHELL = r"""
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$ErrorActionPreference = 'Stop'
function Read-Item($label, [scriptblock]$query) {
    try { & $query } catch { $script:issues += $label }
}
$issues = @()
$cpu = @(Read-Item CPU { Get-CimInstance Win32_Processor |
    Select-Object Name, NumberOfCores, NumberOfLogicalProcessors })
$gpu = @(Read-Item GPU { Get-CimInstance Win32_VideoController |
    Select-Object Name })
$ram = @(Read-Item RAM { Get-CimInstance Win32_PhysicalMemory |
    Select-Object PartNumber, Capacity, SMBIOSMemoryType, ConfiguredClockSpeed, Speed, FormFactor, DeviceLocator })
$disk = @(Read-Item Laufwerke {
    try {
        $physical = @(Get-PhysicalDisk)
        if ($physical.Count -gt 0) {
            $physical | Select-Object FriendlyName, Size, BusType, MediaType
            return
        }
    } catch {}
    Get-CimInstance Win32_DiskDrive | Select-Object @{n='FriendlyName';e={$_.Model}},
        Size, @{n='BusType';e={$_.InterfaceType}}, @{n='MediaType';e={'Unspecified'}}
})
$board = @(Read-Item Mainboard { Get-CimInstance Win32_BaseBoard | Select-Object Manufacturer, Product })
$system = @(Read-Item System { Get-CimInstance Win32_ComputerSystem | Select-Object PCSystemType })
@{cpu=$cpu;gpu=$gpu;ram=$ram;disk=$disk;board=$board;system=$system;issues=$issues} |
    ConvertTo-Json -Depth 4 -Compress
"""


def clean(text):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", text or "")).split())


def normalized(text):
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def euros(value):
    return f"{value:,.2f} €".translate(str.maketrans(",.", ".,"))


def cpu_name(name):
    name = re.sub(r"^\d+(?:st|nd|rd|th) Gen\s+", "", name)
    name = re.sub(r"\((?:R|TM)\)|\s+@.*|\s+\d+-Core Processor.*|\s+with Radeon.*", "", name, flags=re.I)
    return re.sub(r"\s+CPU\b", "", name).strip()


def capacity(size):
    gb = (size or 0) / 1e9
    return f"{gb / 1000:.2g} TB" if gb >= 1000 else f"{gb:.3g} GB"


def inventory():
    exe = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run([str(exe), "-NoProfile", "-NonInteractive", "-Command", POWERSHELL],
                            capture_output=True, encoding="utf-8", errors="replace",
                            timeout=40, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    data = json.loads(result.stdout)
    rows = []
    mobile = any(x.get("PCSystemType") == 2 for x in data["system"])
    for x in data["cpu"]:
        name = cpu_name(x["Name"])
        rows.append(("CPU", name, f"{x['NumberOfCores']} Kerne / {x['NumberOfLogicalProcessors']} Threads", name, {}))
    for x in data["gpu"]:
        name = x.get("Name") or "Unbekannt"
        chip = re.sub(r"^NVIDIA\s+", "", name)
        rows.append(("GPU", name, "Grafikchip laut Windows", chip, {"mobile": mobile}))
    for x in data["ram"]:
        part = (x.get("PartNumber") or "").strip()
        gib = (x["Capacity"] or 0) / 1024**3
        kind = RAM_TYPES.get(x["SMBIOSMemoryType"], "Typ unbekannt")
        form = FORMS.get(x["FormFactor"], "")
        speed = x["ConfiguredClockSpeed"] or x["Speed"]
        details = f"{gib:g} GiB {kind} {form}".strip()
        if speed:
            details += f" · {speed} MT/s"
        if x.get("DeviceLocator"):
            details += f" · {x['DeviceLocator']}"
        rows.append(("RAM", part or "RAM-Modul", details, part,
                     {"kind": kind, "gib": gib, "form": form, "speed": speed}))
    for x in data["disk"]:
        name = (x.get("FriendlyName") or "Unbekannt").strip()
        bus = str(x.get("BusType") or "Unbekannt")
        media = str(x.get("MediaType") or "Unspecified")
        if bus.casefold() == "nvme" and media == "Unspecified":
            media = "SSD"
        size = capacity(x["Size"])
        query = re.sub(r"^KINGSTON (SNV\dS)(\d+G)$", r"\1 \2", name, flags=re.I)
        query = re.sub(r"^Micron (CT\w+)$", r"\1", query, flags=re.I)
        rows.append((media if media in {"SSD", "HDD"} else "Laufwerk", name,
                     f"{size} · {bus}", query, {"size": size, "bus": bus}))
    for x in data["board"]:
        maker = (x["Manufacturer"] or "").replace("Micro-Star International Co., Ltd.", "MSI")
        product = re.sub(r"\s+\(MS-\w+\)$", "", x["Product"] or "")
        name = f"{maker} {product}".strip()
        if product and product.casefold() not in {"default string", "to be filled by o.e.m."}:
            rows.append(("Mainboard", name, "", name, {}))
    total = sum((x["Capacity"] or 0) for x in data["ram"]) / 1024**3
    return rows, total, data["issues"]


def download(url):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "de-DE,de;q=0.9"})
    with urlopen(request, timeout=10) as response:
        return response.read(12_000_000).decode("utf-8", errors="replace")


def market_url(query, category):
    filters = {"fs": query, "hloc": "de"}
    if category == "GPU":
        filters["cat"] = "gra16_512"
    return MARKET + "?" + urlencode(filters)


@lru_cache(maxsize=128)
def market(query, category):
    source = download(market_url(query, category))
    cards = re.findall(r'<article\b[^>]*class="galleryview__item[^"]*"[^>]*>(.*?)</article>', source, re.S)
    if not cards and ("Verbindung wird überprüft" in source or "ghbody" not in source):
        raise ValueError("Preisquelle hat keine auswertbare Seite geliefert.")
    offers = []
    for card in cards:
        item = re.search(r'<a\s+href="([^"]+)"\s+class="galleryview__name-link"\s+title="([^"]+)"', card)
        if not item or urlsplit(item[1]).hostname != "preisvergleich.heise.de":
            continue
        price = re.search(r'<span class="price">\s*€\s*((?:\d{1,3}(?:\.\d{3})+|\d+),\d{2})', card)
        part = re.search(r'<span class="galleryview__mpn">(.*?)</span>', card, re.S)
        amount = Decimal(price[1].replace(".", "").replace(",", ".")) if price else None
        available = bool(re.search(r'class="availability availability--available(?:\s|")', card))
        offers.append((clean(item[2]), amount, html.unescape(item[1]),
                       clean(part[1]) if part else "", available))
    return offers


def gpu_match(chip, title):
    match = re.search(r"\b(?:RTX|GTX|RX|Arc)\s*\d+[a-z]?\s*(?:Ti\s*SUPER|Ti|SUPER|XTX|XT|GRE)?\b", chip, re.I)
    if not match:
        return False
    model = re.escape(match[0].strip()).replace(r"\ ", r"\s*")
    if not re.search(r"\b" + model + r"\b(?!\s*(?:Ti|SUPER|XTX|XT|GRE)\b)", title, re.I):
        return False
    vram = re.search(r"\b\d+\s*GB\b", chip, re.I)
    if vram and not re.search(r"\b" + re.escape(vram[0].replace(" ", "")) + r"\b", title, re.I):
        return False
    return bool(re.search(r"\bGDDR\d", title, re.I))


def same_product(category, query, offer):
    title, _, _, part, _ = offer
    if re.search(r"Komplettsystem|Gaming-PC|Laptop|Notebook|Aufrüstkit|kompatibel|Ladekabel", title, re.I):
        return False
    if category == "GPU":
        return gpu_match(query, title)
    if category == "RAM":
        return normalized(query) == normalized(part)
    if category == "CPU":
        return bool(re.match(re.escape(query) + r"(?:\s+@.*)?(?:,|\s*\(|$)", title, re.I))
    if category == "Mainboard":
        return normalized(query) == normalized(re.sub(r"\s*\([^()]+\)$", "", title))
    short = re.sub(r"\bSSD\b", "", query, flags=re.I)
    label = re.sub(r"\bSSD\b", "", title.split(",")[0], flags=re.I)
    return normalized(short) in {normalized(label), normalized(part)}


@lru_cache(maxsize=1)
def cpu_benchmarks():
    source = download(CPU_BENCH)
    result = {}
    for row in re.findall(r'<tr class="desk_(?:odd|even)">(.*?)</tr>', source, re.S):
        model = re.search(r'<td class="specs"><a href="([^"]+)">([^<]+)</a>', row)
        multi = re.search(r'class="bl_med_val_768_2370">([\d.]+)', row)
        if model and multi:
            result[clean(model[2])] = (float(multi[1]), model[1])
    return result


def first_available(offers, predicate):
    return min((o for o in offers if o[1] is not None and o[4] and predicate(o)),
               key=lambda o: o[1], default=None)


def brand(category, model):
    name = model.casefold()
    if category == "CPU":
        if name.startswith("intel "):
            return "Intel"
        if name.startswith("amd "):
            return "AMD"
    if category == "GPU":
        if name.startswith(("nvidia", "geforce")):
            return "NVIDIA"
        if name.startswith(("amd", "radeon")):
            return "AMD"
        if name.startswith(("intel", "arc")):
            return "Intel"
    return None


def benchmark_options(category, query):
    if category == "GPU":
        scores = DESKTOP_GPU
        query = re.sub(r"^AMD (?=Radeon )", "", query, flags=re.I)
        baseline = scores.get(query)
        label = "PassMark G3D Mark (18.11.2026)"
    else:
        scores = {name: score for name, (score, _) in cpu_benchmarks().items()}
        baseline = scores.get(query)
        label = "Cinebench R23 Multi"
        if not baseline and re.fullmatch(r"Intel Core i\d-\d+KF", query):
            reference = query[:-1]
            baseline = scores.get(reference)
            label += f" · Referenz {reference}"
    if not baseline:
        return []
    candidates = sorted(((abs(score / baseline - 1), name, score / baseline - 1)
                         for name, score in scores.items() if name != query),
                        key=lambda item: (item[0], item[1]))
    return [(name, label + " " + f"{delta:+.1%}".replace(".", ","))
            for error, name, delta in candidates if error <= 0.20]


def market_match(category, query):
    if query:
        return first_available(market(query, category), lambda offer: same_product(category, query, offer))
    return None


def priced_choice(offer, note, label="Vorschlag"):
    return PriceChoice(label, offer[0], note, offer[1], offer[2])


def no_price(note, url="", label="Vorschlag"):
    return PriceChoice(label, "", note, None, url)


def brand_choices(category, query):
    search = market_url(query, category)
    preferred = brand(category, query)
    exact = None
    failed = False
    try:
        exact = market_match(category, query)
    except (OSError, ValueError):
        failed = True
    primary_label = f"{preferred} (Standard)" if preferred else "Vorschlag"
    if exact:
        match = "Gleicher Grafikchip" if category == "GPU" else "Gleiches Modell"
        primary = priced_choice(exact, match, primary_label)
    else:
        primary = None
    if not preferred:
        return (primary or no_price("Kein passendes lagerndes Angebot gefunden" if not failed
                                    else "Online-Abfrage fehlgeschlagen", search),)
    try:
        candidates = benchmark_options(category, query)
    except (OSError, ValueError):
        candidates = []
        failed = True

    def available(target, label):
        lookup_failed = False
        models = [(model, note) for model, note in candidates if brand(category, model) == target]
        for model, note in models[:6]:
            try:
                offer = market_match(category, model)
            except (OSError, ValueError):
                lookup_failed = True
                continue
            if offer:
                return priced_choice(offer, note, label), lookup_failed
        return None, lookup_failed

    if not primary:
        primary, lookup_failed = available(preferred, primary_label)
        failed = failed or lookup_failed
    rivals = {"CPU": {"Intel": "AMD", "AMD": "Intel"},
              "GPU": {"NVIDIA": "AMD", "AMD": "NVIDIA"}}
    opposite = rivals[category].get(preferred)
    alternative, _ = available(opposite, f"{opposite} (Alternative)") if opposite else (None, False)
    if not primary:
        if failed:
            note = f"Abfrage für {preferred} unvollständig"
        elif not candidates:
            note = "Kein Benchmark-Vergleich verfügbar"
        else:
            note = f"Kein vergleichbares lagerndes {preferred}-Angebot gefunden"
        primary = no_price(note, search, primary_label)
    return (primary, alternative) if alternative else (primary,)


def price_row(row):
    category, name, _, query, specs = row
    search_url = market_url(query, category) if query else ""
    if category == "GPU" and (specs["mobile"] or re.search(r"Laptop|Mobile", query, re.I)):
        return (no_price("Notebook-GPU · kein Einzelteilvergleich"),)
    if category in {"CPU", "GPU"}:
        return brand_choices(category, query)
    try:
        offer = market_match(category, query)
        note = "Gleiches Modell"
        if not offer and category == "RAM" and query.upper() == "KF556C40-32":
            # Verkürzte SPD-Kennung: Handelsvariante nur als Vergleich anzeigen.
            retail = "KF556C40BB-32"
            offer = first_available(market(retail, category), lambda o: same_product(category, retail, o))
            note = "DDR5-5600 CL40 · passende Handelsvariante"
        if not offer and category == "RAM" and specs["form"] and specs["speed"] and specs["kind"].startswith("DDR"):
            form, kind, speed, gib = (specs[k] for k in ("form", "kind", "speed", "gib"))
            fallback = f"{kind} {gib:g}GB {speed} {form}"
            def ram_match(o):
                title = o[0]
                form_pattern = r"(?<!SO-)\bU?DIMM\b" if form == "DIMM" else r"\bSO-DIMM\b"
                return (bool(re.search(rf"\b{kind}-{speed}\b", title, re.I))
                        and bool(re.search(rf"\b{gib:g}\s*GB\b", title, re.I))
                        and bool(re.search(form_pattern, title, re.I))
                        and not re.search(r"\b(?:Kit|RDIMM|ECC)\b", title, re.I))
            offer = first_available(market(fallback, category), ram_match)
            note = "Gleiche Kapazität, Bauform und Datenrate"
            search_url = market_url(fallback, category)
        if not offer and category == "SSD":
            size, bus = specs["size"], specs["bus"].upper()
            interface = {"NVME": "NVMe", "USB": "USB", "SATA": "SATA"}.get(bus)
            if interface:
                fast_usb = normalized(query) == "ct2000x9prossd9"
                fallback = f"{interface} SSD {size.replace(' ', '')}"
                if fast_usb:
                    fallback += " USB-C 3.2"
                def disk_match(o):
                    title = o[0]
                    return (bool(re.search(rf"\b{size.replace(' ', r'\s*')}\b", title, re.I))
                            and bool(re.search(r"\bSSD\b", title, re.I))
                            and bool(re.search(rf"\b{interface}\b", title, re.I))
                            and not re.search(r"Gehäuse|Adapter|kompatibel|Komplettsystem|Notebook", title, re.I)
                            and (not fast_usb or bool(re.search(r"USB-C 3\.[12](?!\s+Gen\s*1)", title, re.I)))
                            and (bus != "NVME" or "2280" in title)
                            and (bus != "SATA" or '2.5"' in title or '2.5”' in title))
                if bus == "NVME" and re.search(r"2230|2242|22110", name):
                    return (no_price("Bauform gesondert prüfen", search_url),)
                offer = first_available(market(fallback, category), disk_match)
                note = "Gleiche Kapazität und Schnittstelle"
                if bus == "NVME":
                    note += " · Vergleich in M.2 2280"
                if fast_usb:
                    note += " · USB-C"
                search_url = market_url(fallback, category)
        if offer:
            return (priced_choice(offer, note),)
        status = "Kein passendes lagerndes Angebot gefunden" if query else "Modellnummer fehlt"
        return (no_price(status, search_url),)
    except (OSError, ValueError):
        return (no_price("Online-Abfrage fehlgeschlagen", search_url),)


def compare(rows, callback):
    market.cache_clear()
    cpu_benchmarks.cache_clear()
    stamp = datetime.now().strftime("%d.%m.%Y %H:%M")
    unique = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for index, row in enumerate(rows):
            key = (row[0], row[1], row[3], tuple(row[4].items()))
            if key not in unique:
                unique[key] = (pool.submit(price_row, row), [])
            unique[key][1].append(index)
        for future in concurrent.futures.as_completed([entry[0] for entry in unique.values()]):
            indices = next(indices for job, indices in unique.values() if job is future)
            choices = future.result()
            for index in indices:
                callback(index, choices, stamp)


def product_id(url):
    parsed = urlsplit(url)
    if parsed.scheme == "https" and parsed.hostname == "preisvergleich.heise.de":
        match = re.search(r"-a(\d+)\.html$", parsed.path)
        if match:
            return int(match[1])
    return None


def installed_product(row, choices):
    category, _, _, query, specs = row
    if not query or (category == "GPU" and (specs["mobile"] or re.search(r"Laptop|Mobile", query, re.I))):
        return None
    for choice in choices:
        if choice.note in {"Gleiches Modell", "Gleicher Grafikchip"} and product_id(choice.url):
            return HistoryProduct(choice.title, choice.url, category == "GPU", choice.price)

    offers = market(query, category)
    match = next((o for o in offers if same_product(category, query, o)), None)
    reference = category == "GPU"
    if not match and category == "RAM" and query.upper() == "KF556C40-32":
        retail = "KF556C40BB-32"
        match = next((o for o in market(retail, category) if same_product(category, retail, o)), None)
        reference = True
    if match and product_id(match[2]):
        return HistoryProduct(match[0], match[2], reference, match[1] if match[4] else None)
    return None


def daily_prices(item_id):
    body = json.dumps({"id": item_id, "params": {"days": 9999, "loc": "de"}}).encode("utf-8")
    request = Request(HISTORY_URL, data=body, headers={"Accept": "application/json",
                      "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=10) as response:
        payload = json.loads(response.read(1_500_000), parse_float=Decimal)
    if not isinstance(payload, dict) or not isinstance(payload.get("response"), list):
        raise ValueError("Preisverlauf hat ein unbekanntes Format.")
    points = {}
    for record in payload["response"]:
        if not isinstance(record, list) or len(record) < 2:
            continue
        stamp, price = record[:2]
        if (type(stamp) is int and 0 < stamp < 4_102_444_800_000
                and isinstance(price, (int, Decimal)) and price > 0):
            day = datetime.fromtimestamp(stamp / 1000, timezone.utc).date()
            points[day] = Decimal(price)
    return points


def load_histories(rows, results):
    def resolve(index):
        choices, _ = results.get(index, ((), ""))
        try:
            return installed_product(rows[index], choices)
        except (OSError, ValueError):
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        installed = list(pool.map(resolve, range(len(rows))))
        ids = {product_id(entry.url) for entry in installed if entry}
        ids.update(product_id(choice.url) for choices, _ in results.values() for choice in choices)
        jobs = {pool.submit(daily_prices, item_id): item_id for item_id in ids if item_id is not None}
        histories = {}
        for job in concurrent.futures.as_completed(jobs):
            try:
                histories[jobs[job]] = job.result()
            except (OSError, ValueError):
                pass
    return installed, histories


def sum_history(series, start, end):
    if not series or not all(series):
        return {}
    dates = set(series[0]).intersection(*series[1:])
    return {day: sum(prices[day] for prices in series) for day in dates if start <= day <= end}


def two_years_before(day):
    return day.replace(year=day.year - 2, day=28 if (day.month, day.day) == (2, 29) else day.day)


def compact_product(title):
    return title.split(",", 1)[0]


def extrema(points):
    low = min(points.items(), key=lambda point: (point[1], point[0]))
    high = min(points.items(), key=lambda point: (-point[1], point[0]))
    return low, high


def price_change(current, minimum):
    if current is None:
        return "Aktuell kein vollständiger Preis"
    difference = current - minimum
    if not difference:
        return f"Aktuell {euros(current)} · entspricht dem Tief"
    percentage = f"{abs(difference) / minimum * 100:.1f}".replace(".", ",") + " %"
    direction = "über" if difference > 0 else "unter"
    return f"Aktuell {euros(current)} · {euros(abs(difference))} ({percentage}) {direction} dem Tief"


def complete_total(prices):
    if prices and all(price is not None for price in prices):
        return sum(prices, Decimal("0.00"))
    return None


class HistoryChart(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.lines = []
        self.start_day = self.end_day = date.today()
        self.empty_message = ""
        self.plot_bounds = None
        self.legend = ttk.Label(self, foreground="#314159", anchor="w")
        self.legend.pack(fill="x", pady=(5, 6))
        self.canvas = tk.Canvas(self, height=220, background="#f7f9fd", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.stats = ttk.Label(self, foreground="#314159", anchor="w", font=("Segoe UI", 9))
        self.stats.pack(fill="x", pady=(6, 0))
        self.hover = ttk.Label(self, foreground="#314159", text=" ")
        self.hover.pack(anchor="w", pady=(5, 0))
        self.canvas.bind("<Configure>", self.draw)
        self.canvas.bind("<Motion>", self.move_pointer)
        self.canvas.bind("<Leave>", self.clear_pointer)

    def show(self, lines, start, end, note, empty_message):
        self.start_day, self.end_day = start, end
        self.lines = [HistoryLine(line.label, {d: p for d, p in line.points.items() if start <= d <= end},
                                  line.color, line.current_price, line.dashed) for line in lines]
        self.extremes = [extrema(line.points) if line.points else None for line in self.lines]
        self.empty_message = empty_message
        self.legend.configure(text=note)
        rows = []
        for line, points in zip(self.lines, self.extremes):
            if points:
                (low_day, low), (high_day, high) = points
                rows.append(f"{line.label}   |   Tief {euros(low)} am {low_day:%d.%m.%Y}"
                            f"   |   Hoch {euros(high)} am {high_day:%d.%m.%Y}"
                            f"   |   {price_change(line.current_price, low)}")
            else:
                rows.append(f"{line.label}   |   Keine Tagespreise im Zeitraum")
        self.stats.configure(text="\n".join(rows))
        if rows:
            self.stats.pack(before=self.hover, fill="x", pady=(6, 0))
        else:
            self.stats.pack_forget()
        self.draw()

    def draw(self, _event=None):
        self.canvas.delete("all")
        self.plot_bounds = None
        self.clear_pointer()
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if width < 180 or height < 75:
            return
        values = [float(price) for line in self.lines for price in line.points.values()]
        if not values:
            self.canvas.create_text(width / 2, height / 2, text=self.empty_message, width=width - 30,
                                    fill="#314159", font=("Segoe UI", 11))
            return
        left, right, top, bottom = 82, width - 35, 17, height - 28
        days = max(1, (self.end_day - self.start_day).days)
        low, high = min(values), max(values)
        step_size = max((high - low) / 4, high * 0.015, 0.01)
        magnitude = 10 ** math.floor(math.log10(step_size))
        step = next(factor * magnitude for factor in (1, 2, 2.5, 5, 10)
                    if factor * magnitude >= step_size)
        low = max(0, (math.ceil(low / step) - 1) * step)
        high = (math.floor(high / step) + 1) * step
        self.plot_bounds = left, right, top, bottom, days

        def y(price):
            return bottom - (float(price) - low) / (high - low) * (bottom - top)

        def x(day):
            return left + (day - self.start_day).days / days * (right - left)

        for tick in range(math.ceil(low / step), math.floor(high / step + 1e-8) + 1):
            value = tick * step
            pos = y(value)
            self.canvas.create_line(left, pos, right, pos, fill="#dbe2ee")
            label = euros(value) if step < 1 else f"{value:,.0f} €".replace(",", ".")
            self.canvas.create_text(left - 9, pos, text=label, anchor="e",
                                    fill="#3d4b61", font=("Segoe UI", 9))
        divisions = min(7, days, max(2, (right - left) // 114))
        for tick in range(divisions + 1):
            offset = round(days * tick / divisions)
            day = self.start_day + timedelta(days=offset)
            position = x(day)
            self.canvas.create_line(position, top, position, bottom, fill="#e7edf6")
            self.canvas.create_text(position, bottom + 12, text=day.strftime("%d.%m.%y"),
                                    fill="#3d4b61", font=("Segoe UI", 9))

        for line in self.lines:
            coordinates = []
            previous = None
            for day, price in sorted(line.points.items()):
                if previous is not None and (day - previous).days > 1:
                    self.draw_segment(coordinates, line)
                    coordinates = []
                coordinates.extend((x(day), y(price)))
                previous = day
            self.draw_segment(coordinates, line)
        occupied = []
        for line, points in zip(self.lines, self.extremes):
            if points:
                (low_day, lowest), (high_day, highest) = points
                if low_day == high_day:
                    self.mark_extreme(x(low_day), y(lowest), low_day, "T/H", line.color, occupied)
                else:
                    self.mark_extreme(x(low_day), y(lowest), low_day, "T", line.color, occupied)
                    self.mark_extreme(x(high_day), y(highest), high_day, "H", line.color, occupied)
        self.hover.configure(text="Mit der Maus zeigt das Diagramm die Tagespreise.")

    def mark_extreme(self, x, y, day, kind, color, occupied):
        left, right, top, bottom, _ = self.plot_bounds
        if kind == "T/H":
            self.canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill=color, outline="white", tags="extreme")
        else:
            tip = 6 if kind == "T" else -6
            self.canvas.create_polygon(x - 5, y - tip / 2, x + 5, y - tip / 2, x, y + tip,
                                       fill=color, outline="white", tags="extreme")
        label = self.canvas.create_text(x, y, text=f"{kind} {day:%d.%m.%y}", fill=color,
                                        font=("Segoe UI", 8, "bold"), tags="extreme")
        direction = 1 if kind == "T" else -1
        side = 1 if x < (left + right) / 2 else -1
        box = self.canvas.bbox(label)
        half_width = (box[2] - box[0]) / 2
        label_x = min(right - half_width, max(left + half_width, x + side * (half_width + 7)))
        for offset in (11, -11, 26, -26, 41, -41):
            label_y = max(top - 6, min(bottom - 5, y + direction * offset))
            self.canvas.coords(label, label_x, label_y)
            box = self.canvas.bbox(label)
            if all(box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3] for b in occupied):
                break
        occupied.append(box)
        backdrop = self.canvas.create_rectangle(box[0], box[1], box[2], box[3],
                                                fill="#f7f9fd", outline="", tags="extreme")
        self.canvas.tag_lower(backdrop, label)

    def draw_segment(self, coordinates, line):
        if len(coordinates) > 2:
            self.canvas.create_line(*coordinates, fill=line.color, width=2,
                                    dash=(5, 4) if line.dashed else None)
        elif coordinates:
            x, y = coordinates
            self.canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill=line.color, outline="")

    def clear_pointer(self, _event=None):
        self.canvas.delete("pointer")
        self.hover.configure(text="Mit der Maus zeigt das Diagramm die Tagespreise." if self.plot_bounds else " ")

    def move_pointer(self, event):
        if not self.plot_bounds:
            return
        left, right, top, bottom, days = self.plot_bounds
        if not (left <= event.x <= right and top <= event.y <= bottom):
            self.clear_pointer()
            return
        offset = round(days * (event.x - left) / (right - left))
        day = min(self.start_day + timedelta(days=offset), self.end_day)
        self.canvas.delete("pointer")
        x = left + offset / days * (right - left)
        self.canvas.create_line(x, top, x, bottom, fill="#65748d", dash=(2, 3), tags="pointer")
        values = [f"{line.label}  {euros(line.points[day])}" for line in self.lines if day in line.points]
        self.hover.configure(text="  ·  ".join([day.strftime("%d.%m.%Y"), *(values or ["Keine Preisdaten"])]))


class Window(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Hardware-Check")
        self.geometry(f"{min(1400, self.winfo_screenwidth() - 50)}x{min(850, self.winfo_screenheight() - 95)}")
        self.minsize(900, 675)
        self.events = queue.Queue()
        self.rows = []
        self.results = {}
        self.selected_choices = {}
        self.installed_history = None
        self.histories = {}
        self.summary = ""
        frame = ttk.Frame(self, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Hardware-Check", font=("Segoe UI", 22, "bold")).pack(anchor="w")
        self.status = tk.StringVar(value="Hardware wird ausgelesen …")
        ttk.Label(frame, textvariable=self.status).pack(anchor="w", pady=(4, 12))
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(0, 10))
        self.prices = ttk.Button(actions, text="Preise online abrufen", command=self.refresh, state="disabled")
        self.prices.pack(side="left")
        self.source = ttk.Button(actions, text="Angebot / Suche öffnen", command=self.open_source, state="disabled")
        self.source.pack(side="left", padx=8)
        self.export = ttk.Button(actions, text="Als CSV speichern", command=self.save, state="disabled")
        self.export.pack(side="right")
        selection = ttk.Frame(frame)
        selection.pack(fill="x", pady=(0, 10))
        ttk.Label(selection, text="Vergleich für die markierte Zeile").pack(side="left")
        self.choice = ttk.Combobox(selection, state="disabled", width=46)
        self.choice.pack(side="left", padx=8)
        self.choice.bind("<<ComboboxSelected>>", self.change_choice)
        panes = ttk.Panedwindow(frame, orient="vertical")
        panes.pack(fill="both", expand=True)
        overview = ttk.Frame(panes)
        chart_panel = ttk.Frame(panes)
        panes.add(overview, weight=1)
        panes.add(chart_panel, weight=2)
        table = ttk.Frame(overview)
        table.pack(fill="both", expand=True)
        ttk.Style(self).configure("Treeview", rowheight=27, font=("Segoe UI", 10))
        self.tree = ttk.Treeview(table, columns=COLUMNS, show="headings", selectmode="browse", height=7)
        for label, width in zip(COLUMNS, (82, 210, 200, 240, 230, 112, 128, 122)):
            self.tree.heading(label, text=label)
            self.tree.column(label, width=width, minwidth=75)
        y = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        x = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        y.grid(row=0, column=1, sticky="ns")
        x.grid(row=1, column=0, sticky="ew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self.select_row)
        self.tree.bind("<Double-1>", lambda _e: self.open_source())
        self.total = tk.StringVar(value="Preissumme nach Online-Abfrage")
        ttk.Label(overview, textvariable=self.total, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(8, 0))
        ttk.Label(overview, text="heise Preisvergleich · Deutschland · Preise pro Stück, ggf. zzgl. Versand").pack(anchor="w", pady=(3, 6))
        controls = ttk.Frame(chart_panel)
        controls.pack(fill="x", pady=(8, 0))
        ttk.Label(controls, text="Preisverlauf", font=("Segoe UI", 13, "bold")).pack(side="left")
        self.history_view = ttk.Combobox(controls, state="readonly", width=25,
                                         values=("Gesamtsystem", "Markierte Komponente"))
        self.history_view.current(0)
        self.history_view.pack(side="left", padx=(12, 6))
        self.history_view.bind("<<ComboboxSelected>>", lambda _e: self.update_history())
        self.history_period = ttk.Combobox(controls, state="readonly", width=19,
                                           values=("Letzte 2 Jahre", "Seit erster Listung"))
        self.history_period.current(0)
        self.history_period.pack(side="left", padx=6)
        self.history_period.bind("<<ComboboxSelected>>", lambda _e: self.update_history())
        self.chart = HistoryChart(chart_panel)
        self.chart.pack(fill="both", expand=True)
        self.update_history()
        self.start("scan", inventory)
        self.after(80, self.poll)

    def start(self, event, job):
        def run():
            try:
                self.events.put((event, job()))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        threading.Thread(target=run, daemon=True).start()

    def refresh(self):
        self.prices.configure(state="disabled")
        self.export.configure(state="disabled")
        self.results.clear()
        self.selected_choices.clear()
        self.installed_history = None
        self.histories = {}
        for index, row in enumerate(self.rows):
            self.tree.item(str(index), values=(*row[:3], "", "Online-Abfrage läuft …", "", "", ""))
        self.update_actions()
        self.status.set(f"{self.summary}  ·  Preise werden abgerufen …")
        self.total.set("Preissumme wird berechnet …")
        self.update_history()
        self.start("done", lambda: compare(self.rows, lambda *args: self.events.put(("row", args))))

    def poll(self):
        while not self.events.empty():
            event, payload = self.events.get_nowait()
            if event == "scan":
                self.rows, total, issues = payload
                self.summary = f"{len(self.rows)} Komponenten  ·  {total:g} GiB RAM"
                if issues:
                    self.summary += "  ·  Abfrage fehlgeschlagen für " + ", ".join(issues)
                self.status.set(self.summary)
                for index, row in enumerate(self.rows):
                    self.tree.insert("", "end", iid=str(index), values=row[:3])
                if self.rows:
                    self.prices.configure(state="normal")
                    self.export.configure(state="normal")
            elif event == "row":
                index, choices, stamp = payload
                self.results[index] = choices, stamp
                self.show_choice(index, 0)
                self.update_actions()
            elif event == "done":
                self.status.set(self.summary + "  ·  Preisverläufe werden geladen …")
                self.export.configure(state="normal")
                self.update_total()
                results = self.results.copy()
                self.start("history", lambda: load_histories(self.rows, results))
            elif event == "history":
                self.installed_history, self.histories = payload
                self.status.set(self.summary)
                self.prices.configure(state="normal")
                self.update_history()
            elif event == "error":
                self.status.set("Abfrage fehlgeschlagen")
                if self.rows:
                    self.prices.configure(state="normal")
                    self.export.configure(state="normal")
                    self.update_total()
                    self.update_history()
                messagebox.showerror("Hardware-Check", payload)
        self.after(80, self.poll)

    def selected_row(self):
        selected = self.tree.selection()
        return int(selected[0]) if selected else None

    def select_row(self, _event):
        self.update_actions()
        if self.selected_row() is not None:
            self.history_view.current(1)
            self.update_history()

    def show_choice(self, index, position):
        choices, stamp = self.results[index]
        current = choices[position]
        self.selected_choices[index] = current
        self.tree.item(str(index), values=(*self.rows[index][:3], *current.columns(), stamp))

    def change_choice(self, _event):
        index = self.selected_row()
        position = self.choice.current()
        if index in self.results and position >= 0:
            self.show_choice(index, position)
            self.update_actions()
            if len(self.results) == len(self.rows):
                self.update_total()
            self.update_history()

    def update_actions(self):
        index = self.selected_row()
        current = self.selected_choices.get(index)
        self.source.configure(state="normal" if current and current.url else "disabled")
        self.choice.set("")
        if index in self.results:
            choices, _ = self.results[index]
            self.choice.configure(values=[f"{c.label} · {euros(c.price)}" if c.price is not None
                                          else c.label for c in choices],
                                  state="readonly" if len(choices) > 1 else "disabled")
            self.choice.current(choices.index(current))
        else:
            self.choice.configure(values=(), state="disabled")

    def price_total(self):
        prices = [choice.price for choice in self.selected_choices.values() if choice.price is not None]
        return sum(prices, Decimal("0.00")), len(prices)

    def update_total(self):
        amount, count = self.price_total()
        if count:
            label = "Preissumme" if count == len(self.rows) else "Teilsumme"
            self.total.set(f"{label}  {euros(amount)}  ·  {count} von {len(self.rows)} Positionen")
        else:
            self.total.set("Preissumme nicht verfügbar · keine Position mit Preis")

    def history_points(self, product):
        return self.histories.get(product_id(product.url), {}) if product else {}

    def component_lines(self, index):
        installed = self.installed_history[index]
        current = self.selected_choices[index]
        options, _ = self.results[index]
        labels, lines = [], []
        if installed:
            same = product_id(installed.url) == product_id(current.url)
            role = "Verbaut / Auswahl" if same else "Verbaut"
            if installed.reference:
                role += " (Referenz)"
            prices = self.history_points(installed)
            lines.append(HistoryLine("Blau " + role, prices, "#225cad", installed.current_price))
            labels.append(f"Blau {role}  ·  {compact_product(installed.title)}")
        else:
            labels.append("Verbautes Modell ohne zugeordneten Preisverlauf")
        for choice in (current, *(option for option in options if option != current)):
            if not product_id(choice.url):
                continue
            if installed and product_id(installed.url) == product_id(choice.url):
                continue
            selected = choice == current
            role = "Grün Auswahl" if selected else "Violett weitere Option"
            prices = self.history_points(choice)
            lines.append(HistoryLine(role, prices, "#057968" if selected else "#854db5",
                                     choice.price, dashed=not selected))
            labels.append(f"{role}  ·  {compact_product(choice.title)}")
        return lines, "\n".join(labels)

    def system_lines(self, start, end):
        installed = [self.history_points(product) for product in self.installed_history]
        choices = [self.selected_choices.get(i) for i in range(len(self.rows))]
        selected = [self.history_points(choice) for choice in choices]
        installed_price = complete_total([p.current_price if p else None for p in self.installed_history])
        selected_price = complete_total([choice.price if choice else None for choice in choices])
        lines = [
            HistoryLine("Blau verbaut", sum_history(installed, start, end), "#225cad", installed_price),
            HistoryLine("Grün Auswahl", sum_history(selected, start, end), "#057968", selected_price, dashed=True),
        ]
        labels = []
        for line, products in zip(lines, (installed, selected)):
            coverage = sum(any(start <= day <= end for day in prices) for prices in products)
            missing = "" if line.points else f"  ·  0 gemeinsame Preistage, Daten für {coverage}/{len(self.rows)} Positionen"
            labels.append(line.label + missing)
        note = "    |    ".join(labels) + "\nSumme der Tagespreise aller Positionen"
        if any(product and product.reference for product in self.installed_history):
            note += " · Verbauter Warenkorb enthält Referenzmodelle"
        return lines, note

    def update_history(self):
        end = date.today()
        start = two_years_before(end)
        if self.installed_history is None:
            pending = str(self.prices["state"]) == "disabled" and self.rows
            message = ("Historische Tagespreise werden geladen …" if pending
                       else "Mit „Preise online abrufen“ auch den Preisverlauf laden.")
            self.chart.show([], start, end, "", message)
            return
        all_time = self.history_period.current() == 1
        if all_time:
            start = min((day for prices in self.histories.values() for day in prices), default=start)
        if self.history_view.current() == 0:
            lines, note = self.system_lines(start, end)
        else:
            index = self.selected_row()
            if index not in self.results:
                self.chart.show([], start, end, "", "Wähle eine Komponente in der Tabelle aus.")
                return
            lines, note = self.component_lines(index)
        if all_time:
            start = min((day for line in lines for day in line.points), default=start)
        self.chart.show(lines, start, end, note, "Für diesen Zeitraum sind keine vergleichbaren Tagespreise verfügbar.")

    def open_source(self):
        current = self.selected_choices.get(self.selected_row())
        if current and current.url:
            webbrowser.open(current.url)

    def save(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="Hardware-Check.csv",
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as file:
                writer = csv.writer(file, delimiter=";")
                writer.writerow((*COLUMNS, "URL"))
                for row in self.tree.get_children():
                    values = [self.tree.set(row, column) for column in COLUMNS]
                    current = self.selected_choices.get(int(row))
                    writer.writerow([("'" + v if v.startswith(("=", "+", "-", "@", "\t", "\r")) else v)
                                     for v in (*values, current.url if current else "")])
                amount, count = self.price_total()
                if count:
                    label = "Preissumme" if count == len(self.rows) else "Teilsumme"
                    writer.writerow((label, "", "", "", f"{count} von {len(self.rows)} Positionen",
                                     euros(amount), "", "", ""))
        except OSError as exc:
            messagebox.showerror("Speichern fehlgeschlagen", str(exc))


if __name__ == "__main__":
    if "--test-live" in sys.argv:
        rows, total, issues = inventory()
        print(f"{total:g} GiB RAM, Lesefehler: {issues}")
        def print_choices(index, choices, stamp):
            for option in choices:
                print(*rows[index][:3], option.label, *option.columns(), stamp, option.url, sep=" | ")
        compare(rows, print_choices)
    else:
        Window().mainloop()
