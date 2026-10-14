"""German translation of the coach's generated sentences.

The coach builds its explanations from a fixed set of English sentence templates
(review.py / coach.py). This module maps each template to German, including the
right article for the piece (deinen Springer / deine Dame / den Bauern), and
switches move notation to German letters (S, L, T, D, K).
"""
import re

# nominative, accusative, gender
PIECES = {
    "pawn": ("Bauer", "Bauern", "m"), "knight": ("Springer", "Springer", "m"), "bishop": ("Läufer", "Läufer", "m"),
    "rook": ("Turm", "Turm", "m"), "queen": ("Dame", "Dame", "f"), "king": ("König", "König", "m"),
}
PHASES = {"opening": "die Eröffnung", "middlegame": "das Mittelspiel", "endgame": "das Endspiel"}
SAN_DE = {"K": "K", "Q": "D", "R": "T", "B": "L", "N": "S"}

P = r"(?P<p>pawn|knight|bishop|rook|queen|king)"
SQ = r"(?P<sq>[a-h][1-8])"
SAN = r"(?P<san>[A-Za-z0-9+#=\-]+)"
SAN2 = r"(?P<san2>[A-Za-z0-9+#=\-]+)"
CHK = r"(?P<chk> with check)?"


def acc(m):
    return PIECES[m["p"]][1]


def nom(m):
    return PIECES[m["p"]][0]


def fem(m):
    return PIECES[m["p"]][2] == "f"


def poss(m, base, case):          # dein/deine/deinen, mein/meine/meinen
    if fem(m):
        return base + "e"
    return base + ("en" if case == "acc" else "")


def art(m):                        # den / die (accusative)
    return "die" if fem(m) else "den"


def adj(m):                        # gegnerischen / gegnerische (after den/die)
    return "gegnerische" if fem(m) else "gegnerischen"


def chk(m):
    return " mit Schach" if m["chk"] else ""


RULES = [
    # --- why a move was bad (coach.py explain) ---
    (rf"This let your opponent take your {P} with {SAN}\.",
     lambda m: f"Dadurch konnte dein Gegner {poss(m, 'dein', 'acc')} {acc(m)} mit {m['san']} schlagen."),
    (r"This allowed checkmate in one!", lambda m: "Das hat ein Matt in einem Zug erlaubt!"),
    (rf"You missed checkmate with {SAN}!", lambda m: f"Du hast das Matt mit {m['san']} verpasst!"),
    (rf"{SAN} would have won the {P}\.", lambda m: f"{m['san']} hätte {art(m)} {acc(m)} gewonnen."),
    (rf"Look at checks first: {SAN} was strong\.", lambda m: f"Schau zuerst nach Schachgeboten: {m['san']} war stark."),
    (rf"{SAN} kept a better position\.", lambda m: f"Mit {m['san']} wäre deine Stellung besser geblieben."),
    # --- strategy (strategy.py) ---
    (rf"Your {P} on {SQ} was under attack – {SAN} deals with that\.",
     lambda m: f"{poss(m, 'Dein', 'nom')} {nom(m)} auf {m['sq']} wurde angegriffen – {m['san']} kümmert sich darum."),
    (rf"{SAN} would have castled your king into safety\.", lambda m: f"Mit {m['san']} hättest du rochiert und deinen König in Sicherheit gebracht."),
    (r"Moving your king loses the right to castle – your king stays stuck in the middle\.",
     lambda m: "Mit dem Königszug verlierst du das Rochaderecht – dein König bleibt in der Mitte stecken."),
    (r"Bringing the queen out early lets your opponent attack it and gain time\.",
     lambda m: "Wenn die Dame zu früh rauskommt, kann dein Gegner sie angreifen und dabei Zeit gewinnen."),
    (rf"{SAN} develops a new piece – in the opening, get your knights and bishops out first\.",
     lambda m: f"{m['san']} entwickelt eine neue Figur – in der Eröffnung zuerst Springer und Läufer rausbringen."),
    (rf"{SAN} gives you doubled pawns, which are weak\. {SAN2} keeps your pawns healthy\.",
     lambda m: f"{m['san']} gibt dir Doppelbauern, und die sind schwach. {m['san2']} hält deine Bauernstruktur gesund."),
    (rf"{SAN} leaves you with an isolated pawn that is hard to defend\.", lambda m: f"{m['san']} hinterlässt dir einen isolierten Bauern, der schwer zu verteidigen ist."),
    (rf"{SAN} fights for the center\.", lambda m: f"{m['san']} kämpft ums Zentrum."),
    (rf"{SAN} puts your rook on an open file, where it is much more active\.", lambda m: f"{m['san']} stellt deinen Turm auf eine offene Linie, dort ist er viel aktiver."),
    (rf"{SAN} pushes your passed pawn – in the endgame, passed pawns must be pushed!",
     lambda m: f"{m['san']} schiebt deinen Freibauern – im Endspiel gehören Freibauern nach vorne!"),
    (rf"{SAN} makes your pieces more active\.", lambda m: f"{m['san']} macht deine Figuren aktiver."),
    # --- tactics (tactic_notes / bot moves) ---
    (rf"Now your opponent has a checkmating attack starting with {SAN}\.", lambda m: f"Jetzt hat dein Gegner einen Mattangriff, beginnend mit {m['san']}."),
    (rf"This allows a back-rank mate starting with {SAN} – your king has no escape square\.",
     lambda m: f"Das erlaubt ein Grundreihenmatt, beginnend mit {m['san']} – dein König hat kein Fluchtfeld."),
    (rf"This allows a double check with {SAN}\.", lambda m: f"Das erlaubt ein Doppelschach mit {m['san']}."),
    (rf"This allows a discovered attack with {SAN}\.", lambda m: f"Das erlaubt einen Abzugsangriff mit {m['san']}."),
    (rf"This allows a fork: {SAN} attacks two of your pieces at once\.", lambda m: f"Das erlaubt eine Gabel: {m['san']} greift zwei deiner Figuren gleichzeitig an."),
    (rf"This allows a skewer with {SAN}\.", lambda m: f"Das erlaubt einen Spieß mit {m['san']}."),
    (rf"This walks into a pin: {SAN}\.", lambda m: f"Damit läufst du in eine Fesselung: {m['san']}."),
    (rf"This lets your opponent promote a pawn with {SAN}\.", lambda m: f"Damit kann dein Gegner mit {m['san']} einen Bauern umwandeln."),
    (rf"You missed a back-rank mate starting with {SAN}!", lambda m: f"Du hast ein Grundreihenmatt verpasst, beginnend mit {m['san']}!"),
    (rf"You missed a double check with {SAN}!", lambda m: f"Du hast ein Doppelschach mit {m['san']} verpasst!"),
    (rf"You missed a discovered attack with {SAN}\.", lambda m: f"Du hast einen Abzugsangriff mit {m['san']} verpasst."),
    (rf"You missed a fork: {SAN} attacks two pieces at once\.", lambda m: f"Du hast eine Gabel verpasst: {m['san']} greift zwei Figuren gleichzeitig an."),
    (rf"You missed a skewer with {SAN}\.", lambda m: f"Du hast einen Spieß mit {m['san']} verpasst."),
    (rf"You missed a pin with {SAN}\.", lambda m: f"Du hast eine Fesselung mit {m['san']} verpasst."),
    (rf"You missed promoting with {SAN}\.", lambda m: f"Du hast die Umwandlung mit {m['san']} verpasst."),
    (r"Nice fork!", lambda m: "Schöne Gabel!"), (r"Nice pin!", lambda m: "Schöne Fesselung!"), (r"Nice skewer!", lambda m: "Schöner Spieß!"),
    (r"Nice discovered attack!", lambda m: "Schöner Abzugsangriff!"), (r"Nice double check!", lambda m: "Schönes Doppelschach!"),
    (r"A fork!", lambda m: "Eine Gabel!"), (r"A pin!", lambda m: "Eine Fesselung!"), (r"A skewer!", lambda m: "Ein Spieß!"),
    (r"A discovered attack!", lambda m: "Ein Abzugsangriff!"), (r"Double check!", lambda m: "Doppelschach!"),
    # --- move verdicts (coach_text) ---
    (rf"{SAN} is checkmate! Well played\.", lambda m: f"{m['san']} ist Schachmatt! Gut gespielt."),
    (rf"{SAN} is brilliant! You sacrificed your {P} and your position is still great\.",
     lambda m: f"{m['san']} ist brillant! Du hast {poss(m, 'dein', 'acc')} {acc(m)} geopfert, und deine Stellung ist immer noch super."),
    (rf"{SAN} is a great move – the only move that keeps your position\.",
     lambda m: f"{m['san']} ist ein großartiger Zug – der einzige, der deine Stellung hält."),
    (rf"{SAN} is the best move\.", lambda m: f"{m['san']} ist der beste Zug."),
    (rf"{SAN} is a known opening move\.", lambda m: f"{m['san']} ist ein bekannter Eröffnungszug."),
    (r"This is the (?P<o>.+?)\.(?= [A-Z(]|$)", lambda m: f"Eröffnung: {m['o']}."),
    (rf"{SAN} is excellent\. The engine slightly prefers {SAN2}\.",
     lambda m: f"{m['san']} ist exzellent. Die Engine bevorzugt knapp {m['san2']}."),
    (rf"{SAN} is good, but {SAN2} was better\.", lambda m: f"{m['san']} ist gut, aber {m['san2']} war besser."),
    (rf"{SAN} is an inaccuracy\. Best was {SAN2}\.", lambda m: f"{m['san']} ist eine Ungenauigkeit. Am besten war {m['san2']}."),
    (rf"{SAN} is a mistake\. Best was {SAN2}\.", lambda m: f"{m['san']} ist ein Fehler. Am besten war {m['san2']}."),
    (rf"{SAN} is a blunder\. Best was {SAN2}\.", lambda m: f"{m['san']} ist ein Patzer. Am besten war {m['san2']}."),
    (rf"{SAN} misses a chance! Your opponent just made a mistake and {SAN2} would punish it\.",
     lambda m: f"{m['san']} verpasst eine Chance! Dein Gegner hat gerade einen Fehler gemacht, und {m['san2']} hätte das bestraft."),
    (r"\(Here the game left the known opening lines of the opening\.\)",
     lambda m: "(Hier verlässt die Partie die bekannte Eröffnungstheorie.)"),
    (r"\(Here the game left the known opening lines of the (?P<o>.+?)\.\)",
     lambda m: f"(Hier verlässt die Partie die bekannte Theorie: {m['o']}.)"),
    (r"Your opponent now has mate in (?P<n>\d+)\.", lambda m: f"Dein Gegner hat jetzt Matt in {m['n']}."),
    (r"You have mate in (?P<n>\d+)!", lambda m: f"Du hast Matt in {m['n']}!"),
    # --- ideas behind a move (move_idea) ---
    (r"Castling puts your king in safety and connects your rooks\.",
     lambda m: "Die Rochade bringt deinen König in Sicherheit und verbindet deine Türme."),
    (rf"This takes the {P} on {SQ}{CHK}\.", lambda m: f"Damit wird {art(m)} {acc(m)} auf {m['sq']} geschlagen{chk(m)}."),
    (r"This pawn takes space in the center and fights for the important squares\.",
     lambda m: "Dieser Bauer nimmt Raum im Zentrum und kämpft um die wichtigen Felder."),
    (r"This pawn supports the fight for the center\.", lambda m: "Dieser Bauer unterstützt den Kampf ums Zentrum."),
    (r"This prepares a fianchetto: the bishop can now go to the long diagonal\.",
     lambda m: "Das bereitet ein Fianchetto vor: Der Läufer kann jetzt auf die lange Diagonale."),
    (rf"A small useful move that stops enemy pieces from using {SQ}\.",
     lambda m: f"Ein kleiner, nützlicher Zug, der gegnerischen Figuren das Feld {m['sq']} nimmt."),
    (r"This pawn move opens lines for (?P<w>your|my) pieces\.",
     lambda m: f"Dieser Bauernzug öffnet Linien für {'deine' if m['w'] == 'your' else 'meine'} Figuren."),
    (rf"This develops your {P} to {SQ}{CHK} – get all pieces out before attacking\.",
     lambda m: f"Damit entwickelst du {poss(m, 'dein', 'acc')} {acc(m)} nach {m['sq']}{chk(m)} – bring erst alle Figuren ins Spiel, bevor du angreifst."),
    (rf"This develops my {P} to {SQ}{CHK} – get all pieces out before attacking\.",
     lambda m: f"Damit entwickle ich {poss(m, 'mein', 'acc')} {acc(m)} nach {m['sq']}{chk(m)} – erst alle Figuren ins Spiel bringen, dann angreifen."),
    (rf"(?P<w>Your|My) {P} moves to a more active square{CHK}\.",
     lambda m: f"{poss(m, 'Dein' if m['w'] == 'Your' else 'Mein', 'nom')} {nom(m)} geht auf ein aktiveres Feld{chk(m)}."),
    (rf"The queen comes out{CHK}\. Careful: an early queen can become a target\.",
     lambda m: f"Die Dame kommt heraus{chk(m)}. Vorsicht: Eine frühe Dame kann zur Zielscheibe werden."),
    # --- the coach's own moves and hints (move_reasons) ---
    (r"I castle to bring my king to safety and connect my rooks\.",
     lambda m: "Ich rochiere, um meinen König in Sicherheit zu bringen und meine Türme zu verbinden."),
    (r"You can castle to bring your king to safety and connect your rooks\.",
     lambda m: "Du kannst rochieren, um deinen König in Sicherheit zu bringen und deine Türme zu verbinden."),
    (rf"I take your {P} on {SQ}(?P<safe> – and it can't be taken back!|\.)",
     lambda m: f"Ich schlage {poss(m, 'dein', 'acc')} {acc(m)} auf {m['sq']}" + (" – und du kannst nicht zurückschlagen!" if m["safe"] != "." else ".")),
    (rf"You can take their {P} on {SQ}(?P<safe> – and it can't be taken back!|\.)",
     lambda m: f"Du kannst {art(m)} {adj(m)} {acc(m)} auf {m['sq']} schlagen" + (" – und es kann nicht zurückgeschlagen werden!" if m["safe"] != "." else ".")),
    (rf"My {P} was under attack, so it moves to safety\.",
     lambda m: f"{poss(m, 'Mein', 'nom')} {nom(m)} wurde angegriffen, also bringe ich {'sie' if fem(m) else 'ihn'} in Sicherheit."),
    (rf"Your {P} is under attack – move it to safety\.",
     lambda m: f"{poss(m, 'Dein', 'nom')} {nom(m)} wird angegriffen – bring {'sie' if fem(m) else 'ihn'} in Sicherheit."),
    (r"Check! Your king has to deal with that first\.", lambda m: "Schach! Dein König muss sich zuerst darum kümmern."),
    (r"Check! That forces their king to react\.", lambda m: "Schach! Der gegnerische König muss reagieren."),
    (rf"Now I'm attacking your {P} on {SQ}(?P<u> – and it isn't protected!|\.)",
     lambda m: f"Jetzt greife ich {poss(m, 'dein', 'acc')} {acc(m)} auf {m['sq']} an" + (f" – und {'sie' if fem(m) else 'er'} ist nicht gedeckt!" if m["u"] != "." else ".")),
    (rf"Now you'd be attacking their {P} on {SQ}(?P<u> – and it isn't protected!|\.)",
     lambda m: f"Dann greifst du {art(m)} {adj(m)} {acc(m)} auf {m['sq']} an" + (f" – und {'sie' if fem(m) else 'er'} ist nicht gedeckt!" if m["u"] != "." else ".")),
    (rf"I stop your threat: {SAN} would have been checkmate!", lambda m: f"Ich verhindere deine Drohung: {m['san']} wäre Schachmatt gewesen!"),
    (rf"Stop their threat: {SAN} would have been checkmate!", lambda m: f"Verhindere die gegnerische Drohung: {m['san']} wäre Schachmatt gewesen!"),
    (rf"I protect my {P} on {SQ}\.", lambda m: f"Ich decke {poss(m, 'mein', 'acc')} {acc(m)} auf {m['sq']}."),
    (rf"Protect your {P} on {SQ}\.", lambda m: f"Decke {poss(m, 'dein', 'acc')} {acc(m)} auf {m['sq']}."),
    (rf"I improve my {P} on {SQ}\.", lambda m: f"Ich verbessere {poss(m, 'mein', 'acc')} {acc(m)} auf {m['sq']}."),
    (rf"Improve your {P}\.", lambda m: f"Verbessere {poss(m, 'dein', 'acc')} {acc(m)}."),
    (r"(?<![a-z] )Checkmate!", lambda m: "Schachmatt!"),
    (r"A known opening move – we're now in the (?P<o>.+?)\.(?= [A-Z🤫]|$)", lambda m: f"Ein bekannter Eröffnungszug – wir sind jetzt in: {m['o']}."),
    (r"A known opening move\.", lambda m: "Ein bekannter Eröffnungszug."),
    (rf"My plan: next I'd like to play {SAN}\.", lambda m: f"Mein Plan: Als Nächstes möchte ich {m['san']} spielen."),
    (r"🤫 Psst – this move is actually a mistake\. Can you find a way to punish it\?",
     lambda m: "🤫 Psst – dieser Zug ist eigentlich ein Fehler. Findest du einen Weg, ihn zu bestrafen?"),
    # --- game summary ---
    (r"You played with (?P<a>[\d.]+)% accuracy \(your opponent: (?P<b>[\d.]+)%\)\.",
     lambda m: f"Du hast mit {m['a']}% Genauigkeit gespielt (dein Gegner: {m['b']}%)."),
    (r"Opening: (?P<o>.+?) – the game left the known lines on move (?P<n>\d+)\.",
     lambda m: f"Eröffnung: {m['o']} – ab Zug {m['n']} hat die Partie die bekannte Theorie verlassen."),
    (r"Your best phase was the (?P<a>opening|middlegame|endgame) \((?P<va>[\d.]+)%\), your weakest the (?P<b>opening|middlegame|endgame) \((?P<vb>[\d.]+)%\)\.",
     lambda m: f"Deine beste Phase war {PHASES[m['a']]} ({m['va']}%), deine schwächste {PHASES[m['b']]} ({m['vb']}%)."),
    (r"No mistakes or blunders – great game!", lambda m: "Keine Fehler oder Patzer – tolle Partie!"),
    (r"You made (?P<a>\d+) blunder\(s\), (?P<b>\d+) mistake\(s\) and (?P<c>\d+) missed chance\(s\)\.",
     lambda m: f"Du hattest {m['a']} Patzer, {m['b']} Fehler und {m['c']} verpasste Chance(n)."),
    (rf"The biggest turning point was move (?P<n>\d+): {SAN} \(best was {SAN2}\)\. Use “Retry” on your mistakes to practice\.",
     lambda m: f"Der größte Wendepunkt war Zug {m['n']}: {m['san']} (am besten war {m['san2']}). Übe deine Fehler mit „Nochmal versuchen“."),
    (r"You found (?P<n>\d+) brilliant move\(s\)! 💎", lambda m: f"Du hast {m['n']} brillante(n) Zug/Züge gefunden! 💎"),
]
RULES = [(re.compile(p), f) for p, f in RULES]
SAN_RE = re.compile(r"\b([KQRBN])(?=[a-h]?[1-8]?x?[a-h][1-8])")


def german_san(text):
    text = SAN_RE.sub(lambda m: SAN_DE[m[1]], text)
    return re.sub(r"=([QRBN])", lambda m: "=" + SAN_DE[m[1]], text)


def to_german(text):
    if not text:
        return text
    for rx, fn in RULES:
        text = rx.sub(fn, text)
    text = re.sub(r"(\d)\.(\d)", r"\1,\2", text)          # 90.1% -> 90,1%
    return german_san(text)
