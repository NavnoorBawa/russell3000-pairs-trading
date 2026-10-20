# reference/

Committed reference data from free public sources, read by `pairs_trading/universe.py`.
Each file is rebuilt by a script from raw downloads cached under `data/raw/` (git-ignored);
`--offline` rebuilds byte for byte from those caches without touching the network.

| File | Content | Built by | Source |
|---|---|---|---|
| `universe/iwv_<period>.csv` | the equity-common holdings of the iShares Russell 3000 ETF (IWV) on one quarter-end: `ticker, cusip, isin, name, weight` (weight = share of the equity value; ticker blank when no usable ticker was found) | `scripts/build_pit_universe.py` | SEC N-PORT-P filings, iShares Trust CIK 1100663, series S000004341 |
| `universe/index.json` | one entry per snapshot: period and filing dates, accession, source URL, SHA-256 of the XML, holdings / equity / mapped counts, mapped value share; the issuer `successions` used for CUSIPs without a mapping of their own; filings in the sealed holdout are listed but not downloaded | `scripts/build_pit_universe.py` | EDGAR filing index and headers |
| `universe/cusip_ticker_map.json` | CUSIP (or ISIN) -> US ticker, with the FIGI, OpenFIGI name, exchange code, how it was matched (`cusip`/`isin`, `share class`, `name`, `reported ticker`) and mapping date | `scripts/build_pit_universe.py` | OpenFIGI `/v3/mapping` |
| `industry_ff49.csv` | `ticker, cik, sic, ff49, ff49_name, sector_etf, entity_type` for every ticker in a snapshot or in `data/marketcap.csv` | `scripts/build_reference_data.py` | SEC `company_tickers.json` and submissions API; Ken French `Siccodes49.zip` |
| `listing_venue.csv` | `ticker, venue, etf_flag, as_of` for every non-test issue | `scripts/build_reference_data.py` | Nasdaq Trader `nasdaqtraded.txt` |

```bash
python scripts/build_pit_universe.py      # EDGAR + OpenFIGI (about 40 min without an OpenFIGI key)
python scripts/build_pit_universe.py --remap-missing   # re-ask OpenFIGI for every identifier without an active line
python scripts/build_reference_data.py    # EDGAR submissions for ~5,000 registrants (~12 min)
python scripts/build_pit_universe.py --offline && python scripts/build_reference_data.py --offline
```

Rules and caveats:

- **Membership is point-in-time by period date.** A snapshot is in force from the date its
  holdings describe until the next snapshot (`PITUniverse.members_asof`). Only the third
  month of each fiscal quarter is public, so additions and deletions inside a quarter
  appear at the next quarter end. IWV is a fund, not the index: it holds 2,580-2,900
  equity positions per snapshot, not every constituent.
- **Sealed holdout.** A snapshot dated 2026 or later carries every holding's market value,
  i.e. a 2026 price for every member. 2026 is the pre-registered holdout, so those filings
  are listed in `index.json` under `sealed` and downloaded only with `--include-sealed`,
  after the pre-registration is committed.
- **Tickers are as of the mapping date.** OpenFIGI maps a CUSIP to the security's latest
  ticker, the key under which Yahoo serves its whole history. A delisted security's last
  ticker may since have been taken by another issuer (Barnes Group's `B` is Barrick's
  today); the build looks every such ticker up on OpenFIGI's US composite and, when it
  now belongs to a different share class and issuer name, records the mapping as
  `reused` with no ticker, so no member is joined to someone else's price history.
- **A changed CUSIP is not a delisting.** OpenFIGI stops resolving a CUSIP once a reverse
  split, a holding-company reorganisation or a re-domiciliation replaces it (Linde's ISIN
  until 2023, Cooper's CUSIP until its 2024 split), and Bloomberg's line for a retired
  CUSIP keeps the ticker of years earlier (`CCIV` for Lucid, `PJC` for Piper Sandler).
  From the 2022-09-30 filing on, N-PORT reports every holding's ticker; for an identifier
  OpenFIGI leaves unmapped, or maps only to such a frozen line, the build resolves the
  reported ticker through the same exchCode-US lookup and identity test (`matched_by:
  reported ticker`). For older snapshots, a CUSIP that a new CUSIP of the same issuer
  (same six-character issuer number and issuer name) replaces in the very next snapshot
  takes that CUSIP's ticker (`successions` in `index.json`; General Electric before its
  2021 reverse split).
- **Members acquired after the last snapshot keep their last ticker** (status `delisted`):
  Yahoo serves no history for them, so `PITUniverse.coverage` counts them among the
  members without prices. That is the survivorship gap of free price data, measured
  rather than hidden.
- **Industry and venue are current, not point-in-time.** EDGAR keeps one SIC per
  registrant and the Nasdaq Trader directory lists today's venue. Tickers that SEC no
  longer lists (most delisted names) have blank industry fields.
