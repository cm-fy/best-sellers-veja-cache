# Best-Sellers VEJA Cache

Static cached VEJA bestseller list data, updated weekly via GitHub Actions.

## Why a cache?

VEJA publishes Brazil's leading weekly bestsellers vitrine (`https://veja.abril.com.br/vitrine-livros-mais-vendidos/`).
Category tabs rely on dynamic WordPress AJAX (`admin-ajax.php` with `action: troca_genero_ajax` and session nonce), and full synopses are split across individual book detail pages (`/vitrine-livros-mais-vendidos/<slug>/`).

To give the Best-Sellers Calibre plugin instantaneous loading and complete synopses without hitting rate limits, paywalls, or dynamic scripting in Calibre, this static cache mirrors the 4 weekly bestseller lists pre-enriched with full synopses.

## Data format

- `veja/meta.json` — metadata about all cached lists and update timestamps
- `veja/ficcao.json` — Ficção (Top 20)
- `veja/nao-ficcao.json` — Não ficção (Top 20)
- `veja/autoajuda-e-esoterismo.json` — Autoajuda e esoterismo (Top 20)
- `veja/infantojuvenil.json` — Infantojuvenil (Top 20)

Each book object uses the schema the Best-Sellers plugin expects:

```json
{
  "rank": "1",
  "title": "Verity",
  "authors": "Colleen Hoover",
  "publisher": "GALERA RECORD",
  "cover_url": "https://veja.abril.com.br/wp-content/uploads/...",
  "source_url": "https://veja.abril.com.br/vitrine-livros-mais-vendidos/verity-2/",
  "blurb": "Um casal apaixonado. Uma intrusa. Três mentes doentias...",
  "published": "2020",
  "pages": "320",
  "previous_rank": "1º lugar",
  "weeks_on_list": "226 (não consecutivas)",
  "buy_url": "https://link.amazon/..."
}
```

## GitHub Pages URL pattern

```
https://cm-fy.github.io/best-sellers-veja-cache/veja/{slug}.json
```

## Data freshness

Lists are updated weekly (Sundays at 04:00 UTC) via GitHub Actions. Manual refreshes can also be triggered via the Actions tab.

## Running locally

```bash
pip install requests beautifulsoup4 lxml
python3 fetch_veja.py
```
