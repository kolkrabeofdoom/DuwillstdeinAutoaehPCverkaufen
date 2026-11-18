# DuwillstdeinAutoähPCverkaufen

*Ein Mann mit Rennfahrerblick lehnt sich ins Bild.*

**„Du willst dein Auto … äh, warum hat das drei Lüfter?“**

Kurze Werbepause. Jemand reicht ihm einen Schraubenzieher. Die Kamera zoomt auf den PC. Ralf hätte jetzt gern die Fahrzeugpapiere. Uns reicht Windows.

## Was steckt unter der Haube?

Die App liest CPU, Grafikkarte, RAM, Laufwerke und Mainboard aus. Danach sucht sie nach aktuellen Angeboten für dieselben Teile oder vergleichbare Modelle. Bei CPU und GPU hat die verbaute Marke Vorrang. Passende Angebote der anderen Marke stehen zur Auswahl. Unter der Tabelle steht die Summe, und die Tabelle gibt es auch als CSV.

## Drei Handgriffe bis zur Probefahrt

1. Lade die Windows-EXE aus dem [aktuellen Release](https://github.com/kolkrabeofdoom/DuwillstdeinAutoaehPCverkaufen/releases/latest) und starte sie. Für die EXE brauchst du kein Python.
2. Klicke auf **Preise online abrufen**.
3. Wähle eine Zeile für den Verlauf des Bauteils und seiner Vergleichsprodukte. Unter **Gesamtsystem** siehst du die Summe im Zeitverlauf.

## Der Preis war auch schon mal tiefer

Das Diagramm zeigt **die letzten zwei Jahre** oder den Verlauf **seit der ersten Listung**. **T** markiert das Tief, **H** das Hoch. Beide haben ein Datum. Darunter steht, wie viele Euro und Prozent der aktuelle Preis vom Tief entfernt ist. Bei Preisgleichstand bekommt der früheste Tag den Parkplatz.

Die Tabelle zeigt verfügbare Angebote in Deutschland, ggf. zzgl. Versand. Die Historie enthält erfasste Tagespreise. Einen Gebrauchtpreis für deinen PC ermittelt die App dabei nicht. Die Systemkurve hat nur dort einen Wert, wo für alle Positionen ein Tagespreis vorliegt. Fehlt ein aktuelles Angebot, bleibt der Preisabstand fürs Gesamtsystem offen. Wenn Windows eine Produktvariante nicht eindeutig erkennt, kennzeichnet das Diagramm das verwendete Referenzmodell. [heise Preisvergleich](https://preisvergleich.heise.de/)

## Das Kleingedruckte ohne Schnellsprecher

Die Hardware-Erkennung läuft lokal. Beim Online-Abruf gehen Modellnamen und technische Suchmerkmale an heise. Für CPU-Vergleiche lädt die App bei Bedarf Benchmarkdaten. Für ausgewählte Desktop-GPUs sind Vergleichswerte hinterlegt. [Notebookcheck](https://www.notebookcheck.net/Mobile-Processors-Benchmark-List.2436.0.html) · [PassMark](https://www.videocardbenchmark.net/common_gpus.html)

Das hier ist eine Persiflage. Ralf hat keinen Auftritt gebucht, und deinen PC nimmt hier auch niemand in Zahlung.

## Für Leute, die gern selbst schrauben

Unter Windows mit Python 3.12 oder neuer:

```powershell
python Hardware-Check.py
```
