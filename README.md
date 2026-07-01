# George H.W. Bush NSC Source Notes

Static browser and download package for FRUS-style source-note metadata entries derived from the Bush Library finding aid for the Records of the National Security Council, George H.W. Bush Administration.

## Contents

- `index.html`, `styles.css`, `app.js`: GitHub Pages browser with search, series filters, row filters, and copy buttons.
- `data/entries.min.json`: compact browser payload.
- `data/summary.json`: generation and validation summary.
- `downloads/`: Markdown, text, CSV, and JSON exports.
- `tools/build-bush41-nsc-source-notes.py`: repeatable extraction script for the Bush Library finding aid.

## Source-Note Form

```text
Source: George H.W. Bush Library, Bush Presidential Records, National Security Council, [series path], OA/ID [identifier], [folder title].
```

For the small number of folder rows where the finding aid supplies no Local ID/OA-ID value, the copied source note uses the folder NAID as the locator. Catalog links, online-object URLs, access availability, and record-type labels stay in metadata fields rather than in the copyable Source note.

## Generated Counts

- Entries: 66,807.
- Folder entries: 66,786.
- Series stems for series without container-list rows: 21.
- NSC series harvested: 298.
- Series with container lists: 277.
- Online folder entries: 3,676.
- Scrape errors: 0.
- Source-note validation problems: 0.

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
