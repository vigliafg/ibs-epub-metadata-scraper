#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ibs_fast_metadata_search.py
# EPUB Metadata Scraper & Embedder (Fast Mode)
#
# Searches book metadata from ibs.it via **direct Algolia API** calls
# (no Playwright browser required — much faster).
# Designed for Italian language books.
#
# Usage:
#   python ibs_fast_metadata_search.py <directory> [--force] [--json-only]
#
# Requirements:
#   pip install requests beautifulsoup4

import os
import sys
import re
import json
import time
import shutil
import argparse
import datetime
import zipfile

from urllib.parse import quote, urljoin
from xml.etree import ElementTree as ET

try:
    import requests
except ImportError:
    print('Error: requests library required. Install with: pip install requests')
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print('Error: beautifulsoup4 library required. Install with: pip install beautifulsoup4')
    sys.exit(1)


# Configuration
BASE_URL = 'https://www.ibs.it'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

TIMEOUT = 30

# Algolia credentials (extracted from ibs.it frontend JS)
ALGOLIA_APP_ID = 'FBVFK8AIGY'
ALGOLIA_API_KEY = '460ca8aeaa21b30a35784e7125bfca37'
ALGOLIA_INDEX = 'prd_IBS'
ALGOLIA_URL = 'https://%s-dsn.algolia.net/1/indexes/%s/query' % (ALGOLIA_APP_ID.lower(), ALGOLIA_INDEX)

# Register Dublin Core namespaces for EPUB metadata
for prefix, uri in {
    'dc': 'http://purl.org/dc/elements/1.1/',
    'opf': 'http://www.idpf.org/2007/opf'
}.items():
    ET.register_namespace(prefix, uri)


# Session Management
_session = None

def get_session():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(HEADERS)
    return _session


# EPUB Metadata Reader
def read_epub_metadata(epub_path):
    '''Read metadata from an EPUB file. Returns dict with title, creator, language, description, publisher, identifier or None.'''
    if not os.path.exists(epub_path):
        return None
    try:
        with zipfile.ZipFile(epub_path, 'r') as zf:
            container_xml = zf.read('META-INF/container.xml')
            tree = ET.fromstring(container_xml)

            opf_path = None
            for elem in tree.iter():
                if 'rootfile' in elem.tag.lower():
                    opf_path = elem.get('full-path')
                    if opf_path:
                        break

            if not opf_path:
                for ns_uri in ['http://www.idpf.org/2007/opf', None]:
                    if ns_uri:
                        rootfiles = tree.findall('.//{%s}rootfile' % ns_uri)
                    else:
                        rootfiles = tree.findall('.//rootfile')
                    if rootfiles:
                        opf_path = rootfiles[0].get('full-path')
                        break

            if not opf_path:
                return None

            opf_content = zf.read(opf_path)
            tree = ET.fromstring(opf_content)

            ns = {'dc': 'http://purl.org/dc/elements/1.1/'}
            metadata = {}

            for tag in ['title', 'creator', 'language', 'description', 'publisher', 'identifier']:
                elem = tree.find('.//dc:%s' % tag, ns)
                if elem is None or elem.text is None:
                    for e in tree.iter():
                        t = e.tag.split('}')[-1] if '}' in e.tag else e.tag
                        if t == tag and e.text:
                            metadata[tag] = e.text.strip()
                            break
                elif elem.text:
                    metadata[tag] = elem.text.strip()

            return metadata
    except Exception:
        return None


# Utility Functions
def format_time(seconds):
    '''Format seconds into human-readable time string.'''
    if seconds < 60:
        return '%.1fs' % seconds
    elif seconds < 3600:
        return '%dm %ds' % (int(seconds // 60), int(seconds % 60))
    else:
        return '%dh %dm' % (int(seconds // 3600), int((seconds % 3600) // 60))


def strip_ansi(text):
    '''Remove ANSI color codes from text for log file output.'''
    ansi = re.compile('\u001b' + r'\[([0-9;]*)[mK]')
    return ansi.sub('', text)


# Colored Logger
class Logger:
    '''Colored console logger with file output support.'''

    RESET = '\u001b[0m'
    BOLD = '\u001b[1m'
    DIM = '\u001b[2m'
    CYAN = '\u001b[36m'
    GREEN = '\u001b[32m'
    YELLOW = '\u001b[33m'
    RED = '\u001b[31m'
    WHITE = '\u001b[37m'

    def __init__(self, log_file=None):
        self.log_file = log_file
        self.start = time.time()
        if log_file and os.path.exists(log_file):
            os.remove(log_file)

    def out(self, text):
        print(text, flush=True)
        if self.log_file:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(strip_ansi(text) + '\n')

    def log(self, color, msg):
        ts = time.strftime('%H:%M:%S')
        self.out('%s[%s]%s %s' % (color, ts, self.RESET, msg))

    def header(self, title):
        date = datetime.datetime.now().strftime('%Y-%m-%d')
        w = 76
        self.out('')
        self.out('+' + '=' * w + '+')
        self.out('| %s %s' % (title, date) + ' ' * (w - len(title) - len(date) - 3) + ' |')
        self.out('+' + '=' * w + '+')
        self.out('')

    def phase(self, num, name):
        self.out('')
        w = 76
        self.out('+' + '-' * w + '+')
        pad = w - len(name) - 18
        self.out('|  %s%s[PHASE %d/2]%s %s' % (self.CYAN, self.BOLD, num, self.RESET, name) + ' ' * pad + ' |')
        self.out('+' + '-' * w + '+')
        self.out('')

    def info(self, label, value):
        lc = '%s%s%s' % (self.CYAN, label, self.RESET)
        vc = '%s%s%s' % (self.WHITE, value, self.RESET) if value else '%sN/D%s' % (self.DIM, self.RESET)
        self.out('   |- %s: %s' % (lc, vc))

    def result(self, status, msg):
        if status == 'success':
            icon, col = 'OK', self.GREEN
        elif status == 'error':
            icon, col = 'FAIL', self.RED
        elif status == 'warning':
            icon, col = 'WARN', self.YELLOW
        else:
            icon, col = 'INFO', self.WHITE
        self.log(col, '   [%s] %s' % (icon, msg))

    def progress(self, cur, tot, filename=''):
        if tot == 0:
            return
        pct = cur / tot * 100
        w = 35
        filled = int(w * cur / tot)
        bar = '█' * filled + '░' * (w - filled)
        fn = filename[:45] + '...' if len(filename) > 45 else filename
        prefix = '%s%s[%d/%d]%s' % (self.CYAN, self.BOLD, cur, tot, self.RESET)
        print('\r   %s |%s%s%s| %5.1f%%  %s      ' % (prefix, self.CYAN, bar, self.RESET, pct, fn), end='', flush=True)

    def stats(self, stats, title='STATISTICS'):
        w = 58
        tot = stats.get('total', 0)
        ok = stats.get('success', 0)
        fail = stats.get('failed', 0)
        nf = stats.get('notfound', 0)
        self.out('')
        self.out('+' + '-' * w + '+')
        self.out('| %s' % title + ' ' * (w - len(title) - 3) + ' |')
        self.out('+' + '-' * w + '+')
        sp = ok / tot * 100 if tot else 0
        fp = fail / tot * 100 if tot else 0
        np = nf / tot * 100 if tot else 0
        self.out('| %sOK%s  Success:     %3d (%5.1f%%)' % (self.GREEN, self.RESET, ok, sp) + ' ' * (w - 34) + '|')
        self.out('| %sWARN%s Not Found:  %3d (%5.1f%%)' % (self.YELLOW, self.RESET, nf, np) + ' ' * (w - 34) + '|')
        self.out('| %sFAIL%s Failed:      %3d (%5.1f%%)' % (self.RED, self.RESET, fail, fp) + ' ' * (w - 34) + '|')
        self.out('+' + '-' * w + '+')
        self.out('')

    def phase_done(self, num, elapsed, stats=None):
        t = format_time(elapsed)
        w = 68
        self.out('')
        self.out('+' + '-' * w + '+')
        pad = w - 36 - len(t)
        self.out('|  %s[PHASE %d] COMPLETED in %s%s' % (self.GREEN, num, t, self.RESET) + ' ' * pad + ' |')
        self.out('+' + '-' * w + '+')
        if stats:
            self.stats(stats, 'Phase %d Results' % num)

    def summary(self, total, folders, files):
        self.out('')
        w = 76
        self.out('+' + '=' * w + '+')
        self.out('| %s%sPIPELINE COMPLETED%s%s' % (self.CYAN, self.BOLD, self.RESET, '') + ' ' * (w - 22) + ' |')
        self.out('+' + '=' * w + '+')
        self.out('')
        self.out('   %sFolders created:%s' % (self.BOLD, self.RESET))
        for fld, cnt in folders.items():
            self.out('      %-12s -> %3d files' % (fld, cnt))
        self.out('')
        self.out('   %sFiles generated:%s' % (self.BOLD, self.RESET))
        for fn, sz in files.items():
            self.out('      %-25s (%s)' % (fn, sz))
        self.out('')
        self.out('   %sTotal time:%s %s' % (self.BOLD, self.RESET, format_time(total)))
        self.out('')
        self.out('+' + '=' * w + '+')
        self.out('')


# IBS.it Search via Direct Algolia API
def _parse_algolia_hits(data):
    '''Parse raw Algolia API response into structured book metadata dicts.
    Deduplicates by URL and returns a list of results.'''
    results = []
    seen_urls = set()
    for result in data.get('results', []):
        for hit in result.get('hits', []):
            ean = str(hit.get('ean') or '')
            title = hit.get('title', '')
            product_url = hit.get('productUrl', '')

            if not ean or not title or not product_url:
                continue

            full_url = urljoin(BASE_URL, product_url)
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            authors = hit.get('authors', [])
            author = ', '.join(authors) if authors else ''

            publishers = hit.get('publisher', [])
            publisher = publishers[0] if publishers else ''

            book_types = hit.get('bookType', [])
            book_format = ', '.join(book_types) if book_types else ''

            results.append({
                'title': title.strip(),
                'url': full_url,
                'isbn': ean,
                'author': author,
                'publisher': publisher,
                'published_date': str(hit.get('editionDate') or ''),
                'series': hit.get('series', ''),
                'format': book_format,
                'language': 'it',
                'image': hit.get('image', ''),
                'description': '',  # Fetched from detail page if needed
            })
    return results


def search_ibs(query):
    '''Search for books on ibs.it via **direct Algolia API** call.
    Much faster than the Playwright-based approach — pure HTTP.
    Returns list of dicts with complete metadata extracted from the JSON.
    '''
    session = get_session()
    url = ALGOLIA_URL
    headers = {
        'X-Algolia-API-Key': ALGOLIA_API_KEY,
        'X-Algolia-Application-Id': ALGOLIA_APP_ID,
        'Content-Type': 'application/json',
        'Referer': 'https://www.ibs.it/',
    }
    payload = {
        'params': 'query=%s&hitsPerPage=15' % quote(query)
    }

    try:
        resp = session.post(url, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return _parse_algolia_hits({'results': [data]})
    except Exception:
        return []


def _clean_description(desc):
    '''Clean up a description string: remove boilerplate phrases, trim whitespace.
    Handles Italian UI artifacts like "Leggi di più", "Leggi di meno", "Leggi tutto",
    including concatenated variants (e.g. "Leggi di piùLeggi di meno").
    '''
    if not desc:
        return ''

    # Remove boilerplate phrases: "leggi di più", "leggi di meno", "leggi tutto"
    # Handles any whitespace between words AND the concatenated case (no space between phrases)
    boilerplate = r'(?:leggi\s+di\s+(?:pi[ùu]|meno)|leggi\s+tutto)'
    # Remove one or more boilerplate phrases that may be concatenated
    desc = re.sub(r'(?:\s*' + boilerplate + r')+', '', desc, flags=re.IGNORECASE)

    # Normalize whitespace
    desc = re.sub(r'\s+', ' ', desc).strip()

    return desc


def get_book_description(book_url):
    '''Extract the description from an IBS.it book detail page using static requests.
    Returns the description text string, or empty string on failure.
    '''
    session = get_session()
    try:
        resp = session.get(book_url, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
    except Exception:
        return ''

    desc = ''

    # Look for the main description container
    desc_section = soup.find('div', class_=re.compile(r'cc-em-pdp.*descrizion', re.I))
    if desc_section:
        body = desc_section.find('div', class_=re.compile(r'cc-em-content-body|cc-content-text', re.I))
        if body:
            desc = body.get_text(strip=True)
        else:
            desc = desc_section.get_text(strip=True)
        if desc.startswith('Descrizione'):
            desc = desc[len('Descrizione'):].strip()
        if desc:
            return _clean_description(desc)

    # Fallback: itemprop="description"
    desc_div = soup.find('div', attrs={'itemprop': 'description'})
    if desc_div:
        desc = desc_div.get_text(strip=True)
        if desc:
            return _clean_description(desc)

    # Last resort: h2 "Descrizione" siblings
    desc_h2 = soup.find('h2', string=re.compile(r'Descrizione', re.I))
    if desc_h2:
        parts = []
        for sibling in desc_h2.find_next_siblings():
            if sibling.name == 'h2':
                break
            t = sibling.get_text(strip=True)
            if t and len(t) > 20:
                parts.append(t)
        if parts:
            return _clean_description(' '.join(parts))

    return ''


def get_book_metadata(book_url):
    '''Extract detailed metadata from an IBS.it book detail page.
    Returns dict with url, title, author, isbn, language, pages, format,
    publisher, published_date, description, series.
    Note: Most metadata is already extracted from Algolia; this function
    is used to get pages, description, and verify other fields.
    '''
    session = get_session()
    try:
        resp = session.get(book_url, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
    except Exception:
        return {'url': book_url, 'error': 'fetch failed'}

    text = resp.text
    meta = {
        'url': book_url,
        'title': '',
        'author': '',
        'isbn': '',
        'language': '',
        'pages': '',
        'format': '',
        'publisher': '',
        'published_date': '',
        'description': '',
        'series': '',
    }

    # Extract ISBN from URL
    isbn_m = re.search(r'/e/(\d{13})', book_url)
    if isbn_m:
        meta['isbn'] = isbn_m.group(1)
    else:
        isbn_m = re.search(r'/e/(\d+)', book_url)
        if isbn_m:
            meta['isbn'] = isbn_m.group(1)

    # Title from h1
    h1 = soup.find('h1', class_=re.compile(r'cc-title', re.I))
    if h1:
        meta['title'] = h1.get_text(strip=True)

    # Extract author from cc-content-author div
    content_author = soup.find('div', class_=re.compile(r'cc-content-author', re.I))
    if content_author:
        author_text = content_author.get_text(strip=True)
        # Pattern: "diAuthorName(Autore)Translator(Traduttore)Publisher, Year"
        # Extract author name before (Autore)
        author_m = re.search(r'di(.+?)\(Autore\)', author_text)
        if author_m:
            meta['author'] = author_m.group(1).strip()
        else:
            # Fallback: find first cc-author-name link
            author_link = content_author.find('a', class_=re.compile(r'cc-author-name', re.I))
            if author_link:
                meta['author'] = author_link.get_text(strip=True)
    else:
        # Fallback: find author link in the details section
        author_link = soup.find('a', class_=re.compile(r'cc-author-name', re.I), href=re.compile(r'/libri/autori/'))
        if author_link:
            meta['author'] = author_link.get_text(strip=True)

    # Extract metadata from label-value pairs (cc-item-label / cc-item-value)
    # These are found globally throughout the page within the "Dettagli" section
    for label_el in soup.find_all('span', class_=re.compile(r'cc-item-label', re.I)):
        label_text = label_el.get_text(strip=True).rstrip(':').lower()

        # Find the corresponding value (cc-item-value in the sibling cc-content-value div)
        content_label_div = label_el.find_parent('div', class_=re.compile(r'cc-content-label', re.I))
        if not content_label_div:
            continue
        content_value_div = content_label_div.find_next_sibling('div', class_=re.compile(r'cc-content-value', re.I))
        if not content_value_div:
            continue
        value_el = content_value_div.find('span', class_=re.compile(r'cc-item-value', re.I))
        if not value_el:
            continue
        value = value_el.get_text(strip=True)

        if 'editore' in label_text and not meta['publisher']:
            meta['publisher'] = value
        elif 'anno' in label_text and not meta['published_date']:
            year_m = re.search(r'(\d{4})', value)
            if year_m:
                meta['published_date'] = year_m.group(1)
        elif 'pagine' in label_text and not meta['pages']:
            pages_m = re.search(r'(\d+)', value)
            if pages_m:
                meta['pages'] = pages_m.group(1)
            # Also capture full text for format info
            if not meta['format']:
                meta['format'] = value
        elif 'isbn' in label_text or 'ean' in label_text:
            isbn_m = re.search(r'(\d{13}|\d{10})', value)
            if isbn_m:
                meta['isbn'] = isbn_m.group(1)
        elif 'lingua' in label_text and not meta['language']:
            meta['language'] = value
        elif 'collana' in label_text and not meta['series']:
            meta['series'] = value

    # Description via dedicated function
    meta['description'] = get_book_description(book_url)

    # Language - try to detect from page or default to Italian
    if not meta['language']:
        lang_meta = soup.find('meta', attrs={'name': 'twitter:data2'})
        if lang_meta and lang_meta.get('content'):
            meta['language'] = lang_meta['content']
        else:
            # Default to Italian for Italian bookstore
            meta['language'] = 'it'

    # Ensure all metadata fields are strings, not None
    for field in ['title', 'author', 'language', 'pages', 'format', 'publisher', 'published_date', 'description', 'isbn', 'series']:
        if meta.get(field) is None:
            meta[field] = ''

    return meta


def find_book_in_results(results, author, title):
    '''Find the best matching book from IBS.it search results.
    Uses both the structured fields (author from Algolia) and text matching
    to find the best match for the given author and title.
    '''
    if not results:
        return None

    # Normalize author and title for matching
    author_lower = author.lower().strip() if author else ''
    title_lower = title.lower().strip() if title else ''

    # Split author into significant words
    stop_words = {'una', 'della', 'dei', 'del', 'sul', 'nel', 'gli', 'le',
                  'la', 'lo', 'il', 'un', 'e', 'con', 'per', 'da', 'di', 'a',
                  'in', 'su', 'tra', 'fra', 'che', 'non', 'si', 'piu', 'più',
                  'alla', 'allo', 'dello', 'della', 'degli', 'delle', 'sugli',
                  'sulle', 'nell', 'sull', 'nell', 'sull'}
    author_words = [w for w in re.split(r'[\s,]+', author_lower) if len(w) >= 3 and w not in stop_words]
    title_words = [w for w in title_lower.split() if len(w) >= 3 and w.lower() not in stop_words]

    scored = []
    for r in results:
        score = 0
        rt_lower = r.get('title', '').lower()
        ru_lower = r.get('url', '').lower()
        ra_lower = r.get('author', '').lower()  # Author from Algolia data

        # --- AUTHOR MATCHING (using Algolia author field) ---
        # BIG BONUS: if Algolia author contains the input author (or vice versa)
        author_match_strength = 0
        if author_lower and ra_lower:
            # Check if the input author appears in the Algolia author field
            if author_lower in ra_lower or ra_lower in author_lower:
                author_match_strength = 3  # Best match
                score += 100
                # Extra bonus for exact author match (result has no extra authors)
                if ra_lower == author_lower:
                    score += 30
                elif ra_lower.startswith(author_lower + ',') or ra_lower.startswith(author_lower + ' e '):
                    score += 15  # Author is first in list
            else:
                # Check individual words
                input_author_words = set(w for w in re.split(r'[\s,]+', author_lower) if len(w) >= 3)
                result_author_words = set(w for w in re.split(r'[\s,]+', ra_lower) if len(w) >= 3)
                common = input_author_words & result_author_words
                if common:
                    # Some words match (e.g. "Eco" appears in both)
                    author_match_strength = 1
                    score += 40 * len(common) / max(len(input_author_words), 1)
        elif not author_lower:
            # No input author to match against
            author_match_strength = 1
            score += 10

        # --- AUTHOR TEXT MATCHING (fallback: check in title/URL) ---
        if author_words and author_match_strength < 2:
            matched_words = sum(1 for w in author_words if w in rt_lower or w in ru_lower)
            if matched_words >= len(author_words):
                score += 30
            elif matched_words >= max(1, len(author_words) - 1):
                score += 15

        # --- TITLE MATCHING ---
        if title_words:
            matched_words = sum(1 for w in title_words if w in rt_lower)
            if matched_words >= len(title_words):
                # All significant title words match
                score += 40
                # Extra bonus for exact title match (not partial)
                title_clean = re.sub(r'[^a-z0-9]', ' ', title_lower).strip()
                rt_clean = re.sub(r'[^a-z0-9]', ' ', rt_lower).strip()
                if title_clean in rt_clean or rt_clean in title_clean:
                    score += 30
            elif matched_words >= max(1, len(title_words) - 1):
                score += 25
            else:
                score += matched_words * 5

        # --- URL SLUG BONUS ---
        # Check if significant words appear in the URL slug
        slug = ru_lower.split('/e/')[0] if '/e/' in ru_lower else ru_lower
        all_significant = [w for w in author_words + title_words if w not in stop_words]
        if all_significant:
            slug_matches = sum(1 for w in all_significant if w in slug)
            if slug_matches >= len(all_significant):
                score += 20

        # --- PENALTY for author mismatch ---
        # If result has a non-empty author and it doesn't match input author at all
        if author_lower and ra_lower and author_match_strength == 0:
            score -= 60

        # Must have some title match to be considered
        if title_words:
            title_matched = any(w in rt_lower for w in title_words)
            if not title_matched:
                continue  # Skip results with no title word match

        scored.append((score, r))

    if not scored:
        return None

    # Group by URL and keep highest score
    url_best = {}
    for sc, r in scored:
        u = r.get('url', '')
        if u not in url_best or sc > url_best[u]['score']:
            url_best[u] = {'score': sc, 'result': r}

    # Return best match
    best = max(url_best.values(), key=lambda x: x['score'], default=None)
    if best and best['score'] > 20:
        return best['result']

    return None


def find_book_metadata(author, title):
    '''Search for and retrieve complete metadata for a book on IBS.it.
    Returns dict with book metadata including description, or error if not found.
    Uses Algolia API directly (fast) and fetches detail page only for description.
    '''
    clean_author = re.sub(r',', ' ', author).strip()
    query = '%s %s' % (clean_author, title)

    results = []

    # Try combined author+title query first
    r = search_ibs(query)
    if r:
        results = r
    else:
        # Fallback: title only
        r = search_ibs(title)
        if r:
            results = r
        else:
            # Last fallback: author only
            r = search_ibs(clean_author)
            if r:
                results = r

    if not results:
        return {'error': 'No results found on IBS.it'}

    # Find best matching result from Algolia data
    match = find_book_in_results(results, author, title)

    if not match:
        # If no confident match, try the first result
        match = results[0]

    if not match:
        return {'error': 'No matching result found'}

    # Use Algolia data as base, enrich with detail page data
    meta = dict(match)  # Copy all Algolia fields

    # Ensure all standard fields exist with defaults
    for field in ['title', 'author', 'isbn', 'language', 'pages', 'format',
                   'publisher', 'published_date', 'description', 'series']:
        if field not in meta or not meta[field]:
            meta[field] = ''

    # Download detail page to get description, pages, and verify other fields
    detail_meta = get_book_metadata(match.get('url') or '')
    if 'error' not in detail_meta:
        # Merge: detail page overrides Algolia for verified fields
        for field in ['description', 'pages', 'title', 'author', 'publisher',
                       'published_date', 'isbn', 'language', 'series', 'format']:
            if detail_meta.get(field):
                meta[field] = detail_meta[field]

    meta['matched_url'] = match.get('url') or ''
    return meta


# EPUB Metadata Embedder
def embed_metadata(epub_path, metadata, afn='', tfn=''):
    '''Embed metadata into an EPUB file. Returns (success: bool, error_message: str).'''
    try:
        td = epub_path + '_tmp'
        if os.path.exists(td):
            shutil.rmtree(td)
        os.makedirs(td)

        with zipfile.ZipFile(epub_path, 'r') as z:
            z.extractall(td)

        cp = os.path.join(td, 'META-INF', 'container.xml')
        if not os.path.exists(cp):
            return False, 'no container.xml'

        tree = ET.parse(cp)
        op = None
        for el in tree.getroot().iter():
            if 'rootfile' in el.tag.lower():
                op = el.get('full-path')
                if op:
                    break

        if not op:
            return False, 'no content.opf'

        ofp = os.path.join(td, op)
        tree = ET.parse(ofp)

        me = None
        for el in tree.getroot().iter():
            if 'metadata' in el.tag.lower():
                me = el
                break

        if me is None:
            return False, 'no metadata section'

        def ct(t):
            '''Clean text for embedding (remove newlines, truncate).'''
            if not t:
                return ''
            return re.sub(r'[\n\r\t]', ' ', t).strip()[:50000]

        ft = ct(tfn) if tfn else ct(metadata.get('title', ''))
        fa = ct(afn) if afn else ct(metadata.get('author', ''))
        fl = ct(metadata.get('language', '')) or 'it'
        fd = ct(metadata.get('description', ''))
        fp = ct(metadata.get('publisher', ''))
        fi = ct(metadata.get('isbn', ''))

        fields = {
            '{http://purl.org/dc/elements/1.1/}title': ft,
            '{http://purl.org/dc/elements/1.1/}creator': fa,
            '{http://purl.org/dc/elements/1.1/}language': fl,
            '{http://purl.org/dc/elements/1.1/}description': fd,
            '{http://purl.org/dc/elements/1.1/}publisher': fp,
        }
        if fi:
            fields['{http://purl.org/dc/elements/1.1/}identifier'] = fi

        et = {ch.tag: ch for ch in me}
        for tag, val in fields.items():
            if not val:
                continue
            if tag in et:
                et[tag].text = val
            else:
                ne = ET.SubElement(me, tag)
                ne.text = val

        tree.write(ofp, encoding='utf-8', xml_declaration=True)

        tep = epub_path + '.new'
        with zipfile.ZipFile(tep, 'w', zipfile.ZIP_DEFLATED) as z:
            for rd, ds, fs in os.walk(td):
                for f in fs:
                    fp2 = os.path.join(rd, f)
                    z.write(fp2, os.path.relpath(fp2, td))

        os.replace(tep, epub_path)
        return True, ''

    except Exception as e:
        return False, str(e)
    finally:
        if os.path.exists(td):
            shutil.rmtree(td)


# Filename Parsing
def parse_filename(fn):
    '''Parse EPUB filename to extract author and title.
    Expected format: Author Name - Book Title.epub
    Returns (author_lower, title_lower, original_filename).
    '''
    name = os.path.splitext(fn)[0]
    parts = name.split(' - ')

    if len(parts) >= 2:
        author = parts[0].strip()
        title = parts[-1].strip()
    else:
        author = ''
        title = name

    author = re.sub(r',?/?alias/?', '', author, flags=re.IGNORECASE)
    author = re.sub(r'@[a-z]+', '', author, flags=re.IGNORECASE)

    return author.lower(), title.lower(), fn


# HTML Report Generation
def generate_html_report(wdir, results, stats, total_time):
    '''Generate an HTML report of the pipeline results.'''
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    total = len(results)
    success = sum(1 for r in results if r.get('status') == 'success')
    failed = sum(1 for r in results if r.get('status') in ('error', 'exception'))
    notfound = sum(1 for r in results if r.get('status') == 'not_found')
    embedded = sum(1 for r in results if r.get('status') == 'success' and
                   os.path.exists(os.path.join(wdir, 'embedded', r.get('filename', ''))))

    css = '''
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); min-height: 100vh; color: #eee; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        header { text-align: center; margin-bottom: 30px; padding: 30px; background: rgba(255,255,255,0.05); border-radius: 16px; border: 1px solid rgba(255,255,255,0.1); }
        h1 { font-size: 2.2em; margin-bottom: 10px; background: linear-gradient(90deg, #00d4ff, #7b2cbf); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .subtitle { color: #888; font-size: 0.95em; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .stat-card { background: rgba(255,255,255,0.05); border-radius: 12px; padding: 20px; text-align: center; border: 1px solid rgba(255,255,255,0.1); transition: transform 0.3s, box-shadow 0.3s; }
        .stat-card:hover { transform: translateY(-4px); box-shadow: 0 8px 25px rgba(0,0,0,0.3); }
        .stat-value { font-size: 2.5em; font-weight: bold; margin-bottom: 5px; }
        .stat-label { color: #888; font-size: 0.9em; text-transform: uppercase; letter-spacing: 1px; }
        .stat-success .stat-value { color: #00e676; }
        .stat-warning .stat-value { color: #ffab00; }
        .stat-error .stat-value { color: #ff5252; }
        .stat-info .stat-value { color: #00d4ff; }
        .folders-section { background: rgba(255,255,255,0.03); border-radius: 12px; padding: 25px; margin-bottom: 30px; border: 1px solid rgba(255,255,255,0.08); }
        .folders-section h2 { margin-bottom: 15px; color: #00d4ff; font-size: 1.3em; }
        .folder-row { display: flex; justify-content: space-between; align-items: center; padding: 12px 15px; background: rgba(0,0,0,0.2); border-radius: 8px; margin-bottom: 8px; }
        .folder-name { font-family: monospace; color: #7b2cbf; }
        .folder-count { font-weight: bold; color: #fff; }
        .books-section { background: rgba(255,255,255,0.03); border-radius: 12px; padding: 25px; border: 1px solid rgba(255,255,255,0.08); }
        .books-section h2 { margin-bottom: 20px; color: #00d4ff; font-size: 1.3em; }
        .book-card { background: rgba(255,255,255,0.05); border-radius: 10px; padding: 15px; margin-bottom: 12px; border-left: 4px solid; transition: background 0.2s; }
        .book-card:hover { background: rgba(255,255,255,0.08); }
        .book-card.success { border-left-color: #00e676; }
        .book-card.failed { border-left-color: #ff5252; }
        .book-card.notfound { border-left-color: #ffab00; }
        .book-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; }
        .book-title { font-weight: bold; font-size: 1.05em; color: #fff; }
        .book-status { padding: 4px 12px; border-radius: 20px; font-size: 0.75em; font-weight: bold; text-transform: uppercase; }
        .status-success { background: rgba(0,230,118,0.2); color: #00e676; }
        .status-failed { background: rgba(255,82,82,0.2); color: #ff5252; }
        .status-notfound { background: rgba(255,171,0,0.2); color: #ffab00; }
        .book-meta { font-size: 0.85em; color: #888; margin-bottom: 8px; }
        .book-meta span { margin-right: 15px; }
        .book-detail { font-size: 0.85em; color: #aaa; padding: 8px 12px; background: rgba(0,0,0,0.2); border-radius: 6px; margin-top: 8px; }
        .book-detail code { color: #00d4ff; }
        .time-info { text-align: center; color: #666; font-size: 0.9em; margin-top: 30px; padding-top: 20px; border-top: 1px solid rgba(255,255,255,0.1); }
        .embedded-badge { display: inline-block; background: linear-gradient(135deg, #7b2cbf, #00d4ff); padding: 3px 10px; border-radius: 4px; font-size: 0.7em; margin-left: 8px; }
    </style>
    '''

    books_html = ''
    for r in results:
        status = r.get('status', 'unknown')
        filename = r.get('filename', '')
        author = r.get('author', '')
        title = r.get('title', '')

        if status == 'success':
            card_class = 'success'
            status_label = 'Found'
            status_class = 'status-success'
            meta_parts = []
            if r.get('metadata'):
                m = r['metadata']
                if m.get('isbn'):
                    meta_parts.append('ISBN: <code>' + m['isbn'] + '</code>')
                if m.get('publisher'):
                    meta_parts.append('Editore: <code>' + m['publisher'] + '</code>')
                if m.get('published_date'):
                    meta_parts.append('Anno: <code>' + m['published_date'] + '</code>')
                if m.get('pages'):
                    meta_parts.append('Pagine: <code>' + m['pages'] + '</code>')
                if m.get('matched_url'):
                    url_text = m.get('matched_url', '')
                    meta_parts.append('URL: <code>' + url_text[:60] + '...</code>')
            detail = '<div class="book-detail">' + '<br>'.join(meta_parts) + '</div>' if meta_parts else ''
            embedded_mark = '<span class="embedded-badge">EMBEDDED</span>' if os.path.exists(os.path.join(wdir, 'embedded', filename)) else ''
        elif status == 'not_found':
            card_class = 'notfound'
            status_label = 'Not Found'
            status_class = 'status-notfound'
            detail = '<div class="book-detail">Metadata not found on ibs.it</div>'
            embedded_mark = ''
        else:
            card_class = 'failed'
            status_label = 'Error'
            status_class = 'status-failed'
            err = r.get('error', 'Unknown error')
            detail = '<div class="book-detail">Error: <code>' + err[:100] + '</code></div>'
            embedded_mark = ''

        truncated_fn = filename[:50] + '...' if len(filename) > 50 else filename
        books_html += '''
        <div class="book-card ''' + card_class + '''">
            <div class="book-header">
                <div class="book-title">''' + author + ' - ' + title + embedded_mark + '''</div>
                <span class="book-status ''' + status_class + '''">''' + status_label + '''</span>
            </div>
            <div class="book-meta">
                <span>''' + truncated_fn + '''</span>
            </div>
            ''' + detail + '''
        </div>
        '''

    html = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EPUB Metadata Pipeline (IBS.it Fast) - Report</title>
    ''' + css + '''
</head>
<body>
    <div class="container">
        <header>
            <h1>EPUB Metadata Pipeline &mdash; IBS.it (Fast)</h1>
            <p class="subtitle">Report generated ''' + timestamp + '''</p>
        </header>

        <div class="stats-grid">
            <div class="stat-card stat-info">
                <div class="stat-value">''' + str(total) + '''</div>
                <div class="stat-label">Total Books</div>
            </div>
            <div class="stat-card stat-success">
                <div class="stat-value">''' + str(success) + '''</div>
                <div class="stat-label">Found</div>
            </div>
            <div class="stat-card stat-warning">
                <div class="stat-value">''' + str(notfound) + '''</div>
                <div class="stat-label">Not Found</div>
            </div>
            <div class="stat-card stat-error">
                <div class="stat-value">''' + str(failed) + '''</div>
                <div class="stat-label">Errors</div>
            </div>
        </div>

        <div class="folders-section">
            <h2>File Distribution</h2>
            <div class="folder-row">
                <span class="folder-name">origins/</span>
                <span class="folder-count">''' + str(total) + ''' files (original backups)</span>
            </div>
            <div class="folder-row">
                <span class="folder-name">embedded/</span>
                <span class="folder-count">''' + str(embedded) + ''' files (with embedded metadata)</span>
            </div>
            <div class="folder-row">
                <span class="folder-name">notfound/</span>
                <span class="folder-count">''' + str(notfound) + ''' files (not found)</span>
            </div>
        </div>

        <div class="books-section">
            <h2>Processed Books</h2>
            ''' + books_html + '''
        </div>

        <div class="time-info">
            Total processing time: ''' + format_time(total_time) + '''
        </div>
    </div>
</body>
</html>'''

    report_path = os.path.join(wdir, 'pipeline_report.html')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html)
    return report_path


# Metadata Report Generator
def _metadata_field(label, value, icon=''):
    '''Helper to build a metadata field HTML snippet.'''
    if not value:
        return ''
    icon_html = '<span class="field-icon">%s</span>' % icon if icon else ''
    return '''
            <div class="meta-field">
                %s
                <span class="field-label">%s</span>
                <span class="field-value">%s</span>
            </div>''' % (icon_html, label, value)


def generate_metadata_report(books, output_path):
    '''Generate an HTML report showing metadata found in embedded EPUB files.

    Args:
        books: List of dicts with 'filename' (str) and 'metadata' (dict) keys.
               Metadata dict can contain: title, creator, language, description,
               publisher, identifier.
        output_path: Path to write the HTML file.
    '''
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    total = len(books)

    # Count books with complete metadata
    complete = 0
    partial = 0
    empty = 0
    for book in books:
        m = book.get('metadata', {}) or {}
        filled = [k for k in ('title', 'creator', 'identifier', 'publisher', 'description', 'language') if m.get(k)]
        if len(filled) >= 4:
            complete += 1
        elif len(filled) >= 1:
            partial += 1
        else:
            empty += 1

    css = '''
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
                         'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #0f0c29 0%, #1a1a3e 40%, #24243e 100%);
            min-height: 100vh;
            color: #e0e0e0;
            padding: 24px;
        }
        .container { max-width: 1100px; margin: 0 auto; }

        /* Header */
        header {
            text-align: center;
            margin-bottom: 32px;
            padding: 36px 24px;
            background: rgba(255,255,255,0.04);
            border-radius: 16px;
            border: 1px solid rgba(255,255,255,0.08);
            backdrop-filter: blur(8px);
        }
        h1 {
            font-size: 2em;
            font-weight: 700;
            margin-bottom: 8px;
            background: linear-gradient(135deg, #f093fb, #f5576c, #4facfe);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        .subtitle { color: #8888aa; font-size: 0.92em; }
        .generated-at { color: #666; font-size: 0.82em; margin-top: 6px; }

        /* Stats row */
        .stats-row {
            display: flex;
            gap: 16px;
            justify-content: center;
            margin-bottom: 32px;
            flex-wrap: wrap;
        }
        .stat-pill {
            padding: 10px 22px;
            border-radius: 40px;
            font-size: 0.85em;
            font-weight: 600;
            border: 1px solid rgba(255,255,255,0.1);
            background: rgba(255,255,255,0.05);
        }
        .stat-pill .num { font-size: 1.3em; margin-right: 4px; }
        .stat-complete { border-color: rgba(0,230,118,0.3); }
        .stat-complete .num { color: #00e676; }
        .stat-partial { border-color: rgba(255,171,0,0.3); }
        .stat-partial .num { color: #ffab00; }
        .stat-empty { border-color: rgba(255,82,82,0.3); }
        .stat-empty .num { color: #ff5252; }

        /* Book list - single column */
        .book-grid {
            display: flex;
            flex-direction: column;
            gap: 20px;
        }

        /* Book card */
        .book-card {
            background: rgba(255,255,255,0.04);
            border-radius: 14px;
            padding: 20px;
            border: 1px solid rgba(255,255,255,0.08);
            transition: transform 0.2s, box-shadow 0.2s, border-color 0.2s;
        }
        .book-card:hover {
            transform: translateY(-3px);
            box-shadow: 0 12px 32px rgba(0,0,0,0.3);
            border-color: rgba(255,255,255,0.15);
        }

        .book-header {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 12px;
            margin-bottom: 14px;
            padding-bottom: 12px;
            border-bottom: 1px solid rgba(255,255,255,0.06);
        }
        .book-title {
            font-weight: 700;
            font-size: 1.05em;
            color: #fff;
            line-height: 1.3;
            flex: 1;
        }
        .book-author {
            font-size: 0.85em;
            color: #999;
            margin-top: 3px;
        }
        .book-filename {
            font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
            font-size: 0.72em;
            color: #666;
            margin-top: 4px;
            word-break: break-all;
        }

        .badge {
            flex-shrink: 0;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.68em;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .badge-complete {
            background: rgba(0,230,118,0.15);
            color: #00e676;
            border: 1px solid rgba(0,230,118,0.25);
        }
        .badge-partial {
            background: rgba(255,171,0,0.15);
            color: #ffab00;
            border: 1px solid rgba(255,171,0,0.25);
        }
        .badge-empty {
            background: rgba(255,82,82,0.15);
            color: #ff5252;
            border: 1px solid rgba(255,82,82,0.25);
        }

        /* Metadata fields */
        .meta-fields {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 6px 16px;
        }
        @media (max-width: 400px) {
            .meta-fields { grid-template-columns: 1fr; }
        }
        .meta-field {
            display: flex;
            align-items: baseline;
            gap: 6px;
            padding: 5px 8px;
            border-radius: 6px;
            background: rgba(0,0,0,0.15);
            font-size: 0.85em;
        }
        .meta-field.full-width {
            grid-column: 1 / -1;
        }
        .field-icon { font-size: 0.9em; }
        .field-label {
            color: #7777aa;
            font-weight: 500;
            flex-shrink: 0;
            text-transform: uppercase;
            font-size: 0.75em;
            letter-spacing: 0.3px;
        }
        .field-value {
            color: #ccc;
            word-break: break-word;
            line-height: 1.35;
        }
        .field-value.empty {
            color: #555;
            font-style: italic;
        }

        .description-box {
            grid-column: 1 / -1;
            margin-top: 2px;
        }
        .description-box .field-value {
            font-size: 0.9em;
            color: #aaa;
            line-height: 1.6;
            white-space: pre-line;
        }

        /* Footer */
        footer {
            text-align: center;
            color: #555;
            font-size: 0.82em;
            margin-top: 36px;
            padding-top: 18px;
            border-top: 1px solid rgba(255,255,255,0.06);
        }
    </style>
    '''

    books_html = ''
    for i, book in enumerate(books, 1):
        fn = book.get('filename', '')
        m = book.get('metadata', {}) or {}

        title = m.get('title', '') or ''
        creator = m.get('creator', '') or ''
        identifier = m.get('identifier', '') or ''
        publisher = m.get('publisher', '') or ''
        description = m.get('description', '') or ''
        language = m.get('language', '') or ''

        filled_count = sum(1 for v in [title, creator, identifier, publisher, description, language] if v)
        if filled_count >= 4:
            badge_class = 'badge-complete'
            badge_text = 'Complete'
        elif filled_count >= 1:
            badge_class = 'badge-partial'
            badge_text = 'Partial'
        else:
            badge_class = 'badge-empty'
            badge_text = 'Empty'

        display_title = title if title else '(no title)'
        display_author = creator if creator else 'Autore non specificato'
        short_fn = fn[:55] + '...' if len(fn) > 55 else fn

        # Build fields
        fields_html = ''
        if identifier:
            fields_html += _metadata_field('ISBN', identifier, '\U0001f4d6')
        else:
            fields_html += _metadata_field('ISBN', '\u2014', '\U0001f4d6')

        if publisher:
            fields_html += _metadata_field('Editore', publisher, '\U0001f3e2')
        else:
            fields_html += _metadata_field('Editore', '\u2014', '\U0001f3e2')

        if language:
            lang_name = {'it': 'Italiano', 'en': 'Inglese', 'fr': 'Francese',
                         'de': 'Tedesco', 'es': 'Spagnolo', 'pt': 'Portoghese'}.get(language.lower(), language)
            fields_html += _metadata_field('Lingua', lang_name, '\U0001f310')
        else:
            fields_html += _metadata_field('Lingua', '\u2014', '\U0001f310')

        if description:
            fields_html += '''
            <div class="meta-field full-width description-box">
                <span class="field-icon">\U0001f4dd</span>
                <span class="field-label">Descrizione</span>
                <span class="field-value">%s</span>
            </div>''' % description
        else:
            fields_html += '''
            <div class="meta-field full-width">
                <span class="field-icon">\U0001f4dd</span>
                <span class="field-label">Descrizione</span>
                <span class="field-value empty">\u2014</span>
            </div>'''

        books_html += '''
        <div class="book-card">
            <div class="book-header">
                <div>
                    <div class="book-title">%s</div>
                    <div class="book-author">%s</div>
                    <div class="book-filename">%s</div>
                </div>
                <span class="badge %s">%s</span>
            </div>
            <div class="meta-fields">
                %s
            </div>
        </div>''' % (display_title, display_author, short_fn, badge_class, badge_text, fields_html)

    html = '''<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EPUB Metadata Report</title>
    %s
</head>
<body>
    <div class="container">
        <header>
            <h1>\U0001f4da EPUB Metadata Report</h1>
            <p class="subtitle">Metadata embedded in EPUB files</p>
            <p class="generated-at">Generated %s &middot; %d file(s)</p>
        </header>

        <div class="stats-row">
            <div class="stat-pill stat-complete">
                <span class="num">%d</span> Complete
            </div>
            <div class="stat-pill stat-partial">
                <span class="num">%d</span> Partial
            </div>
            <div class="stat-pill stat-empty">
                <span class="num">%d</span> Empty
            </div>
        </div>

        <div class="book-grid">
            %s
        </div>

        <footer>
            EPUB Metadata Report
        </footer>
    </div>
</body>
</html>''' % (css, timestamp, total, complete, partial, empty, books_html)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    return output_path


# Main Pipeline Function
def ask_embed():
    '''Ask user if they want to proceed with embedding.'''
    print('')
    w = 48
    print('+' + '-' * w + '+')
    print('|  EMBEDDING READY' + ' ' * (w - 18) + '|')
    print('+' + '-' * w + '+')
    r = input('\n   Do you want to proceed with embedding? (y/n): ').strip().lower()
    return r in ('y', 'yes', 's', 'si')


def run_pipeline(wdir, delay=0.0, verbose=False, force=False, json_only=False):
    '''Run the complete metadata pipeline (Fast Mode — direct Algolia API).

    Note: The `delay` parameter is accepted but not used, since fast Algolia
    API calls don't need rate-limiting delays.
    Returns exit code (0 for success).
    '''
    log = Logger(log_file=os.path.join(wdir, 'pipeline.log'))
    wdir = os.path.abspath(wdir)

    if not os.path.isdir(wdir):
        log.log(log.RED, 'Error: Directory not found: %s' % wdir)
        return 1

    epubs = [f for f in os.listdir(wdir) if f.lower().endswith('.epub')]
    if not epubs:
        log.log(log.RED, 'No EPUB files found')
        return 1

    log.header('EPUB METADATA PIPELINE - IBS.it (Fast Mode)')
    log.log(log.CYAN, 'Init pipeline...')
    log.info('Working directory', wdir)
    log.info('EPUB files', str(len(epubs)))
    log.info('Mode', 'Direct Algolia API (no browser)')
    log.info('Source', 'ibs.it')

    # Phase 1: Metadata Search
    log.phase(1, 'Searching metadata from ibs.it (Algolia API)')
    results = []
    st = {'success': 0, 'failed': 0, 'notfound': 0, 'total': len(epubs)}
    t0 = time.time()

    for i, fn in enumerate(epubs, 1):
        name = fn.replace('.epub', '')
        parts = name.split(' - ')
        author = parts[0].strip() if len(parts) >= 2 else ''
        title = parts[-1].strip() if len(parts) >= 2 else name

        author = re.sub(r',?/?alias/?', '', author, flags=re.IGNORECASE)
        author = re.sub(r'@[a-z]+', '', author, flags=re.IGNORECASE)
        author = author.strip(' ,')

        log.log(log.CYAN, '  Book %d/%d' % (i, len(epubs)))
        auth_str = author[:40] if author else '?'
        log.info('Search', '%s - %s' % (auth_str, title[:35]))

        try:
            meta = find_book_metadata(author, title)
            if 'error' in meta:
                log.result('error', meta.get('error', 'Unknown error')[:40])
                st['failed'] += 1
                results.append({
                    'author': author, 'title': title, 'filename': fn,
                    'filepath': os.path.join(wdir, fn), 'status': 'error',
                    'error': meta.get('error')
                })
            else:
                if not meta.get('author') and author:
                    meta['author'] = author
                log.info('URL', (meta.get('matched_url') or meta.get('url', 'N/A'))[:55])
                log.info('ISBN', str(meta.get('isbn', '?')))
                log.info('Publisher', str(meta.get('publisher', '?')))
                log.info('Pages', str(meta.get('pages', '?')))
                log.info('Year', str(meta.get('published_date', '?')))
                desc_len = len(meta.get('description', ''))
                log.info('Description', '%d chars' % desc_len)
                log.result('success', 'FOUND')
                st['success'] += 1
                results.append({
                    'author': author, 'title': title, 'filename': fn,
                    'filepath': os.path.join(wdir, fn), 'status': 'success',
                    'metadata': meta
                })
        except Exception as e:
            log.result('error', str(e)[:40])
            st['failed'] += 1
            results.append({
                'author': author, 'title': title, 'filename': fn,
                'filepath': os.path.join(wdir, fn), 'status': 'exception',
                'error': str(e)
            })

        log.progress(i, len(epubs), fn)

    print('')
    log.phase_done(1, time.time() - t0, st)

    jout = {
        'scrape_time': time.strftime('%Y-%m-%d %H:%M:%S'),
        'source': 'ibs.it (fast)',
        'stats': st,
        'books': results
    }
    jpath = os.path.join(wdir, 'metadata_batch.json')
    with open(jpath, 'w', encoding='utf-8') as f:
        json.dump(jout, f, indent=2, ensure_ascii=False)
    log.log(log.CYAN, '   JSON saved: metadata_batch.json (%.1f KB)' % (os.path.getsize(jpath)/1024))

    if json_only:
        return 0

    if not force and not ask_embed():
        log.log(log.YELLOW, 'Embedding cancelled.')
        return 0

    # Phase 2: Metadata Embedding
    log.phase(2, 'Embedding metadata into EPUBs')
    od = os.path.join(wdir, 'origins')
    nd = os.path.join(wdir, 'notfound')
    ed = os.path.join(wdir, 'embedded')
    os.makedirs(od, exist_ok=True)
    os.makedirs(nd, exist_ok=True)
    os.makedirs(ed, exist_ok=True)

    log.log(log.CYAN, '  Backup to origins/...')
    for book in results:
        fn = book.get('filename', '')
        if fn:
            src = os.path.join(wdir, fn)
            dst = os.path.join(od, fn)
            if os.path.exists(src):
                shutil.copy2(src, dst)
    log.result('success', 'Backup: %d files' % len(results))

    success_count = st.get('success', 0)
    log.log(log.CYAN, '  Embedding in %d books...' % success_count)
    es = {'embedded': 0, 'notfound': st['notfound'], 'failed': 0}
    fb = []
    t1 = time.time()
    ok_books = [b for b in results if b.get('status') == 'success' and b.get('metadata')]

    for i, book in enumerate(ok_books, 1):
        fn = book.get('filename', '')
        src = os.path.join(wdir, fn)
        log.log(log.CYAN, '  Book %d/%d' % (i, len(ok_books)))
        log.info('File', fn[:50])
        fa, ft, _ = parse_filename(fn)
        ok, err = embed_metadata(src, book.get('metadata'), afn=fa, tfn=ft)
        if ok:
            dst = os.path.join(ed, fn)
            if os.path.exists(src):
                shutil.move(src, dst)
            log.result('success', 'EMBEDDED -> embedded/%s' % fn[:40])
            es['embedded'] += 1
        else:
            log.result('error', 'FAILED: %s' % err[:50])
            es['failed'] += 1
            fb.append({'filename': fn, 'error': err})
        log.progress(i, len(ok_books), fn)

    for book in results:
        if book.get('status') == 'not_found':
            fn = book.get('filename', '')
            src = os.path.join(wdir, fn)
            dst = os.path.join(nd, fn)
            if os.path.exists(src):
                shutil.move(src, dst)

    print('')
    es['total'] = len(ok_books)
    log.phase_done(2, time.time() - t1, es)

    total = time.time() - log.start
    folders = {
        'origins/': len(results),
        'embedded/': es['embedded'],
        'notfound/': es['notfound']
    }
    log_path = os.path.join(wdir, 'pipeline.log')
    files = {
        'metadata_batch.json': '%.1f KB' % (os.path.getsize(jpath)/1024),
        'pipeline.log': '%.1f KB' % (os.path.getsize(log_path)/1024) if os.path.exists(log_path) else '0 KB',
    }
    log.summary(total, folders, files)

    if es['failed'] > 0:
        log.log(log.YELLOW, '  %d files failed, remains in directory' % es['failed'])
        for b in fb:
            log.log(log.YELLOW, '     - %s: %s' % (b['filename'], b['error'][:50]))

    report_path = generate_html_report(wdir, results, st, total)
    log.log(log.CYAN, '   Report HTML: pipeline_report.html (%.1f KB)' % (os.path.getsize(report_path)/1024))

    # Generate metadata_report.html from embedded EPUBs
    try:
        metadata_report_path = os.path.join(wdir, 'metadata_report.html')
        epub_files = [f for f in os.listdir(ed) if f.lower().endswith('.epub')]
        books = []
        for filename in epub_files:
            epub_path = os.path.join(ed, filename)
            metadata = read_epub_metadata(epub_path)
            books.append({'filename': filename, 'metadata': metadata or {}})

        generate_metadata_report(books, metadata_report_path)
        log.log(log.CYAN, '   Metadata Report: metadata_report.html (%.1f KB)' % (os.path.getsize(metadata_report_path)/1024))
    except Exception as e:
        log.log(log.YELLOW, '   Warning: Could not generate metadata_report.html: %s' % str(e)[:50])

    return 0


# Entry Point
def main():
    parser = argparse.ArgumentParser(
        description='EPUB Metadata Pipeline (IBS.it Fast) - Search via Algolia API and embed metadata',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python ibs_fast_metadata_search.py ./books              # Interactive mode
  python ibs_fast_metadata_search.py ./books --force      # Auto-embed after scraping
  python ibs_fast_metadata_search.py ./books --json-only  # Only scrape, no embed
        '''
    )
    parser.add_argument('working_dir', help='Directory containing EPUB files')
    parser.add_argument('--delay', type=float, default=0.0,
                        help='Ignored (fast mode has no delay between requests)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose output')
    parser.add_argument('--force', '-f', action='store_true',
                        help='Skip embedding confirmation prompt')
    parser.add_argument('--json-only', action='store_true',
                        help='Only scrape metadata, skip embedding')

    args = parser.parse_args()
    return run_pipeline(
        args.working_dir,
        delay=args.delay,
        verbose=args.verbose,
        force=args.force,
        json_only=args.json_only
    )


if __name__ == '__main__':
    sys.exit(main())
