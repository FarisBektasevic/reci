# Reci — diktat na srpskom (Windows)

Jedan fajl: `reci.py`. Šta radi i zašto je tako — `README.md` (arhitektura, odluke, limiti, otvoreni problemi). Pročitati pre izmena.

## Rad na kodu
- Korisnik koristi **instalirani** `%LOCALAPPDATA%\Programs\Reci\Reci.exe` (autostart prečica pokazuje na njega), ne `reci.py`.
- Logika se testira direktnim pozivima funkcija (`Reci.watch_key` sa zamenjenim `key_down`, `lektor_groq`, `apply_recnik`) — iz Claude okruženja prava tastatura se ne vidi.
- Da korisnik dobije izmenu: `build.bat` **u prvom planu** (u pozadini puca), pa `gh release upload v1.0.0 dist/Reci.exe --clobber` ili novi release, pa `irm .../install.ps1 | iex` kod korisnika.
- **Push i release tek kad korisnik kaže da je zadovoljan** — izmene prvo lokalno (commit lokalno je OK).
- Ključ je u `%LOCALAPPDATA%\reci\.env`, nikad u repou. Log: `%LOCALAPPDATA%\reci\reci.log` (ima original i lektorovu ispravku svake poruke).
- `requirements.txt` još navodi `keyboard` koji se od v1.2 ne koristi — očistiti uz sledeću izmenu README-a.
