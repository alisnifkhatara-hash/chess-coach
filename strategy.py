"""Plain-language strategic reasons why one quiet move is better than another.

quiet_reason(board, played, best) compares the position after the played move
with the position after the engine's best move (both from the mover's view) and
returns one short sentence, or None if no simple reason stands out.
"""
import chess

NAMES = {chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop", chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king"}
VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
CENTER = [chess.D4, chess.E4, chess.D5, chess.E5]


def _after(board, mv):
    b = board.copy()
    b.push(mv)
    return b


def _hanging(board, color):
    return {sq for sq, pc in board.piece_map().items()
            if pc.color == color and pc.piece_type not in (chess.KING, chess.PAWN)
            and board.attackers(not color, sq)
            and (not board.attackers(color, sq)
                 or min(VALUE[board.piece_at(a).piece_type] or 99 for a in board.attackers(not color, sq)) < VALUE[pc.piece_type])}


def _center(board, color):
    return sum(len(board.attackers(color, sq)) for sq in CENTER)


def _files(board, color):
    return [chess.square_file(sq) for sq in board.pieces(chess.PAWN, color)]


def _doubled(board, color):
    f = _files(board, color)
    return sum(f.count(x) - 1 for x in set(f))


def _isolated(board, color):
    f = set(_files(board, color))
    return sum(1 for sq in board.pieces(chess.PAWN, color)
               if chess.square_file(sq) - 1 not in f and chess.square_file(sq) + 1 not in f)


def _mobility(board, color):
    b = board.copy()
    if b.turn != color:
        if b.is_check():
            return 0
        b.push(chess.Move.null())
    return b.legal_moves.count()


def _open_file(board, file):
    return not any(chess.square_file(sq) == file for sq in board.pieces(chess.PAWN, chess.WHITE) | board.pieces(chess.PAWN, chess.BLACK))


def _passed(board, sq, color):
    f, r = chess.square_file(sq), chess.square_rank(sq)
    for e in board.pieces(chess.PAWN, not color):
        ef, er = chess.square_file(e), chess.square_rank(e)
        if abs(ef - f) <= 1 and ((er > r) if color == chess.WHITE else (er < r)):
            return False
    return True


def quiet_reason(board, played, best):
    me = board.turn
    piece = board.piece_at(played.from_square)
    bpiece = board.piece_at(best.from_square)
    if piece is None or bpiece is None:
        return None
    ap, ab = _after(board, played), _after(board, best)
    s_best, s_played = board.san(best), board.san(played)
    ply = board.ply()
    opening = ply < 24 and board.fullmove_number <= 14

    # 1. a piece was under attack and the played move ignored it
    still = _hanging(ap, me) - _hanging(ab, me)
    if still:
        sq = next(iter(still))
        return f"Your {NAMES[ap.piece_at(sq).piece_type]} on {chess.square_name(sq)} was under attack – {s_best} deals with that."
    # 2. king safety
    if board.is_castling(best) and not board.is_castling(played):
        return f"{s_best} would have castled your king into safety."
    if piece.piece_type == chess.KING and not board.is_castling(played) and board.has_castling_rights(me) and opening:
        return f"Moving your king loses the right to castle – your king stays stuck in the middle."
    # 3. early queen
    if opening and piece.piece_type == chess.QUEEN and bpiece.piece_type != chess.QUEEN:
        return "Bringing the queen out early lets your opponent attack it and gain time."
    # 4. development
    home = 0 if me == chess.WHITE else 7
    develops = lambda mv, pc: pc.piece_type in (chess.KNIGHT, chess.BISHOP) and chess.square_rank(mv.from_square) == home
    if opening and develops(best, bpiece) and not develops(played, piece):
        return f"{s_best} develops a new piece – in the opening, get your knights and bishops out first."
    # 5. pawn structure
    if _doubled(ap, me) > _doubled(ab, me):
        return f"{s_played} gives you doubled pawns, which are weak. {s_best} keeps your pawns healthy."
    if _isolated(ap, me) > _isolated(ab, me):
        return f"{s_played} leaves you with an isolated pawn that is hard to defend."
    # 6. center
    if opening and _center(ab, me) - _center(ap, me) >= 2:
        return f"{s_best} fights for the center."
    # 7. rook to an open file
    if bpiece.piece_type == chess.ROOK and _open_file(ab, chess.square_file(best.to_square)) \
            and not _open_file(board, chess.square_file(best.from_square)):
        return f"{s_best} puts your rook on an open file, where it is much more active."
    # 8. passed pawn in the endgame
    if bpiece.piece_type == chess.PAWN and not opening and _passed(ab, best.to_square, me) and piece.piece_type != chess.PAWN:
        return f"{s_best} pushes your passed pawn – in the endgame, passed pawns must be pushed!"
    # 9. general activity
    if _mobility(ab, me) - _mobility(ap, me) >= 6:
        return f"{s_best} makes your pieces more active."
    return None
