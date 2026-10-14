"""Chess.com post-game coach.

Downloads your FINISHED chess.com games, analyzes them with Stockfish and
writes an HTML report with your mistakes, better moves and patterns.

Usage:  python coach.py <chess.com username> [--games 10] [--time 0.1]
"""
import argparse
import html
import io
import json
import math
import os
import re
import shutil
import sys
import urllib.request
import webbrowser
from collections import Counter, defaultdict
from pathlib import Path

import chess
import chess.engine
import chess.pgn
import chess.svg

HERE = Path(__file__).parent
def find_engine():
    """Stockfish: STOCKFISH_PATH, then engine/ next to this file (setup_engine.py puts it there), then the PATH."""
    if os.environ.get("STOCKFISH_PATH"):
        return Path(os.environ["STOCKFISH_PATH"])
    for name in ("stockfish.exe", "stockfish"):
        if (HERE / "engine" / name).exists():
            return HERE / "engine" / name
    found = shutil.which("stockfish")
    return Path(found) if found else HERE / "engine" / "stockfish.exe"


ENGINE = find_engine()
CACHE = HERE / "cache.json"
UA = {"User-Agent": "personal-chess-coach/1.0"}

PIECE_NAMES = {chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop",
               chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king"}
PIECE_VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}


# ---------- chess.com API ----------

def get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.load(r)


def fetch_games(user, count):
    archives = get_json(f"https://api.chess.com/pub/player/{user}/games/archives")["archives"]
    games = []
    for url in reversed(archives):
        month = [g for g in get_json(url)["games"] if g.get("rules") == "chess" and g.get("pgn")]
        games.extend(reversed(month))
        if len(games) >= count:
            break
    return games[:count]


# ---------- evaluation helpers ----------

def win_pct(cp):
    """Lichess formula: centipawns (mover's view) -> winning chance 0..100."""
    cp = max(-1000, min(1000, cp))
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def move_accuracy(loss):
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * loss) - 3.1669))


def phase(board, ply):
    if ply < 24:
        return "opening"
    material = sum(PIECE_VALUE[p.piece_type] for p in board.piece_map().values())
    return "endgame" if material <= 26 else "middlegame"


def clocks(game):
    out = []
    for node in game.mainline():
        m = re.search(r"\[%clk (\d+):(\d+):([\d.]+)\]", node.comment)
        out.append(int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else None)
    return out


def explain(board, played, best, reply):
    """Short human explanation for why the played move was bad."""
    tips = []
    after = board.copy()
    after.push(played)
    if reply and after.is_capture(reply):
        victim = after.piece_at(reply.to_square)
        if victim is None and after.is_en_passant(reply):
            victim = chess.Piece(chess.PAWN, board.turn)
        if victim:
            tips.append(f"This let your opponent take your {PIECE_NAMES[victim.piece_type]} "
                        f"with {after.san(reply)}.")
    if reply:
        a2 = after.copy()
        a2.push(reply)
        if a2.is_checkmate():
            tips.append("This allowed checkmate in one!")
    b2 = board.copy()
    b2.push(best)
    if b2.is_checkmate():
        tips.append(f"You missed checkmate with {board.san(best)}!")
    elif board.is_capture(best):
        victim = board.piece_at(best.to_square)
        name = PIECE_NAMES[victim.piece_type] if victim else "pawn"
        tips.append(f"{board.san(best)} would have won the {name}.")
    elif board.gives_check(best):
        tips.append(f"Look at checks first: {board.san(best)} was strong.")
    if not tips:
        tips.append(f"{board.san(best)} kept a better position.")
    return " ".join(tips)


# ---------- analysis ----------

def analyze_game(engine, g, user, think_time):
    game = chess.pgn.read_game(io.StringIO(g["pgn"]))
    color = chess.WHITE if g["white"]["username"].lower() == user.lower() else chess.BLACK
    me = g["white"] if color == chess.WHITE else g["black"]
    opp = g["black"] if color == chess.WHITE else g["white"]

    board = game.board()
    moves = list(game.mainline_moves())
    clk = clocks(game)

    # one engine call per position
    evals, bests = [], []
    for i in range(len(moves) + 1):
        if board.is_game_over():
            evals.append(-10000 if board.is_checkmate() else 0)  # mover's view
            bests.append(None)
        else:
            info = engine.analyse(board, chess.engine.Limit(time=think_time))
            evals.append(info["score"].pov(board.turn).score(mate_score=10000))
            bests.append(info["pv"][0] if info.get("pv") else None)
        if i < len(moves):
            board.push(moves[i])

    board = game.board()
    mistakes, losses = [], []
    for i, mv in enumerate(moves):
        if board.turn == color and bests[i] is not None:
            before = win_pct(evals[i])
            after = win_pct(-evals[i + 1])
            loss = max(0.0, before - after)
            losses.append(loss)
            kind = "blunder" if loss >= 30 else "mistake" if loss >= 20 else "inaccuracy" if loss >= 10 else None
            if kind and mv != bests[i]:
                mistakes.append({
                    "kind": kind, "loss": round(loss, 1),
                    "move_no": i // 2 + 1, "played": board.san(mv), "best": board.san(bests[i]),
                    "fen": board.fen(), "played_uci": mv.uci(), "best_uci": bests[i].uci(),
                    "phase": phase(board, i), "clock": clk[i] if i < len(clk) else None,
                    "why": explain(board, mv, bests[i], bests[i + 1]),
                    "win_before": round(before), "win_after": round(after),
                })
        board.push(mv)

    accuracy = sum(move_accuracy(l) for l in losses) / len(losses) if losses else 100
    opening = g.get("eco", "").rsplit("/", 1)[-1].replace("-", " ") or game.headers.get("ECO", "?")
    return {
        "url": g["url"], "time_class": g.get("time_class", "?"),
        "color": "white" if color == chess.WHITE else "black",
        "opponent": opp["username"], "opp_rating": opp.get("rating"), "my_rating": me.get("rating"),
        "result": "win" if me["result"] == "win" else "loss" if opp["result"] == "win" else "draw",
        "opening": opening[:60], "accuracy": round(accuracy, 1), "mistakes": mistakes,
    }


# ---------- report ----------

def board_svg(m, color):
    board = chess.Board(m["fen"])
    p, b = chess.Move.from_uci(m["played_uci"]), chess.Move.from_uci(m["best_uci"])
    arrows = [chess.svg.Arrow(p.from_square, p.to_square, color="#d9534fcc"),
              chess.svg.Arrow(b.from_square, b.to_square, color="#3fa34dcc")]
    return chess.svg.board(board, arrows=arrows, size=300, flipped=(color == "black"))


def build_tips(results):
    allm = [m for r in results for m in r["mistakes"] if m["kind"] != "inaccuracy"]
    tips = []
    if not allm:
        return ["Very clean games, no big mistakes found. Try analyzing more games."]
    by_phase = Counter(m["phase"] for m in allm)
    worst, n = by_phase.most_common(1)[0]
    tips.append(f"Most of your mistakes ({n} of {len(allm)}) happen in the <b>{worst}</b>. "
                + {"opening": "Learn the main ideas of your openings and develop pieces before attacking.",
                   "middlegame": "Before each move ask: what does my opponent threaten? Is any piece undefended?",
                   "endgame": "Practice basic endgames (king activity, rook endings, passed pawns)."}[worst])
    hung = sum("take your" in m["why"] for m in allm)
    if hung >= 2:
        tips.append(f"You left pieces hanging {hung} times. Do a 'blunder check' before every move: "
                    "after my move, can any of my pieces be captured for free?")
    missed = sum("would have won" in m["why"] or "missed checkmate" in m["why"] for m in allm)
    if missed >= 2:
        tips.append(f"You missed winning material or mate {missed} times. Always look at "
                    "<b>checks, captures and threats</b> first (in that order).")
    low = [m for m in allm if m["clock"] is not None and m["clock"] < 30]
    if len(low) >= 2:
        tips.append(f"{len(low)} big mistakes were made with less than 30 seconds left. "
                    "Spend less time early so you are not in time trouble.")
    openings = defaultdict(lambda: [0, 0])
    for r in results:
        openings[r["opening"]][0] += 1
        openings[r["opening"]][1] += r["result"] == "loss"
    bad = [(o, n, l) for o, (n, l) in openings.items() if n >= 2 and l / n >= 0.6]
    for o, n, l in bad[:2]:
        tips.append(f"You lost {l} of {n} games in the <b>{html.escape(o)}</b>. Worth studying this opening.")
    return tips


def write_report(user, results, path):
    e = html.escape
    wins = sum(r["result"] == "win" for r in results)
    losses = sum(r["result"] == "loss" for r in results)
    avg_acc = sum(r["accuracy"] for r in results) / len(results)
    counts = Counter(m["kind"] for r in results for m in r["mistakes"])

    rows, cards = [], []
    for gi, r in enumerate(results):
        rows.append(f"<tr><td><a href='#g{gi}'>{gi + 1}</a></td><td class='{r['result']}'>{r['result']}</td>"
                    f"<td>{r['color']}</td><td>{e(r['opponent'])} ({r['opp_rating']})</td>"
                    f"<td>{r['time_class']}</td><td>{e(r['opening'])}</td><td>{r['accuracy']}%</td>"
                    f"<td>{sum(m['kind'] == 'blunder' for m in r['mistakes'])}</td></tr>")
        items = []
        for m in r["mistakes"]:
            if m["kind"] == "inaccuracy":
                continue
            dots = "." if chess.Board(m["fen"]).turn == chess.WHITE else "..."
            clock = f" · {int(m['clock'])}s on clock" if m["clock"] is not None else ""
            items.append(
                f"<div class='mis {m['kind']}'>{board_svg(m, r['color'])}<div>"
                f"<h4>{m['kind'].upper()} · move {m['move_no']}{dots} {e(m['played'])}</h4>"
                f"<p>Better was <b>{e(m['best'])}</b>. {e(m['why'])}</p>"
                f"<p class='meta'>Winning chance {m['win_before']}% → {m['win_after']}% · {m['phase']}{clock}</p>"
                f"<p class='meta'><span style='color:#d9534f'>red</span> = your move, "
                f"<span style='color:#3fa34d'>green</span> = best move</p></div></div>")
        body = "".join(items) or "<p>No mistakes or blunders in this game. Nice!</p>"
        cards.append(f"<section id='g{gi}'><h3>Game {gi + 1}: vs {e(r['opponent'])} "
                     f"<span class='{r['result']}'>({r['result']})</span> · "
                     f"<a href='{e(r['url'])}' target='_blank'>open on chess.com</a></h3>{body}</section>")

    tips = "".join(f"<li>{t}</li>" for t in build_tips(results))
    page = f"""<!doctype html><html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'><title>Chess Coach – {e(user)}</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:1000px;margin:auto;padding:16px;background:#1e1f22;color:#e6e6e6}}
a{{color:#7fb6ff}} table{{border-collapse:collapse;width:100%}} td,th{{padding:6px;border-bottom:1px solid #333;text-align:left}}
.win{{color:#5cc96b}} .loss{{color:#ff6b6b}} .draw{{color:#aaa}}
.stats{{display:flex;gap:12px;flex-wrap:wrap}} .stat{{background:#2b2d31;padding:12px 18px;border-radius:8px}}
.stat b{{display:block;font-size:1.6em}} .tips{{background:#2b2d31;padding:12px 28px;border-radius:8px;line-height:1.6}}
.mis{{display:flex;gap:16px;background:#2b2d31;margin:10px 0;padding:12px;border-radius:8px;border-left:5px solid}}
.mis.blunder{{border-color:#ff6b6b}} .mis.mistake{{border-color:#f0ad4e}} .mis svg{{flex:none;max-width:100%}}
.meta{{color:#999;font-size:.9em}} @media(max-width:650px){{.mis{{flex-direction:column}}}}
</style></head><body>
<h1>Chess Coach report for {e(user)}</h1>
<div class='stats'>
<div class='stat'><b>{len(results)}</b>games</div><div class='stat'><b>{wins}/{losses}</b>wins/losses</div>
<div class='stat'><b>{avg_acc:.1f}%</b>avg accuracy</div><div class='stat'><b>{counts['blunder']}</b>blunders</div>
<div class='stat'><b>{counts['mistake']}</b>mistakes</div><div class='stat'><b>{counts['inaccuracy']}</b>inaccuracies</div></div>
<h2>Your top tips</h2><ul class='tips'>{tips}</ul>
<h2>Games</h2><table><tr><th>#</th><th>Result</th><th>Color</th><th>Opponent</th><th>Type</th><th>Opening</th><th>Accuracy</th><th>Blunders</th></tr>
{''.join(rows)}</table>
<h2>Your mistakes</h2>{''.join(cards)}
</body></html>"""
    path.write_text(page, encoding="utf-8")


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description="Review your finished chess.com games.")
    ap.add_argument("username")
    ap.add_argument("--games", type=int, default=10, help="how many recent games (default 10)")
    ap.add_argument("--time", type=float, default=0.1, help="engine seconds per position (default 0.1)")
    ap.add_argument("--no-open", action="store_true", help="don't open the report in the browser")
    a = ap.parse_args()

    print(f"Downloading last {a.games} games of {a.username} ...")
    try:
        games = fetch_games(a.username, a.games)
    except Exception as ex:
        sys.exit(f"Could not load games (wrong username?): {ex}")
    if not games:
        sys.exit("No finished standard chess games found.")

    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    results = []
    with chess.engine.SimpleEngine.popen_uci(str(ENGINE)) as engine:
        for n, g in enumerate(games, 1):
            key = f"{g['url']}|{a.time}"
            if key not in cache:
                print(f"  analyzing game {n}/{len(games)}  ({g['url']})")
                cache[key] = analyze_game(engine, g, a.username, a.time)
                CACHE.write_text(json.dumps(cache))
            else:
                print(f"  game {n}/{len(games)} already analyzed")
            results.append(cache[key])

    out = HERE / f"report_{a.username}.html"
    write_report(a.username, results, out)
    print(f"\nDone! Report: {out}")
    if not a.no_open:
        webbrowser.open(out.as_uri())


if __name__ == "__main__":
    main()
