# TAGGING_RULES.md — Sistema di classificazione della libreria Calibre

> Regole ufficiali per l'attribuzione del tag classificatore ai libri della
> libreria `/mnt/TOSHIBA4/CalibreLibraryz83/Calibre Library` (24.665 volumi).
>
> **Chi decide il tag:** l'assistente AI (nanobot), sulla base di titolo,
> autore e descrizione ufficiale del libro.
> **Chi lo scrive nell'EPUB:** `ibs_description_embedder.py --tag "TAG"`
> (l'embedder non decide mai: esegue solo).

---

## 1. Struttura del sistema: 31 tag, 2 livelli

### 1a. 14 macro-categorie (per tutta la libreria)

| Tag | Ambito (cosa ci va) |
|---|---|
| **Filosofia Mitologia Religione** | Filosofia (storia e testi), teologia, religioni e tradizioni spirituali, mitologia, esoterismo "classico" e studi religiosi. Categoria più popolata (~21%). |
| **Storia e Biografie** | Storia in ogni ambito (antica, medievale, moderna, contemporanea), biografie, autobiografie, memorie, diari. (~21%) |
| **Letteratura Romanzi e Racconti** | Narrativa: romanzi, racconti, poesia, teatro, classici e contemporanei, letteratura straniera tradotta. (~15%) |
| **Medicina Psicologia Benessere** | Medicina e divulgazione medica, psicologia, psichiatria, salute, benessere, alimentazione salutistica. |
| **Ricette Faidate TempoLibero** | Cucina e ricette, hobby, fai-da-te, giardinaggio, sport, giochi, manuali pratici del tempo libero. |
| **Società e Costume** | Sociologia, antropologia, costume, attualità, politica, questioni sociali, gender, migrazioni. |
| **Arte Musica Spettacolo** | Storia dell'arte, artisti, architettura, cinema, teatro, musica, fotografia, design. |
| **Scienza** | Scienza GENERICA o trasversale: ambiente, ecologia, biologia, zoologia, divulgazione scientifica mista, storia della scienza. È la categoria "resto" scientifica. |
| **Fisica Astrofisica Astronomia** | Fisica in senso lato (classica, quantistica, particellare), cosmologia, astrofisica, astronomia, divulgazione fisica (Kaku, Feynman, Hawking...). |
| **Informatica** | Informatica, programmazione, computer, tecnologia digitale, AI, internet. |
| **Viaggi e Avventura** | Diari di viaggio, esplorazioni, avventure, montagna, reportage geografici. |
| **Matematica** | Matematica, logica, divulgazione matematica, statistica divulgativa. |
| **Misteri Fantastico Esoterismo** | Gialli/mystery non "letteratura", fantasy, paranormali, ufologia, esoterismo popolare. |
| **Enciclopedie Dizionari Manuali** | Opere di riferimento: enciclopedie, dizionari, atlanti, manuali generali. |

### 1b. 15 tag "Scuola" (solo materiale scolastico/didattico)

Riservati a libri di testo, manuali scolastici, antologie per lo studio,
dispense. **Un saggio divulgativo NON è "Scuola *"** anche se tratta la
stessa materia.

Scuola Arte · Scuola Biologia · Scuola Chimica · Scuola Diritto e Economia ·
Scuola Economia Aziendale · Scuola Economia Politica · Scuola Filosofia ·
Scuola Fisica · Scuola Geografia · Scuola Informatica · Scuola Latino ·
Scuola Lingua Italiana e Letteratura · Scuola Lingue · Scuola Matematica ·
Scuola Storia

### 1c. Tag legacy (solo nella vecchia libreria, NON usare)

`Guida`, `calibre` — tag di servizio storici, presenti solo in
`/mnt/TOSHIBA4/CalibreLibrary` (2 libri). Non assegnare mai.

---

## 2. Criteri di scelta (in ordine di priorità)

1. **Coerenza con il sistema esistente.** Prima di assegnare un tag,
   verificare come sono classificati libri simili nella libreria
   (query su `metadata.db`). La logica implicita del sistema prevale
   su qualsiasi definizione astratta.
2. **Il dominio del CONTENUTO, non dell'autore.** Un astrofisico che
   scrive di cucina va in "Ricette Faidate TempoLibero". Conta l'argomento
   reale, desunto da titolo + descrizione ufficiale.
3. **Categoria più specifica se il libro è monografico.** Fisica vera →
   "Fisica Astrofisica Astronomia"; scienza generica/trasversale
   (ambiente, biologia, misc) → "Scienza". Se il libro tocca molte
   discipline o nessuna in particolare → categoria generica.
4. **"Scuola *" solo per materiale didattico** (manuali, antologie di
   studio, livello scolastico). Mai per divulgazione.
5. **In dubbio, decide la descrizione**, non il titolo (il titolo può
   essere evocativo/commerciale; la descrizione dice il contenuto reale).
6. **MONOTAG: un solo tag per libro, sempre.** Se il libro sembra
   appartenere a due categorie, si sceglie quella dominante — quella a cui
   si penserebbe per primo cercandolo. Mai tag multipli, mai tag nuovi
   (il sistema è chiuso a 31).

---

## 3. Workflow operativo

```bash
# 1. L'AI ottiene i materiali per decidere (nessuna modifica ai file):
python3 ibs_description_embedder.py <epub...> --suggest-tags

# 2. L'AI classifica secondo i criteri di questo documento
#    (eventualmente campionando la libreria per coerenza).

# 3. L'embedder scrive descrizione + tag (monotag):
python3 ibs_description_embedder.py <epub...> --tag "TAG SCELTO" [--force]
```

Il tag viene scritto come `<dc:subject>` nell'OPF dell'EPUB: è l'elemento
che calibre legge all'import per popolare i tag del database, quindi il
libro entra in libreria già classificato.

---

## 4. Statistiche di riferimento (2026-11-18)

- 24.665 libri, 24.622 con tag (99%), 43 senza tag, 23 con 2+ tag (anomalie)
- Macro-categorie dominanti: Filosofia Mitologia Religione (5.386),
  Storia e Biografie (5.276), Letteratura Romanzi e Racconti (3.767)
- Serie Scuola: 744 assegnazioni totali
