#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch VEJA bestseller lists and cache them as JSON for the Best-Sellers
calibre plugin.

VEJA publishes weekly bestseller lists across 4 categories:
    - Ficção (ficcao)
    - Não ficção (nao-ficcao)
    - Autoajuda e esoterismo (autoajuda-e-esoterismo)
    - Infantojuvenil (infantojuvenil)

On the live site (https://veja.abril.com.br/vitrine-livros-mais-vendidos/),
the categories are loaded via WordPress admin-ajax (troca_genero_ajax), and
full synopses reside on individual book detail pages (/vitrine-livros-mais-vendidos/<slug>/).

This script mirrors the lists into static JSON files with full detail-page
synopsis enrichment, served via GitHub Pages for the plugin.

Output structure:
    veja/<slug>.json   — one file per category (e.g. veja/ficcao.json)
    veja/meta.json     — metadata and fetch timestamp
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


BASE_URL = 'https://veja.abril.com.br/vitrine-livros-mais-vendidos/'
AJAX_URL = 'https://veja.abril.com.br/wp-admin/admin-ajax.php'

CATEGORIES = [
    ('ficcao', 'Ficção'),
    ('nao-ficcao', 'Não ficção'),
    ('autoajuda-e-esoterismo', 'Autoajuda e esoterismo'),
    ('infantojuvenil', 'Infantojuvenil'),
]

USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/128.0.0.0 Safari/537.36'
)


def _make_ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def _fetch_url(url, data=None, headers=None, timeout=15):
    """Perform HTTP GET or POST request with default headers and retries."""
    req_headers = {
        'User-Agent': USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    }
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(url, data=data, headers=req_headers)
    ctx = _make_ssl_context()
    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
                return resp.read().decode('utf-8', errors='replace')
        except Exception as e:
            last_err = e
            time.sleep(1.0 * (attempt + 1))
    print(f'[WARN] Fetch failed for {url}: {last_err}')
    return None


def parse_veja_cards_html(html_text, base_url=BASE_URL):
    """Parse book cards from VEJA listing HTML."""
    if not html_text or not BeautifulSoup:
        return []
    soup = BeautifulSoup(html_text, 'html.parser')
    cards = soup.select('.listagem-livros .card')
    if not cards:
        cards = soup.select('.card')

    books = []
    for i, card in enumerate(cards, 1):
        # Rank
        rank_el = card.select_one('.classificacao')
        rank = rank_el.get_text(strip=True) if rank_el else str(i)

        # Title
        title_el = card.find('h3') or card.find('h2') or card.find('h4')
        title = title_el.get_text(strip=True) if title_el else ''
        if not title:
            continue

        # Author
        autor_el = card.select_one('.autor')
        authors = autor_el.get_text(strip=True) if autor_el else '—'

        # Publisher
        editora_el = card.select_one('.editora')
        publisher = editora_el.get_text(strip=True) if editora_el else ''

        # Detail link
        detail_a = card.select_one('a.leia-mais, a[href*="/vitrine-livros-mais-vendidos/"]')
        source_url = ''
        if detail_a and detail_a.get('href'):
            source_url = urllib.parse.urljoin(base_url, detail_a['href'])
        elif card.find('a', href=True):
            source_url = urllib.parse.urljoin(base_url, card.find('a', href=True)['href'])

        # Cover image
        cover_img = card.select_one('.capa img, img')
        cover_url = ''
        if cover_img and cover_img.get('src'):
            cover_url = urllib.parse.urljoin(base_url, cover_img['src'].strip())

        # Card synopsis
        sinopse_el = card.select_one('.sinopse')
        blurb = ''
        if sinopse_el:
            b_tag = sinopse_el.find('b')
            if b_tag and 'sinopse' in b_tag.get_text(strip=True).lower():
                b_tag.decompose()
            blurb = sinopse_el.get_text(separator=' ', strip=True)

        # Ranking history
        anterior_el = card.select_one('.anterior')
        prev_rank = ''
        if anterior_el:
            prev_rank = re.sub(r'^\s*semana\s+anterior\s*:\s*', '', anterior_el.get_text(strip=True), flags=re.I)

        consec_el = card.select_one('.consecutiva')
        weeks = ''
        if consec_el:
            weeks = re.sub(r'^\s*semanas\s+na\s+lista\s*:\s*', '', consec_el.get_text(strip=True), flags=re.I)

        # Buy link
        compra_a = card.select_one('a[href*="amazon"], .compra')
        buy_url = ''
        if compra_a:
            buy_url = compra_a['href'] if compra_a.name == 'a' else (
                compra_a.parent.get('href') if compra_a.parent and compra_a.parent.name == 'a' else ''
            )

        books.append({
            'rank': str(rank),
            'title': title,
            'authors': authors,
            'publisher': publisher,
            'cover_url': cover_url,
            'source_url': source_url,
            'blurb': blurb,
            'summary': blurb,
            'previous_rank': prev_rank,
            'weeks_on_list': weeks,
            'buy_url': buy_url,
        })
    return books


def extract_veja_detail(html_text, detail_url=''):
    """Extract full synopsis and metadata from a VEJA detail page."""
    if not html_text or not BeautifulSoup:
        return {}
    soup = BeautifulSoup(html_text, 'html.parser')
    data = {}

    # Full synopsis from .resume
    resume_el = soup.select_one('.resume, .content .resume, .post .resume')
    if resume_el:
        paras = [p.get_text(strip=True) for p in resume_el.find_all('p') if p.get_text(strip=True)]
        if paras:
            data['blurb'] = '\n\n'.join(paras)
            data['summary'] = data['blurb']

    # Ficha técnica table
    book_data = soup.select_one('.book-data')
    if book_data:
        for tr in book_data.find_all('tr'):
            tds = tr.find_all('td')
            if len(tds) >= 2:
                label = tds[0].get_text(strip=True).lower().replace(':', '')
                val = tds[1].get_text(strip=True)
                if 'título' in label or 'titulo' in label:
                    data['title'] = val
                elif 'autor' in label:
                    data['authors'] = val
                elif 'editora' in label:
                    data['publisher'] = val
                elif 'ano' in label:
                    data['published'] = val
                elif 'página' in label or 'pagina' in label:
                    data['pages'] = val

    # Cover image in detail page
    cover_el = soup.select_one('.book .img-book img, .book img')
    if cover_el and cover_el.get('src'):
        src = cover_el['src'].strip()
        if src.startswith('http'):
            data['cover_url'] = src
        elif detail_url:
            data['cover_url'] = urllib.parse.urljoin(detail_url, src)

    return data


def enrich_book(book):
    """Fetch detail page for a single book and merge full synopsis."""
    source_url = book.get('source_url')
    if not source_url or 'veja.abril.com.br' not in source_url:
        return book

    html = _fetch_url(source_url, timeout=12)
    if not html:
        return book

    detail = extract_veja_detail(html, detail_url=source_url)
    if detail.get('blurb'):
        book['blurb'] = detail['blurb']
        book['summary'] = detail['blurb']
    if detail.get('published'):
        book['published'] = detail['published']
    if detail.get('pages'):
        book['pages'] = detail['pages']
    if detail.get('publisher') and not book.get('publisher'):
        book['publisher'] = detail['publisher']
    if detail.get('cover_url') and detail['cover_url'].startswith('http'):
        book['cover_url'] = detail['cover_url']

    return book


def fetch_category_live(slug, nonce, main_html=None):
    """Fetch 20 books for a category from live site."""
    if slug == 'ficcao' and main_html:
        books = parse_veja_cards_html(main_html)
        if books:
            return books

    # Fetch via WordPress admin-ajax
    post_data = urllib.parse.urlencode({
        'action': 'troca_genero_ajax',
        'nonce': nonce or '',
        'genero': slug,
    }).encode('utf-8')

    resp_text = _fetch_url(
        AJAX_URL,
        data=post_data,
        headers={
            'Referer': BASE_URL,
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest',
        }
    )
    if not resp_text:
        return []

    try:
        data = json.loads(resp_text)
        top_20_html = data.get('top_20', '')
        return parse_veja_cards_html(top_20_html)
    except Exception as e:
        print(f'[ERROR] Failed to parse AJAX JSON for {slug}: {e}')
        return []


def run(output_dir='veja', enrich_details=True, local_dir=None):
    """Execute complete fetch and build cache files."""
    os.makedirs(output_dir, exist_ok=True)
    categories_meta = []

    main_html = None
    nonce = None

    if local_dir and os.path.isdir(local_dir):
        print(f'Using local HTML dumps from {local_dir}')
    else:
        print(f'Fetching initial page from {BASE_URL}...')
        main_html = _fetch_url(BASE_URL)
        if main_html and BeautifulSoup:
            soup = BeautifulSoup(main_html, 'html.parser')
            nonce_input = soup.find('input', attrs={'name': 'nonce_vitrine'})
            if nonce_input:
                nonce = nonce_input.get('value')
        print(f'Live page fetched. Nonce: {nonce}')

    for idx, (slug, label) in enumerate(CATEGORIES, 1):
        print(f'\nProcessing [{idx}/{len(CATEGORIES)}] {label} ({slug})...')
        books = []

        if local_dir:
            local_file = os.path.join(local_dir, f'Os livros mais vendidos _ VEJA{idx}.htm')
            if os.path.isfile(local_file):
                with open(local_file, 'r', encoding='utf-8', errors='ignore') as f:
                    books = parse_veja_cards_html(f.read())
                print(f'  Loaded {len(books)} books from local file {local_file}')

        if not books:
            books = fetch_category_live(slug, nonce, main_html=main_html)
            print(f'  Fetched {len(books)} books from live site')

        if enrich_details and books:
            print(f'  Enriching {len(books)} books with detail-page synopses...')
            t0 = time.time()
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {executor.submit(enrich_book, b): b for b in books}
                for f in as_completed(futures):
                    try:
                        f.result()
                    except Exception as ex:
                        print(f'    Enrichment error: {ex}')
            print(f'  Enrichment completed in {time.time()-t0:.1f}s')

        # Save category JSON
        out_path = os.path.join(output_dir, f'{slug}.json')
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(books, f, ensure_ascii=False, indent=2)
        print(f'  Saved {len(books)} books to {out_path}')

        categories_meta.append({
            'slug': slug,
            'name': label,
            'count': len(books),
            'url': f'https://cm-fy.github.io/best-sellers-veja-cache/veja/{slug}.json',
        })

    # Save meta.json
    meta = {
        'updated': datetime.now(timezone.utc).isoformat(),
        'source': BASE_URL,
        'categories': categories_meta,
    }
    meta_path = os.path.join(output_dir, 'meta.json')
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f'\nSaved metadata to {meta_path}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Fetch VEJA bestsellers and build cache')
    parser.add_argument('--output-dir', default='veja', help='Output directory for JSON files')
    parser.add_argument('--no-enrich', action='store_true', help='Skip detail-page synopsis enrichment')
    parser.add_argument('--local-dir', default=None, help='Directory with local HTML files')
    args = parser.parse_args()

    enrich = not args.no_enrich and os.environ.get('VEJA_DETAILS', '1') != '0'
    run(output_dir=args.output_dir, enrich_details=enrich, local_dir=args.local_dir)
