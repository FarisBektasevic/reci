"""Reci — diktat na srpskom. Drži DESNI CTRL dok pričaš, pusti ga i tekst se nalepi gde je kursor.

Radi u pozadini (pythonw, bez prozora), kao Windows Win+H: dok snima i prepoznaje,
na dnu ekrana stoji mala traka koja ne krade fokus.

Tok:  desni Ctrl ↓ → mikrofon → desni Ctrl ↑ → Whisper (Groq) → rečnik → lektor (Groq) → ćirilica→latinica → Ctrl+V

Prepoznavanje ide preko interneta (računar se ne opterećuje):
  - Groq Whisper large-v3 + lektor (qwen) — ako postoji GROQ_API_KEY (env, .env pored programa, %LOCALAPPDATA%\\reci\\.env)
  - Google Web Speech (besplatno, bez naloga) — rezerva ako Groq-a nema ili zakaže

Pri prvom pokretanju pita za Groq ključ (može i bez) i da li da se pali sa Windowsom.
Pokretanje: Reci.exe ili start.bat. Gašenje: ugasi.bat. Log: %LOCALAPPDATA%\\reci\\reci.log
Detalji: README.md
"""
import ctypes
import io
import logging
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
import wave
import winsound
from pathlib import Path

import numpy as np
import pyperclip
import sounddevice as sd

HOLD_KEY = "right ctrl"    # drži dok pričaš (voki-toki)
VK_HOLD = 0xA3             # VK_RCONTROL
POLL_S = 0.025             # koliko često se pita Windows „je li desni Ctrl pritisnut?”
SAMPLE_RATE = 16000
MIN_SECONDS = 0.6          # kraće = slučajan pritisak, tiho se odbacuje
MAX_SECONDS = 180          # automatski stop posle 3 minuta
GOOGLE_CHUNK_MAX_S = 50    # Google prima kratke snimke — duže se seče na tišini
GOOGLE_CHUNK_MIN_S = 35

FROZEN = getattr(sys, "frozen", False)                      # True kad radi kao Reci.exe (PyInstaller)
HERE = Path(sys.executable if FROZEN else __file__).resolve().parent
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "reci"
ENV_FILES = [HERE / ".env", DATA_DIR / ".env"]
RECNIK_FILES = [HERE / "recnik.txt", DATA_DIR / "recnik.txt"]      # oba se primenjuju ako postoje
POJMOVI_FILES = [HERE / "pojmovi.txt", DATA_DIR / "pojmovi.txt"]   # lični pojmovi/žargon za Whisper
LOG_FILE = DATA_DIR / "reci.log"
log = logging.getLogger("reci")

CYR_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ђ": "đ", "е": "e", "ж": "ž",
    "з": "z", "и": "i", "ј": "j", "к": "k", "л": "l", "љ": "lj", "м": "m", "н": "n",
    "њ": "nj", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "ћ": "ć", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "č", "џ": "dž", "ш": "š",
}
CYR_TO_LAT.update({k.upper(): v.capitalize() for k, v in CYR_TO_LAT.items()})


def to_latin(text: str) -> str:
    return "".join(CYR_TO_LAT.get(ch, ch) for ch in text)


def load_groq_key() -> str | None:
    if os.environ.get("GROQ_API_KEY"):
        return os.environ["GROQ_API_KEY"].strip()
    for env in ENV_FILES:
        if not env.exists():
            continue
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("GROQ_API_KEY="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val:
                    return val
    return None


def read_lines(files: list[Path]) -> list[str]:
    """Neprazni redovi bez # komentara iz svih postojećih fajlova."""
    out = []
    for f in files:
        if f.exists():
            out += [l.strip() for l in f.read_text(encoding="utf-8").splitlines()
                    if l.strip() and not l.strip().startswith("#")]
    return out


# --- tastatura bez hook-a ---------------------------------------------------------
# Namerno NEMA globalnog keyboard hook-a (keylogger mehanizam). Program samo pita Windows
# „je li desni Ctrl trenutno pritisnut?" (GetAsyncKeyState za JEDAN taster) i ne dobija
# nikakvu informaciju o ostalim tasterima — osim dok se desni Ctrl drži, kad proveri da li
# je pritisnut još neki taster (desni Ctrl + C = obična prečica, otkaz diktata).

_user32 = ctypes.windll.user32
_CTRL_VKS = {0x11, 0xA2, 0xA3}      # VK_CONTROL, VK_LCONTROL, VK_RCONTROL


def key_down(vk: int) -> bool:
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)


def other_key_down() -> bool:
    return any(key_down(vk) for vk in range(0x08, 0x100) if vk not in _CTRL_VKS)


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("pad", ctypes.c_ubyte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _U)]


def send_ctrl_v():
    """Ctrl+V kroz SendInput (levi Ctrl, da ne dira stanje desnog koji korisnik možda još drži)."""
    KEYUP, VK_LCONTROL, VK_V = 0x0002, 0xA2, 0x56
    seq = [(VK_LCONTROL, 0), (VK_V, 0), (VK_V, KEYUP), (VK_LCONTROL, KEYUP)]
    arr = (_INPUT * len(seq))()
    for i, (vk, flags) in enumerate(seq):
        arr[i].type = 1  # INPUT_KEYBOARD
        arr[i].ki = _KEYBDINPUT(vk, 0, flags, 0, None)
    _user32.SendInput(len(seq), arr, ctypes.sizeof(_INPUT))


# --- prvo pokretanje -------------------------------------------------------------

def startup_shortcut() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup/Reci.lnk"


def set_autostart(on: bool):
    import subprocess
    lnk = startup_shortcut()
    if not on:
        lnk.unlink(missing_ok=True)
        return
    if FROZEN:
        target, args = str(sys.executable), ""
    else:
        target = str(Path(sys.executable).with_name("pythonw.exe"))
        args = f'"{Path(__file__).resolve()}"'
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
          f"$s.TargetPath='{target}';$s.Arguments='{args}';$s.WorkingDirectory='{HERE}';"
          f"$s.Description='Reci - diktat na srpskom (drzi desni Ctrl)';$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)


def first_run_setup(root: tk.Tk):
    """Ako nema ključa ni .env-a: pita za Groq ključ (može prazno) i za autostart. Jednom."""
    if load_groq_key() or any(f.exists() for f in ENV_FILES):
        return
    from tkinter import messagebox, simpledialog
    key = simpledialog.askstring(
        "Reci — podešavanje",
        "Groq API ključ (besplatno na console.groq.com → API Keys).\n"
        "Daje bolje prepoznavanje srpskog, interpunkciju i lektora.\n\n"
        "Ostavite prazno za rad preko Google-a (slabije, bez interpunkcije).",
        parent=root, show="*") or ""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / ".env").write_text(f"GROQ_API_KEY={key.strip()}\n", encoding="utf-8")
    if messagebox.askyesno("Reci — podešavanje",
                           "Da li da se Reci pokreće sam kad se uključi računar?", parent=root):
        set_autostart(True)


def to_wav(samples: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(samples.tobytes())
    return buf.getvalue()


def split_on_silence(samples: np.ndarray) -> list[np.ndarray]:
    """Seče snimak na delove do GOOGLE_CHUNK_MAX_S, rez na najtišem mestu (da ne preseče reč)."""
    chunks, max_n, min_n = [], GOOGLE_CHUNK_MAX_S * SAMPLE_RATE, GOOGLE_CHUNK_MIN_S * SAMPLE_RATE
    win = SAMPLE_RATE // 4
    while len(samples) > max_n:
        region = samples[min_n:max_n].astype(np.float32)
        n_win = len(region) // win
        energy = (region[: n_win * win].reshape(n_win, win) ** 2).mean(axis=1)
        cut = min_n + int(energy.argmin()) * win + win // 2
        chunks.append(samples[:cut])
        samples = samples[cut:]
    chunks.append(samples)
    return chunks


def transcribe_google(samples: np.ndarray) -> str:
    import speech_recognition as sr
    rec = sr.Recognizer()
    parts = []
    for chunk in split_on_silence(samples):
        audio = sr.AudioData(chunk.tobytes(), SAMPLE_RATE, 2)
        try:
            parts.append(rec.recognize_google(audio, language="sr-RS"))
        except sr.UnknownValueError:
            pass
    return " ".join(parts)


# --- Groq: Whisper + lektor --------------------------------------------------

WHISPER_PROMPT_BASE = (
    "Diktat na srpskom jeziku, latinica, ekavica, opušten govorni stil. "
    "Žargon: skontati, skontaš, provaliti, fol, okej, kul, zezati, sredi, šta ima."
)


def whisper_prompt() -> str:
    """Osnovni kontekst + lični pojmovi iz pojmovi.txt (imena, brendovi, stručni izrazi) — čita se pri svakom pozivu."""
    pojmovi = ", ".join(read_lines(POJMOVI_FILES))
    return WHISPER_PROMPT_BASE + (f" Pojmovi: {pojmovi}." if pojmovi else "")


LEKTOR_MODEL = "qwen/qwen3.8-27b"   # brz (~0.3s), drži ekavicu; llama-3.3 više nije na Groq-u
LEKTOR_PROMPT = (
    "Ti si lektor za srpski jezik (latinica, ekavica). Dobijaš tekst nastao prepoznavanjem govora. "
    "Ispravi SAMO očigledne greške prepoznavanja: pogrešan padež imenice ili prideva (npr. 'sa oba sajtova' → "
    "'sa oba sajta', 'u sat vremene' → 'u sat vremena'), pogrešno spojene ili rastavljene reči, i interpunkciju. "
    "NE menjaj lice, broj ni vreme glagola (ko šta radi — 'govori', 'skontaš', 'pogreši' ostaju kako jesu). "
    "NE menjaj smisao, NE dodaj i NE izbacuj rečenice, NE prepričavaj, NE menjaj stil ni redosled misli. "
    "Ako nisi siguran da je nešto greška, OSTAVI kako jeste — bolje je propustiti grešku nego promeniti smisao. "
    "NE prevodi i NE menjaj strane nazive, imena brendova, programa i skraćenice (ostaju kako su izgovoreni). "
    "Govor je opušten i žargonske reči (skontati, provaliti, fol, okej, zezati) su NAMERNE — ostavi ih. "
    "Ne menjaj 'je li' u 'da li'. "
    "Ako je tekst već ispravan, vrati ga nepromenjenog. Odgovori isključivo ispravljenim tekstom, bez objašnjenja."
)


def transcribe_groq(samples: np.ndarray, key: str) -> str:
    import requests
    r = requests.post(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {key}"},
        files={"file": ("reci.wav", to_wav(samples), "audio/wav")},
        data={"model": "whisper-large-v3", "language": "sr", "response_format": "json",
              "prompt": whisper_prompt()},
        timeout=60,
    )
    r.raise_for_status()
    return r.json().get("text", "")


def lektor_groq(text: str, key: str) -> str:
    """Ispravlja padeže/slaganje bez promene smisla. Pri grešci vraća original."""
    import requests
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": LEKTOR_MODEL, "temperature": 0, "max_tokens": 2000,
                  "messages": [{"role": "system", "content": LEKTOR_PROMPT},
                               {"role": "user", "content": text}]},
            timeout=20,
        )
        r.raise_for_status()
        fixed = r.json()["choices"][0]["message"]["content"].strip().strip('"')
    except Exception:
        log.exception("Lektor nije uspeo, šaljem neispravljen tekst")
        return text
    # zaštita od prepričavanja: ako se dužina drastično promeni, veruj originalu
    if not fixed or not 0.6 < len(fixed) / max(len(text), 1) < 1.5:
        log.warning("Lektor promenio dužinu previše (%d→%d), ignorišem", len(text), len(fixed))
        return text
    return fixed


# --- rečnik ---------------------------------------------------------------------

def load_recnik() -> list[tuple[re.Pattern, str]]:
    """Čita recnik.txt pri svakom pozivu — izmene važe odmah, bez restarta."""
    pairs = []
    for line in read_lines(RECNIK_FILES):
        if "=" not in line:
            continue
        wrong, right = (s.strip() for s in line.split("=", 1))
        if wrong and right:
            pairs.append((re.compile(rf"(?<!\w){re.escape(wrong)}(?!\w)", re.IGNORECASE), right))
    return pairs


def apply_recnik(text: str) -> str:
    for pattern, right in load_recnik():
        text = pattern.sub(right, text)
    return text


# --- UI ------------------------------------------------------------------------

class Indicator:
    """Pilula na dnu ekrana, u stilu Win+H: ikonica mikrofona, tekst, trakice jačine glasa.

    Stanja: info (zelena), listening (crvena tačka pulsira + trakice), processing (tri tačke), error (crveno).
    Ne uzima fokus (WS_EX_NOACTIVATE) — paste ide u prozor gde je kursor.
    Thread-safe: show()/hide()/set_level() mogu iz bilo kog threada, tk crta samo u glavnom.
    """
    W, H, R = 340, 64, 32                 # pilula: širina, visina, radijus
    BG, BORDER, TRANSPARENT = "#1c1c1e", "#3a3a3c", "#010203"
    TXT, SUB = "#f2f2f2", "#9a9a9e"
    COL = {"info": "#34c759", "listening": "#ff453a", "processing": "#5ac8fa", "error": "#ff453a"}
    OFFSCREEN = "+-3000+-3000"

    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", self.TRANSPARENT)   # zaobljeni uglovi
        self.root.configure(bg=self.TRANSPARENT)
        self.root.geometry(self.OFFSCREEN)
        self.c = tk.Canvas(self.root, width=self.W, height=self.H, bg=self.TRANSPARENT,
                           highlightthickness=0, bd=0)
        self.c.pack()
        self.root.update_idletasks()
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(self.root.winfo_id())
        GWL_EXSTYLE, WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = -20, 0x8, 0x80, 0x08000000
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        self.q: queue.Queue = queue.Queue()
        self.hide_job = None
        self.state, self.text, self.sub = "info", "", ""
        self.level = 0.0            # 0..1 jačina glasa (iz mikrofona)
        self.levels = [0.0] * 5     # istorija za trakice
        self.tick = 0
        self.visible = False
        self.root.after(40, self._poll)

    # --- API (bilo koji thread) ---
    def show(self, text: str, state: str = "info", sub: str = "", hide_after_ms: int | None = None):
        self.q.put(("show", text, state, sub, hide_after_ms))

    def hide(self):
        self.q.put(("hide",))

    def set_level(self, level: float):
        self.level = max(0.0, min(1.0, level))

    # --- crtanje (glavni thread) ---
    def _pill(self):
        c, W, H, R = self.c, self.W, self.H, self.R
        for fill, outline, d in ((self.BORDER, "", 0), (self.BG, "", 1)):
            c.create_oval(d, d, 2 * R - d, H - d, fill=fill, outline=outline)
            c.create_oval(W - 2 * R + d, d, W - d, H - d, fill=fill, outline=outline)
            c.create_rectangle(R, d, W - R, H - d, fill=fill, outline=outline)

    def _mic(self, x, y, color):
        """Ikonica mikrofona: kapsula + luk + stalak."""
        c = self.c
        c.create_oval(x - 5, y - 11, x + 5, y + 3, fill=color, outline=color)
        c.create_arc(x - 9, y - 6, x + 9, y + 8, start=180, extent=180, style="arc", outline=color, width=2)
        c.create_line(x, y + 8, x, y + 12, fill=color, width=2)
        c.create_line(x - 5, y + 12, x + 5, y + 12, fill=color, width=2)

    def _draw(self):
        c = self.c
        c.delete("all")
        self._pill()
        col = self.COL[self.state]
        ix, iy = 32, self.H // 2
        if self.state == "listening":
            # pulsirajući prsten oko mikrofona
            r = 15 + 3 * abs(((self.tick % 20) / 10) - 1)
            c.create_oval(ix - r, iy - r, ix + r, iy + r, outline=col, width=1)
        c.create_oval(ix - 13, iy - 13, ix + 13, iy + 13, fill="#2c2c2e", outline="")
        self._mic(ix, iy, col)
        tx = 58
        if self.sub:
            c.create_text(tx, iy - 8, text=self.text, fill=self.TXT, anchor="w", font=("Segoe UI Semibold", 11))
            c.create_text(tx, iy + 10, text=self.sub, fill=self.SUB, anchor="w", font=("Segoe UI", 9))
        else:
            c.create_text(tx, iy, text=self.text, fill=self.TXT, anchor="w", font=("Segoe UI Semibold", 11))
        # desna strana: trakice jačine (listening) ili tri tačke (processing)
        rx = self.W - 36
        if self.state == "listening":
            self.levels = self.levels[1:] + [self.level]
            for i, lv in enumerate(self.levels):
                h = 4 + lv * 18
                x = rx - 24 + i * 7
                c.create_rectangle(x, iy - h / 2, x + 4, iy + h / 2, fill=col, outline="")
        elif self.state == "processing":
            for i in range(3):
                on = (self.tick // 4) % 3 == i
                x = rx - 16 + i * 10
                c.create_oval(x - 3, iy - 3, x + 3, iy + 3, fill=col if on else "#48484a", outline="")

    def _place(self):
        x = (self.root.winfo_screenwidth() - self.W) // 2
        y = self.root.winfo_screenheight() - self.H - 80
        self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")
        self.root.lift()

    def _poll(self):
        while not self.q.empty():
            msg = self.q.get()
            if self.hide_job:
                self.root.after_cancel(self.hide_job)
                self.hide_job = None
            if msg[0] == "hide":
                self.visible = False
                self.root.geometry(self.OFFSCREEN)
                continue
            _, self.text, self.state, self.sub, hide_after_ms = msg
            self.tick = 0
            self.levels = [0.0] * 5
            self.visible = True
            self._draw()
            self._place()
            if hide_after_ms:
                self.hide_job = self.root.after(hide_after_ms, self.hide)
        if self.visible and self.state in ("listening", "processing"):
            self.tick += 1
            self._draw()
        self.root.after(50, self._poll)


# --- glavna logika ---------------------------------------------------------------

class Reci:
    def __init__(self, ui: Indicator):
        self.ui = ui
        self.groq_key = load_groq_key()
        self.held = False           # desni Ctrl trenutno držan (auto-repeat se ignoriše)
        self.recording = False
        self.frames: list[np.ndarray] = []
        self.stream = None
        self.started = 0.0
        self.auto_stop_sent = False
        self.lock = threading.Lock()

    # --- tastatura -------------------------------------------------------
    def watch_key(self):
        """Petlja (u svom threadu): pita samo za desni Ctrl, bez hook-a na tastaturu."""
        cancelled = False
        while True:
            down = key_down(VK_HOLD)
            if down and not self.held:
                self.held, cancelled = True, False
                self.start()
            elif down and self.held and not cancelled and other_key_down():
                cancelled = True          # desni Ctrl + neki taster = obična prečica, nije diktat
                self.cancel()
            elif not down and self.held:
                self.held = False
                if not cancelled:
                    self.stop()
            time.sleep(POLL_S)

    # --- snimanje ---------------------------------------------------------
    def _callback(self, indata, frames, time_info, status):
        self.frames.append(indata.copy())
        rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2))) / 32768
        self.ui.set_level(min(1.0, rms * 12))      # tih govor ~0.02, normalan ~0.05–0.1
        if time.time() - self.started > MAX_SECONDS and not self.auto_stop_sent:
            self.auto_stop_sent = True
            threading.Thread(target=self.stop, daemon=True).start()

    def start(self):
        """Mikrofon se otvara tek na pritisak; kratak ton javlja da je spreman — pričajte posle tona."""
        with self.lock:
            if self.recording:
                return
            self.frames = []
            self.started = time.time()
            self.auto_stop_sent = False
            try:
                self.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                             callback=self._callback)
                self.stream.start()
            except Exception as e:
                log.exception("Mikrofon nije dostupan")
                self.ui.show("Mikrofon nije dostupan", "error", str(e)[:40], 3000)
                return
            self.recording = True
        self.ui.show("Slušam", "listening", "pustite desni Ctrl za kraj")
        threading.Thread(target=winsound.Beep, args=(900, 70), daemon=True).start()

    def _close_stream(self) -> bool:
        with self.lock:
            if not self.recording:
                return False
            self.stream.stop()
            self.stream.close()
            self.stream = None
            self.recording = False
            return True

    def cancel(self):
        if self._close_stream():
            self.frames = []
            self.ui.hide()

    def stop(self):
        if not self._close_stream():
            return
        frames, self.frames = self.frames, []
        samples = np.concatenate(frames).flatten() if frames else np.zeros(0, np.int16)
        if len(samples) / SAMPLE_RATE < MIN_SECONDS:
            self.ui.hide()          # slučajan kratak pritisak — tiho
            return
        winsound.Beep(600, 80)
        threading.Thread(target=self._process, args=(samples,), daemon=True).start()

    # --- prepoznavanje ---------------------------------------------------
    def _process(self, samples: np.ndarray):
        secs = len(samples) / SAMPLE_RATE
        engine = "Groq Whisper" if self.groq_key else "Google"
        self.ui.show("Prepoznajem", "processing", f"{secs:.0f} s govora")
        log.info("Prepoznajem %.1fs preko %s", secs, engine)
        try:
            if self.groq_key:
                try:
                    text = transcribe_groq(samples, self.groq_key)
                except Exception:  # limit, loš ključ, Groq pao → Google za ovu poruku
                    log.exception("Groq nije uspeo, prelazim na Google")
                    self.ui.show("Prepoznajem", "processing", "rezerva: Google")
                    text = transcribe_google(samples)
            else:
                text = transcribe_google(samples)
        except Exception as e:  # ni mreže nema
            log.exception("Greška pri prepoznavanju")
            self.ui.show("Greška", "error", str(e)[:44], 3500)
            winsound.Beep(300, 150)
            return
        text = to_latin(text).strip()
        if not text:
            log.info("Ništa nije prepoznato")
            self.ui.show("Ništa nije prepoznato", "error", "pokušajte ponovo", 2000)
            winsound.Beep(300, 150)
            return
        raw = text
        text = apply_recnik(text)
        if self.groq_key:
            text = to_latin(lektor_groq(text, self.groq_key)).strip()
        if text != raw:
            log.info("Ispravka: %s  →  %s", raw, text)
        pyperclip.copy(text)
        send_ctrl_v()
        log.info("OK: %s", text)
        self.ui.hide()


def already_running() -> bool:
    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\Reci")
    return ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS


def main():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    handlers = [logging.FileHandler(LOG_FILE, encoding="utf-8")]
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8")
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=handlers)

    if already_running():
        log.info("Reci već radi — izlazim.")
        return
    ui = Indicator()
    first_run_setup(ui.root)
    r = Reci(ui)
    threading.Thread(target=r.watch_key, daemon=True).start()
    engine = "Groq Whisper large-v3 + lektor" if r.groq_key else "Google (besplatno)"
    log.info("Reci spreman — drži %s | prepoznavanje: %s", HOLD_KEY.upper(), engine)
    ui.show("Reci je spreman", "info", "držite desni Ctrl dok pričate", 2500)
    ui.root.mainloop()


if __name__ == "__main__":
    main()
