# Add Audio to Cards

[Español](README.es.md) | [日本語](README.ja.md)

An Anki add-on that automatically adds **native human audio** to your flashcards by fetching pronunciation recordings from Wiktionary. Supports 12 languages. No API key required. Completely free.

---

## How it works

For each card in your deck, the add-on looks up the word on the English Wiktionary, which hosts thousands of community-recorded pronunciations tagged by language. If a native recording is found, it is downloaded and added to the card. If not, it can optionally fall back to Google Translate TTS.

```mermaid
flowchart TD
    A[Card word field] --> B[Extract candidates\nfrom field text]
    B --> C{Try each\ncandidate}
    C --> D[Query Wiktionary API\nfor audio files]
    D --> E{Spanish audio\nfile found?}
    E -- Yes --> F[Download .wav/.ogg\nfrom Wikimedia]
    F --> G[Save to Anki\nmedia folder]
    G --> H[Update card field\nwith sound tag]
    E -- No --> I{TTS fallback\nenabled?}
    I -- Yes --> J[Google Translate TTS\nsynthetic audio]
    J --> G
    I -- No --> K[Skip card\nno audio found]
    C -- All candidates\nexhausted --> I
```

### Why Wiktionary?

Wiktionary hosts real recordings made by native speakers, stored on Wikimedia Commons and freely licensed. Each language has its own naming pattern — for example, Spanish recordings follow `LL-Q1321 (spa)-Speaker-word.wav` — which the add-on uses to filter results to the correct language.

### Supported languages

Coverage is based on the number of native human recordings available on Wikimedia Commons (Lingua Libre project data, 2024).

| Language | Code | Recordings | Coverage | Notes |
|---|---|---|---|---|
| French | `fr` | ~430 000 | Excellent | Best-covered language by far |
| English | `en` | ~105 000 | Excellent | |
| German | `de` | ~25 000 | Good | |
| Russian | `ru` | ~17 000 | Good | |
| Arabic | `ar` | ~13 000 | Good | |
| Italian | `it` | ~12 000 | Good | |
| Portuguese | `pt` | ~8 000 | Moderate | |
| Spanish | `es` | ~5 000–10 000 | Moderate | ~40% on typical vocabulary decks |
| Dutch | `nl` | ~1 800 | Limited | ⚠ TTS fallback recommended |
| Japanese | `ja` | ~1 000 | Limited | ⚠ Native Wiktionary queried first |
| Korean | `ko` | ~1 000 | Limited | ⚠ Native Wiktionary queried first |
| Chinese | `zh` | < 50 | Very low | ⚠ Almost no recordings; TTS strongly recommended |

For Japanese, Korean, and Chinese the add-on automatically queries the native language Wiktionary (ja/ko/zh.wiktionary.org) before falling back to the English one, which improves hit rates for those languages. The dialog shows a warning when a low-coverage language is selected.

---

## Features

- **Native human audio** — real recordings from Wiktionary, not synthesised speech
- **Smart field parsing** — fields like `"floor piso planta"` or `"cuál?"` are split into candidates; each is tried until audio is found
- **Two audio fields** — optionally write the same audio to both the front and back of a card
- **Optional TTS fallback** — Google Translate TTS fills gaps when no native recording exists
- **Respectful rate limiting** — requests are spaced to avoid overloading Wikimedia's servers
- **Multilingual UI** — the add-on interface adapts to Anki's language: English, Spanish, or Japanese

---

## Requirements

- Anki 23.10 or later (tested on 25.09.2)
- Internet connection during processing

---

## Installation

1. Download **`AddAudioToCards.ankiaddon`** from the [Releases](../../releases) page
2. Open Anki
3. Go to **Tools → Add-ons → Install from file...**
4. Select the downloaded file
5. Restart Anki

The add-on appears under **Tools → Add Audio to Cards...**

---

## Usage

### 1. Open the dialog

**Tools → Add Audio to Cards...**

![Dialog overview](docs/dialog.png)

### 2. Configure the fields

| Setting | Description |
|---|---|
| **Deck** | The deck to process |
| **Word field** | The field containing the word or phrase to look up |
| **Audio field (1)** | The field where the `[sound:…]` tag will be written |
| **Audio field (2)** | *(optional)* A second field to receive the same audio — useful for cards that play audio on both sides |
| **Language** | Target language for audio lookup and TTS fallback |

### 3. Options

#### Overwrite existing audio

When unchecked *(default)*, cards that already have a `[sound:…]` tag in the audio field are skipped entirely. This makes re-runs fast and safe — only cards that still lack audio are processed.

When checked, every card is re-fetched regardless. Use this to replace an old TTS recording with a newly available native one, or to fix a corrupt file.

> **Tip:** the add-on also skips re-downloading files that are already saved on disk, even when "Overwrite" is on. A file that exists in Anki's media folder is reused instantly without any network request.

#### Use TTS as fallback

Controls what happens when no native Wiktionary recording is found **and** when the Wikimedia CDN rate-limits the session.

| TTS setting | No native recording exists | Wikimedia CDN blocks the session |
|---|---|---|
| **Off** *(default)* | Card left with no audio | Processing stops. Cards already done are saved. Run again in 1–2 hours to continue. |
| **On** | Google Translate TTS is used | Seamlessly switches all remaining cards to TTS. The summary notes where the switch happened. |

**Which should I choose?**

- **TTS off** — best when native audio quality matters and you are happy to run the add-on multiple times over a few days until all cards are covered.
- **TTS on** — best when you want the entire deck filled in one go. Google Translate TTS for Spanish, French, German and other well-supported languages is high quality and perfectly suitable for language learning.

### 4. Click "Add Audio"

A progress bar shows the processing status. When done, a summary appears:

```
Done — 777 cards processed

  Native audio (Wiktionary): 312
  Google TTS (synthetic):    200
  Reused from disk:           50
  Skipped (already have audio): 0
  No audio found: 215
```

#### Why does the CDN block the session?

Wikimedia Commons (where all Wiktionary audio files are hosted) enforces a per-session download rate limit on `upload.wikimedia.org`. After roughly 50–150 successful downloads in one session, the server starts returning HTTP 429 errors and will not serve more files regardless of how long you wait between requests.

This is not a bug in the add-on — it is an intentional limit by Wikimedia to protect shared infrastructure. The add-on detects the block as soon as it happens and either switches to TTS or stops cleanly, so no work is lost.

**Re-run strategy (TTS off):** because successfully downloaded files are cached on disk, each subsequent run picks up exactly where the previous one left off. Running the add-on once a day for a few days will gradually fill the entire deck without any manual intervention.

---

## Audio coverage

Coverage depends on what is in your word field:

| Field content | Example | Result |
|---|---|---|
| Single word (target language) | `hablar` | ✅ Native audio |
| Multi-word with target | `floor piso planta` | ✅ Tries `piso` after `floor` fails |
| Phrase with target | `de la mañana` | ✅ Tries `mañana` |
| Word with punctuation | `¿cuál?` | ✅ Cleaned to `cuál` |
| Word in wrong language | `Monday` (with Spanish selected) | ❌ No recording in that language |
| Pure description | `that person informal/formal` | ❌ No match |

---

## Building from source

The `addon/` directory contains the add-on source. To package it:

```bash
python build.py
# → AddAudioToCards.ankiaddon
```

Or manually:

```bash
cd addon
zip -r ../AddAudioToCards.ankiaddon .
```

On Windows (PowerShell):

```powershell
Compress-Archive -Path addon\* -DestinationPath AddAudioToCards.zip
Rename-Item AddAudioToCards.zip AddAudioToCards.ankiaddon
```

### Project structure

```
AddAudioToCardOfAnki/
├── addon/
│   ├── __init__.py        # Registers the Tools menu item
│   ├── audio_fetcher.py   # Wiktionary lookup + Google TTS fallback
│   ├── dialog.py          # Qt UI dialog
│   ├── i18n.py            # Translations (EN / ES / JA)
│   ├── manifest.json      # Anki add-on metadata
│   └── config.json        # Default configuration
├── build.py               # Packaging script
└── README.md
```

### Adding a new UI language

Open `addon/i18n.py` and add your language code to each entry in the `_T` dictionary:

```python
"btn_add": {
    "en": "Add Audio",
    "es": "Añadir Audio",
    "ja": "音声を追加",
    "fr": "Ajouter l'audio",   # ← add here
},
```

Then add the code to the check in `_detect_lang()`.

---

## Technical notes

### Rate limiting

Wiktionary and Wikimedia Commons have separate rate limits:

- **Wiktionary API** (`en.wiktionary.org`) — 1 request per 250 ms
- **Audio downloads** (`upload.wikimedia.org`) — 1 request per 1 second

The add-on enforces both limits automatically. Processing a large deck takes longer as a result, but this avoids HTTP 429 errors and keeps the requests polite.

### File naming

Downloaded audio files are saved to Anki's media folder with the naming scheme:

```
audio_{lang}_{word}.{ogg|mp3}
```

For example: `audio_es_hablar.ogg`

### No external dependencies

The add-on uses only Python's standard library (`urllib`, `ssl`, `json`, `threading`) — no `pip install` needed. It works with Anki's bundled Python out of the box.

---

## License

MIT
