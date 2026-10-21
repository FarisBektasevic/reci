"""WER (procenat pogrešnih reči) Whisper vs Scribe na parovima iz ab.jsonl, uz poznate referentne rečenice.

Svaki par se upari sa najsličnijom referencom (difflib); parovi bez dovoljno sličnosti (slobodan diktat) se preskaču.
Normalizacija: mala slova, bez interpunkcije. Brojevi: cifre se ostavljaju (reference su pisane rečima,
pa se „25" vs „dvadeset pet" broji kao greška — isto za oba motora, pa je poređenje fer).

Pokretanje: python ab_wer.py [putanja/do/referenci.txt]   (podrazumevano: ab_reference.txt pored skripte)
"""
import difflib
import json
import os
import re
import sys
from pathlib import Path

AB_LOG = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "reci" / "ab" / "ab.jsonl"
REF_FILE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("ab_reference.txt")


def norm(s: str) -> list[str]:
    s = s.lower().replace("-", " ")
    s = re.sub(r"[^\w\s]", " ", s)
    return s.split()


def wer(ref: list[str], hyp: list[str]) -> tuple[int, int]:
    """(broj grešaka, broj referentnih reči) — Levenshtein nad rečima."""
    d = list(range(len(hyp) + 1))
    for i in range(1, len(ref) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(hyp) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (ref[i - 1] != hyp[j - 1]))
            prev = cur
    return d[len(hyp)], len(ref)


def diff_words(ref: list[str], hyp: list[str]) -> str:
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ref, hyp).get_opcodes():
        if tag == "equal":
            continue
        out.append(f"[{' '.join(ref[i1:i2]) or '∅'} → {' '.join(hyp[j1:j2]) or '∅'}]")
    return " ".join(out)


def main():
    refs = [l.strip() for l in REF_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    refs = [re.sub(r"^\d+\.\s*", "", r) for r in refs]
    pairs = [json.loads(l) for l in AB_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
    tot = {"whisper": [0, 0], "scribe": [0, 0]}
    used = 0
    for p in pairs:
        if p["scribe"].startswith("<greška"):
            continue
        best = max(refs, key=lambda r: difflib.SequenceMatcher(None, norm(r), norm(p["whisper"])).ratio())
        if difflib.SequenceMatcher(None, norm(best), norm(p["whisper"])).ratio() < 0.6:
            continue
        used += 1
        print(f"\n#{used}  {p['ts']}  ({p['secs']} s)\n   REF: {best}")
        for eng in ("whisper", "scribe"):
            e, n = wer(norm(best), norm(p[eng]))
            tot[eng][0] += e
            tot[eng][1] += n
            print(f"   {eng:7s} {e:2d} greš.  {diff_words(norm(best), norm(p[eng]))}")
    print(f"\n{'=' * 60}\nUpareno sa referencom: {used} od {len(pairs)} parova")
    for eng, (e, n) in tot.items():
        print(f"  {eng:8s} WER = {e / n:.1%}   ({e} grešaka na {n} reči)" if n else f"  {eng}: nema podataka")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
