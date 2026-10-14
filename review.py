"""Chess Coach – a local "Game Review" app (like chess.com Diamond).

Run:  python review.py      -> opens http://localhost:8765

* Watches your chess.com account and reviews every game right AFTER it ends.
* Or paste the PGN of a finished game.
Unfinished games are refused on purpose: no help during a game.
"""
import base64
import hashlib
import io
import math
import statistics
import json
import os
import queue
import random
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import chess
import chess.engine
import chess.pgn
import chess.svg

from i18n_de import to_german
from tactics import motif
from strategy import quiet_reason
from coach import ENGINE, PIECE_NAMES, PIECE_VALUE, clocks, explain, get_json, phase, win_pct

HERE = Path(__file__).parent
DATA = HERE / "reviews"
SETTINGS = HERE / "settings.json"
PORT = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8765
THINK = 0.2          # engine seconds per position
# Stockfish is a console program: started from the app window it would pop up a console
NO_WINDOW = {"creationflags": 0x08000000} if sys.platform == "win32" else {}   # CREATE_NO_WINDOW
POLL = 30            # seconds between checks for new games

DATA.mkdir(exist_ok=True)
VERSION = hashlib.sha1((HERE / "review.py").read_bytes() + (HERE / "index.html").read_bytes()).hexdigest()[:12]
lock = threading.Lock()
settings = json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}
settings.setdefault("username", "")
settings.setdefault("seen", [])
settings.setdefault("primed", False)
status = {"busy": None, "done": 0, "total": 0, "error": None, "watch_error": None, "last_new": None}
jobs = queue.Queue()
pending = set()
recent = {}  # id -> chess.com game json


def save_settings():
    with lock:
        SETTINGS.write_text(json.dumps(settings))


# ---------------- analysis ----------------

def is_sacrifice(board, mv):
    piece = board.piece_at(mv.from_square)
    if piece.piece_type in (chess.PAWN, chess.KING):
        return False
    captured = board.piece_at(mv.to_square)
    val = PIECE_VALUE[piece.piece_type]
    if val - (PIECE_VALUE[captured.piece_type] if captured else 0) < 2:
        return False
    after = board.copy()
    after.push(mv)
    attackers = after.attackers(not piece.color, mv.to_square)
    defended = bool(after.attackers(piece.color, mv.to_square))
    values = [PIECE_VALUE[after.piece_at(s).piece_type] for s in attackers
              if after.piece_at(s).piece_type != chess.KING or not defended]
    return bool(values) and (not defended or min(values) < val)


# ---------------- accuracy ----------------
# Calibrated against chess.com's own accuracy on 80 player-games rated < 900
# (average error ~5.8 points): blend of harmonic mean and volatility-weighted mean.
# Uses a flatter win% curve than the move labels, so moves in already won/lost
# positions still count (chess.com does that too).

def acc_wp(cp):
    cp = max(-1500, min(1500, cp))
    return 50 + 50 * (2 / (1 + math.exp(-0.002 * cp)) - 1)


def move_acc(loss):
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.07 * loss) - 3.1669))


def game_accuracy(items):
    """items: list of (win% loss, volatility)."""
    if not items:
        return 100.0
    accs = [move_acc(l) for l, _ in items]
    harmonic = len(accs) / sum(1 / max(a, 10) for a in accs)
    weighted = sum(a * v for a, (_, v) in zip(accs, items)) / sum(v for _, v in items)
    return round(0.75 * harmonic + 0.25 * weighted, 1)


# ---------------- opening book ----------------

def load_book():
    """position (EPD) -> (eco, name) for every named line; plus all positions on those lines."""
    named, known = {}, set()
    for f in sorted((HERE / "openings").glob("*.tsv")):
        for line in f.read_text(encoding="utf-8").splitlines()[1:]:
            eco, name, pgn = line.split("	")
            b = chess.Board()
            for tok in pgn.split():
                if tok[0].isdigit():
                    continue
                b.push_san(tok)
                known.add(b.epd())
            named[b.epd()] = (eco, name)
    return named, known


BOOK_NAMES, BOOK_POSITIONS = load_book()
CENTER = {chess.D4, chess.E4, chess.D5, chess.E5}


def move_idea(board, mv):
    """One short sentence about the idea behind an opening move."""
    piece = board.piece_at(mv.from_square)
    to = chess.square_name(mv.to_square)
    after = board.copy()
    after.push(mv)
    check = " with check" if after.is_check() else ""
    if board.is_castling(mv):
        return "Castling puts your king in safety and connects your rooks."
    if board.is_capture(mv):
        victim = board.piece_at(mv.to_square)
        name = PIECE_NAMES[victim.piece_type] if victim else "pawn"
        return f"This takes the {name} on {to}{check}."
    if piece.piece_type == chess.PAWN:
        if mv.to_square in CENTER:
            return f"This pawn takes space in the center and fights for the important squares."
        if to[0] in "cf":
            return f"This pawn supports the fight for the center."
        if to in ("g3", "b3", "g6", "b6"):
            return "This prepares a fianchetto: the bishop can now go to the long diagonal."
        if to[0] in "ah":
            return f"A small useful move that stops enemy pieces from using {chr(ord(to[0]) + (1 if to[0] == 'a' else -1))}{'4' if piece.color else '5'}."
        return "This pawn move opens lines for your pieces."
    if piece.piece_type in (chess.KNIGHT, chess.BISHOP):
        home = chess.square_rank(mv.from_square) == (0 if piece.color else 7)
        if home:
            return f"This develops your {PIECE_NAMES[piece.piece_type]} to {to}{check} – get all pieces out before attacking."
        return f"Your {PIECE_NAMES[piece.piece_type]} moves to a more active square{check}."
    if piece.piece_type == chess.QUEEN:
        return f"The queen comes out{check}. Careful: an early queen can become a target."
    return ""


def white_eval(info, board):
    """(cp, mate) from White's view for a position."""
    if info is None:
        if board.is_checkmate():
            return (-10000 if board.turn == chess.WHITE else 10000), 0
        return 0, None
    s = info[0]["score"].white()
    return s.score(mate_score=10000), s.mate()


def classify(in_book, mv, best, loss, before, alts, board, prev_opp_loss):
    if in_book:
        return "book"
    if loss <= 2 and before < 95 and win_pct_after_ok(before, loss) and is_sacrifice(board, mv):
        return "brilliant"
    if mv == best and len(alts) >= 2 and alts[0] - alts[1] >= 20:
        return "great"
    if mv == best or loss < 0.5:
        return "best"
    if prev_opp_loss >= 20 and 10 <= loss < 30:
        return "miss"
    for limit, name in ((2, "excellent"), (5, "good"), (10, "inaccuracy"), (20, "mistake")):
        if loss < limit:
            return name
    return "blunder"


def win_pct_after_ok(before, loss):
    return before - loss >= 45


def coach_text(cls, board, mv, best, reply, info_after, opening=None, left_book=None):
    san, best_san = board.san(mv), board.san(best)
    after = board.copy()
    after.push(mv)
    if after.is_checkmate():
        return f"{san} is checkmate! Well played."
    piece = PIECE_NAMES[board.piece_at(mv.from_square).piece_type]
    text = {
        "brilliant": f"{san} is brilliant! You sacrificed your {piece} and your position is still great.",
        "great": f"{san} is a great move – the only move that keeps your position.",
        "best": f"{san} is the best move.",
        "book": f"{san} is a known opening move. " + (f"This is the {opening}. " if opening else "") + move_idea(board, mv),
        "excellent": f"{san} is excellent. The engine slightly prefers {best_san}.",
        "good": f"{san} is good, but {best_san} was better.",
        "inaccuracy": f"{san} is an inaccuracy. Best was {best_san}. ",
        "mistake": f"{san} is a mistake. Best was {best_san}. ",
        "blunder": f"{san} is a blunder. Best was {best_san}. ",
        "miss": f"{san} misses a chance! Your opponent just made a mistake and {best_san} would punish it. ",
    }[cls]
    if cls in ("inaccuracy", "mistake", "blunder", "miss"):
        why = explain(board, mv, best, reply)
        if why.endswith("kept a better position."):
            why = quiet_reason(board, mv, best) or why
        text += why
    if cls == "good":
        q = quiet_reason(board, mv, best)
        if q:
            text += " " + q
    if left_book:
        text += f" (Here the game left the known opening lines of the {left_book}.)"
    if info_after is not None:
        m = info_after[0]["score"].pov(after.turn).mate()  # from the opponent's view
        if m is not None and m > 0 and cls in ("inaccuracy", "mistake", "blunder", "miss"):
            text += f" Your opponent now has mate in {m}."
        elif m is not None and m < 0 and cls in ("best", "great", "brilliant", "excellent"):
            text += f" You have mate in {-m}!"
    return text


ALLOWED = {
    "mate": "Now your opponent has a checkmating attack starting with {s}.",
    "back_rank": "This allows a back-rank mate starting with {s} – your king has no escape square.",
    "double_check": "This allows a double check with {s}.",
    "discovered": "This allows a discovered attack with {s}.",
    "fork": "This allows a fork: {s} attacks two of your pieces at once.",
    "skewer": "This allows a skewer with {s}.",
    "pin": "This walks into a pin: {s}.",
    "promotion": "This lets your opponent promote a pawn with {s}.",
}
MISSED = {
    "back_rank": "You missed a back-rank mate starting with {s}!",
    "double_check": "You missed a double check with {s}!",
    "discovered": "You missed a discovered attack with {s}.",
    "fork": "You missed a fork: {s} attacks two pieces at once.",
    "skewer": "You missed a skewer with {s}.",
    "pin": "You missed a pin with {s}.",
    "promotion": "You missed promoting with {s}.",
}
NICE = {"fork": "Nice fork!", "pin": "Nice pin!", "skewer": "Nice skewer!", "discovered": "Nice discovered attack!",
        "double_check": "Nice double check!"}


def sans(board, moves):
    b, out = board.copy(), []
    for m in moves:
        if m not in b.legal_moves:
            break
        out.append(b.san(m))
        b.push(m)
    return out


def tactic_notes(board, mv, best, reply, best_pv, reply_pv, cls):
    """Extra sentences about tactics + the motifs, for a move `mv` played in `board`."""
    notes, best_motif, allowed = [], None, None
    after = board.copy()
    after.push(mv)
    if cls in ("inaccuracy", "mistake", "blunder", "miss"):
        best_motif = motif(board, best, best_pv)
        if reply is not None:
            allowed = motif(after, reply, reply_pv)
        if allowed in ALLOWED:
            notes.append(ALLOWED[allowed].format(s=after.san(reply)))
        if best_motif in MISSED:
            notes.append(MISSED[best_motif].format(s=board.san(best)))
    elif cls in ("best", "great", "brilliant", "excellent"):
        played = motif(board, mv)
        if played in NICE:
            notes.append(NICE[played])
            best_motif = played
    return " ".join(notes), best_motif, allowed


def analyze(engine, pgn_text):
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None or not list(game.mainline_moves()):
        raise ValueError("Could not read any moves from this PGN.")
    if game.headers.get("Result", "*") == "*":
        raise ValueError("This game is not finished. Reviews only work after the game is over.")

    h = game.headers
    moves = list(game.mainline_moves())
    board = game.board()
    status.update(done=0, total=len(moves) + 1)

    infos, fens = [], []
    for i in range(len(moves) + 1):
        fens.append(board.fen())
        infos.append(None if board.is_game_over() else
                     engine.analyse(board, chess.engine.Limit(time=settings.get("think", THINK)), multipv=3))
        status["done"] = i + 1
        if i < len(moves):
            board.push(moves[i])

    def mover_eval(k, b):
        if infos[k] is None:
            return -10000 if b.is_checkmate() else 0
        return infos[k][0]["score"].pov(b.turn).score(mate_score=10000)

    # position list (white's view, for eval bar + graph)
    board = game.board()
    positions, evs = [], []
    for k in range(len(moves) + 1):
        cp, mate = white_eval(infos[k], board)
        positions.append({"fen": fens[k], "e": cp, "m": mate, "wp": round(win_pct(cp), 1)})
        evs.append(mover_eval(k, board))
        if k < len(moves):
            board.push(moves[k])

    board = game.board()
    clk = clocks(game)
    plies, losses = [], []
    in_book, opening_name, eco, left_announced = True, None, "", False
    for i, mv in enumerate(moves):
        turn = board.turn
        color = "white" if turn == chess.WHITE else "black"
        before, after = win_pct(evs[i]), win_pct(-evs[i + 1])
        loss = max(0.0, before - after)
        top = infos[i]
        best = top[0]["pv"][0]
        alts = [win_pct(t["score"].pov(turn).score(mate_score=10000)) for t in top]
        reply = infos[i + 1][0]["pv"][0] if infos[i + 1] and infos[i + 1][0].get("pv") else None
        prev_loss = losses[-1][4] if losses and losses[-1][0] != color else 0
        after_board = board.copy()
        after_board.push(mv)
        in_book = in_book and after_board.epd() in BOOK_POSITIONS
        new_name = None
        if in_book and after_board.epd() in BOOK_NAMES:
            eco, new_name = BOOK_NAMES[after_board.epd()]
            new_name = None if new_name == opening_name else new_name
            opening_name = new_name or opening_name
        left = None
        if not in_book and not left_announced:
            left_announced = True
            left = opening_name
        cls = classify(in_book, mv, best, loss, before, alts, board, prev_loss)
        best_pv = top[0]["pv"][:6]
        reply_pv = infos[i + 1][0]["pv"][:6] if infos[i + 1] and infos[i + 1][0].get("pv") else []
        notes, best_motif, allowed = tactic_notes(board, mv, best, reply, best_pv, reply_pv, cls)
        text = coach_text(cls, board, mv, best, reply, infos[i + 1], new_name, left)
        p = {
            "san": board.san(mv), "uci": mv.uci(), "color": color, "cls": cls, "loss": round(loss, 1),
            "best_san": board.san(best), "best_uci": best.uci(), "phase": phase(board, i),
            "text": (text.rstrip() + " " + notes).strip() if notes else text,
            "clock": clk[i] if i < len(clk) else None,
        }
        if best_motif:
            p["motif"] = best_motif
        if allowed:
            p["allowed"] = allowed
        if cls in ("inaccuracy", "mistake", "blunder", "miss"):
            p["legal"] = [m.uci() for m in board.legal_moves]
            p["good"] = [t["pv"][0].uci() for t, a in zip(top, alts) if a >= alts[0] - 3]
            p["best_pv"] = [m.uci() for m in best_pv]
            p["reply_pv"] = [m.uci() for m in reply_pv]
            p["best_pv_san"] = sans(board, best_pv)
            p["reply_pv_san"] = sans(after_board, reply_pv)
        plies.append(p)
        sign = 1 if color == "white" else -1
        acc_loss = max(0.0, (acc_wp(positions[i]["e"]) - acc_wp(positions[i + 1]["e"])) * sign)
        seg = [acc_wp(positions[k]["e"]) for k in range(max(0, i - 2), min(len(positions), i + 3))]
        vol = max(0.5, min(12.0, statistics.pstdev(seg)))
        losses.append((color, acc_loss, p["phase"], vol, loss))
        board.push(mv)

    accuracy, phases, counts = {}, {}, {}
    for c in ("white", "black"):
        mine = [(l, ph, v) for col, l, ph, v, _ in losses if col == c]
        accuracy[c] = game_accuracy([(l, v) for l, _, v in mine])
        phases[c] = {}
        for ph in ("opening", "middlegame", "endgame"):
            ls = [(l, v) for l, p2, v in mine if p2 == ph]
            if ls:
                phases[c][ph] = game_accuracy(ls)
        counts[c] = {}
        for p in plies:
            if p["color"] == c:
                counts[c][p["cls"]] = counts[c].get(p["cls"], 0) + 1

    user = settings.get("username", "").lower()
    my_color = "black" if h.get("Black", "").lower() == user and user else "white"
    opening = (f"{opening_name} ({eco})" if opening_name else
               h.get("ECOUrl", "").rsplit("/", 1)[-1].replace("-", " ") or h.get("Opening", "") or h.get("ECO", ""))
    review = {
        "white": h.get("White", "?"), "black": h.get("Black", "?"),
        "white_elo": h.get("WhiteElo", ""), "black_elo": h.get("BlackElo", ""),
        "result": h.get("Result"), "date": "" if "?" in h.get("Date", "?") else h["Date"].replace(".", "-"),
        "termination": h.get("Termination", ""), "url": h.get("Link", ""),
        "opening": opening[:70], "my_color": my_color,
        "positions": positions, "plies": plies,
        "accuracy": accuracy, "phases": phases, "counts": counts,
    }
    review["summary"] = summary(review)
    return review


def summary(r):
    c = r["my_color"]
    parts = [f"You played with {r['accuracy'][c]}% accuracy "
             f"(your opponent: {r['accuracy']['black' if c == 'white' else 'white']}%)."]
    if r["opening"]:
        out = next((k for k, p in enumerate(r["plies"]) if p["cls"] != "book"), None)
        parts.append(f"Opening: {r['opening']}" + (f" – the game left the known lines on move {out // 2 + 1}." if out else "."))
    ph = r["phases"][c]
    if len(ph) > 1:
        best, worst = max(ph, key=ph.get), min(ph, key=ph.get)
        parts.append(f"Your best phase was the {best} ({ph[best]}%), your weakest the {worst} ({ph[worst]}%).")
    n = r["counts"][c]
    bad = n.get("blunder", 0) + n.get("mistake", 0) + n.get("miss", 0)
    if bad == 0:
        parts.append("No mistakes or blunders – great game!")
    else:
        parts.append(f"You made {n.get('blunder', 0)} blunder(s), {n.get('mistake', 0)} mistake(s) "
                     f"and {n.get('miss', 0)} missed chance(s).")
        worst = max((p for p in r["plies"] if p["color"] == c), key=lambda p: p["loss"])
        k = r["plies"].index(worst)
        parts.append(f"The biggest turning point was move {k // 2 + 1}: {worst['san']} "
                     f"(best was {worst['best_san']}). Use “Retry” on your mistakes to practice.")
    if n.get("brilliant"):
        parts.append(f"You found {n['brilliant']} brilliant move(s)! 💎")
    return " ".join(parts)


# ---------------- background workers ----------------

def enqueue(gid, pgn, label, extra=None, force=False):
    with lock:
        if gid in pending or ((DATA / f"{gid}.json").exists() and not force):
            return False
        pending.add(gid)
    jobs.put((gid, pgn, label, extra or {}))
    return True


def worker():
    with chess.engine.SimpleEngine.popen_uci(str(ENGINE), **NO_WINDOW) as engine:
        while True:
            gid, pgn, label, extra = jobs.get()
            status.update(busy=label, error=None)
            try:
                review = analyze(engine, pgn)
                review["id"] = gid
                old = DATA / f"{gid}.json"
                review["created"] = json.loads(old.read_text()).get("created", time.time()) if old.exists() else time.time()
                review["pgn"] = pgn
                review.update(extra)
                (DATA / f"{gid}.json").write_text(json.dumps(review))
                status["last_new"] = gid
            except Exception as ex:
                status["error"] = f"{label}: {ex}"
            finally:
                with lock:
                    pending.discard(gid)
                status["busy"] = None


def game_id(g):
    return "cc-" + g["url"].rstrip("/").rsplit("/", 1)[-1]


def label_for(g):
    return f"{g['white']['username']} vs {g['black']['username']}"


def extra_for(g):
    return {"chesscom": g["accuracies"]} if g.get("accuracies") else {}


def attach_chesscom(games):
    """chess.com publishes its accuracy once a game was reviewed there – store it with our review."""
    for g in games:
        f = DATA / f"{game_id(g)}.json"
        if g.get("accuracies") and f.exists():
            r = json.loads(f.read_text())
            if r.get("chesscom") != g["accuracies"]:
                r["chesscom"] = g["accuracies"]
                f.write_text(json.dumps(r))


def load_reviews():
    out = []
    for f in DATA.glob("*.json"):
        try:
            out.append(json.loads(f.read_text()))
        except Exception:
            pass
    return sorted(out, key=lambda r: r.get("created", 0), reverse=True)


def personal_offset(reviews):
    """How much higher our accuracy is than chess.com's in this player's games.
    Shrunk toward 0 while there are only a few games to compare."""
    diffs = [r["accuracy"][c] - r["chesscom"][c] for r in reviews if r.get("chesscom")
             for c in ("white", "black")]
    return round(sum(diffs) / (len(diffs) + 2), 1) if diffs else 0.0


def calibrated(r, offset):
    clamp = lambda v: round(max(0.0, min(100.0, v - offset)), 1)
    r = dict(r, offset=offset)
    r["accuracy"] = {c: clamp(v) for c, v in r["accuracy"].items()}
    r["phases"] = {c: {ph: clamp(v) for ph, v in d.items()} for c, d in r["phases"].items()}
    r["summary"] = summary(r)
    return r


def watcher():
    while True:
        user = settings.get("username")
        if user:
            try:
                archives = get_json(f"https://api.chess.com/pub/player/{user}/games/archives")["archives"]
                games = get_json(archives[-1])["games"] if archives else []
                new = [g for g in games if g.get("rules") == "chess" and g["url"] not in settings["seen"]]
                for g in new:
                    settings["seen"].append(g["url"])
                    if settings["primed"]:   # don't flood with old games on first start
                        enqueue(game_id(g), g["pgn"], label_for(g), extra_for(g))
                attach_chesscom(games)
                if new or not settings["primed"]:
                    settings["primed"] = True
                    save_settings()
                status["watch_error"] = None
            except Exception as ex:
                status["watch_error"] = str(ex)
        time.sleep(POLL)


# ---------------- play vs the coach ----------------
# name, approx. rating, chance of a random move, "temperature" for picking among the top moves
LEVELS = {
    1: ("Beginner", 250, 0.30, 25.0),
    2: ("Novice", 400, 0.18, 15.0),
    3: ("Casual", 600, 0.10, 9.0),
    4: ("Club player", 900, 0.05, 5.0),
    5: ("Strong", 1200, 0.02, 2.5),
    6: ("Expert", 1600, 0.0, 1.0),
    7: ("Master", 2200, 0.0, 0.0),
}
PLAY_TIME = 0.25
play_lock = threading.Lock()
play_engine = None
G = None   # the current game


def peng():
    global play_engine
    if play_engine is None:
        play_engine = chess.engine.SimpleEngine.popen_uci(str(ENGINE), **NO_WINDOW)
    return play_engine


def panalyse(board, multipv):
    if board.is_game_over():
        return None
    return peng().analyse(board, chess.engine.Limit(time=PLAY_TIME), multipv=multipv)


def mover_cp(info, board):
    """Score of `board` from the side to move (works for finished games too)."""
    if info is None:
        return -10000 if board.is_checkmate() else 0
    return info[0]["score"].pov(board.turn).score(mate_score=10000)


def book_status(board):
    if board.root().fen() != chess.STARTING_FEN:
        return False, None
    b, name = chess.Board(), None
    for m in board.move_stack:
        b.push(m)
        if b.epd() not in BOOK_POSITIONS:
            return False, name
        if b.epd() in BOOK_NAMES:
            name = BOOK_NAMES[b.epd()][1]
    return True, name


def mate_threats(board):
    """Moves the side NOT to move could mate with if it were its turn."""
    if board.is_check():
        return []
    nb = board.copy()
    nb.push(chess.Move.null())
    out = []
    for m in nb.legal_moves:
        if nb.gives_check(m):
            nb.push(m)
            if nb.is_checkmate():
                out.append(m)
            nb.pop()
    return out


def hanging(board, color):
    """Squares of `color` pieces (not king/pawns) that are attacked and not defended."""
    return {sq for sq, pc in board.piece_map().items()
            if pc.color == color and pc.piece_type not in (chess.KING, chess.PAWN)
            and board.attackers(not color, sq) and not board.attackers(color, sq)}


def move_reasons(board, mv, me=True):
    """Short reasons for a move. me=True: the coach talks about its own move ("I take your ...");
    me=False: a hint for the player ("You can take their ...")."""
    I, my, your, Im = ("I", "my", "your", "I'm") if me else ("You can", "your", "their", "You'd be")
    piece = board.piece_at(mv.from_square)
    name = PIECE_NAMES[piece.piece_type]
    to = chess.square_name(mv.to_square)
    after = board.copy()
    after.push(mv)
    if after.is_checkmate():
        return ["Checkmate!"]
    out = []
    threats = mate_threats(board)
    if threats and not any(after.gives_check(m) and _mates(after, m) for m in after.legal_moves if m in threats):
        nb = board.copy()
        nb.push(chess.Move.null())
        san = nb.san(threats[0])
        out.append(f"{'I stop' if me else 'Stop'} {your} threat: {san} would have been checkmate!")
    if board.is_castling(mv):
        out.append(f"{I} castle to bring {my} king to safety and connect {my} rooks.")
    if board.is_capture(mv):
        victim = board.piece_at(mv.to_square)
        vname = PIECE_NAMES[victim.piece_type] if victim else "pawn"
        safe = not after.attackers(not piece.color, mv.to_square)
        out.append(f"{I} take {your} {vname} on {to}" + (" – and it can't be taken back!" if safe else "."))
    attackers = board.attackers(not piece.color, mv.from_square)
    if attackers and piece.piece_type != chess.KING and not board.is_capture(mv):
        cheapest = min(PIECE_VALUE[board.piece_at(s).piece_type] or 99 for s in attackers)
        if not board.attackers(piece.color, mv.from_square) or cheapest < PIECE_VALUE[piece.piece_type]:
            out.append(f"{my.capitalize()} {name} was under attack, so it moves to safety." if me
                       else f"Your {name} is under attack – move it to safety.")
    if after.is_check():
        out.append("Check! " + ("Your king has to deal with that first." if me else "That forces their king to react."))
    for sq in after.attacks(mv.to_square):
        t = after.piece_at(sq)
        if t and t.color != piece.color and t.piece_type != chess.KING:
            undefended = not after.attackers(t.color, sq)
            if undefended or PIECE_VALUE[t.piece_type] > PIECE_VALUE[piece.piece_type]:
                out.append(f"Now {Im.lower() if not me else Im} attacking {your} {PIECE_NAMES[t.piece_type]} on "
                           f"{chess.square_name(sq)}" + (" – and it isn't protected!" if undefended else "."))
                break
    saved = hanging(board, piece.color) - {mv.from_square}
    for sq in saved:
        if after.piece_at(sq) and after.attackers(piece.color, sq):
            out.append(f"{'I protect' if me else 'Protect'} {my} {PIECE_NAMES[after.piece_at(sq).piece_type]} on {chess.square_name(sq)}.")
            break
    if not out:
        idea = move_idea(board, mv)
        if idea:
            out.append(idea.replace("your ", my + " ") if me else idea)
        else:
            out.append(f"{I} improve {my} {name} on {to}." if me else f"Improve your {name}.")
    return out


def _mates(board, m):
    board.push(m)
    mate = board.is_checkmate()
    board.pop()
    return mate


def clock_tick():
    """Charge the side to move for its thinking time (+ increment). Returns False if it ran out."""
    if not G.get("clock"):
        return True
    G.setdefault("clock_hist", []).append(dict(G["clock"]))
    side = "white" if G["board"].turn == chess.WHITE else "black"
    now = time.time()
    G["clock"][side] -= now - G["turn_start"]
    G["turn_start"] = now
    if G["clock"][side] <= 0:
        G["clock"][side] = 0
        lost_on_time(side)
        return False
    G["clock"][side] += G["tc"][1]
    return True


def lost_on_time(side):
    G["result"] = "0-1" if side == "white" else "1-0"
    G["reason"] = "timeout"


def check_over():
    o = G["board"].outcome(claim_draw=True)
    if o:
        G["result"] = o.result()
        G["reason"] = o.termination.name.lower().replace("_", " ")


def play_state():
    if G is None:
        return {"active": False}
    b = G["board"]
    user_turn = (G["self"] or b.turn == G["user"]) and not G["result"]
    cp = mover_cp(G["info"], b) * (1 if b.turn == chess.WHITE else -1)
    mate = G["info"][0]["score"].white().mate() if G["info"] else None
    name, elo = LEVELS[G["level"]][:2]
    return {
        "active": True, "fen": b.fen(), "user": "white" if G["user"] == chess.WHITE else "black",
        "level": G["level"], "level_name": name, "level_elo": elo,
        "legal": [m.uci() for m in b.legal_moves] if user_turn else [],
        "check": b.king(b.turn) if b.is_check() else None,
        "history": G["history"], "result": G["result"], "reason": G["reason"],
        "e": cp, "m": mate, "wp": round(win_pct(cp), 1), "opening": G["opening"],
        "username": settings.get("username") or "You",
        "self": G["self"], "tips": practice_tips() if G["self"] and user_turn else [],
        "clock": G.get("clock"), "tc": G.get("tc"), "drill": drill_status(),
        "running": None if G["result"] or not G.get("clock") else ("white" if b.turn == chess.WHITE else "black"),
        "elapsed": time.time() - G["turn_start"] if G.get("clock") else 0,
    }


def practice_tips():
    """The best moves for the side to move, with short reasons (practice mode)."""
    b, info = G["board"], G["info"]
    if not info:
        return []
    scored = [(t["pv"][0], win_pct(t["score"].pov(b.turn).score(mate_score=10000))) for t in info if t.get("pv")]
    best = scored[0][1]
    tips = []
    for mv, wp in scored[:3]:
        gap = best - wp
        if tips and gap >= 10:
            break
        label = "Best move" if not tips else "Also good" if gap < 3 else "Playable"
        tips.append({"uci": mv.uci(), "san": b.san(mv), "label": label,
                     "text": " ".join(move_reasons(b, mv, me=False))})
    return tips


def bot_move(info):
    b = G["board"]
    turn = b.turn
    if info is None:
        info = panalyse(b, 5)
    _, _, p_random, temp = LEVELS[G["level"]]
    scored = [(t["pv"][0], win_pct(t["score"].pov(turn).score(mate_score=10000))) for t in info if t.get("pv")]
    best_wp = scored[0][1]
    if random.random() < p_random:
        mv = random.choice(list(b.legal_moves))
    elif temp == 0:
        mv = scored[0][0]
    else:
        weights = [math.exp(-(best_wp - w) / temp) for _, w in scored]
        mv = random.choices([m for m, _ in scored], weights)[0]
    before = b.copy()
    was_book, _ = book_status(b)
    san = b.san(mv)
    if not clock_tick():
        return
    b.push(mv)
    G["info"] = panalyse(b, 3)
    after_wp = 100 - win_pct(mover_cp(G["info"], b))
    loss = max(0.0, best_wp - after_wp)
    G["last_bot_loss"] = loss

    reasons = move_reasons(before, mv, me=True)
    tactic = motif(before, mv)
    if tactic in ("fork", "pin", "skewer", "discovered", "double_check"):
        reasons.insert(0, {"fork": "A fork!", "pin": "A pin!", "skewer": "A skewer!", "discovered": "A discovered attack!",
                           "double_check": "Double check!"}[tactic])
    in_book, opening = book_status(b)
    if was_book and in_book:
        if opening and opening != G["opening"]:
            reasons.insert(0, f"A known opening move – we're now in the {opening}.")
        else:
            reasons.insert(0, "A known opening move.")
    G["opening"] = opening or G["opening"]
    if G["info"] and len(G["info"][0].get("pv", [])) >= 2 and not b.is_game_over():
        tmp = b.copy()
        tmp.push(G["info"][0]["pv"][0])
        reasons.append(f"My plan: next I'd like to play {tmp.san(G['info'][0]['pv'][1])}.")
    if loss >= 15:
        reasons.append("🤫 Psst – this move is actually a mistake. Can you find a way to punish it?")
    G["history"].append({"by": "coach", "san": san, "uci": mv.uci(), "text": " ".join(reasons)})
    check_over()


def user_move(uci):
    b = G["board"]
    try:
        mv = chess.Move.from_uci(uci)
    except ValueError:
        raise ValueError("Illegal move.")
    if G["result"] or (not G["self"] and b.turn != G["user"]) or mv not in b.legal_moves:
        raise ValueError("Illegal move.")
    if not clock_tick():
        return b.fen()
    turn = b.turn
    info_before = G["info"] or panalyse(b, 3)
    best = info_before[0]["pv"][0]
    alts = [win_pct(t["score"].pov(turn).score(mate_score=10000)) for t in info_before]
    before = win_pct(mover_cp(info_before, b))
    was_book, old_name = book_status(b)

    after = b.copy()
    after.push(mv)
    info_after = panalyse(after, 5)                 # also used to choose the coach's answer
    loss = max(0.0, before - (100 - win_pct(mover_cp(info_after, after))))
    in_book, new_name = book_status(after)
    cls = classify(in_book, mv, best, loss, before, alts, b, G["last_bot_loss"])
    reply = info_after[0]["pv"][0] if info_after and info_after[0].get("pv") else None
    text = coach_text(cls, b, mv, best, reply, info_after,
                      new_name if new_name != old_name else None,
                      (old_name or "opening") if was_book and not in_book else None)
    notes, _, _ = tactic_notes(b, mv, best, reply, info_before[0]["pv"][:6],
                               info_after[0]["pv"][:6] if info_after and info_after[0].get("pv") else [], cls)
    if notes:
        text = text.rstrip() + " " + notes
    G["history"].append({"by": "you", "side": "white" if turn == chess.WHITE else "black",
                         "san": b.san(mv), "uci": uci, "cls": cls, "text": text,
                         "best_san": b.san(best), "best_uci": best.uci(), "loss": round(loss, 1)})
    G["opening"] = new_name or G["opening"]
    if mv.promotion:
        G["promoted"] = True
    b.push(mv)
    G["info"] = info_after
    check_over()
    mid_fen = b.fen()
    G["turn_start"] = time.time()          # the coach's clock starts now
    if G.get("drill") and G["drill"]["goal"] == "promote" and G.get("promoted") and not G["result"]:
        G["result"], G["reason"] = ("1-0" if G["user"] == chess.WHITE else "0-1"), "promotion"
    if G["self"]:
        G["last_bot_loss"] = loss        # for "miss" detection on the other side's next move
    elif not G["result"]:
        bot_move(info_after)
    return mid_fen


def play_new(color, level, practice=False, tc=None, drill=None):
    global G
    user = {"white": chess.WHITE, "black": chess.BLACK}.get(color, random.choice([chess.WHITE, chess.BLACK]))
    board = chess.Board()
    d = next((x for x in DRILLS if x["id"] == drill), None)
    if d:
        board = chess.Board(d["fen"])
        user, level, practice, tc = board.turn, 7, False, None
    if practice:
        user = chess.WHITE
    G = {"board": board, "user": user, "drill": {k: d[k] for k in ("id", "title", "goal", "tip")} if d else None, "level": max(1, min(7, int(level))), "history": [],
         "info": None, "result": None, "reason": None, "opening": None, "last_bot_loss": 0.0, "self": practice,
         "tc": None, "clock": None, "turn_start": time.time()}
    if tc and not practice and float(tc[0]) > 0:
        G["tc"] = (float(tc[0]) * 60, float(tc[1]))
        G["clock"] = {"white": G["tc"][0], "black": G["tc"][0]}
    G["info"] = panalyse(G["board"], 5)
    G["turn_start"] = time.time()
    if board.turn != user and not practice:
        bot_move(G["info"])


def play_undo():
    b = G["board"]
    popped = 0
    while G["history"]:
        e = G["history"].pop()
        b.pop()
        popped += 1
        if e["by"] == "you":
            break
    hist = G.get("clock_hist") or []
    if G.get("clock") and popped and len(hist) >= popped:   # give back the time used for the taken-back moves
        G["clock"] = dict(hist[-popped])
        del hist[-popped:]
    if G["self"] and G["history"]:
        G["last_bot_loss"] = G["history"][-1].get("loss", 0.0)
    G["result"] = G["reason"] = None
    if not G["self"]:
        G["last_bot_loss"] = 0.0
    G["opening"] = book_status(b)[1]
    G["info"] = panalyse(b, 5)
    G["turn_start"] = time.time()


def play_hint():
    b = G["board"]
    if G["result"] or (not G["self"] and b.turn != G["user"]):
        raise ValueError("It's not your turn.")
    info = G["info"] or panalyse(b, 3)
    best = info[0]["pv"][0]
    return {"uci": best.uci(), "san": b.san(best), "text": " ".join(move_reasons(b, best, me=False))}


def play_resign():
    G["result"] = "0-1" if G["user"] == chess.WHITE else "1-0"
    G["reason"] = "resignation"


def play_pgn():
    if not G["result"]:
        raise ValueError("Finish the game first.")
    game = chess.pgn.Game.from_board(G["board"])
    me = settings.get("username") or "You"
    bot = me if G["self"] else f"Coach (Level {G['level']})"
    game.headers["White"], game.headers["Black"] = (me, bot) if G["user"] == chess.WHITE else (bot, me)
    game.headers["Result"] = G["result"]
    game.headers["Event"] = "Play vs Coach"
    game.headers["Date"] = time.strftime("%Y.%m.%d")
    return str(game)


# ---------------- puzzles from your own mistakes ----------------
PUZZLES = HERE / "puzzles.json"
# seconds until a solved puzzle comes back, per box (spaced repetition)
BOXES = [0, 86400, 3 * 86400, 7 * 86400, 21 * 86400]


def puzzle_progress():
    try:
        return json.loads(PUZZLES.read_text())
    except Exception:
        return {"items": {}, "streak": 0, "best_streak": 0}


def all_puzzles():
    out = []
    for r in load_reviews():
        c = r["my_color"]
        for i, p in enumerate(r["plies"]):
            if p["color"] == c and p["cls"] in ("mistake", "blunder", "miss") and p.get("legal") and p.get("good"):
                out.append({
                    "id": f"{r['id']}:{i}", "fen": r["positions"][i]["fen"], "color": c, "cls": p["cls"],
                    "played": p["san"], "played_uci": p["uci"], "best_san": p["best_san"], "best_uci": p["best_uci"],
                    "good": p["good"], "legal": p["legal"], "text": p["text"], "move_no": i // 2 + 1,
                    "game": f"{r['white']} vs {r['black']}", "date": r["date"], "review_id": r["id"], "ply": i + 1,
                    "motif": p.get("motif"),
                    "created": r.get("created", 0),
                })
    return out


def puzzle_overview(skip=None, theme=None):
    prog, now = puzzle_progress(), time.time()
    items = prog["items"]
    puzzles = all_puzzles()
    themes = {}
    for pz in puzzles:
        if pz.get("motif"):
            themes[pz["motif"]] = themes.get(pz["motif"], 0) + 1
    if theme:
        puzzles = [pz for pz in puzzles if pz.get("motif") == theme]
    due = [p for p in puzzles if items.get(p["id"], {}).get("due", 0) <= now]

    def order(p):
        st = items.get(p["id"])
        if st and st["box"] == 0:
            return (0, st["due"])                 # failed before: practice first
        if not st:
            return (1, -p["created"])             # new: newest games first
        return (2, st["due"])
    due.sort(key=order)
    nxt = next((p for p in due if p["id"] != skip), due[0] if due else None)
    return {
        "next": nxt, "total": len(puzzles), "due": len(due),
        "solved": sum(1 for p in puzzles if items.get(p["id"], {}).get("box", 0) >= 1),
        "mastered": sum(1 for p in puzzles if items.get(p["id"], {}).get("box", 0) >= 3),
        "streak": prog["streak"], "best_streak": prog["best_streak"], "themes": themes, "theme": theme,
    }


def puzzle_result(pid, ok):
    prog, now = puzzle_progress(), time.time()
    st = prog["items"].get(pid, {"box": 0, "attempts": 0, "solved": 0})
    st["attempts"] += 1
    if ok:
        st["solved"] += 1
        st["box"] = min(st["box"] + 1, len(BOXES) - 1)
        st["due"] = now + BOXES[st["box"]]
        prog["streak"] += 1
        prog["best_streak"] = max(prog["best_streak"], prog["streak"])
    else:
        st["box"] = 0
        st["due"] = now + 600                    # try again in 10 minutes
        prog["streak"] = 0
    prog["items"][pid] = st
    PUZZLES.write_text(json.dumps(prog))


# ---------------- progress statistics ----------------

def stats():
    reviews = load_reviews()
    offset = personal_offset(reviews)
    out = []
    for r in reversed(reviews):                 # oldest first
        r = calibrated(r, offset)
        c = r["my_color"]
        opp = "black" if c == "white" else "white"
        won = r["result"] == ("1-0" if c == "white" else "0-1")
        out.append({
            "id": r["id"], "date": r["date"], "created": r.get("created", 0),
            "opponent": r["black"] if c == "white" else r["white"], "color": c,
            "result": "draw" if r["result"] == "1/2-1/2" else "win" if won else "loss",
            "accuracy": r["accuracy"][c], "chesscom": (r.get("chesscom") or {}).get(c),
            "counts": r["counts"][c], "phases": r["phases"][c],
            "opening": r["opening"].split(" (")[0].split(":")[0] if r["opening"] else "",
            "my_elo": int(r[c + "_elo"]) if str(r.get(c + "_elo", "")).isdigit() else None,
            "opp_elo": int(r[opp + "_elo"]) if str(r.get(opp + "_elo", "")).isdigit() else None,
            "end": ending(r["termination"], r["result"]),
            "moves": sum(1 for p in r["plies"] if p["color"] == c),
            "errors": [{"move": k // 2 + 1, "clock": p.get("clock"), "piece": piece_of(p["san"]), "cls": p["cls"]}
                       for k, p in enumerate(r["plies"]) if p["color"] == c and p["cls"] in ("mistake", "blunder", "miss")],
        })
    return out


def piece_of(san):
    return "K" if san.startswith("O-O") else san[0] if san[0] in "KQRBN" else "P"


def ending(termination, result):
    t = (termination or "").lower()
    if result == "1/2-1/2" or "drawn" in t or "draw" in t:
        return "draw"
    for key, words in (("checkmate", ("checkmate",)), ("resignation", ("resignation",)), ("time", ("on time", "timeout")),
                       ("abandoned", ("abandon",))):
        if any(w in t for w in words):
            return key
    return "other"


_profile = {"at": 0, "data": None, "user": None}


def profile():
    """chess.com profile + ratings for the watched user (cached for 10 minutes)."""
    user = settings.get("username")
    if not user:
        return {}
    if _profile["user"] == user and time.time() - _profile["at"] < 600:
        return _profile["data"]
    try:
        pl = get_json(f"https://api.chess.com/pub/player/{user}")
        st = get_json(f"https://api.chess.com/pub/player/{user}/stats")
    except Exception:
        return _profile["data"] or {}
    ratings = {}
    for key in ("chess_rapid", "chess_blitz", "chess_bullet", "chess_daily"):
        if key in st:
            ratings[key[6:]] = {"last": st[key].get("last", {}).get("rating"), "best": st[key].get("best", {}).get("rating"),
                                "record": st[key].get("record", {})}
    data = {"username": pl.get("username", user), "name": pl.get("name"), "avatar": pl.get("avatar"),
            "country": (pl.get("country") or "").rsplit("/", 1)[-1], "joined": pl.get("joined"),
            "status": pl.get("status"), "ratings": ratings,
            "puzzles": {k: v for k, v in puzzle_overview().items() if k != "next"}}
    _profile.update(at=time.time(), data=data, user=user)
    return data


# ---------------- opening trainer ----------------
POPULAR = ["Italian Game", "Ruy Lopez", "Sicilian Defense", "French Defense", "Caro-Kann Defense", "Queen's Gambit Declined",
           "Queen's Gambit Accepted", "London System", "Scandinavian Defense", "King's Indian Defense", "Scotch Game",
           "Vienna Game", "English Opening", "Slav Defense", "Nimzo-Indian Defense", "Pirc Defense", "Dutch Defense"]


def build_families():
    fam = {}
    for f in sorted((HERE / "openings").glob("*.tsv")):
        for line in f.read_text(encoding="utf-8").splitlines()[1:]:
            eco, name, pgn = line.split("\t")
            family = name.split(":")[0]
            node = fam.setdefault(family, {"tree": {}, "names": {}, "lines": 0})
            node["lines"] += 1
            b = chess.Board()
            for tok in pgn.split():
                if tok[0].isdigit():
                    continue
                mv = b.parse_san(tok)
                parent = b.epd()
                b.push(mv)
                node["tree"].setdefault(parent, {})[mv.uci()] = b.epd()
            node["names"][b.epd()] = name
    for node in fam.values():
        depth = {}

        def d(epd):
            if epd not in depth:
                depth[epd] = 1 + max((d(c) for c in node["tree"].get(epd, {}).values()), default=0)
            return depth[epd]
        d(chess.Board().epd())
        node["depth"] = depth
    return fam


FAMILIES = build_families()


def opening_list():
    mine = {}
    for g in stats():
        if g["opening"]:
            mine.setdefault(g["opening"], []).append(g["color"])
    out = []
    for name, node in FAMILIES.items():
        colors = mine.get(name, [])
        out.append({"name": name, "lines": node["lines"], "depth": node["depth"].get(chess.Board().epd(), 0) - 1,
                    "yours": len(colors), "color": max(set(colors), key=colors.count) if colors else None,
                    "popular": name in POPULAR})
    out.sort(key=lambda o: (-o["yours"], not o["popular"], o["name"]))
    return out


def opening_step(name, color, moves):
    """Stateless trainer step: replays `moves`, then answers with the book moves for the side to move.
    When it is the coach's turn, it also picks the coach's book move."""
    node = FAMILIES.get(name)
    if node is None:
        raise ValueError("Unknown opening.")
    user = chess.WHITE if color == "white" else chess.BLACK
    b = chess.Board()
    for u in moves:
        if u not in node["tree"].get(b.epd(), {}):
            raise ValueError("Illegal move.")
        b.push(chess.Move.from_uci(u))
    coach = None
    kids = node["tree"].get(b.epd(), {})
    if kids and b.turn != user:                       # the coach answers with a book move (prefers long lines)
        ucis = list(kids)
        u = random.choices(ucis, [node["depth"].get(kids[x], 1) for x in ucis])[0]
        coach = {"uci": u, "san": b.san(chess.Move.from_uci(u))}
        b.push(chess.Move.from_uci(u))
        kids = node["tree"].get(b.epd(), {})
    name_now = None
    tmp = chess.Board()
    for m in b.move_stack:
        tmp.push(m)
        name_now = node["names"].get(tmp.epd(), name_now)
    book = sorted(({"uci": u, "san": b.san(chess.Move.from_uci(u)), "depth": node["depth"].get(e, 1)} for u, e in kids.items()),
                  key=lambda x: -x["depth"])
    return {"fen": b.fen(), "coach": coach, "book": book, "done": not book, "line": name_now or name,
            "legal": [m.uci() for m in b.legal_moves], "ply": len(b.move_stack)}


# ---------------- endgame drills ----------------
DRILLS = [
    {"id": "queen", "title": "Checkmate with the queen", "fen": "8/8/8/4k3/8/8/8/3QK3 w - - 0 1", "goal": "mate",
     "tip": "Use the queen to push the enemy king to the edge – stay a knight's move away from it. Then bring your own king closer and give mate. Careful: don't stalemate!"},
    {"id": "rook", "title": "Checkmate with the rook", "fen": "8/8/8/4k3/8/8/8/R3K3 w - - 0 1", "goal": "mate",
     "tip": "Cut the king off with your rook, then walk your king towards it. Give check only when the kings stand opposite each other."},
    {"id": "ladder", "title": "Ladder mate with two rooks", "fen": "8/8/3k4/8/8/8/8/R3K2R w - - 0 1", "goal": "mate",
     "tip": "The rooks take turns: one cuts off a rank, the other gives check on the next rank. Keep them far away from the king."},
    {"id": "pawn", "title": "Promote the pawn", "fen": "4k3/8/4K3/4P3/8/8/8/8 w - - 0 1", "goal": "promote",
     "tip": "Your king stands in front of the pawn – use the opposition to push the enemy king aside, then escort the pawn."},
    {"id": "defend", "title": "Hold the draw", "fen": "8/8/8/4k3/4P3/4K3/8/8 b - - 0 1", "goal": "draw",
     "tip": "Stay directly in front of the pawn and take the opposition when the enemy king comes close. Then it's a draw."},
]


def drill_status():
    d = G.get("drill") if G else None
    if not d:
        return None
    win = G["result"] == ("1-0" if G["user"] == chess.WHITE else "0-1")
    ok = {"mate": win and G["reason"] == "checkmate", "promote": G.get("promoted", False) or win,
          "draw": G["result"] == "1/2-1/2"}[d["goal"]]
    return dict(d, done=bool(G["result"] or ok), success=ok)


# ---------------- language ----------------

def L(text):
    """Translate generated coach text into the selected language."""
    return to_german(text) if settings.get("lang") == "de" else text


def localized_review(r):
    if settings.get("lang") != "de":
        return r
    r = dict(r, summary=L(r["summary"]))
    r["plies"] = [dict(p, text=L(p["text"])) for p in r["plies"]]
    return r


def localized_play(st):
    if settings.get("lang") != "de" or not st.get("active"):
        return st
    st = dict(st)
    st["history"] = [dict(h, text=L(h["text"])) for h in st["history"]]
    st["tips"] = [dict(t, text=L(t["text"])) for t in st["tips"]]
    return st


# ---------------- web server ----------------

def summaries():
    out = []
    reviews = load_reviews()
    offset = personal_offset(reviews)
    for r in reviews:
        r = calibrated(r, offset)
        c = r["my_color"]
        out.append({"id": r["id"], "white": r["white"], "black": r["black"], "result": r["result"],
                    "date": r["date"], "my_color": c, "accuracy": r["accuracy"][c]})
    return out


def piece_sets():
    """All piece sets as data URIs: every folder in pieces/ with 12 SVG or PNG files, plus the built-in 'classic' set."""
    types = {".svg": "image/svg+xml", ".png": "image/png"}
    uri = lambda data, mime="image/svg+xml": f"data:{mime};base64," + base64.b64encode(data).decode()
    sets = {}
    for d in sorted(p for p in (HERE / "pieces").glob("*") if p.is_dir()):
        files = {f.stem: f for f in d.iterdir() if f.suffix.lower() in types}
        names = {c + s: (s if c == "w" else s.lower()) for c in "wb" for s in "PNBRQK"}
        if all(n in files for n in names):
            sets[d.name] = {sym: uri(files[n].read_bytes(), types[files[n].suffix.lower()]) for n, sym in names.items()}
    sets["classic"] = {s: uri(chess.svg.piece(chess.Piece.from_symbol(s)).encode()) for s in "PNBRQKpnbrqk"}
    return sets


def page():
    return (HERE / "index.html").read_text(encoding="utf-8").replace("/*PIECES*/", json.dumps(piece_sets()))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, obj, code=200, ctype="application/json"):
        body = obj.encode() if isinstance(obj, str) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            return self.send(page(), ctype="text/html")
        if u.path == "/api/puzzles":
            o = puzzle_overview(q.get("skip", [None])[0], q.get("theme", [None])[0])
            if o["next"]:
                o["next"] = dict(o["next"], text=L(o["next"]["text"]))
            return self.send(o)
        if u.path == "/api/stats":
            return self.send(stats())
        if u.path == "/api/openings":
            return self.send(opening_list())
        if u.path == "/api/drills":
            return self.send(DRILLS)
        if u.path == "/api/prefs":
            return self.send(prefs())
        if u.path == "/api/profile":
            return self.send(profile())
        if u.path == "/api/play/state":
            with play_lock:
                return self.send(localized_play(play_state()))
        if u.path == "/api/version":
            return self.send({"version": VERSION})
        if u.path == "/api/sounds":
            return self.send(sorted(f.name for f in (HERE / "sounds").glob("*") if f.suffix in (".mp3", ".ogg", ".wav", ".webm")))
        if u.path.startswith("/sounds/"):
            f = HERE / "sounds" / Path(u.path).name
            types = {".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".wav": "audio/wav", ".webm": "audio/webm"}
            if f.suffix in types and f.exists():
                body = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", types[f.suffix])
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                return self.wfile.write(body)
            return self.send({"error": "not found"}, 404)
        if u.path == "/api/state":
            return self.send({"username": settings["username"], "status": status,
                              "queued": len(pending), "reviews": summaries()})
        if u.path == "/api/game":
            f = DATA / f"{q.get('id', [''])[0]}.json"
            if f.parent == DATA and f.exists():
                return self.send(localized_review(calibrated(json.loads(f.read_text()), personal_offset(load_reviews()))))
            return self.send({"error": "not found"}, 404)
        if u.path == "/api/recent":
            user = settings["username"]
            if not user:
                return self.send({"error": "Set your username first."}, 400)
            try:
                archives = get_json(f"https://api.chess.com/pub/player/{user}/games/archives")["archives"]
                games = []
                for a in reversed(archives[-2:]):
                    games += reversed(get_json(a)["games"])
                attach_chesscom(games)
            except Exception as ex:
                return self.send({"error": str(ex)}, 502)
            out = []
            for g in [g for g in games if g.get("rules") == "chess"][:25]:
                gid = game_id(g)
                recent[gid] = g
                me = g["white"] if g["white"]["username"].lower() == user.lower() else g["black"]
                opp = g["black"] if me is g["white"] else g["white"]
                out.append({"id": gid, "opponent": opp["username"], "opp_rating": opp.get("rating"),
                            "result": me["result"], "time_class": g.get("time_class"),
                            "end": g.get("end_time"), "reviewed": (DATA / f"{gid}.json").exists()})
            return self.send(out)
        self.send({"error": "not found"}, 404)

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or "{}")
        except ValueError:
            return self.send({"error": "bad json"}, 400)
        if self.path == "/api/shutdown":
            # a newer coach was started: hand over the port (JSON only, so other websites can't trigger it)
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                return self.send({"error": "bad request"}, 400)
            self.send({"ok": True})
            threading.Thread(target=lambda: (time.sleep(0.2), os._exit(0)), daemon=True).start()
            return
        if self.path == "/api/puzzles/result":
            puzzle_result(str(body.get("id", "")), bool(body.get("ok")))
            o = puzzle_overview(body.get("id"))
            o["next"] = None            # the page only needs the counters here
            return self.send(o)
        if self.path.startswith("/api/play/"):
            action = self.path.rsplit("/", 1)[-1]
            try:
                with play_lock:
                    if action == "new":
                        play_new(body.get("color", "random"), body.get("level", 1), bool(body.get("practice")), body.get("tc"), body.get("drill"))
                        return self.send(localized_play(play_state()))
                    if G is None:
                        return self.send({"error": "Start a new game first."}, 400)
                    if action == "move":
                        mid = user_move(body.get("uci", ""))
                        return self.send({"mid_fen": mid, "state": localized_play(play_state())})
                    if action == "undo":
                        play_undo()
                        return self.send(localized_play(play_state()))
                    if action == "hint":
                        h = play_hint()
                        return self.send(dict(h, text=L(h["text"])))
                    if action == "flag":            # the page saw a clock reach zero
                        if G.get("clock") and not G["result"]:
                            side = "white" if G["board"].turn == chess.WHITE else "black"
                            if G["clock"][side] - (time.time() - G["turn_start"]) <= 0.3:
                                G["clock"][side] = 0
                                lost_on_time(side)
                        return self.send(localized_play(play_state()))
                    if action == "resign":
                        play_resign()
                        return self.send(localized_play(play_state()))
                    if action == "review":
                        pgn = play_pgn()
                        gid = "play-" + hashlib.sha1(pgn.encode()).hexdigest()[:12]
                        enqueue(gid, pgn, "Play vs Coach")
                        return self.send({"id": gid})
            except ValueError as ex:
                return self.send({"error": str(ex)}, 400)
            return self.send({"error": "not found"}, 404)
        if self.path == "/api/opening":
            try:
                return self.send(opening_step(body.get("name", ""), body.get("color", "white"), body.get("moves", [])))
            except ValueError as ex:
                return self.send({"error": str(ex)}, 400)
        if self.path == "/api/prefs":
            if body.get("think") in (0.2, 0.5, 1.0):
                settings["think"] = body["think"]
            if isinstance(body.get("lan"), bool):
                settings["lan"] = body["lan"]           # takes effect after a restart of the coach
            save_settings()
            return self.send(prefs())
        if self.path == "/api/reanalyze":
            f = DATA / f"{body.get('id', '')}.json"
            if f.parent != DATA or not f.exists():
                return self.send({"error": "not found"}, 404)
            r = json.loads(f.read_text())
            if not r.get("pgn"):
                return self.send({"error": "This game cannot be analyzed again."}, 400)
            enqueue(r["id"], r["pgn"], f"{r['white']} vs {r['black']}", {"chesscom": r["chesscom"]} if r.get("chesscom") else {}, force=True)
            return self.send({"id": r["id"]})
        if self.path == "/api/lang":
            if body.get("lang") in ("en", "de") and settings.get("lang") != body["lang"]:
                settings["lang"] = body["lang"]
                save_settings()
            return self.send({"lang": settings.get("lang", "en")})
        if self.path == "/api/settings":
            name = body.get("username", "").strip()
            if name:
                try:
                    name = get_json(f"https://api.chess.com/pub/player/{name.lower()}")["username"]
                except urllib.error.HTTPError as ex:
                    msg = "This chess.com username does not exist." if ex.code == 404 else str(ex)
                    return self.send({"error": msg}, 400)
                except Exception as ex:
                    return self.send({"error": str(ex)}, 502)
            settings.update(username=name, seen=[], primed=False)
            save_settings()
            return self.send({"username": name})
        if self.path == "/api/review":
            g = recent.get(body.get("id"))
            if not g:
                return self.send({"error": "Unknown game, reload the list."}, 400)
            enqueue(body["id"], g["pgn"], label_for(g), extra_for(g))
            return self.send({"id": body["id"]})
        if self.path == "/api/pgn":
            pgn = body.get("pgn", "")
            game = chess.pgn.read_game(io.StringIO(pgn))
            if game is None or not list(game.mainline_moves()):
                return self.send({"error": "Could not read any moves from this PGN."}, 400)
            if game.headers.get("Result", "*") == "*":
                return self.send({"error": "This game is not finished. Reviews only work after the game is over."}, 400)
            gid = "pgn-" + hashlib.sha1(pgn.strip().encode()).hexdigest()[:12]
            enqueue(gid, pgn, f"{game.headers.get('White', '?')} vs {game.headers.get('Black', '?')}")
            return self.send({"id": gid})
        self.send({"error": "not found"}, 404)


def lan_ip():
    """This PC's address in the home network (no data is sent)."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
            sk.connect(("192.168.0.1", 9))
            return sk.getsockname()[0]
    except OSError:
        return None


def prefs():
    ip = lan_ip() if settings.get("lan") else None
    return {"think": settings.get("think", THINK), "lan": bool(settings.get("lan")),
            "lan_url": f"http://{ip}:{PORT}" if ip else None}


class Server(ThreadingHTTPServer):
    allow_reuse_address = False   # on Windows reuse lets several coaches share a port; the oldest would win


def running_version(url):
    try:
        with urllib.request.urlopen(url + "/api/version", timeout=3) as r:
            return json.load(r)["version"]
    except Exception:
        return "old"   # an old coach without /api/version


def start_server(url):
    for attempt in range(30):
        try:
            # home-network access only when switched on in the settings
            return Server(("0.0.0.0" if settings.get("lan") else "127.0.0.1", PORT), Handler)
        except OSError:
            if attempt == 0:
                if running_version(url) == VERSION:
                    return None
                print("An older Chess Coach is running - replacing it ...")
                try:
                    req = urllib.request.Request(url + "/api/shutdown", data=b"{}", method="POST",
                                                 headers={"Content-Type": "application/json"})
                    urllib.request.urlopen(req, timeout=3).read()
                except Exception:
                    pass
            time.sleep(0.5)
    sys.exit(f"Port {PORT} is busy. Close all Chess Coach windows (or restart the PC) and try again.")


def main():
    if not ENGINE.exists():
        sys.exit("Stockfish was not found. Run install.bat (or set STOCKFISH_PATH) first.")
    url = f"http://localhost:{PORT}"
    server = start_server(url)
    if server is None:
        print(f"Chess Coach is already running at {url}")
        if "--no-browser" not in sys.argv:
            webbrowser.open(url)
        return
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=watcher, daemon=True).start()
    print(f"Chess Coach running at {url}  (close this window to stop)")
    if settings.get("lan") and lan_ip():
        print(f"On your phone (same WiFi): http://{lan_ip()}:{PORT}")
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()

