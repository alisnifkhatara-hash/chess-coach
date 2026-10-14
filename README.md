# Chess Coach

A free, open-source chess coach for your own PC. It watches your chess.com account,
reviews every game the moment it ends, explains your mistakes in plain language and
turns them into puzzles - in English or German.

German version below / Deutsche Version weiter unten.

> Chess Coach is an independent hobby project and is **not affiliated with chess.com**.
> It only uses chess.com's public API to read your finished games.

## Features

- **Automatic game review**: enter your chess.com username and every finished game is analysed
  with Stockfish - move ratings (brilliant to blunder), accuracy, evaluation graph, game phases.
- **Explanations**: why a move was bad (hanging pieces, missed mates, forks, pins, skewers,
  discovered attacks, king safety, development, pawn structure) and the best line played out on the board.
- **Retry** your mistakes and solve **puzzles from your own games** with spaced repetition and tactic themes.
- **Play vs. the coach** (7 levels, with clocks): it explains your moves and its own plans.
- **Practice mode**: play both sides with move suggestions and unlimited take-backs.
- **Training**: opening trainer with about 3,600 named lines, basic endgame drills.
- **Progress page**: rating, accuracy trend, when and with which piece you blunder, openings, weekly report.
- English and German, 9 boards, 6 piece sets, drag and drop, promotion picker.
- Runs locally: your games stay on your computer.

## Fair play

The coach **never helps during a game**. Reviews only work for finished games. Using any
analysis tool (including practice mode) in a running online game breaks chess.com's
fair-play rules - please don't.

## Install (Windows)

1. Install **Python 3.10 or newer** from https://www.python.org/downloads/
   (tick "Add python.exe to PATH").
2. Download this project and double-click **install.bat**.
   It installs the Python packages and downloads the official Stockfish engine.
3. Start the coach with **Chess Coach.bat** (its own app window)
   or **Chess Coach (Browser).bat** (opens in your browser at http://localhost:8765).

Linux/macOS: `pip install -r requirements.txt`, install Stockfish with your package manager,
then run `python review.py`. The app window and the installer are made for Windows.

Optional: put your own sound files into `sounds/` (see `sounds/README.txt`).

## License

Chess Coach is free software under the **GNU General Public License v3.0** (see `LICENSE`).
Third-party parts and their licenses are listed in `THIRD_PARTY.md`. The included piece sets
are **CC BY-NC-SA 4.0 (non-commercial)**.

---

# Chess Coach (Deutsch)

Ein kostenloser Open-Source-Schachcoach für deinen PC. Er beobachtet dein chess.com-Konto,
analysiert jede Partie, sobald sie vorbei ist, erklärt deine Fehler verständlich und macht
Puzzles daraus - auf Deutsch oder Englisch.

> Chess Coach ist ein unabhängiges Hobbyprojekt und **nicht mit chess.com verbunden**.
> Er nutzt nur die öffentliche chess.com-API, um deine beendeten Partien zu lesen.

## Funktionen

- **Automatische Partieanalyse** mit Stockfish: Zugbewertungen (Brillant bis Patzer), Genauigkeit,
  Bewertungsgrafik, Spielphasen.
- **Erklärungen**: warum ein Zug schlecht war (hängende Figuren, verpasste Matts, Gabeln, Fesselungen,
  Spieße, Abzugsangriffe, Königssicherheit, Entwicklung, Bauernstruktur) und die beste Fortsetzung auf dem Brett.
- **Fehler nochmal versuchen** und **Puzzles aus deinen eigenen Partien** mit Wiederholung und Taktik-Motiven.
- **Gegen den Coach spielen** (7 Stufen, mit Uhr): Er erklärt deine Züge und seine Pläne.
- **Übungsmodus**: beide Seiten spielen, mit Zugvorschlägen und beliebig vielen Rücknahmen.
- **Training**: Eröffnungs-Trainer mit ca. 3.600 benannten Varianten, Grund-Endspiele.
- **Fortschritt**: Wertung, Genauigkeit, wann und mit welcher Figur du patzt, Eröffnungen, Wochenbericht.
- Deutsch und Englisch, 9 Bretter, 6 Figuren-Sets, Drag & Drop, Umwandlungs-Auswahl.
- Läuft lokal: Deine Partien bleiben auf deinem PC.

## Fair Play

Der Coach **hilft nie während einer Partie**. Analysen gibt es nur für beendete Partien.
Wer ein Analyse-Werkzeug (auch den Übungsmodus) in einer laufenden Online-Partie benutzt,
verstößt gegen die Fair-Play-Regeln von chess.com - bitte nicht.

## Installation (Windows)

1. **Python 3.10 oder neuer** von https://www.python.org/downloads/ installieren
   (Haken bei "Add python.exe to PATH" setzen).
2. Dieses Projekt herunterladen und **install.bat** doppelklicken.
   Das installiert die Python-Pakete und lädt die offizielle Stockfish-Engine herunter.
3. Starten mit **Chess Coach.bat** (eigenes App-Fenster)
   oder **Chess Coach (Browser).bat** (im Browser unter http://localhost:8765).

Eigene Sounds kannst du in den Ordner `sounds/` legen (siehe `sounds/README.txt`).

## Lizenz

Chess Coach ist freie Software unter der **GNU General Public License v3.0** (siehe `LICENSE`).
Fremd-Bestandteile und ihre Lizenzen stehen in `THIRD_PARTY.md`. Die enthaltenen Figuren-Sets
sind **CC BY-NC-SA 4.0 (nicht-kommerziell)**.
