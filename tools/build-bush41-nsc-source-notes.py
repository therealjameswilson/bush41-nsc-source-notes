#!/usr/bin/env python3
"""Build FRUS-style Bush 41 NSC source-note entries from the Bush Library finding aid."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


SITE_ROOT = "https://www.bush41library.gov"
FINDING_AID_URL = (
    "https://www.bush41library.gov/digital-research-room/finding-aid/"
    "records-national-security-council-george-h-w-bush-administration"
)
SERIES_ENDPOINT = SITE_ROOT + "/bush-finding-aids/series-info/{naid}/finding-aids/all"
SOURCE_PREFIX = "George H.W. Bush Library, Bush Presidential Records, National Security Council"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


H_FILES_TITLES = {
    "H-Files - National Security Council (NSC) Meeting Files": "H-Files, NSC Meetings Files",
    "H-Files - National Security Council (NSC)/Deputies Committee (DC) Meetings Files": (
        "H-Files, NSC/DC Meetings Files"
    ),
    "H-Files - National Security Council (NSC)/Deputies Committee (DC) Meetings Follow-up Files": (
        "H-Files, NSC/DC Meetings Follow-up Files"
    ),
    "H-Files - National Security Review (NSR) Files": "H-Files, NSR Files",
}

ORG_PREFIXES = [
    "African Affairs Directorate",
    "European and Eurasian Directorate",
    "European and Soviet Directorate",
    "Executive Secretary",
    "Latin American Affairs Directorate",
    "Latin American Directorate",
    "National Security Council (NSC) Institutional Files (IF)",
    "National Security Council (NSC) Presidential Acquisitions (PA) Limited Access",
    "National Security Council (NSC) Presidential Acquisitions (PA)",
    "National Security Council (NSC) Presidential Record System (PRS) Limited Access",
    "National Security Council (NSC)",
    "NSC (National Security Council)",
    "PRS (Presidential Records System)",
    "White House Situation Room",
    "White House Situation Support Staff (WHSSS)",
]

DESCRIPTOR_STARTS = {
    "1989",
    "1989-1990",
    "1990",
    "Administrative",
    "Briefings",
    "Calendar",
    "Case",
    "CFE",
    "Chronological",
    "Cleared",
    "Commonwealth",
    "Confidential",
    "Concurrence",
    "Correspondence",
    "Country",
    "Economic",
    "Electronic",
    "European",
    "Files",
    "Foreign",
    "International",
    "Iraq-BNL",
    "Litigation",
    "Memcon",
    "Meeting",
    "Meetings",
    "Memorandum",
    "Middle",
    "National",
    "Notebook",
    "North",
    "Pan",
    "Panama",
    "Personal",
    "Personnel",
    "President",
    "Presidential",
    "Press",
    "Robert",
    "Schedule/Phone",
    "Search",
    "Small",
    "Somalia",
    "Soviet",
    "State",
    "Statements",
    "Subject",
    "Summit",
    "Telephone",
    "Terrorism",
    "Tiananmen",
    "Travel",
    "Trip",
    "U.S.-China",
    "USSR",
    "Vietnam",
    "Working",
}


def clean_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    text = re.sub(r"\s*/\s*", "/", text)
    return text


def clean_title(value: str) -> str:
    title = re.sub(r"^-+\s*", "", clean_text(value))
    return re.sub(r"\s*-\s*", "-", title)


def ensure_sentence(text: str) -> str:
    return text if re.search(r"[.?!]$", text) else text + "."


def request_headers(is_ajax: bool = False) -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT}
    if is_ajax:
        headers["X-Requested-With"] = "XMLHttpRequest"
    return headers


def cache_key(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest() + ".cache"


def fetch_text(url: str, *, is_ajax: bool = False, cache_dir: Path | None = None) -> str:
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        target = cache_dir / cache_key(url)
        if target.exists():
            return target.read_text(encoding="utf-8")

    last_error: Exception | None = None
    for attempt in range(5):
        try:
            request = urllib.request.Request(url, headers=request_headers(is_ajax=is_ajax))
            with urllib.request.urlopen(request, timeout=45) as response:
                body = response.read().decode("utf-8", "replace")
            if cache_dir:
                target.write_text(body, encoding="utf-8")
            return body
        except (TimeoutError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Could not fetch {url}: {last_error}")


def iter_tag_blocks(markup: str, tag: str, class_fragment: str):
    class_pattern = re.escape(class_fragment)
    open_re = re.compile(
        rf"<{tag}\b(?=[^>]*class=(?:\"[^\"]*{class_pattern}[^\"]*\"|'[^']*{class_pattern}[^']*'))[^>]*>",
        re.I,
    )
    close_re = re.compile(rf"</?{tag}\b[^>]*>", re.I)
    for match in open_re.finditer(markup):
        depth = 0
        for tag_match in close_re.finditer(markup, match.start()):
            token = tag_match.group(0)
            if token.startswith("</"):
                depth -= 1
                if depth == 0:
                    yield match.start(), tag_match.end(), markup[match.start() : tag_match.end()]
                    break
            else:
                depth += 1


def field_block(markup: str, field_name: str) -> str:
    class_fragment = f"field--name-{field_name}"
    for _, _, block in iter_tag_blocks(markup, "div", class_fragment):
        return block
    return ""


def field_values(markup: str, field_name: str) -> list[str]:
    block = field_block(markup, field_name)
    if not block:
        return []
    values = [
        clean_text(item)
        for item in re.findall(r'<div\b[^>]*class="[^"]*\bfield__item\b[^"]*"[^>]*>(.*?)</div>', block, re.S | re.I)
    ]
    values = [value for value in values if value]
    if values:
        return values
    fallback = re.sub(r'<div\b[^>]*class="[^"]*\bfield__label\b[^"]*"[^>]*>.*?</div>', " ", block, flags=re.S | re.I)
    fallback_text = clean_text(fallback)
    return [fallback_text] if fallback_text else []


def field_text(markup: str, field_name: str) -> str:
    return "; ".join(field_values(markup, field_name))


def first_heading(markup: str, heading: str) -> str:
    match = re.search(rf"<{heading}\b[^>]*>(.*?)</{heading}>", markup, re.S | re.I)
    return clean_text(match.group(1)) if match else ""


def links(markup: str) -> list[dict[str, str]]:
    parsed = []
    for match in re.finditer(r'<a\b[^>]*href="([^"]*)"[^>]*>(.*?)</a>', markup, re.S | re.I):
        href = html.unescape(match.group(1))
        label = clean_text(match.group(2))
        absolute = urllib.parse.urljoin(SITE_ROOT, href)
        parsed.append({"href": absolute, "label": label})
    return parsed


def extract_pdf_url(item_links: list[dict[str, str]]) -> str:
    for link in item_links:
        label = link["label"]
        href = link["href"]
        if label.startswith("http") and ".pdf" in label:
            return label
        if ".pdf" in href and "item_url=" in href:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            item_url = query.get("item_url", [""])[0]
            return urllib.parse.unquote(item_url)
        if href.startswith("http") and ".pdf" in href:
            return href
    return ""


def extract_catalog_url(item_links: list[dict[str, str]]) -> str:
    for link in item_links:
        if "catalog.archives.gov/id/" in link["href"]:
            return link["href"]
    return ""


def series_page_url(page: int) -> str:
    return FINDING_AID_URL if page == 0 else f"{FINDING_AID_URL}?page=,,,{page}"


def parse_series_page(markup: str, page: int) -> list[dict[str, str | int | bool]]:
    rows = []
    for _, _, article in iter_tag_blocks(markup, "article", "node--type-finding-aids-series"):
        title = clean_text(first_heading(article, "h2"))
        if not title:
            continue
        container_match = re.search(r'<div\b[^>]*class="[^"]*finding-aids-related-series[^"]*"[^>]*data-naid="([^"]+)"', article)
        item_links = links(article)
        rows.append(
            {
                "series_order": len(rows) + 1,
                "page": page + 1,
                "title": title,
                "source_series": style_series_title(title),
                "date": field_text(article, "field-series-date"),
                "local_id": field_text(article, "field-finding-aid-local-id"),
                "naid": field_text(article, "field-catalog-naid"),
                "record_types": field_text(article, "field-finding-aid-record-types"),
                "extent": field_text(article, "field-series-extent"),
                "arrangement": field_text(article, "field-series-system-arrangement"),
                "access_restriction": field_text(article, "field-access-restriction-status"),
                "use_restriction": field_text(article, "field-use-restriction-status"),
                "specific_access_restriction": field_text(article, "field-specific-access-restrictio"),
                "container_naid": container_match.group(1) if container_match else "",
                "has_container_list": bool(container_match),
                "catalog_url": extract_catalog_url(item_links)
                or (f"https://catalog.archives.gov/id/{field_text(article, 'field-catalog-naid')}" if field_text(article, "field-catalog-naid") else ""),
            }
        )
    return rows


def normalize_possessive_prefix(prefix: str) -> str:
    prefix = re.sub(r"'s\b", "", prefix)
    prefix = re.sub(r"'\b", "", prefix)
    prefix = re.sub(r"\s+and\s+", " and ", prefix)
    return clean_text(prefix)


def looks_like_person_prefix(prefix: str) -> bool:
    if not prefix:
        return False
    blocked = {
        "Administrative",
        "African",
        "European",
        "Executive",
        "H-Files",
        "Head",
        "Latin",
        "National",
        "NSC",
        "Presidential",
        "PRS",
        "Small",
        "Summit",
        "White",
    }
    first = prefix.split()[0]
    if first in blocked:
        return False
    return bool(re.search(r"[A-Z][a-z]+|[A-Z]\.", prefix))


def style_series_title(raw_title: str) -> str:
    title = clean_text(raw_title)
    if title in H_FILES_TITLES:
        return H_FILES_TITLES[title]

    for prefix in ORG_PREFIXES:
        if title.startswith(prefix + " "):
            rest = clean_title(title[len(prefix) + 1 :])
            return f"{prefix}, {rest}"

    tokens = title.split()
    descriptor_index = None
    for index, token in enumerate(tokens):
        normalized = token.rstrip(",")
        if normalized in DESCRIPTOR_STARTS:
            descriptor_index = index
            break
    if descriptor_index and descriptor_index > 0:
        prefix = normalize_possessive_prefix(" ".join(tokens[:descriptor_index]))
        descriptor = clean_title(" ".join(tokens[descriptor_index:]))
        if looks_like_person_prefix(prefix) and descriptor != "Files":
            return f"{prefix} Files, {descriptor}"
        if looks_like_person_prefix(prefix) and descriptor == "Files":
            return f"{prefix} Files"

    if "'s " in title or "' " in title:
        cleaned = normalize_possessive_prefix(title)
        return cleaned
    return title


def parse_file_units(fragment: str) -> list[dict[str, str]]:
    rows = []
    for start, _, article in iter_tag_blocks(fragment, "article", "node--type-finding-aids-fileunit"):
        summary_matches = list(re.finditer(r"<summary\b[^>]*>(.*?)</summary>", fragment[:start], re.S | re.I))
        container_id = ""
        if summary_matches:
            summary = clean_text(summary_matches[-1].group(1))
            container_id = re.sub(r"^Container ID\s+", "", summary)
        item_links = links(article)
        title = clean_title(first_heading(article, "h4"))
        rows.append(
            {
                "title": title,
                "local_id": field_text(article, "field-finding-aid-local-id"),
                "naid": field_text(article, "field-catalog-naid"),
                "record_types": field_text(article, "field-finding-aid-record-types"),
                "availability": field_text(article, "field-fileunit-online-open"),
                "container_id": container_id,
                "catalog_url": extract_catalog_url(item_links),
                "online_url": extract_pdf_url(item_links),
            }
        )
    return rows


def series_ajax_url(naid: str, page: int) -> str:
    base = SERIES_ENDPOINT.format(naid=naid)
    return base if page == 0 else f"{base}?page=%2C{page}"


def fetch_series_file_units(series: dict, cache_dir: Path | None) -> tuple[str, list[dict[str, str]], list[str]]:
    naid = str(series.get("container_naid") or series.get("naid") or "")
    if not naid:
        return str(series.get("local_id") or series.get("title")), [], []

    page = 0
    rows: list[dict[str, str]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    errors: list[str] = []
    while page < 500:
        url = series_ajax_url(naid, page)
        try:
            payload = json.loads(fetch_text(url, is_ajax=True, cache_dir=cache_dir))
        except Exception as exc:
            errors.append(f"{naid} page {page}: {exc}")
            break

        fragment = ""
        for command in payload:
            if isinstance(command, dict) and command.get("command") == "insert":
                fragment = command.get("data", "")
                break
        page_rows = parse_file_units(fragment)
        if not page_rows:
            break

        unique_page_rows = []
        for row in page_rows:
            key = (row.get("local_id", ""), row.get("naid", ""), row.get("title", ""))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            unique_page_rows.append(row)
        if not unique_page_rows:
            break

        rows.extend(unique_page_rows)
        page += 1

    return naid, rows, errors


def source_locator(local_id: str, naid: str) -> str:
    local_id = clean_text(local_id)
    naid = clean_text(naid)
    if local_id:
        if local_id.startswith("CF") or re.match(r"^\d", local_id):
            return f"OA/ID {local_id}"
        return f"Local ID {local_id}"
    return f"NAID {naid}" if naid else ""


def source_note(source_series: str, folder_title: str = "", local_id: str = "", naid: str = "") -> str:
    pieces = [SOURCE_PREFIX, source_series]
    locator = source_locator(local_id, naid)
    if locator:
        pieces.append(locator)
    if folder_title:
        pieces.append(clean_text(folder_title))
    return ensure_sentence("Source: " + ", ".join(piece for piece in pieces if piece))


def collect_series(cache_dir: Path | None) -> list[dict]:
    series: list[dict] = []
    for page in range(25):
        markup = fetch_text(series_page_url(page), cache_dir=cache_dir)
        page_rows = parse_series_page(markup, page)
        if not page_rows:
            break
        for row in page_rows:
            row["series_order"] = len(series) + 1
            series.append(row)
    return series


def make_entries(series_rows: list[dict], workers: int, cache_dir: Path | None) -> tuple[list[dict], list[str]]:
    entries: list[dict] = []
    errors: list[str] = []
    by_naid: dict[str, list[dict[str, str]]] = {}
    rows_with_lists = [row for row in series_rows if row.get("has_container_list") and row.get("container_naid")]

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(fetch_series_file_units, row, cache_dir): row for row in rows_with_lists}
        completed = 0
        total = len(future_map)
        for future in as_completed(future_map):
            row = future_map[future]
            completed += 1
            try:
                naid, units, unit_errors = future.result()
            except Exception as exc:
                errors.append(f"{row.get('title')}: {exc}")
                continue
            by_naid[naid] = units
            errors.extend(unit_errors)
            if completed == total or completed % 20 == 0:
                print(f"Fetched {completed}/{total} series container lists", file=sys.stderr)

    for series in series_rows:
        source_series = str(series.get("source_series") or series.get("title") or "")
        series_key = str(series.get("container_naid") or series.get("naid") or "")
        file_units = by_naid.get(series_key, [])
        if not file_units:
            note = source_note(source_series)
            entries.append(
                {
                    "id": f"series-{series.get('series_order')}",
                    "entryType": "series_stem",
                    "sourceNote": note,
                    "seriesTitle": series.get("title", ""),
                    "sourceSeries": source_series,
                    "seriesLocalId": series.get("local_id", ""),
                    "seriesNaid": series.get("naid", ""),
                    "folderTitle": "",
                    "localId": "",
                    "fileUnitNaid": "",
                    "availability": "",
                    "recordTypes": series.get("record_types", ""),
                    "containerId": "",
                    "catalogUrl": series.get("catalog_url", ""),
                    "onlineUrl": "",
                }
            )
            continue

        for index, unit in enumerate(file_units, start=1):
            note = source_note(source_series, unit.get("title", ""), unit.get("local_id", ""), unit.get("naid", ""))
            entries.append(
                {
                    "id": f"{series_key}-{unit.get('local_id') or unit.get('naid') or index}",
                    "entryType": "folder",
                    "sourceNote": note,
                    "seriesTitle": series.get("title", ""),
                    "sourceSeries": source_series,
                    "seriesLocalId": series.get("local_id", ""),
                    "seriesNaid": series.get("naid", ""),
                    "folderTitle": unit.get("title", ""),
                    "localId": unit.get("local_id", ""),
                    "fileUnitNaid": unit.get("naid", ""),
                    "availability": unit.get("availability", ""),
                    "recordTypes": unit.get("record_types", ""),
                    "containerId": unit.get("container_id", ""),
                    "catalogUrl": unit.get("catalog_url", ""),
                    "onlineUrl": unit.get("online_url", ""),
                }
            )
    return entries, errors


def validate_entries(entries: list[dict]) -> dict:
    problems: list[str] = []
    notes = [entry["sourceNote"] for entry in entries]
    required_start = f"Source: {SOURCE_PREFIX}, "
    for index, note in enumerate(notes, start=1):
        if not note.startswith(required_start):
            problems.append(f"Entry {index} does not start with required source prefix")
        if "http://" in note or "https://" in note:
            problems.append(f"Entry {index} includes a URL in the copyable source note")
        if "View in National Archives Catalog" in note or "Record Type(s)" in note:
            problems.append(f"Entry {index} includes display metadata in the source note")
        if "\n" in note or "\r" in note:
            problems.append(f"Entry {index} includes a newline")
        if "  " in note:
            problems.append(f"Entry {index} includes double spaces")
    duplicate_count = len(notes) - len(set(notes))
    return {
        "problem_count": len(problems),
        "problems": problems[:50],
        "duplicate_source_note_count": duplicate_count,
        "entries_missing_folder_locator": sum(1 for entry in entries if entry["entryType"] == "folder" and not entry.get("localId")),
        "series_stem_count": sum(1 for entry in entries if entry["entryType"] == "series_stem"),
    }


def write_outputs(root: Path, series_rows: list[dict], entries: list[dict], errors: list[str]) -> dict:
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    validation = validate_entries(entries)
    summary = {
        "generated_at": generated_at,
        "source_url": FINDING_AID_URL,
        "repository_phrase": SOURCE_PREFIX,
        "series_count": len(series_rows),
        "series_with_container_lists": sum(1 for row in series_rows if row.get("has_container_list")),
        "entry_count": len(entries),
        "folder_entry_count": sum(1 for entry in entries if entry["entryType"] == "folder"),
        "series_stem_count": validation["series_stem_count"],
        "online_folder_entry_count": sum(1 for entry in entries if entry.get("availability") == "Online"),
        "catalog_link_count": sum(1 for entry in entries if entry.get("catalogUrl")),
        "online_object_link_count": sum(1 for entry in entries if entry.get("onlineUrl")),
        "scrape_error_count": len(errors),
        "scrape_errors": errors[:100],
        "validation": validation,
    }

    data_dir = root / "data"
    downloads_dir = root / "downloads"
    data_dir.mkdir(parents=True, exist_ok=True)
    downloads_dir.mkdir(parents=True, exist_ok=True)

    browser_payload = {
        "summary": summary,
        "series": [
            {
                "o": row.get("series_order"),
                "t": row.get("title", ""),
                "s": row.get("source_series", ""),
                "l": row.get("local_id", ""),
                "n": row.get("naid", ""),
            }
            for row in series_rows
        ],
        "entries": [
            {
                "n": entry.get("sourceNote", ""),
                "t": entry.get("entryType", ""),
                "ss": entry.get("sourceSeries", ""),
                "st": entry.get("seriesTitle", ""),
                "sl": entry.get("seriesLocalId", ""),
                "sn": entry.get("seriesNaid", ""),
                "f": entry.get("folderTitle", ""),
                "oa": entry.get("localId", ""),
                "na": entry.get("fileUnitNaid", ""),
                "a": entry.get("availability", ""),
                "rt": entry.get("recordTypes", ""),
                "c": entry.get("catalogUrl", ""),
                "o": entry.get("onlineUrl", ""),
            }
            for entry in entries
        ],
    }
    payload = {"summary": summary, "series": series_rows, "entries": entries}
    (data_dir / "entries.min.json").write_text(
        json.dumps(browser_payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    (data_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (downloads_dir / "bush41-nsc-source-note-entries.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    columns = [
        "sourceNote",
        "entryType",
        "sourceSeries",
        "seriesTitle",
        "seriesLocalId",
        "seriesNaid",
        "folderTitle",
        "localId",
        "fileUnitNaid",
        "availability",
        "recordTypes",
        "containerId",
        "catalogUrl",
        "onlineUrl",
    ]
    with (downloads_dir / "bush41-nsc-source-note-entries.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(entries)

    txt = "\n".join(entry["sourceNote"] for entry in entries) + "\n"
    (downloads_dir / "bush41-nsc-source-note-entries.txt").write_text(txt, encoding="utf-8")

    md_lines = [
        "# George H.W. Bush NSC Source Note Entries",
        "",
        f"Generated: {generated_at}",
        f"Source finding aid: {FINDING_AID_URL}",
        "",
        "```text",
        f"Source: {SOURCE_PREFIX}, [series], OA/ID [identifier], [folder title].",
        "```",
        "",
    ]
    current_series = None
    for entry in entries:
        if entry["sourceSeries"] != current_series:
            current_series = entry["sourceSeries"]
            md_lines.extend(["", f"## {current_series}", ""])
        md_lines.append(f"- {entry['sourceNote']}")
    (downloads_dir / "bush41-nsc-source-note-entries.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/bush41-html"))
    parser.add_argument("--allow-scrape-errors", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    series_rows = collect_series(args.cache_dir)
    print(f"Found {len(series_rows)} series", file=sys.stderr)
    entries, errors = make_entries(series_rows, max(1, args.workers), args.cache_dir)
    summary = write_outputs(root, series_rows, entries, errors)
    print(json.dumps(summary, indent=2), file=sys.stderr)

    validation = summary["validation"]
    if validation["problem_count"]:
        print("Validation problems found", file=sys.stderr)
        return 2
    if errors and not args.allow_scrape_errors:
        print("Scrape errors found", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
