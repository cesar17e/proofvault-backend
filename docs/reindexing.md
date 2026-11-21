# Internal embedding reindexing and repair

ProofVault provides an internal, owner-scoped command for inspecting and
repairing statement embeddings. It is not an API endpoint and is not run at
application startup or on a schedule.

Run it from the backend repository root:

```bash
python -m scripts.reindex_embeddings --owner-id USER_UUID --dry-run
```

A real bounded run uses the same indexing service as entry creation and
updates:

```bash
python -m scripts.reindex_embeddings --owner-id USER_UUID
```

Target one entry with `--entry-id ENTRY_UUID`. Collection runs select at most
20 entries by default. `--limit` accepts 1 through 100, and
`--interval-seconds` changes the default 30-second interval between initial
provider request starts.

Pending entries are treated as potentially active. By default, only pending
entries whose activity timestamp is at least five minutes old are eligible.
Change that threshold with `--pending-min-age-seconds`, or exclude pending
entries completely with `--skip-stale-pending`.

## Rate-limit boundary

The utility processes entries sequentially and its local pacer spaces initial
provider calls. Provider retries remain bounded by the existing Voyage adapter.
This is not a global rate limiter: API POST/PATCH requests, another utility
process, and other backend instances do not share its pacing state.

The report totals token usage returned by Voyage, but the utility cannot know
the exact token count before sending a statement. Very long statements can
still encounter the provider's token-per-minute limit. Keep the default pacing,
use smaller run limits for long mathematical content, and rerun failed entries
after the provider window resets.

Dry runs query only the entry and embedding fields needed for freshness checks.
They do not call Voyage or modify stored entries. Reports display entry IDs and
repair reasons, never statement text or API keys.
