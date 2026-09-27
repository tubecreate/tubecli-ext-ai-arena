# -*- coding: utf-8 -*-
"""Cờ Tướng (Xiangqi) cho AI Arena — engine luật thuần Python, không thư viện ngoài.

Người dùng chốt 27/9/2026: «làm bộ engine cho cờ tướng» thay vì chỉ nhờ cloud gửi danh
sách nước — có engine thì AIPlayer tự kiểm luật + thử lại tại máy (đỡ đốt lượt), và cờ
tướng vào GAME_REGISTRY như cờ vua (đấu AI-vs-AI, replay, học nguyên tắc về sau).

Toạ độ: cột a-i (x 0-8, trái→phải theo bên Đỏ), hàng 0-9 (0 = đáy, phía Đỏ). Nước đi là
chuỗi 4 ký tự "a0a1". FEN cùng định dạng với bộ trọng tài @weshell/xiangqi.js trên cloud
(hàng 9 ghi trước; chữ HOA = Đỏ = 'w'): hai đầu không bao giờ lệch nhau về ký hiệu.

Luật đã cài đủ: xe trượt thẳng; pháo đi như xe nhưng ĂN phải nhảy đúng một «ngòi»; mã
ngày bị «cản mã» ô kề; tượng đi chéo 2 bị «mắt tượng» chặn và không qua sông; sĩ chéo 1
trong cung; tướng ngang dọc 1 trong cung; tốt tiến 1, qua sông thêm đi ngang, không lùi;
hai tướng KHÔNG được đối mặt trống cột; và LUẬT THUA đặc trưng: bên tới lượt mà hết nước
hợp lệ là THUA (kể cả không bị chiếu — khác cờ vua, không có hoà stalemate).
"""
from typing import Any, Dict, List, Optional, Tuple

from engine.base_game import BaseGame

START_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"
FILES = "abcdefghi"

Sq = Tuple[int, int]                 # (x 0-8, y 0-9)
Board = Dict[Sq, Tuple[str, str]]    # sq -> (color 'w'/'b', type 'rnbakcp')


def parse_fen(fen: str) -> Tuple[Board, str]:
    parts = str(fen or "").split()
    rows = parts[0].split("/")
    if len(rows) != 10:
        raise ValueError("bad fen")
    board: Board = {}
    for i, row in enumerate(rows):           # hàng 9 ghi trước
        y = 9 - i
        x = 0
        for ch in row:
            if ch.isdigit():
                x += int(ch)
            else:
                color = "w" if ch.isupper() else "b"
                board[(x, y)] = (color, ch.lower())
                x += 1
        if x != 9:
            raise ValueError("bad fen row")
    turn = parts[1] if len(parts) > 1 and parts[1] in ("w", "b") else "w"
    return board, turn


def emit_fen(board: Board, turn: str, move_number: int = 1) -> str:
    rows = []
    for y in range(9, -1, -1):
        row, empty = "", 0
        for x in range(9):
            p = board.get((x, y))
            if p is None:
                empty += 1
            else:
                if empty:
                    row += str(empty)
                    empty = 0
                ch = p[1]
                row += ch.upper() if p[0] == "w" else ch
        if empty:
            row += str(empty)
        rows.append(row)
    return "/".join(rows) + f" {turn} - - 0 {max(1, move_number)}"


def _in_board(x: int, y: int) -> bool:
    return 0 <= x <= 8 and 0 <= y <= 9


def _in_palace(x: int, y: int, color: str) -> bool:
    if not 3 <= x <= 5:
        return False
    return 0 <= y <= 2 if color == "w" else 7 <= y <= 9


def _crossed_river(y: int, color: str) -> bool:
    return y >= 5 if color == "w" else y <= 4


def _king_sq(board: Board, color: str) -> Optional[Sq]:
    for sq, (c, t) in board.items():
        if c == color and t == "k":
            return sq
    return None


def kings_facing(board: Board) -> bool:
    wk, bk = _king_sq(board, "w"), _king_sq(board, "b")
    if not wk or not bk or wk[0] != bk[0]:
        return False
    x = wk[0]
    lo, hi = min(wk[1], bk[1]), max(wk[1], bk[1])
    return all((x, y) not in board for y in range(lo + 1, hi))


def gen_pseudo(board: Board, color: str) -> List[Tuple[Sq, Sq]]:
    """Mọi nước theo dáng quân (chưa xét chiếu/đối mặt)."""
    out: List[Tuple[Sq, Sq]] = []
    for (x, y), (c, t) in list(board.items()):
        if c != color:
            continue
        src = (x, y)
        if t == "r" or t == "c":
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                # đoạn trống: cả xe lẫn pháo đều ĐI được
                while _in_board(nx, ny) and (nx, ny) not in board:
                    out.append((src, (nx, ny)))
                    nx, ny = nx + dx, ny + dy
                if not _in_board(nx, ny):
                    continue
                if t == "r":
                    if board[(nx, ny)][0] != color:
                        out.append((src, (nx, ny)))
                else:
                    # pháo: nhảy qua đúng MỘT ngòi rồi ăn quân đầu tiên phía sau
                    nx, ny = nx + dx, ny + dy
                    while _in_board(nx, ny) and (nx, ny) not in board:
                        nx, ny = nx + dx, ny + dy
                    if _in_board(nx, ny) and board[(nx, ny)][0] != color:
                        out.append((src, (nx, ny)))
        elif t == "n":
            for dx, dy, lx, ly in ((1, 2, 0, 1), (-1, 2, 0, 1), (1, -2, 0, -1), (-1, -2, 0, -1),
                                   (2, 1, 1, 0), (2, -1, 1, 0), (-2, 1, -1, 0), (-2, -1, -1, 0)):
                nx, ny = x + dx, y + dy
                if not _in_board(nx, ny) or (x + lx, y + ly) in board:   # cản mã
                    continue
                if board.get((nx, ny), ("", ""))[0] != color:
                    out.append((src, (nx, ny)))
        elif t == "b":
            for dx, dy in ((2, 2), (2, -2), (-2, 2), (-2, -2)):
                nx, ny = x + dx, y + dy
                if not _in_board(nx, ny) or _crossed_river(ny, color):   # tượng không qua sông
                    continue
                if (x + dx // 2, y + dy // 2) in board:                  # mắt tượng
                    continue
                if board.get((nx, ny), ("", ""))[0] != color:
                    out.append((src, (nx, ny)))
        elif t == "a":
            for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                nx, ny = x + dx, y + dy
                if _in_palace(nx, ny, color) and board.get((nx, ny), ("", ""))[0] != color:
                    out.append((src, (nx, ny)))
        elif t == "k":
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if _in_palace(nx, ny, color) and board.get((nx, ny), ("", ""))[0] != color:
                    out.append((src, (nx, ny)))
        elif t == "p":
            fwd = 1 if color == "w" else -1
            steps = [(0, fwd)]
            if _crossed_river(y, color):
                steps += [(1, 0), (-1, 0)]
            for dx, dy in steps:
                nx, ny = x + dx, y + dy
                if _in_board(nx, ny) and board.get((nx, ny), ("", ""))[0] != color:
                    out.append((src, (nx, ny)))
    return out


def in_check(board: Board, color: str) -> bool:
    """color đang bị chiếu (kể cả hai tướng đối mặt — thế cờ cấm)."""
    if kings_facing(board):
        return True
    ksq = _king_sq(board, color)
    if not ksq:
        return True                          # mất tướng = thua rồi
    enemy = "b" if color == "w" else "w"
    return any(to == ksq for _, to in gen_pseudo(board, enemy))


def apply_raw(board: Board, frm: Sq, to: Sq) -> Board:
    nb = dict(board)
    nb[to] = nb.pop(frm)
    return nb


def legal_moves(board: Board, color: str) -> List[str]:
    out = []
    for frm, to in gen_pseudo(board, color):
        if not in_check(apply_raw(board, frm, to), color):
            out.append(FILES[frm[0]] + str(frm[1]) + FILES[to[0]] + str(to[1]))
    return out


def _parse_move(move: str) -> Tuple[Sq, Sq]:
    m = str(move or "").strip().lower().replace("-", "")
    if len(m) != 4 or m[0] not in FILES or m[2] not in FILES or not m[1].isdigit() or not m[3].isdigit():
        raise ValueError(f"bad move format: {move!r}")
    return (FILES.index(m[0]), int(m[1])), (FILES.index(m[2]), int(m[3]))


_ZH_NAME = {"w": {"r": "Xe", "n": "Mã", "b": "Tượng", "a": "Sĩ", "k": "Tướng", "c": "Pháo", "p": "Tốt"},
            "b": {"r": "Xe", "n": "Mã", "b": "Tượng", "a": "Sĩ", "k": "Tướng", "c": "Pháo", "p": "Tốt"}}


class XiangqiGame(BaseGame):
    name = "xiangqi"
    display_name = "Cờ Tướng"
    icon = "🀄"
    min_players = 2
    max_players = 2
    description = "Cờ tướng Trung Hoa: Đỏ đi trước; hết nước hợp lệ là thua."

    # «white» = Đỏ, «black» = Đen — giữ đúng cặp tên mà hub/manager đã dùng cho chess.
    def get_initial_state(self, player_ids: List[str]) -> dict:
        return {
            "fen": START_FEN,
            "players": {"white": player_ids[0], "black": player_ids[1]},
            "move_history": [],
            "move_count": 0,
            "captured": {"white": [], "black": []},
        }

    # Engine chỉ được hỏi cho BÊN TỚI LƯỢT (decide_move/play-turn), nên màu lấy theo FEN
    # — không tin state["players"] (adapter của hub từng gán nhầm khi current_turn viết
    # 'w' thay vì 'white').
    def _turn(self, state: dict) -> str:
        _, turn = parse_fen(state["fen"])
        return turn

    def get_valid_moves(self, state: dict, player_id: str) -> list:
        board, turn = parse_fen(state["fen"])
        return legal_moves(board, turn)

    def get_current_player(self, state: dict) -> str:
        color = "white" if self._turn(state) == "w" else "black"
        return state["players"].get(color, "")

    def apply_move(self, state: dict, player_id: str, move: Any) -> dict:
        board, turn = parse_fen(state["fen"])
        frm, to = _parse_move(move)
        uci = FILES[frm[0]] + str(frm[1]) + FILES[to[0]] + str(to[1])
        if uci not in legal_moves(board, turn):
            raise ValueError(f"illegal move: {uci}")
        captured = board.get(to)
        if captured:
            side = "white" if turn == "w" else "black"
            state["captured"].setdefault(side, []).append(captured[1].upper())
        piece = board[frm]
        nb = apply_raw(board, frm, to)
        nxt = "b" if turn == "w" else "w"
        state["fen"] = emit_fen(nb, nxt, state["move_count"] // 2 + 1)
        state["move_history"].append({
            "player": player_id,
            "uci": uci,
            "san": _ZH_NAME[piece[0]][piece[1]] + " " + uci,
            "move_number": state["move_count"] + 1,
        })
        state["move_count"] = state.get("move_count", 0) + 1
        return state

    def check_game_over(self, state: dict) -> Optional[dict]:
        board, turn = parse_fen(state["fen"])
        if not legal_moves(board, turn):
            # Cờ tướng: hết nước là THUA — bị chiếu hết hay bị vây đều thế.
            loser_color = "white" if turn == "w" else "black"
            winner_color = "black" if turn == "w" else "white"
            w_id = state["players"].get(winner_color, "")
            l_id = state["players"].get(loser_color, "")
            return {
                "winner": w_id,
                "reason": "checkmate" if in_check(board, turn) else "stalemate",
                "scores": {w_id: 1.0, l_id: 0.0},
            }
        if state.get("move_count", 0) >= self.get_max_turns():
            w_id = state["players"].get("white", "")
            b_id = state["players"].get("black", "")
            return {"winner": None, "reason": "max_turns", "scores": {w_id: 0.5, b_id: 0.5}}
        return None

    def get_max_turns(self) -> int:
        return 300

    def render_state_for_ai(self, state: dict, player_id: str) -> str:
        board, turn = parse_fen(state["fen"])
        legal = legal_moves(board, turn)
        hist = " ".join(m["uci"] for m in state.get("move_history", [])[-12:]) or "(game start)"
        side = "RED" if turn == "w" else "BLACK"
        # Bàn ASCII cho model «nhìn»: hàng 9 trên cùng, chữ hoa = Đỏ.
        rows = []
        for y in range(9, -1, -1):
            row = []
            for x in range(9):
                p = board.get((x, y))
                row.append("." if p is None else (p[1].upper() if p[0] == "w" else p[1]))
            rows.append(f"{y} " + " ".join(row))
        rows.append("  " + " ".join(FILES))
        return (
            f"You are playing Chinese Chess (Xiangqi) as the {side} side.\n"
            "Uppercase = Red, lowercase = black. r=chariot n=horse b=elephant a=advisor k=king c=cannon p=pawn.\n"
            + "\n".join(rows) + "\n"
            f"FEN: {state['fen']}\n"
            f"Recent moves: {hist}\n"
            "ALL LEGAL MOVES for you (from-to squares): " + " ".join(legal) + "\n"
            "Pick the strongest move. You MUST pick exactly one move from the legal list above.\n"
            'Respond with ONLY a JSON object: {"move": "<one move from the list>", '
            '"chat": "<one short strategic comment, max 120 chars>"}'
        )

    def parse_ai_move(self, ai_response: str, state: dict, player_id: str) -> Any:
        board, turn = parse_fen(state["fen"])
        legal = set(legal_moves(board, turn))
        text = str(ai_response or "").strip().lower()
        import re as _re

        for cand in _re.findall(r"[a-i][0-9]\s*-?\s*[a-i][0-9]", text):
            uci = _re.sub(r"[\s-]", "", cand)
            if uci in legal:
                return uci
        raise ValueError(f"no legal xiangqi move in response: {text[:80]!r}")

    def render_state_for_ui(self, state: dict) -> dict:
        return {
            "fen": state["fen"],
            "move_history": state.get("move_history", []),
            "captured": state.get("captured", {}),
            "move_count": state.get("move_count", 0),
        }
# ── Lượng giá + tìm kiếm alpha-beta ─────────────────────────────────────────
# User 27/9/2026: «agent đánh dở vậy» → sức cờ phải đến từ TÌM KIẾM, model chỉ còn vai
# bình luận. Negamax + cắt tỉa alpha-beta, sắp nước ăn trước (MVV-LVA), đào sâu dần theo
# ngân sách giờ. Nút trong không lọc «hợp lệ» từng nước (đắt) — thay bằng mẹo chuẩn của
# engine: cho phép ĂN TƯỚNG với điểm thắng tuyệt đối, thế nào để tướng bị ăn/đối mặt tự
# thua ở lớp sau; danh sách nước ở GỐC vẫn là legal_moves chuẩn nên không bao giờ trả
# nước phạm luật.
import time as _time

MATE = 100000
_PVAL = {"k": 10000, "r": 900, "c": 450, "n": 430, "b": 110, "a": 110, "p": 100}


def _pst(color: str, t: str, x: int, y: int) -> int:
    """Điểm vị trí, nhìn từ phía quân `color` (y đã là toạ độ tuyệt đối)."""
    fwd = y if color == "w" else 9 - y            # đi càng sâu càng lớn
    s = 0
    if t == "p":
        if _crossed_river(y, color):
            s += 70 + 12 * (fwd - 5)              # tốt qua sông lớn dần theo độ sâu
            if 2 <= x <= 6:
                s += 10
        else:
            s += 4 * max(0, fwd - 3)
    elif t == "n":
        s += 6 * (4 - max(abs(x - 4), 0)) // 2 + (8 if 2 <= fwd <= 7 else 0)
    elif t == "c":
        s += 8 if x == 4 else 0                   # pháo đầu
        s += 4 if fwd >= 5 else 0
    elif t == "r":
        s += 6 if _crossed_river(y, color) else 0
    return s


def evaluate(board: Board, color: str) -> int:
    """Điểm thế cờ nhìn từ `color` (dương = lợi cho color)."""
    s = 0
    for (x, y), (c, t) in board.items():
        v = _PVAL[t] + _pst(c, t, x, y)
        s += v if c == color else -v
    return s


def _ordered(board: Board, moves):
    """Nước ăn quân to xếp trước — alpha-beta cắt được nhiều nhất khi nước tốt đi đầu."""
    def key(mv):
        cap = board.get(mv[1])
        return -(_PVAL[cap[1]] if cap else 0)
    return sorted(moves, key=key)


class _TimeUp(Exception):
    pass


def _negamax(board: Board, turn: str, depth: int, alpha: int, beta: int, deadline: float) -> int:
    if _time.monotonic() > deadline:
        raise _TimeUp()
    if depth <= 0:
        return evaluate(board, turn)
    moves = _ordered(board, gen_pseudo(board, turn))
    if not moves:
        return -MATE + 1
    best = -MATE - 1
    for frm, to in moves:
        cap = board.get(to)
        if cap and cap[1] == "k":
            return MATE - 1                        # ăn được tướng = thế trước phạm luật/thua
        sc = -_negamax(apply_raw(board, frm, to), "b" if turn == "w" else "w",
                       depth - 1, -beta, -alpha, deadline)
        if sc > best:
            best = sc
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break
    return best


def best_moves(fen: str, top_n: int = 5, budget_s: float = 2.5):
    """[(nước, điểm)] tốt nhất ở GỐC — luôn là nước hợp lệ chuẩn. Đào sâu dần tới khi
    hết giờ; trả kết quả của lớp sâu nhất đã hoàn tất (lớp 1 luôn xong)."""
    board, turn = parse_fen(fen)
    roots = legal_moves(board, turn)
    if not roots:
        return []
    deadline = _time.monotonic() + max(0.3, float(budget_s))
    scored = [(m, 0) for m in roots]
    other = "b" if turn == "w" else "w"
    for depth in range(1, 7):
        cur = []
        alpha = -MATE - 1
        try:
            # Lấy lại thứ tự tốt của lớp trước: nước đầu bảng dò trước, cắt tỉa sâu hơn.
            for m, _ in scored:
                frm = (FILES.index(m[0]), int(m[1]))
                to = (FILES.index(m[2]), int(m[3]))
                sc = -_negamax(apply_raw(board, frm, to), other, depth - 1,
                               -MATE - 1, -alpha, deadline)
                cur.append((m, sc))
                if sc > alpha:
                    alpha = sc
        except _TimeUp:
            break
        cur.sort(key=lambda t: -t[1])
        scored = cur
    return scored[:max(1, int(top_n))]
