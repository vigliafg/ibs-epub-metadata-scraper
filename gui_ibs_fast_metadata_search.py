#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# gui_ibs_fast_metadata_search.py
# GUI for EPUB Metadata Scraper (Fast Mode) via customtkinter
#
# Provides an easy-to-use interface to select the working directory,
# configure options, run the pipeline, and view live execution logs.

import os
import sys
import threading
import queue
import re
import json
import time
import shutil
import datetime

from tkinter import filedialog, messagebox

try:
    import customtkinter as ctk
except ImportError:
    print('Error: customtkinter library required. Install with: pip install customtkinter')
    sys.exit(1)

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

# ── Import everything from the original script ──────────────────────────────────
from ibs_fast_metadata_search import (
    BASE_URL, HEADERS, TIMEOUT,
    ALGOLIA_APP_ID, ALGOLIA_API_KEY, ALGOLIA_INDEX, ALGOLIA_URL,
    get_session, read_epub_metadata, format_time, strip_ansi, Logger,
    search_ibs, _parse_algolia_hits, get_book_description, get_book_metadata,
    find_book_in_results, find_book_metadata, embed_metadata, parse_filename,
    generate_html_report, generate_metadata_report,
    ET,
)

# ── ANSI colour constants (matches Logger palette) ──────────────────────────────
RESET  = '\u001b[0m'
BOLD   = '\u001b[1m'
DIM    = '\u001b[2m'
CYAN   = '\u001b[36m'
GREEN  = '\u001b[32m'
YELLOW = '\u001b[33m'
RED    = '\u001b[31m'
WHITE  = '\u001b[37m'

# Map logical names → CTk hex colours
CTK_COLOUR = {
    'CYAN':   '#00d4ff',
    'GREEN':  '#00e676',
    'YELLOW': '#ffab00',
    'RED':    '#ff5252',
    'WHITE':  '#cccccc',
    'DIM':    '#555555',
}


# ── Logger that also feeds lines into the GUI queue ────────────────────────────
class Guilogger(Logger):
    """Logger that puts every line into a queue for the GUI Text widget."""

    def __init__(self, queue_obj, log_file=None):
        super().__init__(log_file)
        self._queue = queue_obj

    def out(self, text):
        print(text, flush=True)
        if self.log_file:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(strip_ansi(text) + '\n')
        self._queue.put(strip_ansi(text))


# ── Redirect Python prints into the log queue ───────────────────────────────────
class _OutputRedirector:
    def __init__(self, queue_obj, prefix=''):
        self._queue = queue_obj
        self._prefix = prefix

    def write(self, text):
        if text.strip():
            self._queue.put(self._prefix + text)

    def flush(self):
        pass


# ── Core pipeline (runs in a background thread) ─────────────────────────────────
def pipeline_thread(log_queue, wdir, force, json_only, verbose):
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = _OutputRedirector(log_queue, '[PY] ')
    sys.stderr = _OutputRedirector(log_queue, '[ERR] ')

    try:
        log = Guilogger(log_queue, log_file=os.path.join(wdir, 'pipeline.log'))
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

        # ── Phase 1: Metadata Search ────────────────────────────────────────────
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

        # If json_only or not force (GUI auto-confirms via --force), skip embedding
        if json_only or not force:
            log.log(log.CYAN, '   Embedding skipped (JSON-only mode or --force not set).')
            log.log(log.GREEN, '*** PIPELINE COMPLETED ***')
            return 0

        # ── Phase 2: Metadata Embedding ────────────────────────────────────────
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

        total_elapsed = time.time() - log.start
        folders = {
            'origins/': len(results),
            'embedded/': es['embedded'],
            'notfound/': es['notfound']
        }
        log_path = os.path.join(wdir, 'pipeline.log')
        files = {
            'metadata_batch.json': '%.1f KB' % (os.path.getsize(jpath)/1024),
            'pipeline.log': '%.1f KB' % (os.path.getsize(log_path)/1024)
                           if os.path.exists(log_path) else '0 KB',
        }
        log.summary(total_elapsed, folders, files)

        if es['failed'] > 0:
            log.log(log.YELLOW, '  %d files failed, remains in directory' % es['failed'])
            for b in fb:
                log.log(log.YELLOW, '     - %s: %s' % (b['filename'], b['error'][:50]))

        report_path = generate_html_report(wdir, results, st, total_elapsed)
        log.log(log.CYAN, '   Report HTML: pipeline_report.html (%.1f KB)'
               % (os.path.getsize(report_path)/1024))

        try:
            metadata_report_path = os.path.join(wdir, 'metadata_report.html')
            epub_files = [f for f in os.listdir(ed)
                          if f.lower().endswith('.epub')]
            books = []
            for filename in epub_files:
                epub_path = os.path.join(ed, filename)
                metadata = read_epub_metadata(epub_path)
                books.append({'filename': filename, 'metadata': metadata or {}})
            generate_metadata_report(books, metadata_report_path)
            log.log(log.CYAN,
                    '   Metadata Report: metadata_report.html (%.1f KB)'
                    % (os.path.getsize(metadata_report_path)/1024))
        except Exception as e:
            log.log(log.YELLOW,
                    '   Warning: Could not generate metadata_report.html: %s'
                    % str(e)[:50])

        log.log(log.GREEN, '*** PIPELINE COMPLETED ***')
        return 0

    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        log_queue.put(None)   # Sentinel: end of stream


# ── Colour detection helper ─────────────────────────────────────────────────────
def _detect_colour(line):
    """Return the CTk colour name for a log line based on its content."""
    s = line.strip()
    if '[OK]' in s or 'FOUND' in s or 'EMBEDDED' in s or 'COMPLETED' in s:
        return 'GREEN'
    if '[FAIL]' in s or 'ERROR' in s or ' FAILED' in s or 'failed' in s:
        return 'RED'
    if '[WARN]' in s or 'WARNING' in s:
        return 'YELLOW'
    if '[PHASE' in s:
        return 'CYAN'
    if s.startswith('+') or s.startswith('|') or s.startswith(' '):
        return 'DIM'
    return 'WHITE'


# ── Main GUI Application ────────────────────────────────────────────────────────
class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode('dark')
        ctk.set_default_color_theme('blue')

        self.title('EPUB Metadata Scraper – IBS.it (Fast Mode)')
        self.geometry('960x740')
        self.minsize(820, 600)

        self._running = False
        self._thread = None

        self._build_ui()

    # ── UI construction ────────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Top banner ──────────────────────────────────────────────────────────
        banner = ctk.CTkFrame(self, fg_color='#1a1a2e', height=56)
        banner.pack(fill='x', padx=0, pady=0)
        banner.pack_propagate(False)

        ctk.CTkLabel(
            banner,
            text='📚  EPUB Metadata Scraper – IBS.it (Fast Mode)',
            font=ctk.CTkFont(size=17, weight='bold'),
            text_color='#00d4ff'
        ).pack(side='left', padx=20, pady=12)

        # ── Settings panel ──────────────────────────────────────────────────────
        settings = ctk.CTkFrame(self, fg_color='transparent')
        settings.pack(fill='x', padx=16, pady=(12, 0))

        # Working directory row
        dir_frame = ctk.CTkFrame(settings, fg_color='transparent')
        dir_frame.pack(fill='x', pady=(0, 10))

        ctk.CTkLabel(dir_frame, text='Working Directory:', width=140,
                     anchor='w').pack(side='left', padx=(0, 8))

        self.dir_var = ctk.StringVar()
        dir_entry = ctk.CTkEntry(dir_frame, textvariable=self.dir_var,
                                  font=('Courier', 12), height=36)
        dir_entry.pack(side='left', fill='x', expand=True, padx=(0, 8))

        ctk.CTkButton(dir_frame, text='Browse…', width=100, height=36,
                      command=self._browse_dir).pack(side='left')

        # Options row (checkboxes)
        opts_frame = ctk.CTkFrame(settings, fg_color='transparent')
        opts_frame.pack(fill='x', pady=(0, 10))

        self.force_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(opts_frame,
                        text='--force  (Skip embedding confirmation, auto-embed)',
                        variable=self.force_var, onvalue=True, offvalue=False
                        ).pack(side='left', padx=(0, 24))

        self.json_only_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(opts_frame,
                        text='--json-only  (Scrape only, skip embedding)',
                        variable=self.json_only_var, onvalue=True, offvalue=False
                        ).pack(side='left', padx=(0, 24))

        self.verbose_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(opts_frame, text='--verbose',
                        variable=self.verbose_var, onvalue=True, offvalue=False
                        ).pack(side='left')

        # ── Buttons row ──────────────────────────────────────────────────────────
        btn_frame = ctk.CTkFrame(self, fg_color='transparent')
        btn_frame.pack(fill='x', padx=16, pady=(4, 8))

        self.run_btn = ctk.CTkButton(
            btn_frame, text='▶  Run Pipeline', height=40,
            font=ctk.CTkFont(size=15, weight='bold'),
            fg_color='#00e676', text_color='#000000',
            hover_color='#00c853',
            command=self._on_run
        )
        self.run_btn.pack(side='left', padx=(0, 12))

        ctk.CTkButton(btn_frame, text='Clear Log', height=40,
                      fg_color='#555555', hover_color='#666666',
                      command=self._clear_log
                      ).pack(side='left', padx=(0, 12))

        self.stop_btn = ctk.CTkButton(
            btn_frame, text='■ Stop', height=40,
            fg_color='#ff5252', hover_color='#ff1744',
            state='disabled',
            command=self._on_stop
        )
        self.stop_btn.pack(side='left')

        # ── Status bar ───────────────────────────────────────────────────────────
        self.status_var = ctk.StringVar(value='Ready – select a directory and click Run')
        ctk.CTkLabel(self, textvariable=self.status_var, anchor='w',
                     height=24, font=ctk.CTkFont(size=11),
                     text_color='#888888').pack(fill='x', padx=16, pady=(0, 4))

        # ── Log text widget ─────────────────────────────────────────────────────
        log_frame = ctk.CTkFrame(self, fg_color='#0d1117')
        log_frame.pack(fill='both', expand=True, padx=16, pady=(0, 12))

        self.log_queue = queue.Queue()
        self.log_text = ctk.CTkTextbox(
            log_frame,
            font=ctk.CTkFont(family='Courier', size=11),
            fg_color='#0d1117', text_color='#cccccc',
            border_width=0, undo=False, wrap='none'
        )
        self.log_text.pack(fill='both', expand=True, padx=4, pady=4)

        # Scrollbar
        scrollbar = ctk.CTkScrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(side='right', fill='y')
        self.log_text.configure(yscrollcommand=scrollbar.set)

        # Define colour tags
        for colour_name, colour_hex in CTK_COLOUR.items():
            self.log_text.tag_config(colour_name, foreground=colour_hex)

        # Start polling the queue
        self._poll_job = None
        self._schedule_poll()

    # ── Directory browser ───────────────────────────────────────────────────────
    def _browse_dir(self):
        path = filedialog.askdirectory(
            title='Select working directory with EPUB files')
        if path:
            self.dir_var.set(path)

    # ── Run / Stop ──────────────────────────────────────────────────────────────
    def _on_run(self):
        wdir = self.dir_var.get().strip()
        if not wdir:
            self._append_log('ERROR: Please select a working directory.', 'RED')
            return
        if not os.path.isdir(wdir):
            self._append_log('ERROR: Directory not found: %s' % wdir, 'RED')
            return

        epubs = [f for f in os.listdir(wdir) if f.lower().endswith('.epub')]
        if not epubs:
            self._append_log('ERROR: No EPUB files in directory.', 'RED')
            return

        self._clear_log()
        self._append_log('▶ Starting pipeline …', 'CYAN')
        self._append_log('   Directory: %s  |  EPUB files: %d' % (wdir, len(epubs)), 'WHITE')
        self._append_log('', 'WHITE')

        # Guard against conflicting options
        if self.force_var.get() and self.json_only_var.get():
            self._append_log('ERROR: --force and --json-only cannot be used together.', 'RED')
            return

        self._running = True
        self.run_btn.configure(state='disabled', fg_color='#444444', text_color='#888888')
        self.stop_btn.configure(state='normal')
        self.status_var.set('Running…')

        force = self.force_var.get()
        json_only = self.json_only_var.get()
        verbose = self.verbose_var.get()

        self._thread = threading.Thread(
            target=pipeline_thread,
            args=(self.log_queue, wdir, force, json_only, verbose),
            daemon=True
        )
        self._thread.start()

    def _on_stop(self):
        self._append_log('\n■ Stop requested – pipeline will finish current book…', 'YELLOW')
        self.stop_btn.configure(state='disabled')

    # ── Queue polling (runs on main thread via self.after) ─────────────────────
    def _schedule_poll(self):
        self._poll_job = self.after(100, self._poll_queue)

    def _poll_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                if msg is None:
                    self._on_pipeline_done()
                    break
                self._process_log_line(msg)
        except queue.Empty:
            pass
        self._schedule_poll()

    def _process_log_line(self, line):
        """Append a line to the log with colour coding based on content."""
        if not line:
            return
        colour = _detect_colour(line)
        self.log_text.insert('end', line.rstrip() + '\n', colour)
        self.log_text.see('end')

    def _append_log(self, text, colour='WHITE'):
        self.log_text.insert('end', text.rstrip() + '\n', colour)
        self.log_text.see('end')

    def _on_pipeline_done(self):
        self._running = False
        self.run_btn.configure(state='normal', fg_color='#00e676',
                               text_color='#000000')
        self.stop_btn.configure(state='disabled')
        self.status_var.set('Pipeline finished')
        self._append_log('\n=== DONE ===', 'GREEN')

    # ── Clear log ────────────────────────────────────────────────────────────────
    def _clear_log(self):
        self.log_text.delete('0.0', 'end')


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app = App()
    app.mainloop()