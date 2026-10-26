# reference/

Committed reference data from free public sources, read by `pairs_trading/universe.py`.
Each file is rebuilt by a script from raw downloads cached under `data/raw/` (git-ignored)
and, for `industry_ff49.csv`, the v32 universe file `data/marketcap.csv` (git-ignored too;
the build stops when it is missing unless `--no-marketcap` is given, and logs its SHA-256
and ticker count); `--offline` rebuilds byte for byte from those inputs without touching
the network.

| File | Content | Built by | Source |
|---|---|---|---|
| `universe/iwv_<period>.csv` | the equity-common holdings of the iShares Russell 3000 ETF (IWV) on one quarter-end: `ticker, cusip, isin, name, weight, price` (weight = share of the equity value; price = value per share, `valUSD` / shares held, the price the holding traded at that day; ticker blank when no usable ticker was found) | `scripts/build_pit_universe.py` | SEC N-PORT-P filings, iShares Trust CIK 1100663, series S000004341 |
| `universe/index.json` | one entry per snapshot: period and filing dates, accession, source URL, SHA-256 of the XML, holdings / equity / mapped counts, mapped value share; the issuer `successions` used for CUSIPs without a mapping of their own; filings in the sealed holdout are listed but not downloaded | `scripts/build_pit_universe.py` | EDGAR filing index and headers |
| `universe/cusip_ticker_map.json` | CUSIP (or ISIN) -> US ticker, with the FIGI, OpenFIGI name, exchange code, how it was matched (`cusip`/`isin`, `share class`, `name`, `reported ticker`, `price check`) and mapping date | `scripts/build_pit_universe.py` | OpenFIGI `/v3/mapping` |
| `industry_ff49.csv` | `ticker, cik, sic, ff49, ff49_name, sector_etf, entity_type` for every ticker in a snapshot or in `data/marketcap.csv` | `scripts/build_reference_data.py` | SEC `company_tickers.json` and submissions API; Ken French `Siccodes49.zip` |
| `listing_venue.csv` | `ticker, venue, etf_flag, as_of` for every non-test issue | `scripts/build_reference_data.py` | Nasdaq Trader `nasdaqtraded.txt` |
| `holdout_inputs.sha256` | the SHA-256 of the git-ignored input the holdout runbook reads, `data/marketcap.csv`, checked by `scripts/run_holdout.sh` (`sha256sum --check --strict`) | by hand | the file itself (see below) |

```bash
python scripts/build_pit_universe.py      # EDGAR + OpenFIGI (about 40 min without an OpenFIGI key)
python scripts/build_pit_universe.py --remap-missing   # re-ask OpenFIGI for every identifier without an active line
python scripts/build_pit_universe.py --reresolve       # resolve those again from the cached OpenFIGI answers (a rule changed)
python scripts/build_reference_data.py    # EDGAR submissions for ~5,000 registrants (~12 min); reads data/marketcap.csv
python scripts/build_pit_universe.py --offline && python scripts/build_reference_data.py --offline
```

**The original inputs were lost.** The working storage of the session that built these files,
`data/` included, was lost when its container was recycled (by 2026-10-22 at 17:29 UTC): the raw
downloads under `data/raw/` and the original `data/marketcap.csv` (Nasdaq screener, 2026-10-18,
SHA-256 `34661d82644fd36d80b91f4a129cc8435afcbf69faf6a61b89977a461197ca3e`, 3,000 rows: symbol,
name, market value, sector, industry). The committed files are unchanged, but `--offline` can no
longer rebuild them byte for byte. `data/marketcap.csv` was rebuilt on 2026-10-26 from the
committed `results/v32_dev/price_fetch_manifest.json`, whose `outcomes` hold the 2,999 valid
symbols the loader kept from the original (`EnhancedRussell3000DataProcessor.load_symbols`
validates, de-duplicates and sorts them; the 3,000th row was dropped). The rebuilt file has one
column, `Symbol`, and no market values; the loader returns the same 2,999 symbols from it, so
S3's universe and the holdout's fetch list are unchanged. `holdout_inputs.sha256` pins the
rebuilt file:

```bash
python - <<'PY'
import json
syms = sorted(json.load(open('results/v32_dev/price_fetch_manifest.json'))['outcomes'])
open('data/marketcap.csv', 'w').write('Symbol\n' + ''.join(s + '\n' for s in syms))
PY
sha256sum --check reference/holdout_inputs.sha256
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
  2021 reverse split). Where identity data cannot make the link (a rename or a
  holding-company reorganisation under a new issuer number, a merger the security
  survived under the other party's name), the price check below makes it:
  `ACCEPTED_MAPPINGS` in `scripts/build_pit_universe.py` gives 85 identifiers the ticker
  under which their history sits (`matched_by: price check`, the evidence as note), among
  them United Technologies (`RTX`), Aon before its move to Ireland (`AON`), BB&T (`TFC`),
  Ingersoll-Rand (`TT`), FleetCor (`CPAY`), the old IAC (`PPLI`), LabCorp before its 2024
  reorganisation (`LH`), Howard Hughes (`HHH`), iStar (`SAFE`) and the Liberty tracking
  stocks (`FWONK`, `BATRK`, `LLYVA`).
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
- **Every mapping that is not OpenFIGI's own line is price-checked** (rebuilds of
  2026-10-20 and 2026-10-21). For each held period date, N-PORT's own value per share
  (`valUSD / balance`) is compared with the ticker's split-unadjusted close on the last
  session on or before that date: the development cache's `Close_PIT`; or, where the cache
  has no bar (the 2019 snapshots, tickers it never fetched) or where `Close_PIT` misses only
  because it is still dividend-adjusted, Yahoo's chart close (adjusted for splits, not
  dividends) times the split ratios dated after it, requested with `period2` = 2026-01-01
  00:00 UTC. A mapping is accepted when the two agree within **2%** on every held date. The
  check covers every identifier whose ticker or status changed against the map before the
  data review (commit `4bcc8b5`), and every unchanged mapping not made by OpenFIGI's own
  active US line (name, share-class and reported-ticker matches, delisted lines):

  | verdict | changed | held dates checked | unchanged, not OpenFIGI's own line | held dates checked |
  |---|---:|---:|---:|---:|
  | accepted: within 2% on every held date (largest deviation 1.83%; 1.92%) | 152 | 1,588 | 78 | 797 |
  | accepted by exception: a constant ratio on every held date | 17 | 244 | 21 | 302 |
  | accepted by exception: Scilex (below) | | | 1 | 3 |
  | rejected: status `reused`, no ticker (`REJECTED_MAPPINGS` 16, the shared-ticker rule 2, the ticker another security's line now and off on prices 3) | 21 | | | |
  | `reused`: the ticker's line, another security's now, has no bar on the held dates | 6 | | | |
  | kept unchecked: no bar dated 2025 or earlier under the ticker, in the cache or on Yahoo, so no price is joined | 312 | | 375 | |
  | no identifier (a contingent value right or escrow placeholder, a line without one) | 7 | | | |
  | total | 515 | | 475 | |

  Of the accepted, 85 (627 held dates) are the `ACCEPTED_MAPPINGS` above: 78 within 2%
  (largest deviation 1.7%), 7 at a constant ratio. Every accepted mapping is checked on
  every held date it has a ticker for.

  Two searches close what the table leaves open. **Every `reused` entry** of the map (72)
  is checked against the ticker its note names, the one it is denied: none agrees, on
  prices or at a constant ratio; 22 are off on prices and 50 have no bar under that ticker
  on their held dates. **A wrong-ticker search** covers every held identifier left without
  a ticker or with a ticker that has no bar dated 2025 or earlier (1,253 identifiers,
  78,463 candidate checks): the ticker a `reused` note names, N-PORT's reported tickers,
  the tickers of identifiers with the same six-character issuer number or the same N-PORT
  issuer name, and those of every identifier first held in the snapshot right after it was
  last held. Its matches are the 85 accepted mappings; what is left is a cancelled equity
  whose ticker's history continues with its reorganised successor (Oasis Petroleum, under
  `CHRD`: 0.12 to 31.00 on 2020-11-20, so it is not accepted), and coincidences on one or
  two dates, or on part of the held dates, with unrelated securities.

  Tolerance exceptions. (1) `Close_PIT` is dividend-adjusted by every dividend paid up to
  the cache's October 2026 download, 2026's included; for 57 changed and 29 unchanged
  accepted identifiers, 518 and 291 dates agree only with Yahoo's dividend-free close
  (`Close_PIT` sits up to 54% below the traded price for Chimera and New York Mortgage
  Trust, 75% for Apartment Investment and Management). (2) A constant multiple of the close
  on every held date, judged on Yahoo's dividend-free close: among the changed, Advantage
  Solutions and agilon health 0.04, Cue Biopharma 1/30, BRC, Granite Point and Real
  Brokerage 0.1, Service Properties 0.2, Marqeta 0.25, QIAGEN (old ISIN) 0.969, the old
  Liberty Formula One series A 1.03, Arconic Inc (now Howmet) 1.3, Rexnord (now Zurn) 2.1,
  Columbia Financial 2.2, StoneX 2.25, Xperi (now Adeia, two CUSIPs) 2.3, Piper Sandler 4.0;
  among the unchanged, Beyond Meat 1/30, Amcor 0.2, DuPont 1/3, Honeywell 0.954 and 17 more.
  The co-movement over 3 to 26 dates identifies the security; the factor is the vendor's
  share-basis change (below). (3) Scilex (80880W106; OpenFIGI's share-class FIGI for this
  CUSIP is `SCLX`'s): N-PORT's price is 1.55, 1.59 and 1.60 times the close on its three
  held dates, while `Close_PIT` and Yahoo agree with each other and the price fell 72%. A
  vendor factor drifting by 3% is not another security's path.

  Rejections. Identity data cannot tell these from a genuine successor, so the builder
  lists them in `REJECTED_MAPPINGS` with the reason (vet_mappings, on every online build).
  On prices: old Safehold (`SAFE` was iStar's line before their 2023 merger), old Caesars
  (`CZR` was Eldorado's before 2020), old Coherent (`COHR` was II-VI's before 2022), old
  Biohaven (`BHVN` is the 2022 spin-off) and Bally's old CUSIP (`BALY`'s line starts
  2024-12-06 and is 3.1% off on the one held date it covers). By dates: the ticker's prices
  start only after the security was last held, because they are another security's: the
  equity issued in a reorganisation (Core Scientific, Wolfspeed, WW International,
  California Resources, Diebold Nixdorf, Gulfport, Seadrill, Vroom), a spin-off or a later
  listing that took the name (Inhibrx; SailPoint) or another issuer (Sarcos: `STRC` is
  Strategy Inc's line since 2025-07-30). Crane Co is denied `CR` (Crane Company, the 2023
  spin-off) and given `CXT`, the line of its own successor, Crane NXT. iStar, Eldorado and
  II-VI carry the tickers their old partners are denied. issuer_successions never links a
  rejected or accepted CUSIP. The shared-ticker rule removes OmniAb's two earnout CUSIPs
  (N-PORT values each position of 1,502 shares at $0.02) from `OABI`.
- **`Close_PIT` is anchored to N-PORT's price.** `Close_PIT` undoes the splits inside the
  cache only. The vendor's series also carries every later share-basis change, applied to
  the whole history but not returned as an event by a request that ends on 2026-01-01, and
  every later dividend. A check of every mapped holding against `Close_PIT`, OpenFIGI's own
  lines included (2,779 identifier-ticker pairs with cached prices, 52,468 held dates from
  2020-03-31; the cache starts in 2020), finds no member joined to another security's
  prices, but finds 51 identifiers (50 tickers, 1.6% to 1.8% of the index in each
  snapshot) at a constant ratio no dividend can produce, below 0.98 or above 1.2 on every
  held date: reverse splits and spin-offs (Gossamer Bio 1/80, Beyond Meat 1/30, Advantage
  Solutions and agilon health 1/25, Alight 1/20, MicroVision 1/15, fuboTV 1/12, Cardlytics,
  CarParts.com, PLAYSTUDIOS and BRC 1/10, Amcor and Service Properties 1/5, Marqeta 1/4,
  DuPont 1/3, Match Group's old CUSIP 0.29, Honeywell 0.97) and forward splits or
  distributions (Booking 25, KLA 10, Corteva 6.7, Carvana 5, CrowdStrike 4, Piper Sandler
  4.1, Climb Global 4, CommScope 3.6, Powell and Willis Lease 3, StoneX 2.25 under two
  CUSIPs, Adeia 2.3, Columbia Financial 2.2, Amphenol, Monster, Mueller, ServisFirst and IES
  2, Zurn 2.1, and 14 more between 1.2 and 1.6). Booking's `Close_PIT` on 2025-12-31 is
  212.68, N-PORT's price 5,355.33; Gossamer Bio's is 248.00 against 3.10.
  `Close_PIT` is off N-PORT's price by more than 10% on some held date for 1,071 of the
  2,779 pairs, mostly by dividends, and on the snapshot dates 9 to 44 members per snapshot
  (0.02% to 0.28% of the index) sit on the other side of the $5 screen. Since
  `Close_PIT` sets the $5 screen and the per-share cost terms, a point-in-time study
  anchors it: `PITUniverse.traded_prices` reads each member's price from the snapshots, and
  `data_processor.anchor_point_in_time` multiplies each bar's `Close_PIT` by N-PORT's price
  over `Close_PIT` on the latest snapshot date on or before it (before the first, the
  first), so `Close_PIT` equals the traded price on every snapshot date; `Volume_PIT` is
  divided by the same ratio (dollar volume is unchanged), and `Close`, with every return,
  is untouched. On the development cache this moves the `Close_PIT` of 777 of the 2,625
  members with prices by more than 10% (median over the series) and changes the $5 screen
  of 14 to 20 members in each three-year formation window ending 2022-12-31 to 2025-07-01
  (mostly high-yield names whose dividend-adjusted price sat below $5; Advantage Solutions,
  fuboTV, MicroVision, PLAYSTUDIOS and BRC fall below it from 2024). The v32 universe file
  is not a point-in-time universe and its run is not anchored.
- **The survivorship gap, before and after the data review**: the index weight of holdings
  without a ticker, and of mapped holdings without prices in the development cache
  (`data/enhanced_russell_3000_data_manifest.json`: never fetched, or fetched with outcome
  `not_found`, `short`, `invalid`, `empty` or an error), at `4bcc8b5` and now:

  | snapshot | unmapped | mapped, no cached prices | of which never fetched (after) | total |
  |---|---|---|---:|---|
  | 2019-09-30 | 4.15% -> 1.04% | 5.30% -> 5.81% | 4.01% | 9.45% -> 6.85% |
  | 2019-12-31 | 3.93% -> 0.95% | 4.90% -> 5.50% | 3.67% | 8.83% -> 6.45% |
  | 2020-12-31 | 3.03% -> 0.57% | 3.84% -> 4.88% | 3.10% | 6.87% -> 5.46% |
  | 2021-12-31 | 2.31% -> 0.42% | 2.90% -> 4.02% | 2.30% | 5.21% -> 4.43% |
  | 2022-12-30 | 2.18% -> 0.14% | 2.10% -> 3.24% | 1.39% | 4.28% -> 3.38% |
  | 2023-12-31 | 1.35% -> 0.07% | 1.36% -> 2.18% | 1.00% | 2.71% -> 2.24% |
  | 2024-12-31 | 0.78% -> 0.03% | 0.79% -> 1.40% | 0.70% | 1.57% -> 1.43% |
  | 2025-12-31 | 0.61% -> 0.01% | 0.36% -> 0.87% | 0.52% | 0.96% -> 0.88% |

  The next development run's top-up fetches the 787 never-fetched tickers (306 of them in
  no snapshot file of `4bcc8b5`). Yahoo serves bars dated 2025 or earlier for 116 of them,
  at most 0.22% of the index in any snapshot. Almost all of the remaining gap is members
  for which Yahoo serves no bar dated 2025 or earlier (never fetched and none on Yahoo:
  3.91% of 2019-09-30, 0.49% of 2025-12-31; fetched as `not_found`: 1.74% and 0.18%), and
  the wrong-ticker search above found no other ticker for them. Newly active tickers
  (status `active`, in no snapshot file of `4bcc8b5`) without cached prices: ACET, BBUC,
  BOLT, CUE, CVM, GPMT, GTES, LOGC, MCRB, MRX, NFE, NVRI, QGEN, REAX, SCOR, SKIN, TIL, WVE
  and XPRO were never fetched, Yahoo serves bars for each, and the top-up fetches them
  (with the delisted LBRDA, at most 0.06% of the index); SENS (outcome `invalid`) and OPI
  (an error, and no bar on Yahoo) are recorded failures, which the top-up does not retry,
  and so are two accepted tickers, KNTK and ONIT (`invalid`, 0.004% and 0.001%).
- **Industry and venue are current, not point-in-time.** EDGAR keeps one SIC per
  registrant and the Nasdaq Trader directory lists today's venue. Tickers that SEC no
  longer lists (most delisted names) have blank industry fields.
