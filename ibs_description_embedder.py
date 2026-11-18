#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IBS EPUB Description Embedder
=============================

Inserisce la descrizione ufficiale di IBS.it nei metadati (dc:description)
di file EPUB, in TESTO PURO (niente HTML arricchito).

Supporta anche l'embedding del TAG classificatore (--tag): sistema
MONOTAG, un solo tag per libro, scritto come <dc:subject> nell'OPF
(l'elemento che calibre legge all'import per popolare i tag del DB).
I dc:subject pre-esistenti vengono sostituiti dal tag unico.

Basato su ibs_fast_metadata_search.py, con questi fix:
  1. Non tocca title/creator/publisher: modifica SOLO dc:description
     (niente più titoli/autori sovrascritti in minuscolo).
  2. Descrizione estratta a blocchi dalla pagina IBS: niente coda
     "Argomenti...", niente "Leggi di più/meno", niente spazi persi
     fra i blocchi ("diLa fisica" -> paragrafi separati).
  3. Descrizione in testo puro con paragrafi separati da riga vuota
     (convenzione calibre per le descrizioni non HTML).
  4. Riscrittura ZIP conforme: "mimetype" resta la prima entry,
     non compressa (STORED), come richiede lo standard EPUB.
  5. Se l'EPUB ha già una descrizione non vuota, viene saltato
     (usare --force per sovrascrivere).
  6. RINOMINA AUTOMATICA: ogni epub processato viene rinominato
     "<Autore> - <Titolo completo>.epub". Fonte del nome, in ordine di
     affidabilità: match IBS.it (titolo/autore verificati sul sito) ->
     metadati OPF interni (dc:creator/dc:title, sottotitolo EPUB3
     incluso) -> nome file attuale. I nomi vengono puliti da spazzatura
     tipo "(z-lib.org)", "[English]" e da caratteri illegali; le
     collisioni ottengono suffisso " (2)", " (3)"... L'originale non
     rinominato è sempre nel backup (origins/). Disattivabile con
     --no-rename.

Uso:
    python3 ibs_description_embedder.py <file.epub | directory> [...] [opzioni]

Opzioni:
    --force            sovrascrive anche le descrizioni esistenti
    --tag TAG          embed del tag classificatore (monotag, <dc:subject>);
                       sostituisce gli eventuali dc:subject esistenti
    --suggest-tags     non modifica nulla: stampa autore/titolo/descrizione
                       di ogni epub (JSON) per decidere il tag giusto
    --backup-dir DIR   cartella di backup degli originali (default: origins/)
    --no-rename        non rinomina i file (default: rinomina in
                       "<Autore> - <Titolo completo>.epub")
    --json             stampa i risultati anche in JSON su stdout
    --dry-run          non modifica i file, mostra solo cosa farebbe

Dipendenze: requests, beautifulsoup4
"""

import os
import re
import sys
import json
import shutil
import zipfile
import argparse
import time
import posixpath
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

# ---------------------------------------------------------------------------
# Configurazione IBS.it (API Algolia pubblica del sito)
# ---------------------------------------------------------------------------
BASE_URL = 'https://www.ibs.it/'
ALGOLIA_APP_ID = 'FBVFK8AIGY'
ALGOLIA_API_KEY = '460ca8aeaa21b30a35784e7125bfca37'
ALGOLIA_INDEX = 'prd_IBS'
ALGOLIA_URL = 'https://%s-dsn.algolia.net/1/indexes/%s/query' % (
    ALGOLIA_APP_ID.lower(), ALGOLIA_INDEX)

HEADERS = {
    'User-Agent': ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/120.0 Safari/537.36'),
    'Accept-Language': 'it-IT,it;q=0.9',
}
TIMEOUT = 30

BOILERPLATE = re.compile(
    r'leggi\s+di\s+(?:pi[ùu]|meno)|leggi\s+tutto', re.IGNORECASE)
SKIP_SECTION = re.compile(
    r'show-more|clamp-trigger|pdp-tags|accordion', re.IGNORECASE)


# ---------------------------------------------------------------------------
# Ricerca su IBS.it via API Algolia
# ---------------------------------------------------------------------------
def search_ibs(query, session):
    """Cerca libri su IBS.it tramite l'API Algolia. Ritorna lista di dict."""
    headers = {
        'X-Algolia-API-Key': ALGOLIA_API_KEY,
        'X-Algolia-Application-Id': ALGOLIA_APP_ID,
        'Content-Type': 'application/json',
        'Referer': BASE_URL,
    }
    payload = {'params': 'query=%s&hitsPerPage=15' % quote(query)}
    try:
        resp = session.post(ALGOLIA_URL, headers=headers, json=payload,
                            timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    results, seen = [], set()
    for hit in data.get('hits', []):
        ean = str(hit.get('ean') or '')
        title = (hit.get('title') or '').strip()
        product_url = hit.get('productUrl') or ''
        if not ean or not title or not product_url:
            continue
        full_url = urljoin(BASE_URL, product_url)
        if full_url in seen:
            continue
        seen.add(full_url)
        authors = hit.get('authors') or []
        results.append({
            'title': title,
            'url': full_url,
            'isbn': ean,
            'author': ', '.join(authors),
        })
    return results


def _words(text):
    """Parole significative per il matching (senza stopwords)."""
    stop = {'di', 'de', 'del', 'della', 'delle', 'dei', 'degli', 'la', 'le',
            'il', 'lo', 'gli', 'un', 'una', 'e', 'ed', 'a', 'al', 'alla',
            'per', 'con', 'in', 'su', 'da', 'the', 'of', 'a', 'an', 'to'}
    return [w for w in re.findall(r"[a-zàèéìòù0-9]+", text.lower())
            if w not in stop]


def match_score(result, author, title):
    """Punteggio di pertinenza di un risultato di ricerca."""
    a_words, t_words = _words(author), _words(title)
    rt = result['title'].lower()
    ra = result['author'].lower()
    ru = result['url'].lower()
    score = 0

    if t_words:
        matched = sum(1 for w in t_words if w in rt)
        if matched >= len(t_words):
            score += 40
            tc = re.sub(r'[^a-z0-9]', ' ', title.lower()).strip()
            rc = re.sub(r'[^a-z0-9]', ' ', rt).strip()
            if tc and (tc in rc or rc in tc):
                score += 30
        elif matched >= max(1, len(t_words) - 1):
            score += 25
        else:
            score += matched * 5
        if not any(w in rt for w in t_words):
            return -1  # nessuna parola del titolo: scartato

    if a_words:
        matched = sum(1 for w in a_words if w in ra)
        if matched >= len(a_words):
            score += 30
        elif matched >= max(1, len(a_words) - 1):
            score += 15
        elif ra:
            score -= 60  # autore completamente diverso

    slug = ru.split('/e/')[0] if '/e/' in ru else ru
    sig = a_words + t_words
    if sig:
        hits = sum(1 for w in sig if w in slug)
        if hits >= len(sig):
            score += 20
    return score


def find_book(session, author, title):
    """Cerca il libro su IBS.it. Ritorna (url, isbn) del miglior match o None."""
    query = '%s %s' % (author.replace(',', ' ').strip(), title)
    results = search_ibs(query, session)
    if not results:
        results = search_ibs(title, session)
    if not results:
        return None

    best, best_score = None, 0
    for r in results:
        s = match_score(r, author, title)
        if s > best_score:
            best, best_score = r, s
    if best is None or best_score <= 20:
        return None
    return best


# ---------------------------------------------------------------------------
# Estrazione descrizione dalla pagina di dettaglio IBS.it
# ---------------------------------------------------------------------------
def _clean_text(t):
    """Normalizza spazi; niente spazio prima della punteggiatura."""
    t = re.sub(r'\s+', ' ', t).strip()
    t = re.sub(r'\s+([,.:;!?])', r'\1', t)
    return t


def _extract_blocks(container):
    """
    Estrae i blocchi di testo della descrizione percorrendo i figli diretti
    (con ricorsione nei div di contenuto). Gestisce l'HTML malformato di IBS
    dove il testo successivo a <br> finisce DENTRO l'elemento <br>.
    Si ferma alle sezioni "show-more" / "Argomenti".
    """
    blocks = []

    def walk(el):
        for c in el.children:
            if isinstance(c, NavigableString):
                t = BOILERPLATE.sub('', _clean_text(str(c)))
                if t:
                    blocks.append(t)
            elif isinstance(c, Tag):
                if c.name == 'br':
                    t = BOILERPLATE.sub('', _clean_text(c.get_text(' ', strip=True)))
                    if t:
                        blocks.append(t)
                elif c.name == 'p':
                    t = BOILERPLATE.sub('', _clean_text(c.get_text(' ', strip=True)))
                    if t:
                        blocks.append(t)
                elif c.name in ('div', 'section'):
                    if SKIP_SECTION.search(' '.join(c.get('class', []))):
                        return True  # fine descrizione
                    if walk(c):
                        return True
        return False

    walk(container)
    # dedup di blocchi consecutivi identici
    out = []
    for b in blocks:
        if not out or out[-1] != b:
            out.append(b)
    return out


def get_description(book_url, session):
    """
    Scarica la pagina di dettaglio IBS.it ed estrae la descrizione ufficiale
    come testo puro (paragrafi separati da riga vuota). Ritorna '' se non trovata.
    """
    try:
        resp = session.get(book_url, timeout=TIMEOUT)
        resp.raise_for_status()
    except Exception:
        return ''
    soup = BeautifulSoup(resp.text, 'html.parser')

    section = soup.find('div', class_=re.compile(r'cc-em-pdp.*descrizion', re.I))
    if section:
        body = section.find('div', class_=re.compile(r'cc-em-content-body', re.I))
        container = (body.find('div', class_=re.compile(r'cc-content-text', re.I))
                     if body else None) or body or section
        blocks = _extract_blocks(container)
        if blocks:
            return '\n\n'.join(blocks)

    # Fallback: markup schema.org
    div = soup.find('div', attrs={'itemprop': 'description'})
    if div:
        t = BOILERPLATE.sub('', _clean_text(div.get_text('\n', strip=True)))
        if t:
            return t
    return ''


# ---------------------------------------------------------------------------
# Lettura/scrittura EPUB
# ---------------------------------------------------------------------------
def read_opf_path(epub_path):
    """Ritorna il percorso interno del file .opf, o None."""
    try:
        import xml.etree.ElementTree as ET
        with zipfile.ZipFile(epub_path) as z:
            tree = ET.fromstring(z.read('META-INF/container.xml'))
            for el in tree.iter():
                if el.tag.endswith('rootfile'):
                    return el.get('full-path')
    except Exception:
        pass
    return None


def read_existing_description(epub_path, opf_path):
    """Ritorna la descrizione esistente nell'OPF ('' se assente/vuota)."""
    import xml.etree.ElementTree as ET
    try:
        with zipfile.ZipFile(epub_path) as z:
            data = z.read(opf_path).decode('utf-8')
        m = re.search(r'<dc:description[^>]*>(.*?)</dc:description>',
                      data, re.S)
        if m:
            import html as _html
            return _html.unescape(m.group(1)).strip()
    except Exception:
        pass
    return ''


def rewrite_epub(epub_path, opf_path, new_description, new_tag=None):
    """
    Riscrive l'EPUB sostituendo/inserendo dc:description (testo puro,
    XML-escaped) e, se new_tag è fornito, il tag classificatore unico
    come <dc:subject> (rimuove gli eventuali dc:subject pre-esistenti:
    sistema monotag). Preserva ordine delle entry e 'mimetype' come
    prima entry non compressa.
    """
    from xml.sax.saxutils import escape

    with zipfile.ZipFile(epub_path) as z:
        data = z.read(opf_path).decode('utf-8')
        entries = [(i, z.read(i.filename)) for i in z.infolist()]

    desc_html = escape(new_description)
    if re.search(r'<dc:description[^>]*>', data):
        new_data = re.sub(
            r'(<dc:description[^>]*>).*?(</dc:description>)',
            lambda m: m.group(1) + desc_html + m.group(2),
            data, flags=re.S)
    else:
        # inserisce prima della chiusura di </metadata>
        new_data, n = re.subn(
            r'(</metadata\s*>)',
            lambda m: '<dc:description>%s</dc:description>%s' % (desc_html, m.group(1)),
            data, count=1)
        if n != 1:
            return False, 'tag </metadata> non trovato nell\'OPF'

    if new_tag:
        # sistema monotag: rimuove TUTTI i dc:subject esistenti
        new_data = re.sub(r'<dc:subject[^>]*>.*?</dc:subject>\s*', '',
                          new_data, flags=re.S)
        new_data = re.sub(r'<dc:subject[^>]*/>\s*', '', new_data)
        subj = '<dc:subject>%s</dc:subject>' % escape(new_tag)
        new_data, n = re.subn(r'(</metadata\s*>)',
                              lambda m: subj + m.group(1),
                              new_data, count=1)
        if n != 1:
            return False, 'tag </metadata> non trovato nell\'OPF (subject)'

    tmp = epub_path + '.tmp'
    with zipfile.ZipFile(tmp, 'w') as zout:
        for info, content in entries:
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = (zipfile.ZIP_STORED
                                if info.filename == 'mimetype'
                                else info.compress_type)
            zi.external_attr = info.external_attr
            zout.writestr(zi,
                          new_data.encode('utf-8')
                          if info.filename == opf_path else content)
    os.replace(tmp, epub_path)
    return True, ''


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def parse_filename(fn):
    """Formato atteso: 'Autore - Titolo.epub' (ultimo ' - ' come separatore)."""
    name = os.path.splitext(os.path.basename(fn))[0]
    parts = name.split(' - ')
    if len(parts) >= 2:
        return parts[0].strip(), parts[-1].strip()
    return '', name


# ---------------------------------------------------------------------------
# Rinomina intelligente "<Autore> - <Titolo completo>.epub"
# ---------------------------------------------------------------------------
JUNK_PAREN = re.compile(
    r'\(\s*(?:z-?lib[^)]*|libgen[^)]*|b-?ok[^)]*|calibre[^)]*|ebook[^)]*'
    r'|[^)]*\.(?:org|com|net|it)[^)]*)\s*\)', re.I)
JUNK_BRACKET = re.compile(
    r'\[\s*(?:z-?lib[^\]]*|libgen[^\]]*|unknown|english|italian[oa]?|'
    r'inglese|italiano|ita|eng|epub|pdf|converted?[^\]]*)\s*\]', re.I)
MAX_NAME = 200  # lunghezza massima del basename senza estensione


def clean_component(s):
    """Pulisce una componente del nome file: spazzatura, caratteri
    illegali, spazi multipli. ':' diventa '. ' (convenzione
    "Titolo. Sottotitolo" già usata nella libreria)."""
    s = JUNK_PAREN.sub('', s or '')
    s = JUNK_BRACKET.sub('', s)
    s = s.replace('/', ' ').replace('\\', ' ')
    s = re.sub(r'[\x00-\x1f*?<>"|]', ' ', s)
    s = re.sub(r'\s*:\s*', '. ', s)
    s = re.sub(r'\s+', ' ', s).strip(' .,-_')
    return s


def build_filename(author, title):
    """Costruisce '<Autore> - <Titolo completo>.epub' sanificato.
    Ritorna '' se entrambe le componenti sono vuote."""
    author = clean_component(author)
    title = clean_component(title)
    name = '%s - %s' % (author, title) if author and title else (author or title)
    if not name:
        return ''
    if len(name) > MAX_NAME:
        if author and len(author) + 3 < MAX_NAME - 20:
            room = MAX_NAME - len(author) - 3
            cut = title[:room]
            if ' ' in cut:
                cut = cut.rsplit(' ', 1)[0]
            name = '%s - %s' % (author, cut)
        else:
            name = name[:MAX_NAME]
            if ' ' in name:
                name = name.rsplit(' ', 1)[0]
    return name + '.epub'


def rename_epub(epub_path, new_name, dry_run=False):
    """
    Rinomina epub_path in new_name (stessa directory), gestendo le
    collisioni con suffissi ' (2)', ' (3)', ...
    Ritorna (percorso_finale, cambiato).
    """
    directory = os.path.dirname(os.path.abspath(epub_path))
    target = os.path.join(directory, new_name)
    if os.path.abspath(target) == os.path.abspath(epub_path):
        return epub_path, False
    base, ext = os.path.splitext(new_name)
    n = 2
    while os.path.exists(target):
        target = os.path.join(directory, '%s (%d)%s' % (base, n, ext))
        n += 1
    if not dry_run:
        os.rename(epub_path, target)
    return target, True


def read_opf_metadata(epub_path, opf_path):
    """
    Legge autore e titolo completo dai metadati OPF dell'EPUB.
    Ritorna (creator, title); stringhe vuote se assenti.
    Il titolo completo include l'eventuale sottotitolo EPUB3 ('Main: Subtitle').
    """
    import html as _html
    try:
        with zipfile.ZipFile(epub_path) as z:
            data = z.read(opf_path).decode('utf-8')
    except Exception:
        return '', ''

    def txt(s):
        return _html.unescape(re.sub(r'<[^>]+>', '', s)).strip()

    m = re.search(r'<dc:creator[^>]*role="aut"[^>]*>(.*?)</dc:creator>',
                  data, re.S | re.I)
    if not m:
        m = re.search(r'<dc:creator[^>]*>(.*?)</dc:creator>', data, re.S | re.I)
    author = txt(m.group(1)) if m else ''

    titles = []
    for tm in re.finditer(r'<dc:title([^>]*)>(.*?)</dc:title>', data,
                          re.S | re.I):
        idm = re.search(r'id\s*=\s*"([^"]+)"', tm.group(1))
        titles.append((idm.group(1) if idm else '', txt(tm.group(2))))
    title = next((t for _i, t in titles if t), '')

    # EPUB3: titolo completo = main + subtitle (via meta refines)
    for mm in re.finditer(r'<meta([^>]*)>(.*?)</meta>', data, re.S | re.I):
        attrs, val = mm.group(1), txt(mm.group(2))
        if 'title-type' in attrs and val.lower() == 'subtitle':
            rm = re.search(r'refines\s*=\s*"#([^"]+)"', attrs)
            if rm:
                sub = next((t for i, t in titles if i == rm.group(1)), '')
                if sub:
                    title = '%s: %s' % (title, sub) if title else sub
    return author, title


def log(msg):
    print(time.strftime('[%H:%M:%S] ') + msg, file=sys.stderr, flush=True)


def process_epub(epub_path, session, backup_dir, force, dry_run,
                 tag=None, suggest=False, rename=True):
    """Processa un EPUB. Ritorna dict con l'esito."""
    name = os.path.basename(epub_path)
    res = {'file': name, 'status': '', 'detail': ''}

    opf_path = read_opf_path(epub_path)
    if not opf_path:
        res['status'] = 'error'
        res['detail'] = 'OPF non trovato (EPUB non valido?)'
        return res

    # candidati autore/titolo: prima i metadati OPF, poi il nome file
    meta_author, meta_title = read_opf_metadata(epub_path, opf_path)
    fn_author, fn_title = parse_filename(name)
    cand_author = meta_author or fn_author
    cand_title = meta_title or fn_title
    res['author'] = cand_author
    res['title'] = cand_title

    if suggest:
        existing = read_existing_description(epub_path, opf_path)
        res['status'] = 'suggest'
        res['existing_description'] = existing
        if cand_title:
            match = find_book(session, cand_author, cand_title)
            if match:
                res['matched_url'] = match['url']
                res['isbn'] = match['isbn']
                res['description'] = get_description(match['url'], session)
            else:
                res['description'] = ''
                res['detail'] = 'nessun match su IBS.it'
        return res

    # match IBS: serve per la descrizione E per la rinomina verificata
    match = None
    if cand_author and cand_title:
        match = find_book(session, cand_author, cand_title)

    # --- rinomina intelligente "<Autore> - <Titolo completo>.epub" ---
    if rename:
        if match and match.get('title'):
            new_author = match.get('author') or cand_author
            new_title = match['title']
            src = 'ibs'
        elif meta_title:
            new_author, new_title = meta_author or cand_author, meta_title
            src = 'opf'
        else:
            new_author, new_title = cand_author, cand_title
            src = 'filename'
        desired = build_filename(new_author, new_title)
        if desired and desired != name:
            # backup dell'originale col nome attuale, poi rinomina
            if not dry_run:
                os.makedirs(backup_dir, exist_ok=True)
                backup_path = os.path.join(backup_dir, name)
                if not os.path.exists(backup_path):
                    shutil.copy2(epub_path, backup_path)
            new_path, changed = rename_epub(epub_path, desired, dry_run)
            if changed:
                res['renamed_from'] = name
                res['renamed_to'] = os.path.basename(new_path)
                res['rename_source'] = src
                epub_path = new_path
                name = res['file'] = os.path.basename(new_path)

    existing = read_existing_description(epub_path, opf_path)
    if existing and not force and not tag:
        res['status'] = 'skipped'
        res['detail'] = 'descrizione già presente (%d char)' % len(existing)
        return res

    if not cand_title:
        res['status'] = 'error'
        res['detail'] = ('titolo non determinabile: né dal nome file '
                         'né dai metadati OPF')
        return res

    if not match:
        res['status'] = 'not_found'
        res['detail'] = 'nessun match affidabile su IBS.it'
        return res

    description = get_description(match['url'], session)
    if not description:
        res['status'] = 'not_found'
        res['detail'] = 'descrizione non disponibile su %s' % match['url']
        return res

    res['matched_url'] = match['url']
    res['isbn'] = match['isbn']
    res['description_chars'] = len(description)
    res['description_preview'] = description[:120]
    if tag:
        res['tag'] = tag

    if dry_run:
        res['status'] = 'dry_run'
        return res

    # backup dell'originale (solo la prima volta)
    os.makedirs(backup_dir, exist_ok=True)
    backup_path = os.path.join(backup_dir, name)
    if not os.path.exists(backup_path):
        shutil.copy2(epub_path, backup_path)

    ok, err = rewrite_epub(epub_path, opf_path, description, tag)
    if not ok:
        res['status'] = 'error'
        res['detail'] = err
        return res

    res['status'] = 'embedded'
    res['detail'] = '%d char, %d paragrafi%s' % (
        len(description), len(description.split('\n\n')),
        (', tag="%s"' % tag) if tag else '')
    return res


def main():
    ap = argparse.ArgumentParser(
        description='Inserisce la descrizione ufficiale IBS.it nei metadati EPUB (testo puro).')
    ap.add_argument('paths', nargs='+',
                    help='file .epub o directory contenente file .epub')
    ap.add_argument('--force', action='store_true',
                    help='sovrascrive le descrizioni esistenti')
    ap.add_argument('--tag', metavar='TAG', default=None,
                    help='tag classificatore unico da embeddare (monotag)')
    ap.add_argument('--suggest-tags', action='store_true',
                    help='stampa autore/titolo/descrizione (JSON) per decidere i tag, senza modificare nulla')
    ap.add_argument('--no-rename', action='store_true',
                    help='disattiva la rinomina automatica in "<Autore> - <Titolo completo>.epub"')
    ap.add_argument('--backup-dir', default='origins',
                    help='cartella di backup degli originali (default: origins/)')
    ap.add_argument('--json', action='store_true',
                    help='stampa i risultati anche in JSON')
    ap.add_argument('--dry-run', action='store_true',
                    help='mostra solo cosa farebbe, senza modificare i file')
    args = ap.parse_args()

    epubs = []
    for p in args.paths:
        if os.path.isdir(p):
            epubs.extend(sorted(
                os.path.join(p, f) for f in os.listdir(p)
                if f.lower().endswith('.epub')))
        elif p.lower().endswith('.epub') and os.path.exists(p):
            epubs.append(p)
        else:
            print('ignorato (non trovato o non .epub): %s' % p, file=sys.stderr)
    if not epubs:
        print('nessun EPUB da processare', file=sys.stderr)
        sys.exit(1)

    session = requests.Session()
    session.headers.update(HEADERS)

    t0 = time.time()
    results = []
    for i, ep in enumerate(epubs, 1):
        log('[%d/%d] %s' % (i, len(epubs), os.path.basename(ep)[:70]))
        r = process_epub(ep, session, args.backup_dir, args.force,
                         args.dry_run, tag=args.tag, suggest=args.suggest_tags,
                         rename=not args.no_rename)
        icon = {'embedded': '[OK]', 'skipped': '[SKIP]',
                'not_found': '[MISS]', 'error': '[FAIL]',
                'dry_run': '[DRY]', 'suggest': '[SUGG]'}.get(r['status'], '[?]')
        log('   %s %s | %s' % (icon, r['status'].upper(), r['detail']))
        if r.get('renamed_to'):
            log('   [RENAME] %s -> %s (fonte: %s)' % (
                r['renamed_from'], r['renamed_to'], r.get('rename_source', '?')))
        results.append(r)

    if args.suggest_tags:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    stats = {}
    for r in results:
        stats[r['status']] = stats.get(r['status'], 0) + 1

    log('')
    log('Completato in %.1fs — %s' % (
        time.time() - t0,
        ', '.join('%s=%d' % kv for kv in sorted(stats.items()))))

    if args.json:
        print(json.dumps({'results': results, 'stats': stats},
                         ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
