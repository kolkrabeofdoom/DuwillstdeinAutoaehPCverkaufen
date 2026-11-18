# DuwillstdeinAutoähPCverkaufen

Windows-Programm für eine Übersicht deiner PC-Hardware und einen Preisvergleich mit aktuellen Angeboten. Die App liest Prozessor, Grafikkarte, RAM, Laufwerke und Mainboard aus.

## Starten

1. Lade die Windows-EXE aus dem [aktuellen Release](https://github.com/kolkrabeofdoom/DuwillstdeinAutoaehPCverkaufen/releases/latest) herunter und öffne sie. Python ist für die EXE nicht erforderlich.
2. Klicke auf **Preise online abrufen**.
3. Wähle eine Tabellenzeile, um die eingebauten Teile und verfügbaren Vergleichsprodukte im Diagramm zu sehen. Über **Gesamtsystem** wechselst du zurück zur Summe.
4. Mit **Letzte 2 Jahre** oder **Seit erster Listung** stellst du den Zeitraum ein.

## Preise lesen

**T** und **H** markieren den Tiefst- und Höchstpreis mit Datum. Unter dem Diagramm stehen die Beträge und der Abstand des aktuell abrufbaren Preises zum Tief in Euro und Prozent. Bei Preisgleichstand markiert die App jeweils den frühesten Tag im angezeigten Zeitraum.

Die Daten stammen vom [heise Preisvergleich](https://preisvergleich.heise.de/) für Deutschland. Die Tabelle enthält verfügbare Einzelangebote, ggf. zzgl. Versand. Der historische Verlauf zeigt die erfassten Tagespreise. Das sind keine Verkaufspreise für gebrauchte Teile. Für die historische Systemsumme berücksichtigt die App nur Tage mit Preisen für alle Positionen. Bei unvollständigen aktuellen Angeboten bleibt der Preisabstand für das Gesamtsystem offen. Kaufbare Modellvarianten können als Referenz dienen, wenn sich der genaue Artikel aus den Windows-Daten nicht bestimmen lässt.

Die Hardware-Erkennung läuft lokal. Beim Preisabruf fragt die App Modellnamen und technische Suchmerkmale bei heise ab und lädt bei Bedarf CPU-Benchmark-Daten von [Notebookcheck](https://www.notebookcheck.net/Mobile-Processors-Benchmark-List.2436.0.html). Für ausgewählte Desktop-GPUs sind [PassMark-Vergleichswerte](https://www.videocardbenchmark.net/common_gpus.html) im Quellcode hinterlegt.

## Aus dem Quellcode starten

Unter Windows mit Python 3.12 oder neuer:

```powershell
python Hardware-Check.py
```
