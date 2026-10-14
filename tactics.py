"""Recognise the tactical motif behind a move (fork, pin, skewer, ...).

motif(board, move, pv) looks at the position *before* `move` (the side to move
plays it) and returns one of:
  mate, back_rank, double_check, discovered, fork, skewer, pin, hanging, promotion
or None when the move is not a recognisable tactic.
"""
import chess

VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}
SLIDERS = (chess.BISHOP, chess.ROOK, chess.QUEEN)


def _beyond(board, start, target):
    """First piece behind `target` on the line from `start` through `target` (or None)."""
    df = (chess.square_file(target) > chess.square_file(start)) - (chess.square_file(target) < chess.square_file(start))
    dr = (chess.square_rank(target) > chess.square_rank(start)) - (chess.square_rank(target) < chess.square_rank(start))
    f, r = chess.square_file(target) + df, chess.square_rank(target) + dr
    while 0 <= f < 8 and 0 <= r < 8:
        sq = chess.square(f, r)
        if board.piece_at(sq):
            return sq
        f, r = f + df, r + dr
    return None


def _ends_in_mate(board, pv, plies=5):
    b = board.copy()
    for m in pv[:plies]:
        if m not in b.legal_moves:
            return None
        b.push(m)
        if b.is_checkmate():
            return b
    return None


def _back_rank(mated):
    k = mated.king(mated.turn)
    if k is None or chess.square_rank(k) not in (0, 7):
        return False
    return any(mated.piece_at(s).piece_type in (chess.ROOK, chess.QUEEN) and chess.square_rank(s) == chess.square_rank(k)
               for s in mated.checkers())


def _worth_attacking(after, attacker_sq, target_sq):
    """An attacked enemy piece counts as a real target if it is the king, worth more than the attacker, or undefended."""
    target, attacker = after.piece_at(target_sq), after.piece_at(attacker_sq)
    if target.piece_type == chess.KING:
        return True
    if target.piece_type == chess.PAWN:
        return False
    return VALUE[target.piece_type] > VALUE[attacker.piece_type] or not after.attackers(target.color, target_sq)


def motif(board, mv, pv=None):
    if mv not in board.legal_moves:
        return None
    us, them = board.turn, not board.turn
    piece = board.piece_at(mv.from_square)
    after = board.copy()
    after.push(mv)
    to = mv.to_square

    if after.is_checkmate():
        return "back_rank" if _back_rank(after) else "mate"
    if pv and pv[0] == mv:
        mated = _ends_in_mate(board, pv)
        if mated is not None:
            return "back_rank" if _back_rank(mated) else "mate"

    if after.is_check() and len(after.checkers()) > 1:
        return "double_check"
    if after.is_check() and to not in after.checkers():
        return "discovered"

    # discovered attack: another of our sliders now hits a valuable target
    for sq in after.pieces(chess.BISHOP, us) | after.pieces(chess.ROOK, us) | after.pieces(chess.QUEEN, us):
        if sq == to:
            continue
        for t in after.attacks(sq) - board.attacks(sq):
            tp = after.piece_at(t)
            if tp and tp.color == them and tp.piece_type in (chess.QUEEN, chess.ROOK) and _worth_attacking(after, sq, t):
                return "discovered"

    # fork: the moved piece attacks two real targets at once (and isn't simply lost)
    targets = [t for t in after.attacks(to) if after.piece_at(t) and after.piece_at(t).color == them and _worth_attacking(after, to, t)]
    safe = not after.attackers(them, to) or after.attackers(us, to)
    if len(targets) >= 2 and (safe or after.is_check()):
        return "fork"

    if piece.piece_type in SLIDERS:
        for t in after.attacks(to):
            tp = after.piece_at(t)
            if not tp or tp.color != them:
                continue
            behind = _beyond(after, to, t)
            if behind is None:
                continue
            bp = after.piece_at(behind)
            if bp.color != them or bp.piece_type == chess.PAWN:
                continue
            # skewer: the big piece in front must move away, the piece behind falls
            if tp.piece_type in (chess.KING, chess.QUEEN) and VALUE[bp.piece_type] < VALUE[tp.piece_type]:
                return "skewer"
            # pin: the piece in front cannot move without exposing a bigger one behind
            if VALUE[bp.piece_type] > VALUE[tp.piece_type] and VALUE[tp.piece_type] >= 3:
                return "pin"

    if board.is_capture(mv):
        victim = board.piece_at(to)
        if victim is not None and (not board.attackers(them, to) or VALUE[victim.piece_type] > VALUE[piece.piece_type]):
            return "hanging"

    if mv.promotion:
        return "promotion"
    return None
