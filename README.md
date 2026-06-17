# IBS EPUB Metadata Scraper

> **Arricchisci i tuoi EPUB con metadati da IBS.it** — ricerca automatica, estrazione e embedding di metadati (ISBN, editore, descrizione, lingua, pagine) direttamente nel file EPUB.

Tre script Python per cercare e incorporare metadati librari in file EPUB, partendo dal nome del file (formato `Autore - Titolo.epub`).

Include anche una **interfaccia GUI** moderna per chi preferisce non usare la riga di comando.

---

## 📋 Tabella Comparativa

| Caratteristica | `ibs_fast_metadata_search.py` 🏆 | `ibs_metadata_search.py` | `gui_ibs_fast_metadata_search.py` 🖥️ |
|---|---|---|---|
| **Tipo** | CLI | CLI | GUI (customtkinter) |
| **Sorgente** | IBS.it (API Algolia diretta) | IBS.it (Algolia via Playwright) | IBS.it (API Algolia diretta) |
| **Velocità** | ⚡ **1.1 sec/libro** | 🐢 ~8-15 sec/libro | ⚡ **come ibs_fast** |
| **Success rate** | **100%** su test 49 libri | Non testato | Come ibs_fast |
| **Browser richiesto** | ❌ Nessuno | ✅ Playwright | ❌ Nessuno |
| **Dipendenze** | `requests`, `beautifulsoup4` | `requests`, `beautifulsoup4`, `playwright` | + `customtkinter` |
| **Log in tempo reale** | ❌ Solo terminale | ❌ Solo terminale | ✅ GUI con colori |
| **Selezione directory** | CLI args | CLI args | ✅ GUI con Browse… |
| **Opzioni** | `--force`, `--json-only` | `--force`, `--json-only` | ✅ Checkboxes |

---

## 📦 Installazione

### Dipendenze comuni

```bash
pip install requests beautifulsoup4
```

### Per `ibs_fast_metadata_search.py` — solo richieste HTTP

```bash
# Nessun'altra dipendenza necessaria
```

### Per `gui_ibs_fast_metadata_search.py` — interfaccia grafica

```bash
pip install customtkinter
```

L'interfaccia GUI richiede anche `requests` e `beautifulsoup4` (già elencati sopra).

### Per `ibs_metadata_search.py` — richiede Playwright

```bash
pip install playwright
playwright install chromium
```

---

## 🚀 Utilizzo

### 🖥️ GUI (`gui_ibs_fast_metadata_search.py`)

```bash
python gui_ibs_fast_metadata_search.py
```

L'interfaccia grafica permette di:
- **Selezionare la cartella** di lavoro con un dialogo Browse…
- **Scegliere le opzioni** tramite checkbox (`--force`, `--json-only`, `--verbose`)
- **Avviare la pipeline** con un clic e **visualizzare il log in tempo reale** colorato nella finestra
- **Fermare** l'esecuzione in qualsiasi momento

> La GUI usa `customtkinter` per un look moderno e scuro, e aggiorna il log in tempo reale attraverso un thread separato.

### ⌨️ CLI

Entrambi gli script CLI condividono la stessa interfaccia a riga di comando:

```bash
python <script>.py <directory> [--force] [--json-only] [--delay N]
```

### Esempi

```bash
# Scansione interattiva (chiede conferma prima dell'embedding)
python ibs_fast_metadata_search.py ./libri/

# Solo scraping, nessun embedding (produce metadata_batch.json)
python ibs_fast_metadata_search.py ./libri/ --json-only

# Scraping + embedding automatico (nessuna conferma)
python ibs_fast_metadata_search.py ./libri/ --force

# Con delay personalizzato (solo per ibs_metadata_search)
python ibs_metadata_search.py ./libri/ --delay 2.0
```

### Argomenti

| Argomento | Default | Descrizione |
|---|---|---|
| `working_dir` | (obbligatorio) | Directory contenente i file `.epub` |
| `--force`, `-f` | `False` | Salta la conferma prima dell'embedding |
| `--json-only` | `False` | Solo scraping, salta embedding |
| `--delay` | 2.0s (ibs legacy), 0s (ibs-fast) | Delay tra richieste |
| `--verbose`, `-v` | `False` | Output verboso (non implementato in tutti) |

---

## 🧠 Script Dettaglio

### 1️⃣ `ibs_fast_metadata_search.py` — Il Più Veloce (Consigliato)

> CLI veloce consigliata per automazione e scripting.

### 1b️⃣ `gui_ibs_fast_metadata_search.py` — Interfaccia Grafica (Consigliato per uso interattivo)

> Interfaccia GUI completa che usa `ibs_fast_metadata_search.py` internamente. Ideale per chi preferisce non usare la riga di comando.

**Caratteristiche:**
- Finestra moderna con tema scuro (`customtkinter`)
- Selezione directory con dialogo nativo
- Checkbox per tutte le opzioni: `--force`, `--json-only`, `--verbose`
- Log in tempo reale colorato (verde = successo, rosso = errore, giallo = warning)
- Pulsante **Stop** per interrompere l'esecuzione
- Barra di stato con stato corrente

**Screenshot quick-start:**
```
1. Clicca "Browse…" → seleziona la cartella con i tuoi .epub
2. Spunta le opzioni desiderate:
   □ --force   (salta conferma embedding, embed automatico)
   □ --json-only (solo scraping, nessun embedding)
3. Clicca "▶ Run Pipeline"
4. Guarda il log scorrere in tempo reale nella finestra
```

### 2️⃣ `ibs_metadata_search.py` — Versione Playwright

> **Strategia**: usa **Playwright** per caricare la pagina di ricerca di IBS.it, intercettare la risposta XHR di Algolia, ed estrarre i dati strutturati dal JSON.

**Come funziona:**
1. Avvia un browser Chrome headless via Playwright
2. Naviga a `ibs.it/algolia-search?ts=as&query=...`
3. Intercetta la risposta dell'API Algolia usando `page.on('response')`
4. Estrae i dati strutturati dal JSON
5. Fa una richiesta HTTP (con `requests`) alla pagina dettaglio per descrizione e pagine
6. Opzionalmente: embedding dei metadati

**Vantaggi:**
- Robustezza (se l'API Algolia cambia, Playwright può adattarsi)
- Approccio simile a un utente reale (carica JavaScript, cookie, sessioni)

**Svantaggi:**
- 🐢 Lento (richiede ~2-3 secondi per navigazione + rendering)
- 🐘 Richiede Playwright + Chromium (~300 MB extra)
- ❌ Può fallire se Chrome non è installato o non accessibile

---

## 📁 Pipeline Output

Eseguito con `--force` su una directory, lo script:

1. **Scarica metadati** da IBS.it
2. **Copia backup originali** in `origins/`
3. **Riscrive gli EPUB** con metadati arricchiti, spostandoli in `embedded/`
4. **Sposta i non trovati** in `notfound/`
5. **Genera report HTML** e **JSON** dei risultati

### Struttura directory dopo pipeline

```
📂 libri/
├── 📁 origins/              # Backup degli EPUB originali
│   ├── Autore - Titolo.epub
│   └── ...
├── 📁 embedded/             # EPUB con metadati arricchiti
│   ├── Autore - Titolo.epub
│   └── ...
├── 📁 notfound/             # EPUB non trovati online
├── 📄 metadata_batch.json   # Metadati in formato JSON
├── 📄 pipeline_report.html  # Report HTML della pipeline
├── 📄 metadata_report.html  # Report dei metadati embeddati
└── 📄 pipeline.log          # Log dettagliato
```

### Formato `metadata_batch.json`

```json
{
  "scrape_time": "2026-05-27 12:30:00",
  "source": "ibs.it (fast)",
  "stats": {
    "total": 49,
    "success": 49,
    "failed": 0,
    "notfound": 0
  },
  "books": [
    {
      "author": "Philip K. Dick",
      "title": "L'Invasione Divina",
      "filename": "Philip K. Dick - L'Invasione Divina.epub",
      "status": "success",
      "metadata": {
        "title": "L'Invasione Divina",
        "author": "Philip K. Dick",
        "isbn": "9788804758000",
        "publisher": "Mondadori",
        "published_date": "2023",
        "pages": "384",
        "language": "it",
        "description": "...",
        "series": "Oscar fantastica",
        "matched_url": "https://www.ibs.it/..."
      }
    }
  ]
}
```

---

## 🏆 Raccomandazioni

| Scenario | Script consigliato |
|---|---|
| **Uso interattivo** — massima semplicità | `gui_ibs_fast_metadata_search.py` |
| **Uso quotidiano** — massima velocità e qualità | `ibs_fast_metadata_search.py` |
| **IBS.it cambia API** — fallback con Playwright | `ibs_metadata_search.py` |

---

## 🧪 Esempi Avanzati

### 🔀 Usare jq per interrogare i risultati JSON

Dopo uno scraping con `--json-only`, puoi analizzare il JSON con `jq`:

```bash
# Libri con più di 300 pagine
cat metadata_batch.json | jq '.books[] | select(.metadata.pages | tonumber? // 0 > 300) | "\(.author) - \(.title) (\(.metadata.pages) pp)"'

# Libri per editore
cat metadata_batch.json | jq '.books[] | .metadata.publisher' | sort | uniq -c | sort -rn

# Libri per anno di pubblicazione
cat metadata_batch.json | jq '.books[] | .metadata.published_date' | sort | uniq -c | sort -rn

# Libri senza ISBN (anomalie)
cat metadata_batch.json | jq '.books[] | select(.metadata.isbn == "") | .filename'

# Statistiche rapide
cat metadata_batch.json | jq '{total: .stats.total, success: .stats.success, pct: (.stats.success / .stats.total * 100 | floor)}'
```

### 🔀 Confrontare due esecuzioni sullo stesso dataset

```bash
# Esegui lo script con --json-only due volte (es. con parametri diversi) e confronta
python ibs_fast_metadata_search.py ./libri/ --json-only
mv metadata_batch.json metadata_batch_run1.json

python ibs_fast_metadata_search.py ./libri/ --json-only --delay 1.0
mv metadata_batch.json metadata_batch_run2.json

# Diff tra i due JSON
jq -r '.books[] | .filename' metadata_batch_run1.json | sort > run1_files.txt
jq -r '.books[] | .filename' metadata_batch_run2.json | sort > run2_files.txt
diff run1_files.txt run2_files.txt
```

### 🎯 Estrarre solo un campo specifico per tutti i libri

```bash
# Output: ISBN,Autore,Titolo,Pagine
cat metadata_batch.json | jq -r '.books[] | select(.status == "success") | [.metadata.isbn, .author, .title, .metadata.pages] | @csv' > isbn_list.csv
```

### 🔁 Riprocessare solo i libri non trovati

```bash
python ibs_fast_metadata_search.py ./libri/ --json-only

# Estrai i libri non trovati
jq -r '.books[] | select(.status != "success") | .filename' metadata_batch.json > notfound.txt

# Crea una directory con solo i non trovati e riprova
mkdir -p ./retry
while IFS= read -r f; do
    cp "./libri/$f" ./retry/
done < notfound.txt

# Riprova con lo script legacy (Playwright)
python ibs_metadata_search.py ./retry/ --force
```

### 📦 Batch processing: più directory in sequenza

```bash
# Processa tutte le directory di libri in una cartella padre
for dir in /path/to/libri/*/; do
    echo "=== Processing $dir ==="
    python ibs_fast_metadata_search.py "$dir" --json-only
    mv "$dir/metadata_batch.json" "$dir/metadata_$(date +%Y%m%d).json"
done

# Con parallel GNU per eseguire più directory in parallelo
echo "/path/to/libri/fiction
/path/to/libri/saggistica
/path/to/libri/ebooks" | parallel 'python ibs_fast_metadata_search.py {} --json-only 2>&1 | tee {}/pipeline.log'
```

### ⏰ Automazione con cron

```bash
# Ogni domenica alle 3:00, processa una directory
# Aggiungi a crontab -e:
# 0 3 * * 0 cd /home/utente/epubsearch_ibs && python ibs_fast_metadata_search.py /home/utente/libri/ --force >> /home/utente/libri/cron.log 2>&1
```

**`run_pipeline.sh`:**
```bash
#!/bin/bash
# Processa 3 directory in sequenza, con log separati
DIRS=("/home/libri/raccolte/" "/home/libri/novita/" "/home/libri/saggi/")
DATE=$(date +%F)

for dir in "${DIRS[@]}"; do
    if [ -d "$dir" ]; then
        echo "[$(date)] Processing $dir"
        python /home/utente/epubsearch_ibs/ibs_fast_metadata_search.py "$dir" --force \
            >> "$dir/pipeline_$DATE.log" 2>&1
        echo "[$(date)] Done: $dir"
    fi
done
```

### 🔍 Grep avanzato nel log

```bash
# Libri non trovati (rosso nel log = stringa FAIL)
grep '\[FAIL\]' pipeline.log

# Libri embeddati con successo
grep 'EMBEDDED' pipeline.log

# Tempo totale di esecuzione
grep 'Total time' pipeline.log

# Statistiche finali
grep -A5 'PIPELINE COMPLETED' pipeline.log
```

### 📋 Creare un report personalizzato con pipe

```bash
# Genera un sommario — log in console + JSON salvato + report testuale
python ibs_fast_metadata_search.py ./libri/ --json-only 2>&1 | tee pipeline.log

# Processa il JSON generato per estrarre solo i dati che ti servono
jq -r '.books[] | select(.status == "success") | "\(.metadata.isbn) - \(.author): \(.title)"' \
    metadata_batch.json > report.txt
```

### 🩺 Verifica rapida dell'embedding

```bash
# Controlla che gli EPUB embeddati abbiano i metadati corretti
for epub in ./embedded/*.epub; do
    title=$(unzip -p "$epub" META-INF/container.xml | grep -oP 'full-path="\K[^"]+' | xargs -I{} sh -c 'unzip -p "$1" "$2"' _ "$epub" {} | grep -oP '<dc:title>[^<]+' | head -1 | sed 's/<dc:title>//')
    isbn=$(unzip -p "$epub" META-INF/container.xml | grep -oP 'full-path="\K[^"]+' | xargs -I{} sh -c 'unzip -p "$1" "$2"' _ "$epub" {} | grep -oP '<dc:identifier>[^<]+' | head -1 | sed 's/<dc:identifier>//')
    echo "$epub → $title | $isbn"
done
```

### 🗑️ Cleanup rapido

```bash
# Rimuovi tutti i file generati dalla pipeline, mantieni solo gli EPUB
rm -rf origins/ embedded/ notfound/
rm -f metadata_batch.json pipeline_report.html metadata_report.html pipeline.log
```

---

## 🔧 Note Tecniche

### Regex Escaping

Una versione precedente di `ibs_fast_metadata_search.py` conteneva regex con doppio escaping (`\\s`, `\\d`, `\\\\[`). Questo è stato corretto — il file attuale usa il corretto escaping singolo.

Vedere `MEMO_regex_escaping.md` per i dettagli.

### Nome File Atteso

Il parser assume il formato standard:

```
Autore - Titolo.epub
```

Casi particolari gestiti automaticamente:
- **Alias/username**: rimossi (`/@[a-z]+/`)
- **Virgole**: normalizzate
- **Sottotitoli**: ignorati (viene preso solo l'ultimo ` - `)

---

## 📊 Test Real-World

Test eseguito su **49 EPUB** italiani con `ibs_fast_metadata_search.py`:

| Metrica | IBS.it Fast |
|---|---|
| Tempo totale scraping | **54.5 sec** |
| Tempo per libro | **~1.1 sec** |
| Success rate | **100%** (49/49) |
| Con ISBN | **49/49** |
| Con editore | **49/49** |
| Con descrizione | **49/49** |
| Con pagine | **46/49** |

---

## 🔧 Troubleshooting

### `ModuleNotFoundError: No module named 'requests'`

Manca la libreria `requests`. Installala:
```bash
pip install requests
```
Se usi Python 3 in un ambiente virtuale, attivalo prima.

---

### `ModuleNotFoundError: No module named 'bs4'`

Manca `beautifulsoup4`:
```bash
pip install beautifulsoup4
```

---

### `Error: playwright library not found` (solo `ibs_metadata_search.py`)

Playwright è necessario solo per lo script legacy. Se usi `ibs_fast_metadata_search.py` puoi ignorare questo warning.
Per installarlo:
```bash
pip install playwright
playwright install chromium
```

---

### `'NoneType' object has no attribute 'get_text'` o simili AttributeError

IBS.it potrebbe aver modificato il markup HTML delle pagine dettaglio. Lo script fallisce perché non trova i selector CSS attesi.

**Soluzione:**
- Usa `--json-only` e controlla `metadata_batch.json` per vedere se la struttura Algolia è ancora valida
- Se l'API Algolia è cambiata, la versione Playwright (`ibs_metadata_search.py`) potrebbe funzionare come fallback

---

### `404 Client Error` o `Timeout` durante lo scraping

Il sito potrebbe essere momentaneamente giù o la connessione di rete potrebbe essere instabile.

**Soluzioni:**
- Riprova dopo qualche minuto
- Aumenta il delay (`--delay 5.0`) per evitare rate limiting
- Per IBS Fast: l'API Algolia potrebbe richiedere nuove credenziali. Controlla la console del browser su `ibs.it` cercando richieste a `algolia.net`

---

### `SyntaxError: bad escape \u at position 0`

Errore di escaping nelle regex. Se compare, una stringa come `\u001b` è stata scritta con doppi backslash invece di uno singolo.

**Rimedio rapido:**
```bash
# Sostituisci \\u001b con \x1b nei file problematici
sed -i "s/\\\\u001b/\\x1b/g" ibs_fast_metadata_search.py
```
Vedi anche `MEMO_regex_escaping.md` per la documentazione completa del bug.

---

### Nessun risultato trovato per un libro che sicuramente esiste

Cause possibili:
- **Formato nome file errato**: deve essere `Autore - Titolo.epub`. Sottotitoli dopo un secondo ` - ` vengono ignorati.
- **Caratteri speciali**: virgolette, accenti, caratteri non ASCII possono confondere la ricerca. Prova a rinominare il file con caratteri base.
- **Libro non presente su IBS.it**: non tutti i libri italiani sono indicizzati su IBS.
- **Query troppo specifica**: lo script cerca con `autore + titolo`. Se il titolo contiene sottotitoli lunghi, potrebbero non corrispondere.

---

### `JSON saved: metadata_batch.json (0.0 KB)`

Il file JSON è stato creato vuoto — significa che nessun libro è stato processato.

**Controlla:**
- La directory contiene file `.epub`? (case-sensitive: l'estensione deve essere `.epub`, non `.EPUB` o altro)
- Lo script ha i permessi di lettura/scrittura sulla directory?

---

### `FileNotFoundError: [Errno 2] No such file or directory: '...'`

Il percorso della directory passato come argomento non esiste o è sbagliato.

**Soluzione:** usa il percorso assoluto o verifica il percorso relativo:
```bash
# Usa percorso assoluto
python ibs_fast_metadata_search.py /home/utente/Scaricati/libri/

# O verifica che il percorso relativo sia corretto
ls ./libri/
```

---

### Embedding fallito con `'no container.xml'` o `'no content.opf'`

Il file EPUB non è valido o è danneggiato. Lo script non riesce ad accedere alla sua struttura interna.

**Verifica manuale:**
```bash
# Controlla se l'EPUB è un valido archivio ZIP
unzip -l libro.epub | head -20
# Deve contenere META-INF/container.xml e un file .opf
```

---

### `PermissionError: [Errno 13] Permission denied`

Lo script non ha permessi di scrittura sulla directory o sui file EPUB.

**Soluzione:**
```bash
# Dai permessi di scrittura
chmod -R u+w /home/utente/Scaricati/libri/
```

---

## 📄 Licenza

Progetto a uso personale — nessuna garanzia.
