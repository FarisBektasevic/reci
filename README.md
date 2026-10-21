# Reci

**Diktat na srpskom za Windows.** Držiš desni Ctrl, pričaš, pustiš — tekst se pojavi tamo gde ti je kursor. Radi u svakom programu: browser, Word, Slack, Claude, terminal…

Windowsovo glasovno kucanje (Win+H) nema srpski. Reci ga ima — i to kao prvi jezik, ne kao jedan od sto. Besplatno, bez naloga ako hoćeš, bez jakog računara (sve se prepoznaje na serveru).

> *Serbian dictation for Windows. Hold right Ctrl, speak, release — text is pasted at the cursor. Free; uses Groq Whisper (or Google as fallback) with a grammar pass tuned for Serbian (Latin script, ekavian). Serbian-first — docs below are in Serbian.*

## Instalacija iz terminala

PowerShell (Win+X → *Terminal*), jedna linija — bez git-a, bez Python-a:

```powershell
irm https://raw.githubusercontent.com/FarisBektasevic/reci/main/install.ps1 | iex
```

Skine poslednji `Reci.exe` u `%LOCALAPPDATA%\Programs\Reci`, napravi prečicu u Start meniju i pokrene ga. Ista komanda radi i za ažuriranje. Skripta je [install.ps1](install.ps1) — pročitaj je pre pokretanja ako ti je tako lakše.

Deinstalacija: obriši `%LOCALAPPDATA%\Programs\Reci`, `%LOCALAPPDATA%\reci` (ključ, log) i `shell:startup\Reci.lnk`.

## Instalacija ručno

1. Skini **`Reci.exe`** sa [Releases](../../releases/latest) stranice.
2. Prebaci ga gde hoćeš (npr. `C:\Programi\Reci\`) i pokreni dvoklikom.
3. Pri prvom pokretanju Reci pita dve stvari:
   - **Groq API ključ** — besplatan, bez kartice: [console.groq.com](https://console.groq.com) → *API Keys* → *Create*. Nalepi ga. Daje bolje prepoznavanje, interpunkciju i lektora.
     Ako ostaviš prazno, radi preko Google-a: slabije, bez interpunkcije, ali bez ikakvog naloga.
   - **Da li da se pali sa Windowsom** — preporuka *Da*.
4. Na dnu ekrana se pojavi „Reci — držite desni Ctrl dok pričate”. To je to.

Windows može da pita „Da li ste sigurni da želite da pokrenete ovaj program?” jer `.exe` nije digitalno potpisan — *More info → Run anyway*. Ko ne veruje `.exe`-u, može da pokrene iz koda (dole).

**Gašenje:** nema prozor ni ikonu — Reci radi tiho u pozadini. Ugasi ga iz Task Manager-a (`Reci.exe`) ili `ugasi.bat` ako radiš iz koda.
**Autostart kasnije uključi/isključi:** `Win+R` → `shell:startup` → dodaj/obriši prečicu `Reci.lnk`.

## Kako se koristi

1. Klikni gde treba tekst.
2. **Drži desni Ctrl** → kratak ton → traka „● Slušam…” na dnu ekrana.
3. Pričaj. *(Posle tona — mikrofon se otvara tek na pritisak, ne ranije.)*
4. **Pusti desni Ctrl** → drugi ton → „Prepoznajem” → tekst se nalepi za 1–2 s.

Dobro je znati:
- Desni Ctrl + bilo koji taster (npr. desni Ctrl+C) je obična prečica — snimanje se tiho otkaže.
- Dodir kraći od 0,6 s se ignoriše.
- Snimak se sam zaustavi posle 3 minuta (oko 400 reči).
- Tekst ostaje i u clipboardu — ako se ne nalepi, Ctrl+V.
- Crvena traka + dug nizak ton = greška (nema interneta, ništa prepoznato).
- Ako pričaš engleski, dobijaš **srpski prevod** — Whisperu je zadat srpski pa ne pogađa jezik. Namerno: tako je srpski najtačniji.

## Podešavanje pod svoju ruku

Dva tekstualna fajla, menjaju se bez restarta. Mogu da stoje pored `Reci.exe` **ili** u `%LOCALAPPDATA%\reci\` (primenjuju se oba):

| Fajl | Čemu služi | Primer |
|---|---|---|
| `pojmovi.txt` | Imena, brendovi, programi, stručni izrazi — jedan po redu. Whisper ih dobija kao kontekst pa ih ređe kvari. | `Porudžbinator`, `n8n`, `WooCommerce` |
| `recnik.txt` | Reči koje prepoznavanje *uvek isto* pogreši. `pogrešno = ispravno`, cele reči. | `skuntaš = skontaš` |

Rečnik **nije** način da se popravi opšta tačnost — ne možeš da pokriješ običan govor spiskom. Služi samo za imena i žargon. Na tačnost stvarno utiču mikrofon i model (vidi dole).

Ključ: `%LOCALAPPDATA%\reci\.env` (red `GROQ_API_KEY=gsk_...`). Može i `.env` pored programa ili env promenljiva.
Log: `%LOCALAPPDATA%\reci\reci.log` — svaka poruka: trajanje, motor, šta je lektor promenio, konačan tekst.

## Kako radi

```
desni Ctrl ↓  ──►  mikrofon (16 kHz, mono)  ──►  desni Ctrl ↑
                                                      │
                                   ┌──────────────────┴──────────────────┐
                                   │ 1. Whisper large-v3 (Groq)           │  prepoznavanje, lang=sr + pojmovi.txt
                                   │    ↳ pad / limit → Google Web Speech │  rezerva, bez interpunkcije
                                   │ 2. recnik.txt                        │  „pogrešno = ispravno"
                                   │ 3. lektor — qwen3.8-27b (Groq)       │  samo padeži/slaganje/interpunkcija
                                   │ 4. ćirilica → latinica               │  Whisper ponekad vrati ćirilicu
                                   └──────────────────┬──────────────────┘
                                                      ▼
                                       clipboard  ──►  Ctrl+V u aktivni prozor
```

| Deo | Šta radi | U kodu |
|---|---|---|
| Prečica | `keyboard.hook` prati desni Ctrl. Prvi `down` pali (auto-repeat se ignoriše), `up` gasi. Drugi taster tokom držanja = otkaz. | `Reci.on_key` |
| Snimanje | `sounddevice.InputStream`, otvara se **tek na pritisak** (mikrofon nije stalno otvoren), zatvara na puštanje. | `Reci.start / stop` |
| Whisper | Groq `whisper-large-v3`, `language=sr`, `prompt` = latinica/ekavica/žargon + `pojmovi.txt`. | `transcribe_groq`, `whisper_prompt` |
| Google rezerva | `SpeechRecognition` → Google Web Speech `sr-RS`. Dugi snimci se seku na najtišem mestu (35–50 s). | `transcribe_google`, `split_on_silence` |
| Rečnik | `recnik.txt`, cele reči, bez razlike velikih/malih. | `apply_recnik` |
| Lektor | Groq chat `qwen/qwen3.8-27b`, `temperature=0`. Strog: samo padeži imenica/prideva, spojene/rastavljene reči, interpunkcija. **Ne sme** da menja lice/broj/vreme glagola, smisao, žargon, „je li”. Ako promeni dužinu van 0,6–1,5× → ignoriše se. Greška → original. | `lektor_groq`, `LEKTOR_PROMPT` |
| Pilula | `tkinter` Canvas, zaobljena kroz `-transparentcolor`, `WS_EX_NOACTIVATE` da ne krade fokus (inače bi Ctrl+V otišao u nju). Stanja: spreman / sluša (pulsira + trakice jačine glasa iz RMS-a) / prepoznaje (tri tačke) / greška. | `Indicator` |
| Prvo pokretanje | Nema ključa ni `.env`-a → dijalog za ključ + pitanje za autostart → upis u `%LOCALAPPDATA%\reci`. | `first_run_setup`, `set_autostart` |
| Jedna instanca | Mutex `Local\Reci` — drugi start se odmah ugasi. | `already_running` |

### Zašto baš tako

- **Mikrofon nije stalno otvoren.** Varijanta sa stalnim mikrofonom i 1 s „pre-roll” bafera bi hvatala i reči izgovorene pre pritiska — odbačena zbog privatnosti. Zato ton: pričaj posle njega.
- **`keyboard.add_hotkey` se ne koristi.** Na `press` okida više puta (auto-repeat → start pa odmah stop), a `trigger_on_release` ne okida ako se modifikator pusti pre glavnog tastera. Ručni hook sa `held` flagom.
- **Lektor je namerno plašljiv.** Prva verzija je „usklađivala” lica glagola i menjala smisao („da ispravno govori” → „govoriš”). Pravilo: u sumnji ostavi.
- **Prisilan srpski, ne auto-detekcija.** Auto-detekcija srpski često proglasi za hrvatski/bosanski pa stiže „tjedan”. Cena: engleski se prevede.

## Pokretanje iz koda

Windows 10/11, Python 3.11+, mikrofon, internet.

```bat
git clone https://github.com/FarisBektasevic/reci.git
cd reci
pip install -r requirements.txt
start.bat          &rem pokreće u pozadini kroz pythonw; prvi put pita za ključ
```

`ugasi.bat` gasi. Posle izmene koda: `ugasi.bat` pa `start.bat`.
`build.bat` pravi `dist\Reci.exe` (treba `pip install pyinstaller`).

## Limiti (Groq, besplatan nalog)

| | Whisper | Lektor |
|---|---|---|
| Zahteva/min | 20 | 30 |
| Zahteva/dan | 2.000 | ~14.400 |
| Zvuk | 2 h/sat, 8 h/dan; fajl ≤ 25 MB (~13 min) | — |

Normalna upotreba (20–50 poruka na sat) ne dolazi ni blizu. Ako Whisper udari u limit, ta poruka ide preko Google-a.

## Tačnost — šta znamo

- Whisper large-v3 je najbolji **besplatan** model za srpski; greši oko 2–3 % reči (jedna u 40). Nijedan besplatan sistem nije bez greške.
- Lektor sređuje padeže („sa oba sajtova” → „sa oba sajta”), ne i pogrešno prepoznate reči.
- Šta pomaže, po redu uticaja: **1.** slušalice sa mikrofonom umesto onog u laptopu; **2.** bolji model (ElevenLabs Scribe / Google Chirp su po nezavisnim merenjima bolji za slovenske jezike, ali se plaćaju, ~0,4 €/sat govora); **3.** `pojmovi.txt` za imena.

## Problemi

| Simptom | Fix |
|---|---|
| Ništa na desni Ctrl | Reci ne radi — pokreni ga. Pogledaj `reci.log`. |
| Traka se pojavi, tekst se ne nalepi | Taj prozor ne prima Ctrl+V — tekst je u clipboardu, nalepi ručno. |
| „Prepoznajem (Google)” umesto Groq | Limit, pad ili loš ključ — `reci.log`, red „Groq nije uspeo”. |
| Fale prve reči | Pričaj posle tona; mikrofonu treba ~100 ms. |
| Ne čuje se ton | `winsound.Beep` na nekim laptopovima ne izlazi na zvučnike. Pokušaj sa `PlaySound` + WAV je **pokvario prepoznavanje** (nejasno zašto) — vraćeno. Otvoreno. |
| Lektor promenio smisao | Otvori issue sa redom iz loga („Ispravka: … → …”). |
| Antivirus se buni na `Reci.exe` | PyInstaller `.exe` bez potpisa ponekad okine false positive. Pokreni iz koda. |

## Istorija

- **21.10.2026** — v1: Ctrl+Alt+Space, crni prozor, Google. → v2: voki-toki desni Ctrl, pozadina, traka, autostart, mutex. → Groq Whisper + Google rezerva. → Ton pri otvaranju mikrofona. → Lektor (qwen3.8-27b; llama-3.3 više nije na Groq-u, gpt-oss-120b odbačen: ijekavica, sporiji). → Rečnik, pojmovi. → `Reci.exe`, prvo pokretanje sa dijalogom, javni repo. → Pilula u stilu Win+H (mikrofon, jačina glasa, animacije), `install.ps1` za instalaciju iz terminala.

## Ideje

- Ikonica u tray-u (status, gašenje, otvaranje loga) umesto Task Manager-a.
- Druga prečica za engleski (bez prevođenja).
- A/B Whisper vs Scribe na pravim snimcima.
- Ton koji se stvarno čuje.
- Potpisan `.exe`.

## Licenca

MIT — radi šta hoćeš, bez garancije.
