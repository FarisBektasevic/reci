"""Reci — diktat na srpskom. Drži DESNI CTRL dok pričaš, pusti ga i tekst se nalepi gde je kursor.

Radi u pozadini (pythonw, bez prozora), kao Windows Win+H: dok snima i prepoznaje,
na dnu ekrana stoji mala traka koja ne krade fokus.

Tok:  desni Ctrl ↓ → mikrofon → desni Ctrl ↑ → Whisper (Groq) → rečnik → lektor (Groq) → ćirilica→latinica → Ctrl+V

Prepoznavanje ide preko interneta (računar se ne opterećuje):
  - Groq Whisper large-v3 + lektor (qwen) — ako postoji GROQ_API_KEY (reci/.env, pa assistant/.env, pa env)
  - Google Web Speech (besplatno, bez naloga) — rezerva ako Groq-a nema ili zakaže

Pokretanje: start.bat (ili sam krene sa Windowsom). Gašenje: ugasi.bat. Log: %LOCALAPPDATA%\\reci\\reci.log
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

import keyboard
import numpy as np
import pyperclip
import sounddevice as sd

HOLD_KEY = "right ctrl"    # drži dok pričaš (voki-toki)
SAMPLE_RATE = 16000
MIN_SECONDS = 0.6          # kraće = slučajan pritisak, tiho se odbacuje
MAX_SECONDS = 180          # automatski stop posle 3 minuta
GOOGLE_CHUNK_MAX_S = 50    # Google prima kratke snimke — duže se seče na tišini
GOOGLE_CHUNK_MIN_S = 35

HERE = Path(__file__).resolve().parent
ENV_FILES = [HERE / ".env", HERE.parent / "assistant" / ".env"]
RECNIK_FILE = HERE / "recnik.txt"
LOG_FILE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "reci" / "reci.log"
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

WHISPER_PROMPT = (
    "Diktat na srpskom jeziku, latinica, ekavica, opušten govorni stil. Razgovor o online prodavnici muške odeće. "
    "Pojmovi: Taman, Taman Shop, TamanHub, Porudžbinator, Butik Lučna, WooCommerce, n8n, Claude, Groq, "
    "Whisper, Supabase, GitHub, Instagram, SKU, API, webhook, Sors, Snorlax, D Express, Pošta. "
    "Žargon: skontati, skontaš, provaliti, fol, okej, kul, zezati, sredi, šta ima."
)

LEKTOR_MODEL = "qwen/qwen3.8-27b"   # brz (~0.3s), drži ekavicu; llama-3.3 više nije na Groq-u
LEKTOR_PROMPT = (
    "Ti si lektor za srpski jezik (latinica, ekavica). Dobijaš tekst nastao prepoznavanjem govora. "
    "Ispravi SAMO očigledne greške prepoznavanja: pogrešan padež imenice ili prideva (npr. 'sa oba sajtova' → "
    "'sa oba sajta', 'u sat vremene' → 'u sat vremena'), pogrešno spojene ili rastavljene reči, i interpunkciju. "
    "NE menjaj lice, broj ni vreme glagola (ko šta radi — 'govori', 'skontaš', 'pogreši' ostaju kako jesu). "
    "NE menjaj smisao, NE dodaj i NE izbacuj rečenice, NE prepričavaj, NE menjaj stil ni redosled misli. "
    "Ako nisi siguran da je nešto greška, OSTAVI kako jeste — bolje je propustiti grešku nego promeniti smisao. "
    "NE prevodi strane nazive (Taman, Porudžbinator, WooCommerce, n8n, Claude, Groq, SKU ostaju). "
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
              "prompt": WHISPER_PROMPT},
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
    if not RECNIK_FILE.exists():
        return pairs
    for line in RECNIK_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
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
    """Mala traka na dnu ekrana (kao Win+H). Ne uzima fokus — paste ide u prozor gde je kursor.

    Thread-safe: show()/hide() mogu da se zovu iz bilo kog threada, tk radi samo u glavnom.
    """
    BG = "#202020"
    OFFSCREEN = "+-3000+-3000"

    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.93)
        self.root.configure(bg=self.BG)
        self.root.geometry(self.OFFSCREEN)
        self.label = tk.Label(self.root, text="", fg="white", bg=self.BG,
                              font=("Segoe UI", 12), padx=20, pady=9)
        self.label.pack()
        self.root.update_idletasks()
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(self.root.winfo_id())
        GWL_EXSTYLE, WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = -20, 0x8, 0x80, 0x08000000
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        self.q: queue.Queue = queue.Queue()
        self.hide_job = None
        self.root.after(40, self._poll)

    def show(self, text: str, color: str = "white", hide_after_ms: int | None = None):
        self.q.put(("show", text, color, hide_after_ms))

    def hide(self):
        self.q.put(("hide",))

    def _poll(self):
        while not self.q.empty():
            msg = self.q.get()
            if self.hide_job:
                self.root.after_cancel(self.hide_job)
                self.hide_job = None
            if msg[0] == "hide":
                self.root.geometry(self.OFFSCREEN)
                continue
            _, text, color, hide_after_ms = msg
            self.label.config(text=text, fg=color)
            self.root.update_idletasks()
            w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
            x = (self.root.winfo_screenwidth() - w) // 2
            y = self.root.winfo_screenheight() - h - 90
            self.root.geometry(f"{w}x{h}+{x}+{y}")
            self.root.lift()
            if hide_after_ms:
                self.hide_job = self.root.after(hide_after_ms, lambda: self.root.geometry(self.OFFSCREEN))
        self.root.after(40, self._poll)


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
    def on_key(self, e):
        if e.name == HOLD_KEY:
            if e.event_type == "down" and not self.held:
                self.held = True
                self.start()
            elif e.event_type == "up" and self.held:
                self.held = False
                self.stop()
        elif e.event_type == "down" and self.held:
            # desni Ctrl + neki taster = obična prečica (Ctrl+C...), nije diktat
            self.cancel()

    # --- snimanje ---------------------------------------------------------
    def _callback(self, indata, frames, time_info, status):
        self.frames.append(indata.copy())
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
                self.ui.show(f"✗ Mikrofon nije dostupan: {e}", "#ff8080", 3000)
                return
            self.recording = True
        self.ui.show("●  Slušam…   pustite desni Ctrl za kraj", "#ff6b6b")
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
        self.ui.show("…  Prepoznajem", "#9ecbff")
        log.info("Prepoznajem %.1fs preko %s", secs, engine)
        try:
            if self.groq_key:
                try:
                    text = transcribe_groq(samples, self.groq_key)
                except Exception:  # limit, loš ključ, Groq pao → Google za ovu poruku
                    log.exception("Groq nije uspeo, prelazim na Google")
                    self.ui.show("…  Prepoznajem (Google)", "#9ecbff")
                    text = transcribe_google(samples)
            else:
                text = transcribe_google(samples)
        except Exception as e:  # ni mreže nema
            log.exception("Greška pri prepoznavanju")
            self.ui.show(f"✗ Greška: {e}"[:90], "#ff8080", 3500)
            winsound.Beep(300, 150)
            return
        text = to_latin(text).strip()
        if not text:
            log.info("Ništa nije prepoznato")
            self.ui.show("✗ Ništa nije prepoznato", "#ff8080", 2000)
            winsound.Beep(300, 150)
            return
        raw = text
        text = apply_recnik(text)
        if self.groq_key:
            text = to_latin(lektor_groq(text, self.groq_key)).strip()
        if text != raw:
            log.info("Ispravka: %s  →  %s", raw, text)
        pyperclip.copy(text)
        keyboard.send("ctrl+v")
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
    r = Reci(ui)
    keyboard.hook(r.on_key)
    engine = "Groq Whisper large-v3 + lektor" if r.groq_key else "Google (besplatno)"
    log.info("Reci spreman — drži %s | prepoznavanje: %s", HOLD_KEY.upper(), engine)
    ui.show("Reci — držite desni Ctrl dok pričate", "#a0e0a0", 2500)
    ui.root.mainloop()


if __name__ == "__main__":
    main()
