#!/usr/bin/env python3
"""Link the note's cross-references in index.html, so every citation of evidence is one click.

Inside <main> (and the footer), outside tags, links, code and SVG:

  * "Exhibit 8" -> <a class="xref" href="#ex-8">Exhibit 8</a>; "Exhibits 15 and 17" links each number;
  * "Section 7" -> <a class="xref" href="#testing">Section 7</a>, by the contents list's numbering;
  * each exhibit's label <span class="ex-label">Exhibit 8</span> becomes a link to the exhibit itself;
  * a commit hash shown as <code>7c7d3f9</code> links to that commit on GitHub (only hashes that
    resolve to a commit of this repository; design and calendar hashes are left alone).

Text is never changed: only links are added, so every data-metric marker keeps its text.
Idempotent: a second run changes nothing. --check exits 1 if the page has a reference left
unlinked (tests/test_site_links.py runs it).
"""

import argparse
import html
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = ROOT / 'index.html'
REPO_URL = 'https://github.com/NavnoorBawa/russell3000-pairs-trading'

REF = re.compile(r'\b(Exhibits?|Sections?)(\s+)(\d+)((?:(?:,\s*|\s+and\s+|\s*[–-]\s*|\s+to\s+)\d+)*)')
SKIP = {'a', 'code', 'pre', 'svg', 'script', 'style', 'title', 'noscript'}


def section_ids(page):
    """Section number -> id, from the contents list (<span class="toc-n">N</span> in a link)."""
    out = {}
    for m in re.finditer(r'<a href="#([\w-]+)"><span class="toc-n">(\d+)</span>', page):
        out.setdefault(int(m.group(2)), m.group(1))
    return out


def exhibit_ids(page):
    return {int(n) for n in re.findall(r'<figure class="exhibit[^"]*" id="ex-(\d+)"', page)}


def full_commit(short):
    try:
        out = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--verify', '-q', short + '^{commit}'],
                             capture_output=True, text=True, check=False)
    except OSError:
        return None
    return out.stdout.strip() or None


def link_text(text, sections, exhibits, missing):
    """Link the references in one run of text (no tags inside)."""
    def one(kind, n):
        n = int(n)
        if kind.startswith('Exhibit'):
            if n not in exhibits:
                missing.append(f'Exhibit {n}')
                return None
            return f'#ex-{n}'
        if n not in sections:
            missing.append(f'Section {n}')
            return None
        return f'#{sections[n]}'

    def sub(m):
        kind, space, first, rest = m.groups()
        single = kind in ('Exhibit', 'Section')
        href = one(kind, first)
        if single and not rest:
            return f'<a class="xref" href="{href}">{kind}{space}{first}</a>' if href else m.group(0)
        noun = kind.rstrip('s')
        parts = [kind + space]
        h = one(kind, first)
        parts.append(f'<a class="xref" href="{h}" aria-label="{noun} {first}">{first}</a>' if h else first)
        for sep, num in re.findall(r'((?:,\s*|\s+and\s+|\s*[–-]\s*|\s+to\s+))(\d+)', rest):
            h = one(kind, num)
            parts.append(sep + (f'<a class="xref" href="{h}" aria-label="{noun} {num}">{num}</a>' if h else num))
        return ''.join(parts)

    return REF.sub(sub, text)


def link_region(region, sections, exhibits, missing):
    """Link the text of an HTML region, skipping tags, links, code, pre and SVG."""
    out, stack = [], []
    for tok in re.split(r'(<[^>]+>)', region):
        if tok.startswith('<'):
            m = re.match(r'<(/?)([a-zA-Z][\w-]*)', tok)
            if m:
                closing, name = m.group(1) == '/', m.group(2).lower()
                if name in SKIP and not tok.endswith('/>'):
                    if closing:
                        if name in stack:
                            while stack and stack.pop() != name:
                                pass
                    else:
                        stack.append(name)
            out.append(tok)
        elif stack:
            out.append(tok)
        else:
            out.append(link_text(tok, sections, exhibits, missing))
    return ''.join(out)


def link_labels(page):
    return re.sub(r'<span class="ex-label">Exhibit (\d+)</span>',
                  r'<a class="ex-label" href="#ex-\1">Exhibit \1</a>', page)


def link_commits(region, cache):
    def sub(m):
        short = m.group(1)
        if short not in cache:
            cache[short] = full_commit(short)
        full = cache[short]
        if not full:
            return m.group(0)
        return f'<a class="commit" href="{REPO_URL}/commit/{full}"><code>{short}</code></a>'
    # a <code>hash</code> not already inside a link
    parts = re.split(r'(<a\b[^>]*>.*?</a>)', region, flags=re.S)
    return ''.join(p if p.startswith('<a') else re.sub(r'<code>([0-9a-f]{7,40})</code>', sub, p) for p in parts)


def apply(page):
    sections, exhibits, missing, cache = section_ids(page), exhibit_ids(page), [], {}
    page = link_labels(page)
    a, b = page.index('<main'), page.index('</main>')
    main = link_commits(link_region(page[a:b], sections, exhibits, missing), cache)
    page = page[:a] + main + page[b:]
    return page, missing


def unlinked(page):
    """References left as plain text inside <main> (what --check reports)."""
    sections, exhibits = section_ids(page), exhibit_ids(page)
    a, b = page.index('<main'), page.index('</main>')
    found = []
    stack = []
    for tok in re.split(r'(<[^>]+>)', page[a:b]):
        if tok.startswith('<'):
            m = re.match(r'<(/?)([a-zA-Z][\w-]*)', tok)
            if m and m.group(2).lower() in SKIP and not tok.endswith('/>'):
                if m.group(1):
                    while stack and stack.pop() != m.group(2).lower():
                        pass
                else:
                    stack.append(m.group(2).lower())
        elif not stack:
            for r in REF.finditer(html.unescape(tok)):
                found.append(r.group(0))
    return found


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--check', action='store_true', help='exit 1 if a reference is left unlinked')
    args = ap.parse_args(argv)
    page = PAGE.read_text(encoding='utf-8')
    if args.check:
        left = unlinked(page)
        if left:
            print('unlinked references in index.html:', ', '.join(left))
            return 1
        print('every Exhibit and Section reference in index.html is linked')
        return 0
    new, missing = apply(page)
    if missing:
        print('references to nothing on the page: ' + ', '.join(sorted(set(missing))), file=sys.stderr)
        return 1
    if new != page:
        PAGE.write_text(new, encoding='utf-8')
        print('linked the references in index.html')
    else:
        print('index.html already linked')
    return 0


if __name__ == '__main__':
    sys.exit(main())
