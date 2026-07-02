#!/usr/bin/env python3
"""Build FRUS-style Bush 41 source-note entries from Bush Library and Catalog data."""

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
CATALOG_ROOT = "https://catalog.archives.gov"
FINDING_AID_URL = (
    "https://www.bush41library.gov/digital-research-room/finding-aid/"
    "records-national-security-council-george-h-w-bush-administration"
)
SERIES_ENDPOINT = SITE_ROOT + "/bush-finding-aids/series-info/{naid}/finding-aids/all"
NSC_SOURCE_PREFIX = "George H.W. Bush Library, Bush Presidential Records, National Security Council"
SCOWCROFT_SOURCE_PREFIX = "George H.W. Bush Library, Bush Presidential Records, Brent Scowcroft Collection"
BUSH_PRESIDENTIAL_SOURCE_PREFIX = "George H.W. Bush Library, Bush Presidential Records"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

CATALOG_SERIES_SOURCES = [
    {
        "name": "National Security Council Catalog: NSC Meetings",
        "root_naid": "312293887",
        "prefix": NSC_SOURCE_PREFIX,
        "group": "National Security Council",
        "mode": "series",
    },
    {
        "name": "National Security Council Catalog: NSC/DC Meetings",
        "root_naid": "312294079",
        "prefix": NSC_SOURCE_PREFIX,
        "group": "National Security Council",
        "mode": "series",
    },
    {
        "name": "National Security Council Catalog: NSC/DC Meetings Follow-Up",
        "root_naid": "312294094",
        "prefix": NSC_SOURCE_PREFIX,
        "group": "National Security Council",
        "mode": "series",
    },
    {
        "name": "National Security Council Catalog: NSR Files",
        "root_naid": "313189297",
        "prefix": NSC_SOURCE_PREFIX,
        "group": "National Security Council",
        "mode": "series",
    },
    {
        "name": "National Security Council Catalog: NSD Files",
        "root_naid": "313189290",
        "prefix": NSC_SOURCE_PREFIX,
        "group": "National Security Council",
        "mode": "series",
    },
    {
        "name": "National Security Council Catalog: IF Transition Files",
        "root_naid": "348937136",
        "prefix": NSC_SOURCE_PREFIX,
        "group": "National Security Council",
        "mode": "series",
    },
    {
        "name": "Presidential Daily Files",
        "root_naid": "595141",
        "prefix": BUSH_PRESIDENTIAL_SOURCE_PREFIX,
        "group": "Presidential Daily Files",
        "mode": "online_search",
        "include_items": True,
    },
]

SCOWCROFT_COLLECTION_SOURCE = {
    "name": "Brent Scowcroft Collection",
    "root_naid": "4522156",
    "prefix": SCOWCROFT_SOURCE_PREFIX,
    "group": "Brent Scowcroft Collection",
    "mode": "collection",
}


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
                "source_prefix": NSC_SOURCE_PREFIX,
                "source_group": "National Security Council",
                "source_root_naid": "2163580",
                "source_url": FINDING_AID_URL,
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


def source_note(
    source_series: str,
    folder_title: str = "",
    local_id: str = "",
    naid: str = "",
    source_prefix: str = NSC_SOURCE_PREFIX,
) -> str:
    pieces = [source_prefix, source_series]
    locator = source_locator(local_id, naid)
    if locator:
        pieces.append(locator)
    if folder_title:
        pieces.append(clean_text(folder_title))
    return ensure_sentence("Source: " + ", ".join(piece for piece in pieces if piece))


def fetch_json(url: str, cache_dir: Path | None) -> dict:
    return json.loads(fetch_text(url, cache_dir=cache_dir))


def catalog_url(path: str, params: dict | None = None) -> str:
    url = f"{CATALOG_ROOT}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return url


def record_from_hit(hit: dict) -> dict:
    record = dict(hit.get("_source", {}).get("record", {}))
    record.setdefault("naId", hit.get("_id", ""))
    return record


def catalog_record(naid: str, cache_dir: Path | None) -> dict:
    payload = fetch_json(catalog_url("/proxy/records/search", {"naId": naid}), cache_dir)
    hits = payload.get("body", {}).get("hits", {}).get("hits", [])
    if not hits:
        raise RuntimeError(f"Catalog NAID {naid} returned no record")
    return record_from_hit(hits[0])


def catalog_total(payload: dict) -> int:
    total = payload.get("body", {}).get("hits", {}).get("total", {})
    if isinstance(total, dict):
        return int(total.get("value") or 0)
    return int(total or 0)


def catalog_hits(payload: dict) -> list[dict]:
    return [record_from_hit(hit) for hit in payload.get("body", {}).get("hits", {}).get("hits", [])]


def catalog_parent_records(parent_naid: str, cache_dir: Path | None) -> list[dict]:
    rows: list[dict] = []
    first = fetch_json(catalog_url(f"/proxy/records/parentNaId/{parent_naid}", {"page": 1}), cache_dir)
    total = catalog_total(first)
    page_size = max(1, len(catalog_hits(first)))
    pages = (total + page_size - 1) // page_size
    for page in range(1, pages + 1):
        payload = first if page == 1 else fetch_json(catalog_url(f"/proxy/records/parentNaId/{parent_naid}", {"page": page}), cache_dir)
        rows.extend(catalog_hits(payload))
    return rows


def catalog_online_descendants(root_naid: str, cache_dir: Path | None, include_items: bool = True) -> list[dict]:
    rows: list[dict] = []
    params = {
        "q": f"record.ancestors.naId:{root_naid}",
        "availableOnline": "true",
        "limit": 100,
        "page": 1,
    }
    if not include_items:
        params["levelOfDescription"] = "fileUnit"
    first = fetch_json(catalog_url("/proxy/records/search", params), cache_dir)
    total = catalog_total(first)
    page_size = max(1, len(catalog_hits(first)))
    pages = (total + page_size - 1) // page_size
    for page in range(1, pages + 1):
        params["page"] = page
        payload = first if page == 1 else fetch_json(catalog_url("/proxy/records/search", params), cache_dir)
        rows.extend(catalog_hits(payload))
    return rows


def first_digital_object_url(record: dict) -> str:
    for obj in record.get("digitalObjects") or []:
        if obj.get("objectUrl"):
            return obj["objectUrl"]
    return ""


def catalog_record_types(record: dict) -> str:
    return "; ".join(record.get("generalRecordsTypes") or [])


def catalog_container_id(record: dict) -> str:
    for occurrence in record.get("physicalOccurrences") or []:
        for media in occurrence.get("mediaOccurrences") or []:
            if media.get("containerId"):
                return str(media["containerId"])
    return ""


def catalog_record_entry(
    record: dict,
    source: dict,
    series_record: dict,
    source_series: str,
) -> dict:
    naid = str(record.get("naId") or "")
    local_id = clean_text(str(record.get("localIdentifier") or ""))
    title = clean_title(str(record.get("title") or ""))
    online_url = first_digital_object_url(record)
    entry_type = "item" if record.get("levelOfDescription") == "item" else "folder"
    note = source_note(source_series, title, local_id, naid, source_prefix=source["prefix"])
    return {
        "id": f"catalog-{naid}",
        "entryType": entry_type,
        "sourceNote": note,
        "sourcePrefix": source["prefix"],
        "sourceGroup": source.get("group", source["name"]),
        "sourceRootNaid": source["root_naid"],
        "sourceUrl": f"{CATALOG_ROOT}/id/{source['root_naid']}",
        "seriesTitle": series_record.get("title", ""),
        "sourceSeries": source_series,
        "seriesLocalId": clean_text(str(series_record.get("localIdentifier") or "")),
        "seriesNaid": str(series_record.get("naId") or ""),
        "folderTitle": title,
        "localId": local_id,
        "fileUnitNaid": naid,
        "availability": "Online" if online_url else "On Site",
        "recordTypes": catalog_record_types(record),
        "containerId": catalog_container_id(record),
        "catalogUrl": f"{CATALOG_ROOT}/id/{naid}" if naid else "",
        "onlineUrl": online_url,
    }


def style_scowcroft_series_title(title: str) -> str:
    styled = clean_title(title)
    if styled.startswith("Brent Scowcroft "):
        return "Scowcroft " + styled[len("Brent Scowcroft ") :]
    return styled


def catalog_series_row(source: dict, series_record: dict, source_series: str) -> dict:
    naid = str(series_record.get("naId") or "")
    return {
        "series_order": 0,
        "page": "",
        "title": clean_text(str(series_record.get("title") or "")),
        "source_series": source_series,
        "source_prefix": source["prefix"],
        "source_group": source.get("group", source["name"]),
        "source_root_naid": source["root_naid"],
        "source_url": f"{CATALOG_ROOT}/id/{source['root_naid']}",
        "date": "",
        "local_id": clean_text(str(series_record.get("localIdentifier") or "")),
        "naid": naid,
        "record_types": catalog_record_types(series_record),
        "extent": "",
        "arrangement": "",
        "access_restriction": (series_record.get("accessRestriction") or {}).get("status", ""),
        "use_restriction": (series_record.get("useRestriction") or {}).get("status", ""),
        "specific_access_restriction": "",
        "container_naid": naid,
        "has_container_list": True,
        "catalog_url": f"{CATALOG_ROOT}/id/{naid}" if naid else "",
    }


def harvest_catalog_source(source: dict, cache_dir: Path | None) -> tuple[list[dict], list[dict]]:
    series_rows: list[dict] = []
    entries: list[dict] = []

    if source["mode"] == "collection":
        child_series = [record for record in catalog_parent_records(source["root_naid"], cache_dir) if record.get("levelOfDescription") == "series"]
        for series_record in child_series:
            source_series = style_scowcroft_series_title(str(series_record.get("title") or ""))
            series_rows.append(catalog_series_row(source, series_record, source_series))
            for record in catalog_parent_records(str(series_record.get("naId")), cache_dir):
                if record.get("levelOfDescription") not in {"fileUnit", "item"}:
                    continue
                entries.append(catalog_record_entry(record, source, series_record, source_series))
        return series_rows, entries

    series_record = catalog_record(source["root_naid"], cache_dir)
    if source["mode"] == "online_search":
        source_series = clean_title(str(series_record.get("title") or source["name"]))
        series_rows.append(catalog_series_row(source, series_record, source_series))
        for record in catalog_online_descendants(source["root_naid"], cache_dir, include_items=bool(source.get("include_items"))):
            if record.get("levelOfDescription") not in {"fileUnit", "item"}:
                continue
            entries.append(catalog_record_entry(record, source, series_record, source_series))
        return series_rows, entries

    source_series = style_series_title(str(series_record.get("title") or source["name"]))
    series_rows.append(catalog_series_row(source, series_record, source_series))
    for record in catalog_parent_records(source["root_naid"], cache_dir):
        if record.get("levelOfDescription") not in {"fileUnit", "item"}:
            continue
        entries.append(catalog_record_entry(record, source, series_record, source_series))
    return series_rows, entries


def entry_dedupe_key(entry: dict) -> tuple[str, str]:
    if entry.get("fileUnitNaid"):
        return ("naid", str(entry["fileUnitNaid"]))
    if entry.get("localId"):
        return (
            "local",
            "|".join([str(entry.get("sourcePrefix", "")), str(entry.get("sourceSeries", "")), str(entry.get("localId", ""))]),
        )
    return ("note", str(entry.get("sourceNote", "")))


def merge_catalog_sources(
    series_rows: list[dict],
    entries: list[dict],
    cache_dir: Path | None,
) -> tuple[list[dict], list[dict], dict, list[str]]:
    errors: list[str] = []
    catalog_series: list[dict] = []
    catalog_entries: list[dict] = []
    for source in [SCOWCROFT_COLLECTION_SOURCE, *CATALOG_SERIES_SOURCES]:
        try:
            source_series, source_entries = harvest_catalog_source(source, cache_dir)
            catalog_series.extend(source_series)
            catalog_entries.extend(source_entries)
            print(f"Fetched Catalog source {source['name']}: {len(source_entries)} entries", file=sys.stderr)
        except Exception as exc:
            errors.append(f"{source['name']}: {exc}")

    seen = {entry_dedupe_key(entry) for entry in entries}
    added_entries: list[dict] = []
    duplicates = 0
    for entry in catalog_entries:
        key = entry_dedupe_key(entry)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        added_entries.append(entry)

    existing_series_keys = {(str(row.get("source_prefix", "")), str(row.get("naid", ""))) for row in series_rows}
    added_series: list[dict] = []
    for row in catalog_series:
        key = (str(row.get("source_prefix", "")), str(row.get("naid", "")))
        if key in existing_series_keys:
            continue
        existing_series_keys.add(key)
        added_series.append(row)

    merged_series = [*series_rows, *added_series]
    for index, row in enumerate(merged_series, start=1):
        row["series_order"] = index

    summary = {
        "catalog_source_count": 1 + len(CATALOG_SERIES_SOURCES),
        "catalog_series_raw_count": len(catalog_series),
        "catalog_series_added_count": len(added_series),
        "catalog_entry_raw_count": len(catalog_entries),
        "catalog_entry_added_count": len(added_entries),
        "catalog_entry_duplicate_count": duplicates,
    }
    return merged_series, [*entries, *added_entries], summary, errors


def dedupe_exact_source_notes(entries: list[dict]) -> tuple[list[dict], int]:
    seen: set[str] = set()
    deduped: list[dict] = []
    duplicate_count = 0
    for entry in entries:
        note = entry.get("sourceNote", "")
        if note in seen:
            duplicate_count += 1
            continue
        seen.add(note)
        deduped.append(entry)
    return deduped, duplicate_count


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
        source_prefix = str(series.get("source_prefix") or NSC_SOURCE_PREFIX)
        source_group = str(series.get("source_group") or "National Security Council")
        series_key = str(series.get("container_naid") or series.get("naid") or "")
        file_units = by_naid.get(series_key, [])
        if not file_units:
            note = source_note(source_series, source_prefix=source_prefix)
            entries.append(
                {
                    "id": f"series-{series.get('series_order')}",
                    "entryType": "series_stem",
                    "sourceNote": note,
                    "sourcePrefix": source_prefix,
                    "sourceGroup": source_group,
                    "sourceRootNaid": series.get("source_root_naid", ""),
                    "sourceUrl": series.get("source_url", ""),
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
            note = source_note(
                source_series,
                unit.get("title", ""),
                unit.get("local_id", ""),
                unit.get("naid", ""),
                source_prefix=source_prefix,
            )
            entries.append(
                {
                    "id": f"{series_key}-{unit.get('local_id') or unit.get('naid') or index}",
                    "entryType": "folder",
                    "sourceNote": note,
                    "sourcePrefix": source_prefix,
                    "sourceGroup": source_group,
                    "sourceRootNaid": series.get("source_root_naid", ""),
                    "sourceUrl": series.get("source_url", ""),
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
    for index, note in enumerate(notes, start=1):
        if not note.startswith("Source: George H.W. Bush Library, "):
            problems.append(f"Entry {index} does not start with required Bush Library source prefix")
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
        "entries_missing_folder_locator": sum(
            1
            for entry in entries
            if entry["entryType"] in {"folder", "item"}
            and not source_locator(str(entry.get("localId", "")), str(entry.get("fileUnitNaid", "")))
        ),
        "series_stem_count": sum(1 for entry in entries if entry["entryType"] == "series_stem"),
    }


def write_outputs(root: Path, series_rows: list[dict], entries: list[dict], errors: list[str], catalog_summary: dict) -> dict:
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    validation = validate_entries(entries)
    summary = {
        "generated_at": generated_at,
        "source_url": FINDING_AID_URL,
        "repository_phrases": sorted({entry.get("sourcePrefix", "") for entry in entries if entry.get("sourcePrefix")}),
        "series_count": len(series_rows),
        "series_with_container_lists": sum(1 for row in series_rows if row.get("has_container_list")),
        "entry_count": len(entries),
        "folder_entry_count": sum(1 for entry in entries if entry["entryType"] == "folder"),
        "item_entry_count": sum(1 for entry in entries if entry["entryType"] == "item"),
        "series_stem_count": validation["series_stem_count"],
        "online_folder_entry_count": sum(
            1 for entry in entries if entry["entryType"] == "folder" and entry.get("availability") == "Online"
        ),
        "online_entry_count": sum(1 for entry in entries if entry.get("availability") == "Online"),
        "catalog_link_count": sum(1 for entry in entries if entry.get("catalogUrl")),
        "online_object_link_count": sum(1 for entry in entries if entry.get("onlineUrl")),
        "source_group_counts": dict(sorted({group: sum(1 for entry in entries if entry.get("sourceGroup") == group) for group in {entry.get("sourceGroup", "") for entry in entries}}.items())),
        "catalog_harvest": catalog_summary,
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
                "g": row.get("source_group", ""),
                "p": row.get("source_prefix", ""),
                "l": row.get("local_id", ""),
                "n": row.get("naid", ""),
            }
            for row in series_rows
        ],
        "entries": [
            {
                "n": entry.get("sourceNote", ""),
                "t": entry.get("entryType", ""),
                "g": entry.get("sourceGroup", ""),
                "p": entry.get("sourcePrefix", ""),
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
        "sourceGroup",
        "sourcePrefix",
        "sourceRootNaid",
        "sourceUrl",
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
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
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
        "Source: George H.W. Bush Library, [record collection], [series path], OA/ID or NAID [identifier], [folder or item title].",
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
    series_rows, entries, catalog_summary, catalog_errors = merge_catalog_sources(series_rows, entries, args.cache_dir)
    entries, exact_duplicate_count = dedupe_exact_source_notes(entries)
    catalog_summary["exact_source_note_duplicate_count"] = exact_duplicate_count
    errors.extend(catalog_errors)
    summary = write_outputs(root, series_rows, entries, errors, catalog_summary)
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
