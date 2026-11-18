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
     incluso) -> nome file attuale. Il match usa la catena: EAN/ISBN
     esatto (dc:identifier o filename numerico, ISBN-10 convertito in
     EAN-13) -> ricerca a parole autore+titolo -> ricerca con ruoli
     invertiti (file "Titolo - Autore") -> deep scan delle prime
     pagine (lettura non distruttiva) -> GOOGLE BOOKS (fallback per i
     libri stranieri non a catalogo IBS; la descrizione Google viene
     convertita in testo puro). Il parse del filename è tollerante con
     gli underscore ('_-_'). I nomi vengono puliti da spazzatura tipo
     "(z-lib.org)", "[English]" e da caratteri illegali; le collisioni
     ottengono suffisso " (2)", " (3)"... L'originale non rinominato è
     sempre nel backup (origins/). Disattivabile con --no-rename.

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
GOOGLE_BOOKS_URL = 'https://www.googleapis.com/books/v1/volumes'
OPENLIB_URL = 'https://openlibrary.org'
# opzionale: chiave API gratuita di Google Cloud per sollevare la quota
# anonima (spesso esaurita: HTTP 429). Env: GOOGLE_BOOKS_API_KEY
GOOGLE_API_KEY = os.environ.get('GOOGLE_BOOKS_API_KEY', '')
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
def _hit_to_result(hit):
    """Converte un hit Algolia nel dict risultato interno, o None."""
    ean = str(hit.get('ean') or '')
    title = (hit.get('title') or '').strip()
    product_url = hit.get('productUrl') or ''
    if not ean or not title or not product_url:
        return None
    return {
        'title': title,
        'url': urljoin(BASE_URL, product_url),
        'isbn': ean,
        'author': ', '.join(hit.get('authors') or []),
    }


def _algolia_query(session, query, hits_per_page=15):
    """Esegue una query sull'API Algolia di IBS. Ritorna la lista di hit."""
    headers = {
        'X-Algolia-API-Key': ALGOLIA_API_KEY,
        'X-Algolia-Application-Id': ALGOLIA_APP_ID,
        'Content-Type': 'application/json',
        'Referer': BASE_URL,
    }
    payload = {'params': 'query=%s&hitsPerPage=%d'
               % (quote(query), hits_per_page)}
    try:
        resp = session.post(ALGOLIA_URL, headers=headers, json=payload,
                            timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json().get('hits', [])
    except Exception:
        return []


def search_ibs(query, session):
    """Cerca libri su IBS.it tramite l'API Algolia. Ritorna lista di dict."""
    results, seen = [], set()
    for hit in _algolia_query(session, query):
        r = _hit_to_result(hit)
        if not r or r['url'] in seen:
            continue
        seen.add(r['url'])
        results.append(r)
    return results


def find_book_by_ean(session, ean):
    """Cerca su IBS per EAN/ISBN: match esatto sul campo 'ean' dell'indice.
    Ritorna il dict risultato o None."""
    for hit in _algolia_query(session, ean, hits_per_page=5):
        if str(hit.get('ean') or '') == ean:
            r = _hit_to_result(hit)
            if r:
                return r
    return None


def isbn10_to_ean(isbn10):
    """Converte un ISBN-10 in EAN-13 (prefisso 978, check digit ricalcolato)."""
    core = '978' + isbn10[:9]
    if not core.isdigit():
        return ''
    total = sum((1 if i % 2 == 0 else 3) * int(d) for i, d in enumerate(core))
    return core + str((10 - total % 10) % 10)


def extract_ean(epub_path, opf_path):
    """Estrae un EAN/ISBN dai dc:identifier dell'OPF ('' se assente).
    Preferisce gli EAN-13; gli ISBN-10 vengono convertiti in EAN-13."""
    import html as _html
    try:
        with zipfile.ZipFile(epub_path) as z:
            data = z.read(opf_path).decode('utf-8')
    except Exception:
        return ''
    idents = []
    for m in re.finditer(r'<dc:identifier[^>]*>(.*?)</dc:identifier>',
                         data, re.S | re.I):
        v = _html.unescape(re.sub(r'<[^>]+>', '', m.group(1))).strip()
        v = re.sub(r'(?i)^urn:isbn:', '', v)
        v = v.replace('-', '').replace(' ', '').upper()
        if re.fullmatch(r'\d{9}[\dX]|\d{13}', v):
            idents.append(v)
    for v in idents:
        if len(v) == 13 and v.isdigit():
            return v
    for v in idents:
        if len(v) == 10:
            ean = isbn10_to_ean(v)
            if ean:
                return ean
    return ''


# ---------------------------------------------------------------------------
# Deep scan: lettura NON distruttiva delle prime pagine dell'EPUB
# ---------------------------------------------------------------------------
def read_first_pages_text(epub_path, opf_path, max_docs=6, max_chars=8000):
    """
    Legge (SOLO lettura, nessuna modifica) le prime pagine del documento
    seguendo lo spine dell'OPF: title page + pagina di copyright.
    Ritorna la lista dei testi, uno per documento ('' se non disponibile)."""
    import html as _html
    try:
        with zipfile.ZipFile(epub_path) as z:
            data = z.read(opf_path).decode('utf-8')
            items = {}
            for m in re.finditer(r'<item\b[^>]*>', data):
                tag = m.group(0)
                idm = re.search(r'id="([^"]+)"', tag)
                hm = re.search(r'href="([^"]+)"', tag)
                mt = re.search(r'media-type="([^"]+)"', tag)
                if idm and hm:
                    items[idm.group(1)] = (hm.group(1),
                                           mt.group(1) if mt else '')
            spine = re.findall(r'<itemref[^>]*idref="([^"]+)"', data)
            base = posixpath.dirname(opf_path)
            chunks = []
            total = 0
            for idref in spine:
                if total >= max_chars or len(chunks) >= max_docs:
                    break
                doc = items.get(idref)
                if not doc:
                    continue
                href, mtype = doc
                if mtype and 'html' not in mtype:
                    continue
                if not re.search(r'\.(x?html|htm)$', href, re.I) and not mtype:
                    continue
                path = posixpath.normpath(
                    posixpath.join(base, href)) if base else href
                try:
                    raw = z.read(path).decode('utf-8', 'replace')
                except Exception:
                    continue
                raw = re.sub(r'<(script|style)\b.*?</\1>', ' ', raw,
                             flags=re.S | re.I)
                txt = _html.unescape(re.sub(r'<[^>]+>', '\n', raw))
                lines = [l.strip() for l in txt.splitlines() if l.strip()]
                if lines:
                    chunks.append('\n'.join(lines))
                    total += len(chunks[-1])
            return chunks
    except Exception:
        return []


def extract_isbns_from_text(text):
    """Estrae gli ISBN dal testo delle prime pagine (con etichetta 'ISBN'
    o EAN-13 nudi 978/979). Ritorna lista deduplicata, in ordine."""
    found = []
    for m in re.finditer(
            r'ISBN(?:[-:\s]*(?:13|10))?\s*[:\-]?\s*'
            r'([0-9][0-9\- ]{8,28}[0-9Xx])', text, re.I):
        v = m.group(1).replace('-', '').replace(' ', '').upper()
        if re.fullmatch(r'\d{9}[\dX]|\d{13}', v) and v not in found:
            found.append(v)
    for m in re.finditer(r'\b(97[89]\d{10})\b', text):
        if m.group(1) not in found:
            found.append(m.group(1))
    return found


def title_candidates_from_text(text, max_cands=3):
    """Candidati titolo dalle prime righe delle prime pagine (per la
    ricerca a parole su IBS quando non c'e' nessun ISBN). Solo righe
    con almeno 2 parole e 8 caratteri: le righe frammentate o di
    impaginazione producono falsi positivi."""
    cands = []
    for line in text.splitlines():
        l = line.strip()
        if not (8 <= len(l) <= 120):
            continue
        if re.search(r'isbn|www|http|https?|©|copyright|all rights|'
                     r'edizione|traduzione|stampa|volume\s+\d', l, re.I):
            continue
        if re.search(r'^page\s+\d+\s+(?:of|/)\s+\d+', l, re.I) or \
                re.fullmatch(r'[\d\s.,;:\-–—]+', l):
            continue
        if len(re.findall(r'[A-Za-zàèéìòùÀÈÉÌÒÙ]{2,}', l)) < 2:
            continue
        if l not in cands:
            cands.append(l)
        if len(cands) >= max_cands:
            break
    return cands


def deep_scan_match(session, epub_path, opf_path):
    """
    Ultima rete per file senza metadati né filename significativo:
    lettura NON distruttiva delle prime pagine (title page, copyright),
    estrazione di ISBN/autore/titolo e match su IBS.
    Ritorna il dict risultato o None."""
    pages = read_first_pages_text(epub_path, opf_path)
    if not pages:
        return None
    # 1) ISBN trovati nelle prime pagine -> match esatto per EAN
    text_all = '\n'.join(pages)
    for isbn in extract_isbns_from_text(text_all):
        ean = isbn if len(isbn) == 13 else isbn10_to_ean(isbn)
        if ean:
            m = find_book_by_ean(session, ean)
            if m:
                return m
    # 2) nessun ISBN utile -> SOLO le righe della prima pagina (title
    #    page) come titolo, con soglia severa (45) contro i falsi
    #    positivi: il corpo del testo produce solo frammenti inaffidabili
    for cand in title_candidates_from_text(pages[0]):
        m = find_book(session, '', cand, min_score=45)
        if m:
            return m
    return None


# ---------------------------------------------------------------------------
# Fallback Google Books (libri stranieri non a catalogo IBS)
# ---------------------------------------------------------------------------
def clean_google_description(html_desc):
    """Converte la descrizione HTML di Google Books in TESTO PURO
    (paragrafi separati da riga vuota): regola utente, mai HTML arricchito."""
    if not html_desc:
        return ''
    import html as _html
    t = re.sub(r'<(script|style)\b.*?</\1>', ' ', html_desc,
               flags=re.S | re.I)
    t = re.sub(r'<br\s*/?>|</p>|</div>|</h\d>', '\n\n', t, flags=re.I)
    t = re.sub(r'<[^>]+>', ' ', t)
    t = _html.unescape(t)
    paras = [re.sub(r'\s+', ' ', p).strip()
             for p in re.split(r'\n\s*\n', t)]
    return '\n\n'.join(p for p in paras if p)


def search_google_books(session, query, ean=None, author='', title='',
                        min_score=0):
    """Cerca su Google Books (fallback per libri non a catalogo IBS).
    Con ean: match esatto sugli industryIdentifiers. Con min_score:
    scarta i risultati poco pertinenti (match_score). Ritorna un dict
    compatibile con i risultati IBS (+ 'source': 'google') o None."""
    try:
        params = {'q': query, 'maxResults': 10}
        if GOOGLE_API_KEY:
            params['key'] = GOOGLE_API_KEY
        resp = session.get(GOOGLE_BOOKS_URL, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        items = resp.json().get('items', [])
    except Exception:
        return None
    for item in items:
        info = item.get('volumeInfo') or {}
        title = (info.get('title') or '').strip()
        if not title:
            continue
        if ean:
            gids = [(i.get('identifier') or '').replace('-', '')
                    for i in (info.get('industryIdentifiers') or [])]
            if ean not in gids:
                continue
        subtitle = (info.get('subtitle') or '').strip()
        full_title = '%s: %s' % (title, subtitle) if subtitle else title
        r = {
            'title': full_title,
            'url': info.get('infoLink')
                   or info.get('canonicalVolumeLink') or '',
            'isbn': ean or '',
            'author': ', '.join(info.get('authors') or []),
            'source': 'google',
            'description': clean_google_description(
                info.get('description') or ''),
        }
        if min_score and match_score(r, author, title) < min_score:
            continue
        return r
    return None


def _ol_clean_text(t):
    """Testo puo' da note/excerpt Open Library (possono contenere HTML)."""
    if not t:
        return ''
    import html as _html
    if isinstance(t, dict):
        t = t.get('value') or ''
    t = re.sub(r'<(script|style)\b.*?</\1>', ' ', t, flags=re.S | re.I)
    t = re.sub(r'<br\s*/?>|</p>|</div>', '\n\n', t, flags=re.I)
    t = re.sub(r'<[^>]+>', ' ', t)
    t = _html.unescape(t)
    paras = [re.sub(r'\s+', ' ', p).strip()
             for p in re.split(r'\n\s*\n', t)]
    return '\n\n'.join(p for p in paras if p)


def search_openlibrary(session, ean=None, author='', title='', min_score=0):
    """Fallback Open Library (API libera, nessuna chiave): prima match
    esatto per ISBN, poi ricerca a parole. Ritorna un dict compatibile
    con i risultati IBS (+ 'source': 'openlibrary') o None."""
    if ean:
        try:
            resp = session.get(
                '%s/api/books' % OPENLIB_URL,
                params={'bibkeys': 'ISBN:%s' % ean, 'format': 'json',
                        'jscmd': 'data'}, timeout=TIMEOUT)
            resp.raise_for_status()
            data = (resp.json() or {}).get('ISBN:%s' % ean) or {}
            if data.get('title'):
                return {
                    'title': data['title'],
                    'url': data.get('url') or '',
                    'isbn': ean,
                    'author': ', '.join(a.get('name', '')
                                        for a in data.get('authors') or []),
                    'source': 'openlibrary',
                    'description': _ol_clean_text(
                        data.get('excerpt') or data.get('notes') or ''),
                }
        except Exception:
            pass
    if title:
        try:
            q = '%s %s' % (author, title) if author else title
            resp = session.get('%s/search.json' % OPENLIB_URL,
                               params={'q': q, 'limit': 5}, timeout=TIMEOUT)
            resp.raise_for_status()
            for doc in (resp.json() or {}).get('docs', []):
                t = (doc.get('title') or '').strip()
                if not t:
                    continue
                sub = (doc.get('subtitle') or '').strip()
                full = '%s: %s' % (t, sub) if sub else t
                r = {
                    'title': full,
                    'url': '%s%s' % (OPENLIB_URL, doc.get('key', '')),
                    'isbn': ean or '',
                    'author': ', '.join(doc.get('author_name') or []),
                    'source': 'openlibrary',
                    'description': '',
                }
                if min_score and match_score(r, author, title) < min_score:
                    continue
                return r
        except Exception:
            pass
    return None


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


def find_book(session, author, title, min_score=20):
    """Cerca il libro su IBS.it. Ritorna (url, isbn) del miglior match
    sopra min_score, o None."""
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
    if best is None or best_score < min_score:
        return None
    return best


def find_book_smart(session, epub_path, opf_path, cand_author, cand_title,
                    name):
    """Catena di match IBS in ordine di affidabilità:
    1) EAN/ISBN esatto (dc:identifier dell'OPF, o filename numerico
       tipo ISBN; ISBN-10 convertito in EAN-13);
    2) ricerca a parole autore+titolo;
    3) ricerca con ruoli invertiti (file "Titolo - Autore").
    Ritorna il dict risultato o None."""
    ean = extract_ean(epub_path, opf_path)
    if not ean:
        stem = os.path.splitext(os.path.basename(name))[0]
        if re.fullmatch(r'\d{9}[\dXx]|\d{13}', stem):
            raw = stem.upper()
            ean = raw if len(raw) == 13 else isbn10_to_ean(raw)
    if ean:
        m = find_book_by_ean(session, ean)
        if m:
            return m
    if cand_author and cand_title:
        m = find_book(session, cand_author, cand_title)
        if m:
            return m
        m = find_book(session, cand_title, cand_author)
        if m:
            return m
    # 4) deep scan: prime pagine dell'EPUB (lettura non distruttiva)
    m = deep_scan_match(session, epub_path, opf_path)
    if m:
        return m
    # 5) Google Books: fallback per libri stranieri non a catalogo IBS
    if ean:
        m = search_google_books(session, 'isbn:%s' % ean, ean=ean)
        if m:
            return m
    if cand_author and cand_title:
        m = search_google_books(
            session, '%s %s' % (cand_author, cand_title),
            author=cand_author, title=cand_title, min_score=30)
        if m:
            return m
    # 6) Open Library: seconda rete senza chiavi API
    m = search_openlibrary(session, ean=ean, author=cand_author,
                           title=cand_title, min_score=30)
    if m:
        return m
    return None


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


def parse_filename_loose(fn):
    """Parse tollerante: normalizza '_' in spazi (e spazi multipli) prima
    di separare autore e titolo. Rete di sicurezza per i nomi tipo
    'All_the_Queens_Men_-_Sophie_Shorland.epub'."""
    name = os.path.splitext(os.path.basename(fn))[0]
    name = re.sub(r'\s+', ' ', name.replace('_', ' ')).strip()
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
    # (strict, poi loose con '_' normalizzati in spazi)
    meta_author, meta_title = read_opf_metadata(epub_path, opf_path)
    fn_author, fn_title = parse_filename(name)
    if not (fn_author and fn_title):
        la, lt = parse_filename_loose(name)
        fn_author = fn_author or la
        fn_title = fn_title or lt
    cand_author = meta_author or fn_author
    cand_title = meta_title or fn_title
    res['author'] = cand_author
    res['title'] = cand_title

    if suggest:
        existing = read_existing_description(epub_path, opf_path)
        res['status'] = 'suggest'
        res['existing_description'] = existing
        if cand_title:
            match = find_book_smart(session, epub_path, opf_path,
                                    cand_author, cand_title, name)
            if match:
                res['matched_url'] = match['url']
                res['isbn'] = match['isbn']
                res['match_source'] = match.get('source', 'ibs')
                if match.get('source') == 'google':
                    res['description'] = match.get('description') or ''
                else:
                    res['description'] = get_description(match['url'],
                                                        session)
            else:
                res['description'] = ''
                res['detail'] = 'nessun match (IBS.it / Google Books)'
        return res

    # match IBS: serve per la descrizione E per la rinomina verificata
    match = find_book_smart(session, epub_path, opf_path,
                            cand_author, cand_title, name)

    # --- rinomina intelligente "<Autore> - <Titolo completo>.epub" ---
    if rename:
        if match and match.get('title'):
            new_author = match.get('author') or cand_author
            new_title = match['title']
            src = match.get('source', 'ibs')
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
        res['detail'] = 'nessun match affidabile (IBS.it / Google Books)'
        return res

    if match.get('source') == 'google':
        description = match.get('description') or ''
    else:
        description = get_description(match['url'], session)
    if not description:
        res['status'] = 'not_found'
        res['detail'] = 'descrizione non disponibile su %s' % match['url']
        return res

    res['matched_url'] = match['url']
    res['isbn'] = match['isbn']
    res['match_source'] = match.get('source', 'ibs')
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
