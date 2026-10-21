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
python scripts/build_pit_universe.py --reresolve       # resolve those again from the cached OpenFIGI answers (a rule changed)
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
  rather than hidden. `delisted` means only that OpenFIGI's exchCode-US lookup returns no
  record for the ticker today: it includes members held through 2025-12-31 (Electronic
  Arts, AvalonBay, Warner Bros. Discovery) for which Yahoo now serves no bar dated 2025 or
  earlier either.
- **A ticker is not taken from another holding.** When a security held in a snapshot is
  mapped to a ticker by its own CUSIP or ISIN as an active US line, another holding of the
  same snapshot that reaches that ticker only indirectly (reported ticker, name or share
  class) gets status `reused` and no ticker (BlackRock books OmniAb's earnout shares under
  `OABI`). `RDUS` and `STR` stay shared in a few snapshots: neither holder has an active
  line, and Yahoo serves no history under either ticker.
- **Every changed mapping is price-checked** (rebuild of 2026-10-20, against the previous
  committed map). For each held period date, N-PORT's own value per share (`valUSD /
  balance`) is compared with the ticker's split-unadjusted close on the last session on or
  before that date: the development cache's `Close_PIT`; or, where the cache has no bar (the
  2019 snapshots, tickers it never fetched) or where `Close_PIT` misses only because it is
  still dividend-adjusted, Yahoo's chart close (adjusted for splits, not dividends) times
  the split ratios dated after it, requested with `period2` = 2026-01-01 00:00 UTC. A
  mapping is accepted when the two agree within **2%** on every held date; a mapping the
  builder rejects is checked against the ticker it is denied. The check also covers the
  516 unchanged mappings not made by OpenFIGI's own active US line (name, share-class and
  reported-ticker matches, delisted lines). It rejected 10 of them, which are therefore
  among the 448 identifiers whose ticker or status changed in at least one snapshot:

  | verdict | changed | held dates checked | unchanged, not OpenFIGI's own line | held dates checked |
  |---|---:|---:|---:|---:|
  | accepted: within 2% on every held date (largest deviation 1.83%; 1.92%) | 74 | 1,012 | 78 | 797 |
  | accepted by exception: a constant ratio on every held date | 10 | 193 | 21 | 302 |
  | accepted by exception: Scilex (below) | | | 1 | 3 |
  | rejected: status `reused`, no ticker (`REJECTED_MAPPINGS` 17, the shared-ticker rule 2) | 19 | | | |
  | kept unchecked: no bar dated 2025 or earlier under the ticker, in the cache or on Yahoo, so no price is joined | 322 | | 406 | |
  | no ticker before or after (status change only) | 23 | | | |
  | total | 448 | | 506 | |

  Every accepted mapping is checked on every held date it has a ticker for.

  Tolerance exceptions. (1) `Close_PIT` is dividend-adjusted by every dividend paid up to
  the cache's October 2026 download, 2026's included; for 22 changed and 29 unchanged
  accepted identifiers, 292 and 291 dates agree only with Yahoo's dividend-free close
  (`Close_PIT` sits up to 54% below the traded price for Chimera and New York Mortgage
  Trust, 75% for Apartment Investment and Management). (2) A constant multiple of the close
  on every held date, judged on Yahoo's dividend-free close: Advantage Solutions and agilon
  health 0.04, BRC and Granite Point 0.1, Cue Biopharma 1/30, Marqeta 0.25, Service
  Properties 0.2, Columbia Financial 2.2, Piper Sandler 4.0, QIAGEN (old ISIN) 0.969; among
  the unchanged, Beyond Meat 1/30, Amcor 0.2, DuPont 1/3, Honeywell 0.954 and 17 more. For
  29 of the 31 no split event dated 2025 or earlier explains the factor (DuPont's and
  Honeywell's 2025 spin-off events are in the series; the factor comes on top): the vendor
  has applied a share-basis change to the whole history that a request ending 2026-01-01
  does not return as an event. For the other two, a split event in the window is not in the
  series: Match Group's old CUSIP (all four held dates before the 3.502:1 event of
  2020-07-01) and SITE Centers (all 20 before the 1:4 of 2024-08-19), whose close unadjusted
  by those events reads 3.5 and 0.30 times the traded price. The co-movement over 4 to 26
  dates identifies the security in every case, but the factor stays in `Close_PIT`, which
  sets the $5 price screen and the per-share cost terms (Advantage Solutions and Beyond
  Meat show them 25 and 30 times their traded price); returns, from the adjusted close, are
  unaffected. (3) Scilex (80880W106; OpenFIGI's share-class FIGI for this CUSIP is
  `SCLX`'s): N-PORT's price is 1.55, 1.59 and 1.60 times the close on its three held
  dates, while `Close_PIT` and Yahoo agree with each other and the price fell 72%. A vendor
  factor drifting by 3% is not another security's path.

  Rejections. Identity data cannot tell these from a genuine successor, so the builder
  lists them in `REJECTED_MAPPINGS` with the reason (vet_mappings, on every online build).
  On prices: old Safehold (`SAFE` was iStar's line before their 2023 merger), old Caesars
  (`CZR` was Eldorado's before 2020), old Coherent (`COHR` was II-VI's before 2022), old
  Biohaven (`BHVN` is the 2022 spin-off) and Bally's old CUSIP (`BALY`'s line starts
  2024-12-06 and is 3.1% off on the one held date it covers). By dates: the ticker's prices
  start only after the security was last held, because they are another security's: the
  equity issued in a reorganisation (Core Scientific, Wolfspeed, WW International,
  California Resources, Diebold Nixdorf, Gulfport, Seadrill, Vroom), a spin-off or a later
  listing that took the name (Crane Co: `CR` is Crane Company; Inhibrx; SailPoint) or
  another issuer (Sarcos: `STRC` is Strategy Inc's line since 2025-07-30).
  issuer_successions never links a rejected CUSIP. The shared-ticker rule removes OmniAb's
  two earnout CUSIPs (N-PORT values each position of 1,502 shares at $0.02) from `OABI`.
- **The survivorship gap, before and after the rebuild**: the index weight of holdings
  without a ticker, and of mapped holdings without prices in the development cache
  (`data/enhanced_russell_3000_data_manifest.json`: never fetched, or fetched with outcome
  `not_found`, `short`, `invalid`, `empty` or an error):

  | snapshot | unmapped | mapped, no cached prices | of which never fetched (after) | total |
  |---|---|---|---:|---|
  | 2019-09-30 | 4.15% -> 2.23% | 5.30% -> 6.29% | 4.48% | 9.45% -> 8.51% |
  | 2019-12-31 | 3.93% -> 1.93% | 4.90% -> 5.92% | 4.08% | 8.83% -> 7.85% |
  | 2020-12-31 | 3.03% -> 0.84% | 3.84% -> 5.04% | 3.24% | 6.87% -> 5.88% |
  | 2021-12-31 | 2.31% -> 0.67% | 2.90% -> 4.09% | 2.37% | 5.21% -> 4.76% |
  | 2022-12-30 | 2.18% -> 0.24% | 2.10% -> 3.31% | 1.45% | 4.28% -> 3.55% |
  | 2023-12-31 | 1.35% -> 0.11% | 1.36% -> 2.24% | 1.06% | 2.71% -> 2.35% |
  | 2024-12-31 | 0.78% -> 0.04% | 0.79% -> 1.41% | 0.71% | 1.57% -> 1.45% |
  | 2025-12-31 | 0.61% -> 0.01% | 0.36% -> 0.87% | 0.52% | 0.96% -> 0.88% |

  The next development run's top-up fetches the 822 never-fetched tickers (312 of them in
  no earlier snapshot file). Yahoo serves bars dated 2025 or earlier for 114 of them, at
  most 0.22% of the index in any snapshot. Almost all of the remaining gap is members for
  which Yahoo serves no bar dated 2025 or earlier (never fetched and none on Yahoo: 4.38% of
  2019-09-30, 0.50% of 2025-12-31; fetched as `not_found`: 1.75% and 0.18%), not mapping
  failures. Newly active tickers (status `active`, in no earlier snapshot file) without
  cached prices: ACET, BBUC, BOLT, CUE, CVM, GPMT, GTES, LOGC, MCRB, MRX, NFE, NVRI, QGEN,
  SCOR, TIL, WVE and XPRO were never fetched, Yahoo serves bars for each, and the top-up
  fetches them (with the delisted LBRDA, at most 0.06% of the index); SENS (outcome
  `invalid`) and OPI (an error, and no bar on Yahoo) are recorded failures, which the
  top-up does not retry.
- **Industry and venue are current, not point-in-time.** EDGAR keeps one SIC per
  registrant and the Nasdaq Trader directory lists today's venue. Tickers that SEC no
  longer lists (most delisted names) have blank industry fields.
