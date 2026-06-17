# Changelog

## 2026-06-17 — Creazione del repository

Questo repository è stato creato estraendo dal progetto [epub-metadata-scraping](https://github.com/vigliafg/epub-metadata-scraping) solo gli script relativi al motore di ricerca **IBS.it**, escludendo il motore AVX.

### Cosa è stato fatto

- **Creato repository pubblico** `ibs-epub-metadata-scraper` su GitHub (via SSH)
- **Copiati solo i file IBS**: `ibs_fast_metadata_search.py`, `ibs_metadata_search.py`, `gui_ibs_fast_metadata_search.py`
- **Esclusi i file AVX**: `avx_metadata_search.py`
- **README.md ripulito** da tutti i riferimenti ad AVX (tabella comparativa, esempi, troubleshooting, raccomandazioni)
- **Aggiunto `requirements.txt`** con le dipendenze del progetto (`requests`, `beautifulsoup4`, `customtkinter`, `playwright`)
- **Aggiunta licenza MIT**

### File nel repository

| File | Descrizione |
|---|---|
| `ibs_fast_metadata_search.py` | CLI veloce via API Algolia diretta (~1.1s/libro, 100% successo) |
| `ibs_metadata_search.py` | CLI legacy via Playwright (browser automation) |
| `gui_ibs_fast_metadata_search.py` | GUI moderna con `customtkinter` per uso interattivo |
| `README.md` | Documentazione completa con esempi, troubleshooting, cron jobs |
| `requirements.txt` | Dipendenze Python del progetto |
| `LICENSE` | Licenza MIT |
| `.gitignore` | Ignora output di pipeline, cache Python, IDE |
| `.gitattributes` | Normalizzazione LF per file di testo |

### Relazione col repo originale

Il repository originale [epub-metadata-scraping](https://github.com/vigliafg/epub-metadata-scraping) continua a contenere anche il motore **AVX.se** (`avx_metadata_search.py`) come fallback per libri non presenti su IBS.it.

Questo repo è la versione «leggera» focalizzata esclusivamente su IBS.it.
