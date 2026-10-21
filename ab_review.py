"""Ocenjivanje A/B parova (Whisper vs Scribe) koje je Reci sačuvao u %LOCALAPPDATA%\\reci\\ab\\.

Prikazuje dva teksta bez oznake ko je ko (strane nasumične), dugme za preslušavanje snimka,
i tri izbora: levi bolji / isti / desni bolji. Glasovi idu u ab_votes.jsonl; na kraju rezime.

Pokretanje: python ab_review.py
"""
import json
import os
import random
import tkinter as tk
import winsound
from pathlib import Path

AB_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "reci" / "ab"
AB_LOG, VOTES = AB_DIR / "ab.jsonl", AB_DIR / "ab_votes.jsonl"


def load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def summary(votes: list[dict]) -> str:
    n = len(votes)
    if not n:
        return "Još nema ocena."
    w = sum(1 for v in votes if v["better"] == "whisper")
    s = sum(1 for v in votes if v["better"] == "scribe")
    t = n - w - s
    return (f"Ocenjeno: {n}\n\nWhisper bolji: {w}  ({w / n:.0%})\nScribe bolji:  {s}  ({s / n:.0%})\n"
            f"Isti:          {t}  ({t / n:.0%})\n\n"
            + ("Scribe vodi." if s > w else "Whisper vodi." if w > s else "Nerešeno."))


class Review:
    def __init__(self):
        voted = {v["ts"] for v in load_jsonl(VOTES)}
        self.pairs = [p for p in load_jsonl(AB_LOG)
                      if p["ts"] not in voted and not p["scribe"].startswith("<greška")]
        self.i = 0
        self.root = tk.Tk()
        self.root.title("Reci — A/B ocenjivanje")
        self.root.configure(bg="#1c1c1e")
        self.root.geometry("820x420")
        f = ("Segoe UI", 12)
        self.head = tk.Label(self.root, fg="#9a9a9e", bg="#1c1c1e", font=("Segoe UI", 10))
        self.head.pack(pady=(12, 4))
        row = tk.Frame(self.root, bg="#1c1c1e")
        row.pack(fill="both", expand=True, padx=16)
        self.left = tk.Label(row, fg="#f2f2f2", bg="#2c2c2e", font=f, wraplength=370, justify="left", padx=14, pady=14)
        self.right = tk.Label(row, fg="#f2f2f2", bg="#2c2c2e", font=f, wraplength=370, justify="left", padx=14, pady=14)
        self.left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self.right.pack(side="left", fill="both", expand=True, padx=(6, 0))
        btns = tk.Frame(self.root, bg="#1c1c1e")
        btns.pack(pady=14)
        for txt, cmd in (("◀ Levi bolji  (1)", lambda: self.vote("L")), ("Isti  (2)", lambda: self.vote("T")),
                         ("Desni bolji ▶  (3)", lambda: self.vote("R")), ("▶ Pusti snimak  (razmak)", self.play)):
            tk.Button(btns, text=txt, command=cmd, font=("Segoe UI", 11), bg="#3a3a3c", fg="white",
                      activebackground="#5a5a5c", relief="flat", padx=14, pady=6).pack(side="left", padx=6)
        self.root.bind("1", lambda e: self.vote("L"))
        self.root.bind("2", lambda e: self.vote("T"))
        self.root.bind("3", lambda e: self.vote("R"))
        self.root.bind("<space>", lambda e: self.play())
        self.show()

    def show(self):
        if self.i >= len(self.pairs):
            self.left.config(text=summary(load_jsonl(VOTES)))
            self.right.config(text="Nema više parova za ocenu.\n\nZatvorite prozor.")
            self.head.config(text="Rezime")
            return
        p = self.pairs[self.i]
        self.flip = random.random() < 0.5          # True = levo je Scribe
        a, b = (p["scribe"], p["whisper"]) if self.flip else (p["whisper"], p["scribe"])
        self.left.config(text=a or "(prazno)")
        self.right.config(text=b or "(prazno)")
        self.head.config(text=f"{self.i + 1} / {len(self.pairs)}   ·   {p['ts']}   ·   {p['secs']} s")

    def play(self):
        if self.i < len(self.pairs):
            winsound.PlaySound(str(AB_DIR / self.pairs[self.i]["wav"]), winsound.SND_FILENAME | winsound.SND_ASYNC)

    def vote(self, side: str):
        if self.i >= len(self.pairs):
            return
        p = self.pairs[self.i]
        if side == "T":
            better = "tie"
        else:
            left_engine = "scribe" if self.flip else "whisper"
            right_engine = "whisper" if self.flip else "scribe"
            better = left_engine if side == "L" else right_engine
        with VOTES.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": p["ts"], "better": better}, ensure_ascii=False) + "\n")
        self.i += 1
        self.show()


if __name__ == "__main__":
    Review().root.mainloop()
