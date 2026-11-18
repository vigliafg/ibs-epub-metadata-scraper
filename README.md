# IBS EPUB Metadata Scraper

> **Strumento principale: `ibs_description_embedder.py`** — arricchisce gli EPUB con la descrizione ufficiale di IBS.it (testo puro), il tag classificatore della libreria (sistema monotag) e rinomina i file secondo il pattern `<Autore> - <Titolo>.epub`.

Il repo contiene anche alcuni tool legacy (vedi [Tool legacy](#-tool-legacy) in fondo).

---

## 📦 Installazione

Requisiti: **Python 3.8+** con `requests` e `beautifulsoup4`:

```bash
pip install requests beautifulsoup4
# oppure
pip install -r requirements.txt
```

Nessun browser, nessuna chiave API obbligatoria. Facoltativo: una chiave Google Books (gratuita, da Google Cloud) per alzare la quota anonima del fallback Google Books:

```bash
export GOOGLE_BOOKS_API_KEY="la-tua-chiave"
```

---

## 🚀 Utilizzo

```bash
python3 ibs_description_embedder.py <file.epub | directory> [...] [opzioni]
```

Accetta uno o più file `.epub` oppure directory (processa tutti gli `.epub` dentro).
Log su **stderr**, risultati completi in **JSON su stdout** (con `--json`).

### Opzioni

| Opzione | Effetto |
|---|---|
| `--tag "TAG"` | Embed del tag classificatore come `<dc:subject>` (sistema monotag: un solo tag, i subject pre-esistenti vengono sostituiti) |
| `--suggest-tags` | Sola lettura: stampa autore/titolo/descrizione (JSON) per decidere il tag giusto. **Non modifica né rinomina nulla** |
| `--force` | Sovrascrive anche descrizioni esistenti e file già in regola |
| `--no-rename` | Disattiva la rinomina automatica |
| `--backup-dir DIR` | Cartella di backup degli originali (default: `origins/`) |
| `--dry-run` | Mostra cosa farebbe senza toccare nulla |
| `--json` | Stampa i risultati in JSON su stdout |

### Workflow tipico

```bash
# 1) Ispezione: cosa contiene il libro? (nessuna modifica)
python3 ibs_description_embedder.py ~/Scaricati/*.epub --suggest-tags

# 2) Si sceglie UN tag dal sistema di classificazione (31 tag, vedi
#    TAGGING_RULES.md) e si esegue: descrizione + tag + rinomina in un colpo
python3 ibs_description_embedder.py ~/Scaricati/*.epub --tag "Fisica Astrofisica Astronomia"
```

Il tag viene scelto dall'operatore (o dall'assistente AI) secondo `TAGGING_RULES.md`; lo script esegue solo.

---

## ✅ Criterio "già in regola": il monotag

Un file è considerato **già processato** se ha **esattamente un `dc:subject` coincidente con uno dei 31 tag ufficiali** (14 macro-categorie + 15 "Scuola *", elencati in `TAGGING_RULES.md` e hardcoded come `VALID_TAGS` nello script; confronto case-insensitive).

Perché questo criterio:

- I 31 tag sono **vocabolario proprietario** della libreria: nessun publisher o z-lib li scrive → fingerprint affidabile del nostro pipeline;
- **viaggia col file** (rename, spostamenti, copie non lo perdono);
- un file **taggato ma senza descrizione** (es. descrizione non disponibile su IBS) è comunque in regola → nessun ri-tentativo sprecato alle passate successive.

Ordine di skip (salvo `--force`):

1. monotag valido → `[SKIP] in regola: monotag valido "…"`
2. descrizione pre-esistente ma senza monotag valido → `[SKIP]` con nota "serve `--tag` per classificarlo" (non si sovrascrivono descrizioni di terzi senza `--force`)
3. né tag né descrizione → si processa

---

## ✏️ Rinomina automatica (default ON, `--no-rename` per disattivare)

Ogni epub processato viene rinominato **`<Autore> - <Titolo completo>.epub`**. Il nome è preso dalla fonte più affidabile disponibile:

| Priorità | Fonte | Note |
|---|---|---|
| 1 | **Match IBS.it** | Titolo/autore verificati sul catalogo |
| 2 | **Metadati OPF** | `dc:creator`/`dc:title` interni (sottotitolo EPUB3 appendato con `: `) |
| 3 | **Nome file attuale** | Solo pulizia |

La catena di match condivisa con la descrizione (vedi sotto) include anche deep scan e fallback esterni, quindi la rinomina sfrutta la stessa verifica.

Pulizia del filename:

- spazzatura tipo `(z-lib.org)`, `[English]` rimossa;
- separatori laschi normalizzati (`_-_` → ` - `);
- `:` → `. ` nei sottotitoli (convenzione libreria "Titolo. Sottotitolo");
- caratteri illegali sanificati;
- collisioni → suffisso ` (2)`, ` (3)`…

L'originale col nome pre-rinomina è sempre nel backup (`origins/`). La rinomina avviene **anche** se la descrizione non è disponibile. Report: `[RENAME] vecchio -> nuovo (fonte: ibs|opf|filename)` e campi JSON `renamed_from` / `renamed_to` / `rename_source`.

---

## 🔎 Catena di match (7 livelli, in ordine di affidabilità)

`find_book_smart()` prova in sequenza e si ferma al primo match affidabile:

1. **EAN/ISBN esatto** — da `dc:identifier` dell'OPF (ISBN-10 convertito in EAN-13) o da filename numerico;
2. **Ricerca a parole su IBS.it** (API Algolia pubblica) con autore+titolo e scoring di pertinenza (match sotto soglia scartati);
3. **Ruoli invertiti** — per file nominati "Titolo - Autore";
4. **Deep scan** — lettura *non distruttiva* delle prime pagine dello spine (frontespizio + copyright): ISBN nel testo → match esatto; altrimenti candidati-titolo dalla sola prima pagina (filtro anti-falsi-positivi);
5. **Google Books** — per libri stranieri non a catalogo IBS (EAN esatto o ricerca a parole, `min_score 30`; descrizione HTML convertita in testo puro; quota anonima spesso esaurita → HTTP 429, con `GOOGLE_BOOKS_API_KEY` si alza);
6. **Open Library** — senza chiavi (`api/books?jscmd=data` per ISBN, `search.json` a parole; note/excerpt pulite a testo puro);
7. **Amazon** — ultima rete, marketplace in ordine `.it` → `.com` → `.co.uk` (i libri in inglese matchano sui marketplace anglofoni con descrizione in lingua originale; scraping senza API pubblica: search → primi ASIN organici → pagina prodotto `productTitle`/byline/descrizione; richiede header browser-fingerprint completi, altrimenti serve un challenge `bm-verify`; CAPTCHA rilevato → marketplace successivo; max 3 pagine prodotto per marketplace con `sleep(1)` fra loro; `min_score 30` per scartare sponsored; sorgente etichettata col dominio, es. `amazon.com`).

---

## 📝 Descrizione: testo puro, sempre

- Estratta a **blocchi** dalla pagina di dettaglio IBS.it: niente code "Argomenti…", niente "Leggi di più/meno", paragrafi veri;
- serializzata in **testo puro** con paragrafi separati da riga vuota (`\n\n`) — convenzione calibre per le descrizioni non HTML. **Mai HTML arricchito** (requisito esplicito);
- scritta in `dc:description` XML-escaped verbatim: calibre la rilegge identica;
- per i fallback (Google Books / Open Library / Amazon) l'HTML delle descrizioni viene convertito in testo puro prima dell'embedding.

---

## 🧷 Integrità dell'EPUB

Lo script modifica **solo** `dc:description` e `dc:subject` nell'OPF. Mai toccati: `dc:title`, `dc:creator`, `dc:publisher`, `dc:identifier` (dentro il file — la rinomina agisce sul solo filename).

La riscrittura ZIP è conforme allo standard EPUB: **`mimetype` resta la prima entry, non compressa (`ZIP_STORED`)**.

---

## 🩺 Covalida finale (last-look)

A fine job ogni file toccato viene **riletto** e verificato (lettura non distruttiva):

1. integrità ZIP + `mimetype` prima entry STORED;
2. `dc:description` presente e in testo puro (mai markup HTML);
3. monotag: un solo `dc:subject`, uguale al tag richiesto;
4. filename conforme ad `Autore - Titolo.epub`;
5. `dc:title`/`dc:creator` identici al backup originale.

Esito: `[OK]` / `[FAIL]` con elenco dei problemi. Con monotag valido ma descrizione non disponibile (es. `not_found` su IBS) il file è `[OK]` con una **nota**, non un FAIL — coerenza col criterio monotag.

---

## 📁 Struttura dopo l'esecuzione

```
📂 cartella/
├── *.epub                  # file processati e rinominati
└── 📁 origins/             # backup degli originali (nome pre-rinomina)
```

Gli skip non modificano nulla; i file non trovati restano al loro posto (segnalati in log/JSON).

---

## 🧪 Esempi

```bash
# Ispezione di un singolo file
python3 ibs_description_embedder.py "Autore - Titolo.epub" --suggest-tags

# Prova generale su una cartella, senza toccare nulla
python3 ibs_description_embedder.py ~/Scaricati/ --dry-run

# Descrizione + tag + rinomina su tutta la cartella
python3 ibs_description_embedder.py ~/Scaricati/ --tag "Storia e Biografie"

# Solo rinomina (descrizioni già presenti verranno skipppate, ma i file
# senza monotag valido vengono comunque rinominati)
python3 ibs_description_embedder.py ~/Scaricati/ --no-rename   # ometti --no-rename per rinominare

# Risultati machine-readable
python3 ibs_description_embedder.py ~/Scaricati/ --tag "Informatica" --json | jq '.stats'
```

---

## ⚠️ Limiti noti

- **Descrizioni IBS mancanti**: alcuni titoli non hanno descrizione sul sito (`NOT_FOUND`) — il file viene comunque rinominato e, se taggato, è in regola;
- **Quota Google Books anonima** spesso esaurita (HTTP 429): serve `GOOGLE_BOOKS_API_KEY` per un uso intensivo del fallback;
- **Amazon**: scraping senza API ufficiale — soggetto a CAPTCHA/challenge; lo script li rileva e passa al marketplace successivo;
- **Sequenziale**: un file alla volta (il collo di bottiglia è la latenza di rete della catena di fallback, worst case ~10–20s/file).

---

## 🗂️ Tool legacy

Script più vecchi, mantenuti per riferimento (documentazione estesa nelle git history):

| Script | Note |
|---|---|
| `ibs_fast_metadata_search.py` | Prima generazione: scraping IBS + embedding di metadati multipli. **Contiene bug noti** (sovrascrittura title/creator dal filename, flattening `get_text(strip=True)`, rezip che rompe la convenzione `mimetype`) — non usarlo come base |
| `ibs_metadata_search.py` | Variante Playwright (lenta, ~300 MB di Chromium) |
| `gui_ibs_fast_metadata_search.py` | GUI customtkinter per il tool legacy |

---

## 📄 Licenza

Progetto a uso personale — nessuna garanzia.
