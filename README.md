# Reci

Diktat na srpskom za Windows. Držiš **desni Ctrl**, pričaš, pustiš — i tekst se pojavi tamo gde ti je kursor. Radi u svakom programu (Claude Code, browser, Word, Slack…), kao Windowsov Win+H, samo što Win+H ne zna srpski.

Napravljen zato što Windows glasovno kucanje nema srpski, a laptop (i3, 8 GB, bez GPU) ne može da vrti Whisper lokalno. Zato prepoznavanje ide preko interneta, besplatno.

## Kako se koristi

1. Klikni gde treba tekst.
2. **Drži desni Ctrl** → kratak visok ton → na dnu ekrana traka „● Slušam…”.
3. Pričaj (posle tona — mikrofon se otvara tek na pritisak).
4. **Pusti desni Ctrl** → srednji ton → traka „Prepoznajem” → tekst se nalepi za 1–2 s.

Sitnice:
- Desni Ctrl + neki taster (npr. desni Ctrl+C) je obična prečica — snimanje se tiho otkaže.
- Pritisak kraći od 0,6 s se ignoriše (slučajan dodir).
- Snimak se sam prekida posle 3 minuta.
- Tekst ostaje i u clipboardu — ako se ne nalepi, Ctrl+V.
- Nizak dug ton + crvena traka = greška (nema interneta, ništa nije prepoznato).

## Kako radi

```
desni Ctrl ↓  ──►  mikrofon (16 kHz, mono)  ──►  desni Ctrl ↑
                                                      │
                                   ┌──────────────────┴──────────────────┐
                                   │ 1. Whisper large-v3 (Groq)           │  prepoznavanje govora, lang=sr
                                   │    ↳ pad / limit → Google Web Speech │  rezerva, bez interpunkcije
                                   │ 2. recnik.txt                        │  lični parovi „pogrešno = ispravno"
                                   │ 3. lektor — qwen3.8-27b (Groq)       │  samo padeži/slaganje/interpunkcija
                                   │ 4. ćirilica → latinica               │  Whisper ponekad vrati ćirilicu
                                   └──────────────────┬──────────────────┘
                                                      ▼
                                       clipboard  ──►  Ctrl+V u aktivni prozor
```

### Delovi

| Deo | Šta radi | Gde u kodu |
|---|---|---|
| Prečica | `keyboard.hook` prati desni Ctrl. Reaguje na prvi `down` (auto-repeat ignoriše), snima do `up`. Drugi taster tokom držanja = otkaz. | `Reci.on_key` |
| Snimanje | `sounddevice.InputStream`, otvara se **tek na pritisak** (privatnost — mikrofon nije stalno otvoren), zatvara na puštanje. | `Reci.start / stop` |
| Whisper | Groq `whisper-large-v3`, `language=sr`, uz `prompt` sa kontekstom (latinica, ekavica, naši pojmovi, žargon). | `transcribe_groq`, `WHISPER_PROMPT` |
| Google rezerva | `SpeechRecognition` → Google Web Speech `sr-RS`. Prima kratke snimke, pa se duži seku na najtišem mestu u prozoru 35–50 s. | `transcribe_google`, `split_on_silence` |
| Rečnik | `recnik.txt`, red `pogrešno = ispravno`, cele reči, bez razlike velikih/malih slova. Čita se pri svakom pozivu — izmene važe odmah. | `apply_recnik` |
| Lektor | Groq chat `qwen/qwen3.8-27b`, `temperature=0`. Strog prompt: samo padeži imenica/prideva, spojene/rastavljene reči, interpunkcija. **Ne sme** da menja lice/broj/vreme glagola, smisao, žargon, „je li”. Ako promeni dužinu van 0,6–1,5×, ignoriše se. Pri grešci → original. | `lektor_groq`, `LEKTOR_PROMPT` |
| Traka | `tkinter` prozor bez okvira, `WS_EX_NOACTIVATE` da ne krade fokus (inače bi Ctrl+V otišao u traku). Thread-safe kroz queue. | `Indicator` |
| Jedna instanca | Windows mutex `Local\Reci` — drugi start se odmah ugasi. | `already_running` |
| Log | `%LOCALAPPDATA%\reci\reci.log` — svaka poruka: trajanje, motor, ispravke, konačan tekst. | `main` |

### Zašto ovako

- **Mikrofon nije stalno otvoren.** Varijanta sa stalno otvorenim mikrofonom i 1 s „pre-roll” bafera bi uhvatila i prve reči pre pritiska, ali je odbačena zbog privatnosti. Zato ton — pričaj posle njega.
- **`keyboard.add_hotkey` se ne koristi.** Na `press` okida više puta (auto-repeat → start pa odmah stop), a `trigger_on_release` ne okida ako se modifikator pusti pre glavnog tastera. Zato ručni hook sa `held` flagom.
- **Lektor je namerno plašljiv.** Prva verzija je „usklađivala” lica glagola i menjala smisao („da ispravno govori” → „govoriš”). Sad je pravilo: u sumnji ostavi.
- **Rečnik nije rešenje za tačnost** — ne može da pokrije običan govor. Služi samo za imena koja se stalno ponavljaju (Groq, Porudžbinator). Pravi uticaj na tačnost imaju model i mikrofon.

## Instalacija

Potrebni: Windows 10/11, Python 3.11 (`C:\Python311`), mikrofon, internet.

```bat
pip install --user -r requirements.txt
copy .env.example .env     &rem upiši GROQ_API_KEY (besplatno na console.groq.com)
start.bat
```

Ključ se traži redom: env promenljiva `GROQ_API_KEY` → `reci/.env` → `../assistant/.env`. Bez ključa radi preko Google-a.

**Autostart sa Windowsom:** prečica u `shell:startup` ka `C:\Python311\pythonw.exe "…\reci\reci.py"`. (Na ovom računaru već postoji: `Diktat (srpski).lnk`.)

**Gašenje:** `ugasi.bat`. **Restart posle izmene koda:** `ugasi.bat` pa `start.bat`.

## Limiti (Groq besplatan nalog)

| | Whisper | Lektor (qwen) |
|---|---|---|
| Zahteva/min | 20 | 30 |
| Zahteva/dan | 2.000 | ~14.400 |
| Zvuk | 2 h / sat, 8 h / dan | — |

Realna upotreba (~20–50 poruka/sat) ne dolazi ni blizu. Ako Whisper padne na limit, ta poruka ide preko Google-a. Limiti su po organizaciji, ne po ključu.

## Tačnost — šta znamo

- Whisper large-v3 je najbolji **besplatan** model za srpski; greška oko 2–3 % reči (jedna reč u 40). Nijedan besplatan sistem nije bez greške.
- Lektor sređuje padeže („sa oba sajtova” → „sa oba sajta”, „u sat vremene” → „u sat vremena”), ne i pogrešno prepoznate reči.
- Što dalje pomaže, po redu uticaja:
  1. **Mikrofon** — slušalice sa mikrofonom umesto Realtek niza u laptopu.
  2. **Bolji model** — ElevenLabs Scribe / Google Chirp su po nezavisnim merenjima bolji za slovenske jezike (Scribe ~0,4 €/sat govora, ima mali besplatan paket). Pre plaćanja: A/B test na 5–6 snimljenih poruka, brojke a ne utisak.
  3. Rečnik — samo za imena.

## Rešavanje problema

| Simptom | Uzrok / fix |
|---|---|
| Ništa se ne dešava na desni Ctrl | Reci ne radi — `start.bat`. Proveri `reci.log`. |
| Traka se pojavi, tekst se ne nalepi | Aktivni prozor ne prima Ctrl+V — tekst je u clipboardu, nalepi ručno. |
| „Prepoznajem (Google)” umesto Groq | Groq limit/pad/loš ključ — vidi `reci.log`, red „Groq nije uspeo”. |
| Prve reči fale | Pričaj posle tona; mikrofonu treba ~100 ms da se otvori. |
| Ne čuje se ton | `winsound.Beep` na nekim laptopovima ne izlazi na zvučnike. Pokušaj sa `winsound.PlaySound` i WAV-om u memoriji je **pokvario prepoznavanje** (još neistraženo zašto) — vraćeno. Otvoreno. |
| Lektor promenio smisao | Pošalji red iz loga („Ispravka: … → …”) — zateže se `LEKTOR_PROMPT`. |

## Istorija

- **21.10.2026** — v1: Ctrl+Alt+Space toggle, crni prozor, Google. Problemi s prečicom (auto-repeat, release). → v2: voki-toki desni Ctrl, pozadina (pythonw), traka, autostart, mutex. → Groq Whisper + Google rezerva. → Ton pri otvaranju mikrofona (umesto stalno otvorenog). → Lektor (llama-3.3 više ne postoji na Groq-u → qwen3.8-27b; gpt-oss-120b odbačen: ijekavica, sporiji). → Rečnik. → Preseljeno iz `assistant/tools/diktat` u ovaj repo kao **Reci**.

## Ideje

- Prečica koja otvara Claude prozor i stavlja kursor u polje za poruku.
- A/B test Whisper vs Scribe na pravim snimcima.
- Ton koji se stvarno čuje (bez kvarenja prepoznavanja).
- Opcija da dugi diktat ide direktno kao fajl, ne kroz clipboard.
