# Third-party components

Chess Coach itself is licensed under the GNU GPL v3.0 (see `LICENSE`).
It uses or includes the following parts made by others:

| Component | Used for | Author | License | Included? |
|---|---|---|---|---|
| [Stockfish](https://stockfishchess.org) | chess engine (analysis, playing) | The Stockfish developers | GPL-3.0 | downloaded by `setup_engine.py` from the [official releases](https://github.com/official-stockfish/Stockfish/releases) |
| [python-chess](https://github.com/niklasf/python-chess) | move generation, PGN, engine communication, the "classic" pieces (Colin M.L. Burnett) | Niklas Fiekas and contributors | GPL-3.0 (pieces: GPL-2.0+) | installed with pip |
| [pywebview](https://github.com/r0x0r/pywebview) | the desktop app window | Roman Sirokov and contributors | BSD-3-Clause | installed with pip |
| [Lichess chess-openings](https://github.com/lichess-org/chess-openings) | opening names, book moves, opening trainer (`openings/*.tsv`) | lichess.org contributors | CC0-1.0 (public domain) | yes |
| Piece set **staunty** | pieces | sadsnake1 (lichess.org) | CC BY-NC-SA 4.0 | yes, `pieces/staunty` |
| Piece set **cardinal** | pieces | sadsnake1 (lichess.org) | CC BY-NC-SA 4.0 | yes, `pieces/cardinal` |
| Piece set **fresca** | pieces | sadsnake1 (lichess.org) | CC BY-NC-SA 4.0 | yes, `pieces/fresca` |
| Piece set **maestro** | pieces | sadsnake1 (lichess.org) | CC BY-NC-SA 4.0 | yes, `pieces/maestro` |
| Piece set **california** | pieces | Jerry S. | CC BY-NC-SA 4.0 | yes, `pieces/california` |
| [Nunito](https://fonts.google.com/specimen/Nunito) | user-interface font, loaded from Google Fonts | Vernon Adams and others | SIL Open Font License 1.1 | no (loaded online) |
| [chess.com Published-Data API](https://www.chess.com/news/view/published-data-api) | reading your finished games and ratings | chess.com | their terms of service | no (online service) |

The piece sets come from the [lila repository](https://github.com/lichess-org/lila) (see its
`COPYING.md`). Because of their **NonCommercial** license, Chess Coach must stay free – it may
not be sold or used commercially as long as these piece sets are included. The app icon
(`icon.ico`) is made from the staunty knight and shares its license.

The accuracy formula is our own; it was tuned to give values similar to chess.com's.
Chess Coach is **not affiliated with, endorsed by or connected to chess.com or lichess.org**.
