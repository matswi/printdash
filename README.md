# Printdash

Ett modernt, lättviktigt webbgränssnitt för CUPS. Byggt för en Raspberry Pi som delar en USB-skrivare på nätverket, men fungerar på vilken Linux-maskin som helst med CUPS.

- Översikt över skrivare med status i realtid
- Kö med aktiva jobb och historik: pausa, släpp, avbryt, skriv ut igen
- Dra och släpp en fil för att skriva ut direkt från webbläsaren eller mobilen
- Pausa/återuppta skrivare, testsida, byt standardskrivare, töm kö
- Ljust och mörkt läge, fungerar i mobilen
- Valfritt lösenord
- Mock-läge för utveckling utan CUPS

CUPS gör fortfarande allt det tunga (drivrutiner, firmware, IPP-delning). Printdash är bara ett nytt ansikte utåt.

## Installation på Pi:n

```bash
git clone https://github.com/matswi/printdash.git
cd printdash
sudo ./deploy/install.sh
```

Öppna sedan `http://<pi-ip>:8080`.

Skriptet installerar `python3-cups`, skapar systemanvändaren `printdash` (medlem i `lpadmin`), lägger appen i `/opt/printdash` och startar den som systemd-tjänst.

**Uppdatera:** `git pull && sudo ./deploy/install.sh`

### Lösenord

Redigera `/etc/printdash.env`:

```
PRINTDASH_PASSWORD=ditt-lösenord
```

och kör `sudo systemctl restart printdash`. Webbläsaren frågar då efter inloggning (användarnamnet spelar ingen roll).

### Inställningar

| Variabel | Standard | Beskrivning |
|---|---|---|
| `PRINTDASH_PASSWORD` | – | Kräv lösenord om satt |
| `PRINTDASH_MAX_UPLOAD_MB` | `50` | Största fil som kan laddas upp |
| `PRINTDASH_MOCK` | – | `1` = simulerad skrivare i stället för CUPS |

Porten ändras i `deploy/printdash.service`.

## Utveckling

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
PRINTDASH_MOCK=1 uvicorn app.main:app --reload --port 8080
```

Mock-läget simulerar en HP LaserJet 1020 som skriver ut ungefär en sida var fjärde sekund. Kör testerna med `pytest`.

API-dokumentation finns på `/api/docs`.

### Struktur

```
app/
  backend.py   CupsBackend (pycups) och MockBackend
  main.py      FastAPI-routes
  static/      Frontend (vanilla JS, inget byggsteg)
deploy/        systemd-tjänst och installationsskript
tests/         API-tester mot mock-backend
```

## Felsökning

- **"Kunde inte nå CUPS"**: kontrollera att CUPS kör (`systemctl status cups`).
- **Åtgärder ger "Forbidden"**: kontrollera att `printdash` är medlem i `lpadmin` (`id printdash`) och att `lpadmin` finns under `SystemGroup` i `/etc/cups/cups-files.conf`.
- **"Skriv ut igen" fungerar inte**: CUPS sparar bara jobbfiler en begränsad tid. Se `PreserveJobFiles` i `/etc/cups/cupsd.conf`.
- **Loggar**: `journalctl -u printdash -f`
