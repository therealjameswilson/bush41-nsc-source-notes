# George H.W. Bush Source Notes

Static browser and download package for FRUS-style source-note metadata entries derived from the Bush Library finding aid and National Archives Catalog source lists for George H.W. Bush administration records.

## Contents

- `index.html`, `styles.css`, `app.js`: GitHub Pages browser with search, series filters, row filters, and copy buttons.
- `data/entries.min.json`: compact browser payload.
- `data/summary.json`: generation and validation summary.
- `downloads/`: Markdown, text, CSV, and JSON exports.
- `tools/build-bush41-nsc-source-notes.py`: repeatable extraction script for the Bush Library finding aid and selected Catalog source lists.

## Source Lists

- Records of the National Security Council, George H.W. Bush Administration.
- Brent Scowcroft Collection.
- Presidential Daily Files.
- NSC Meetings.
- NSC/DC Meetings.
- NSC/DC Meetings Follow-Up.
- NSR Files.
- NSD Files.
- IF Transition Files.

## Source-Note Form

```text
Source: George H.W. Bush Library, [record collection], [series path], OA/ID or NAID [identifier], [folder or item title].
```

Where a source list supplies no Local ID/OA-ID value, the copied source note uses the NAID as the locator. Catalog links, online-object URLs, access availability, and record-type labels stay in metadata fields rather than in the copyable Source note.

## Generated Counts

- Entries: 68,699.
- Folder entries: 68,665.
- Catalog item entries: 13.
- Series stems for series without container-list rows: 21.
- Series/source lists harvested: 319.
- Series with container lists: 298.
- Online records: 6,321.
- Source groups: 66,054 National Security Council; 646 Brent Scowcroft Collection; 1,999 Presidential Daily Files.
- Catalog entries deduped before merge: 1,102.
- Exact duplicate Source notes removed after merge: 753.
- Scrape errors: 0.
- Source-note validation problems: 0.
- Duplicate Source notes: 0.

The five largest lazy-loaded series required paced tail fetching after the Bush Library server reset faster concurrent requests. Their terminal empty pages are cached locally during the build but the cache is not committed.

## Local Preview

Run a static server from this directory:

```bash
python3 -m http.server 8765
```

Then open `http://127.0.0.1:8765/`.

To rebuild the data and exports:

```bash
python3 tools/build-bush41-nsc-source-notes.py --workers 10
```
