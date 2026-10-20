// The study's paper: the research-note site in print.
//
// Every result this file prints comes from build/paper_data.json, written by
// scripts/build_paper.py from assets/study.json (the data the site's charts and checked
// numbers come from) and the headline JSON it was built from. Numbers are placed with
// #m("key"); a result that does not exist yet is null there and prints as "pending" with
// its reason. A sentence whose wording depends on the data carries #claim("name"): the
// compile stops if the data no longer support it. Build: python scripts/build_paper.py

#let D = json("build/paper_data.json")

// ── tokens (the site's light theme, read from assets/site.css by the builder) ─────────
#let col(name) = rgb(D.colors.at(name))
#let ink = col("ink")
#let ink2 = col("ink-2")
#let ink3 = col("ink-3")
#let rule = col("rule")
#let rule2 = col("rule-2")
#let accent = col("accent")
#let sunk = col("sunk")
#let sans = "IBM Plex Sans"
#let sans-md = "IBM Plex Sans Medm"
#let sans-sb = "IBM Plex Sans SmBld"
#let serif = "IBM Plex Serif"
#let serif-sb = "IBM Plex Serif SmBld"
#let mono = "IBM Plex Mono"

// ── data helpers ──────────────────────────────────────────────────────────────────────
// A number from the data; null (not yet available) prints its reason, never a number.
#let pend(reason) = text(style: "italic", fill: ink3)[#reason]
// The metadata marks the null branch for tests/test_build_paper.py (typst query <pending>).
#let m(key) = {
  let v = D.m.at(key)
  if v == none [#pend(D.why.at(key))#metadata(key) <pending>] else { v }
}
// Asserts a statement of the surrounding prose against the data; prints nothing.
#let claim(name) = {
  assert(D.claims.at(name), message: "paper/main.typ: claim '" + name + "' is false for this data")
}
#let flag(name) = D.flags.at(name)
// A repository path held in the data, set like the paths typed in the text.
#let path(key, suffix: "") = raw(D.m.at(key) + suffix)
#let T(name) = D.tables.at(name)

// ── page ──────────────────────────────────────────────────────────────────────────────
#let text-width = D.layout.text_width_mm * 1mm
#let margin-x = (210mm - text-width) / 2
#let short-title = [No detectable edge: Russell 3000 pairs trading]
#let date-parts = D.meta.paper_date.split("-").map(int)

#set document(
  title: [No detectable edge: cointegration pairs trading on the Russell 3000, #m("paper.years")],
  author: "Navnoor Bawa",
  date: datetime(year: date-parts.at(0), month: date-parts.at(1), day: date-parts.at(2)),
  keywords: ("statistical arbitrage", "pairs trading", "cointegration", "walk-forward", "Sharpe ratio inference"),
)
#set page(
  paper: "a4",
  margin: (x: margin-x, top: 25mm, bottom: 22mm),
  header: context {
    if here().page() > 1 {
      set text(font: sans, size: 7pt, fill: ink3)
      grid(columns: (1fr, auto), short-title, [Research note · #m("paper.paper_date_long")])
      v(-5pt)
      line(length: 100%, stroke: 0.4pt + rule)
    }
  },
  footer: context {
    set text(font: sans, size: 7pt, fill: ink3)
    grid(columns: (1fr, auto),
      [Hypothetical backtest. Not investment advice.],
      [#counter(page).display("1") / #counter(page).final().first()])
  },
)
#set text(font: serif, size: 9.6pt, fill: ink, lang: "en", region: "gb",
  number-type: "lining", number-width: "tabular", hyphenate: true)
#set par(justify: true, leading: 0.64em, spacing: 0.95em)
#show strong: set text(font: serif-sb, weight: "regular")
#show link: set text(fill: accent)
#show raw: set text(font: mono, size: 7.6pt)
#set list(indent: 0.4em, body-indent: 0.6em, marker: text(fill: ink3)[–])
#set enum(indent: 0.4em, body-indent: 0.6em)
#show ref: set text(fill: ink)
#show cite: set text(fill: ink)

// headings: numbered sections, serif, number in the accent colour
#set heading(numbering: "1.1")
#show heading.where(level: 1): it => {
  set par(justify: false)
  block(above: 1.9em, below: 0.85em, sticky: true, {
    set text(font: serif-sb, size: 13pt, weight: "regular")
    if it.numbering != none {
      box(width: 9mm, text(font: sans-sb, size: 10.5pt, fill: accent, counter(heading).display(it.numbering)))
    }
    it.body
  })
}
#show heading.where(level: 2): it => {
  set par(justify: false)
  block(above: 1.35em, below: 0.65em, sticky: true, {
    set text(font: serif-sb, size: 10.2pt, weight: "regular")
    if it.numbering != none {
      box(width: 9mm, text(font: sans-sb, size: 8.8pt, fill: accent, counter(heading).display(it.numbering)))
    }
    it.body
  })
}

// ── exhibits and tables ───────────────────────────────────────────────────────────────
#set figure(gap: 5pt)
#set place(clearance: 1.5em)
#show figure: set block(breakable: false)
#show figure: set align(left)
#show figure.where(kind: "exhibit"): set figure.caption(position: top)
#show figure.where(kind: table): set figure.caption(position: top)
#show figure.caption: it => {
  set par(justify: false, leading: 0.5em)
  set align(left)
  block(width: 100%, below: 3pt, {
    text(font: sans-sb, size: 6.8pt, fill: accent, tracking: 0.07em,
      upper(it.supplement) + [ ] + context it.counter.display(it.numbering))
    linebreak()
    text(font: sans-sb, size: 9pt, fill: ink, it.body)
  })
}
#let foot(notes, source) = {
  set text(font: sans, size: 7pt, fill: ink2)
  set par(justify: false, leading: 0.5em, spacing: 0.45em)
  if notes != none { block(above: 6pt)[#text(font: sans-sb, fill: ink)[Notes] #h(3pt) #notes] }
  if source != none { block(above: 3pt)[#text(font: sans-sb, fill: ink)[Source] #h(3pt) #source] }
}
#let pending-box(status, note) = block(width: 100%, fill: sunk, inset: (x: 9pt, y: 8pt), radius: 2pt, {
  set text(font: sans, size: 7.4pt, fill: ink2)
  set par(justify: false, leading: 0.5em)
  text(font: sans-sb, fill: ink, status)
  if note != none [ #note]
})
// An exhibit: label and takeaway title above, subtitle, the chart (or its pending
// panel), notes and source below. Floats to the top or bottom of a page unless pinned.
#let exhibit(id, title, sub: none, notes: none, source: none, pending: none, width: 100%, float: true) = {
  let file = D.figures.at(id)
  let body = {
    set align(left)
    set text(font: sans, size: 7.4pt, fill: ink2)
    set par(justify: false, leading: 0.5em)
    if sub != none { block(below: 5pt, text(size: 7.6pt, sub)) }
    if file != none { image(file, width: width) } else { pending-box(D.pending.at(id), pending) }
    foot(notes, source)
  }
  [#figure(body, kind: "exhibit", supplement: [Exhibit], caption: title,
    placement: if float { auto } else { none }) #label("ex-" + id)]
}
// booktabs: a heavy rule above and below, a light one under the header, no verticals
#let booktab(columns: auto, align: auto, header: (), rows: (), size: 7.4pt, inset-y: 2.7pt) = {
  set text(font: sans, size: size, fill: ink, hyphenate: false)
  set par(justify: false, leading: 0.45em)
  table(
    columns: columns, align: align, stroke: none, inset: (x: 4pt, y: inset-y),
    table.header(
      table.hline(stroke: 0.8pt + ink),
      ..header.map(h => text(font: sans-md, fill: ink2, h)),
      table.hline(stroke: 0.45pt + ink),
    ),
    ..rows.flatten(),
    table.hline(stroke: 0.8pt + ink),
  )
}
#let tablefig(name, caption, body, notes: none, source: none, float: false) = [
  #figure(block(width: 100%, { set align(left); body; foot(notes, source) }), kind: table, supplement: [Table],
    caption: caption, placement: if float { auto } else { none }) #label("tab-" + name)
]
#let float-row(..cells) = place(auto, float: true, clearance: 1.5em,
  grid(columns: (1fr,) * cells.pos().len(), column-gutter: 6mm, row-gutter: 8pt, ..cells))
// "Exhibits 16–19": the number of the last exhibit of a run
#let exnum(lbl) = context counter(figure.where(kind: "exhibit")).at(lbl).first()
#let small(body) = text(font: sans, size: 7.4pt, fill: ink2, body)
#let tag(body) = box(inset: (x: 4pt, y: 1.6pt), radius: 1.5pt, stroke: 0.5pt + rule2,
  text(font: sans-md, size: 6.8pt, fill: ink2, tracking: 0.03em, upper(body)))

// ══════════════════════════════════════════════════════════════════════════════════════
// Title block
// ══════════════════════════════════════════════════════════════════════════════════════

#block(below: 0pt, {
  grid(columns: (1fr, auto), align: (left + horizon, right + horizon),
    text(font: sans-md, size: 7.4pt, fill: accent, tracking: 0.08em, upper[Research note · Statistical arbitrage]),
    tag[Hypothetical backtest])
  v(5pt)
  set par(justify: false, leading: 0.42em)
  text(font: serif-sb, size: 20pt)[No detectable edge: cointegration pairs trading on the Russell 3000, #m("paper.years")]
  v(7pt)
  set par(leading: 0.55em)
  text(font: sans, size: 10pt, fill: ink2)[A pairs strategy with formation-only selection, next-day fills and a per-stock cost model, tested in a main backtest, in a continuous walk-forward and against two baselines. Its returns cannot be told apart from zero, from the textbook distance method or from random pairs. A pre-registered test on 2026 data is pending.]
  v(8pt)
  text(font: sans, size: 7.8pt, fill: ink2)[
    #text(font: sans-sb, fill: ink)[Navnoor Bawa] #h(5pt)·#h(5pt) Note of #m("paper.paper_date_long") #h(5pt)·#h(5pt) Study run v#m("paper.version") of #m("paper.run_date_long"), commit #raw(m("paper.commit_short"))
  ]
  v(1pt)
  grid(columns: (auto, 1fr), column-gutter: 8pt, row-gutter: 3pt,
    text(font: sans-md, size: 7.2pt, fill: ink3)[Code and data],
    link("https://github.com/NavnoorBawa/russell3000-pairs-trading", text(font: sans, size: 7.4pt)[github.com/NavnoorBawa/russell3000-pairs-trading]),
    text(font: sans-md, size: 7.2pt, fill: ink3)[Research-note site],
    link("https://navnoorbawa.github.io/russell3000-pairs-trading/", text(font: sans, size: 7.4pt)[navnoorbawa.github.io/russell3000-pairs-trading]))
})

#v(10pt)
#claim("main_ci_spans_zero") #claim("oos_ci_spans_zero") #claim("not_different_from_gatev")
#claim("inside_random_spread") #claim("gross_not_significant") #claim("gross_below_cost")
#claim("cannot_reject_sharpe_half") #claim("holdout_sealed")
#block(width: 100%, inset: (x: 11pt, y: 10pt), fill: sunk, radius: 2pt, {
  grid(columns: (1fr, auto), align: (left + horizon, right + horizon),
    text(font: serif-sb, size: 10.5pt)[Summary],
    box(inset: (x: 6pt, y: 2.5pt), radius: 1.5pt, fill: ink,
      text(font: sans-sb, size: 7pt, fill: white, tracking: 0.06em, upper[No detectable edge])))
  v(2pt)
  set par(leading: 0.6em)
  [We test whether a cointegration pairs-trading strategy on the Russell 3000 earns a return after realistic execution costs. From #m("paper.period_start_month") to #m("paper.period_end_month") the strategy returned #m("main.total_return_pct") on its capital (Sharpe #m("main.sharpe")\; 95% interval #m("significance.main.boot_lo") to #m("significance.main.boot_hi")), and its continuous walk-forward out-of-sample Sharpe is #m("oos.pooled_sharpe") (#m("significance.oos_daily.boot_lo") to #m("significance.oos_daily.boot_hi")). Neither differs from zero, from the Gatev distance method (difference #m("benchmarks.sharpe_diff_vs_gatev.diff"), p = #m("benchmarks.sharpe_diff_vs_gatev.p")) or from random pairs (#m("paper.percentile_ordinal") percentile). Before costs the average trade earned #m("study.dev.facts.gross_bp") bp of its gross notional (t = #m("study.dev.facts.gross_t")) against #m("study.dev.facts.cost_bp") bp of modelled cost, so there is no gross edge for costs to remove. The sample rules out a Sharpe ratio above #m("study.dev.facts.sharpe_ucb") (one-sided 95% bound) but cannot tell 0 from 0.5. The decisive test, on untouched 2026 data, stays sealed until its pre-registration is filed.]
})

#v(8pt)
#let kpi(label, value, sub) = block(width: 100%, inset: (top: 6pt, bottom: 2pt), stroke: (top: 0.6pt + ink), {
  set par(justify: false, leading: 0.45em)
  text(font: sans-md, size: 6.6pt, fill: ink2, tracking: 0.05em, upper(label))
  v(3pt)
  text(font: sans-sb, size: 14pt, fill: ink, value)
  v(2pt)
  text(font: sans, size: 6.8pt, fill: ink2, sub)
})
#let kpi-value(key, empty) = if D.m.at(key) == none [#text(fill: ink3, empty)#metadata(key) <pending>] else { m(key) }
#grid(columns: (1fr, 1fr, 1fr), column-gutter: 12pt, row-gutter: 9pt,
  kpi([Holdout 2026 · net Sharpe], kpi-value("paper.holdout.sharpe", [Sealed]),
    [Until the pre-registration is filed and the v33 code frozen. No 2026 price has been fetched.]),
  kpi([Walk-forward OOS Sharpe], m("oos.pooled_sharpe"),
    [95% CI #m("significance.oos_daily.boot_lo") to #m("significance.oos_daily.boot_hi") · HAC p = #m("significance.oos_daily.hac_p") · #m("study.dev.facts.oos_days") days]),
  kpi([Deflated Sharpe, OOS], m("significance.oos_daily.dsr_pct"),
    [Probability the Sharpe beats the best of #m("study.dev.facts.dsr_trials") null trials · P(SR > 0) = #m("significance.oos_daily.psr_pct")]),
  kpi([Gross edge per trade], [#m("study.dev.facts.gross_bp") bp],
    [t = #m("study.dev.facts.gross_t") · n = #m("main.trades") · cost #m("study.dev.facts.cost_bp") bp per trade]),
  kpi([Break-even cost multiple], m("study.dev.facts.break_even_x"),
    [Net P&L is zero at this fraction of modelled costs; the gross itself is not significant]),
  kpi([Data snooping · SPA p], kpi-value("paper.snooping.spa_p", [Pending]),
    [Declared family: #m("study.dev.snooping.grid_points")-point grid, #m("study.dev.snooping.toggles") toggles; runs on the v33 development calendar]),
)

// ══════════════════════════════════════════════════════════════════════════════════════
= Introduction
// ══════════════════════════════════════════════════════════════════════════════════════

== The question

Pairs trading buys one stock and sells another when the spread between them is unusually wide, and closes the position when it narrows. #cite(<gatev2006>, form: "prose") documented excess returns from a simple distance rule on US stocks over four decades; later studies find that the edge has shrunk and is small after realistic costs @do2010 @do2012 @rad2016, and #cite(<krauss2017>, form: "prose") surveys the methods. This note asks one question and is built to answer it honestly: *does a cointegration pairs-trading strategy on the Russell 3000 have an edge after realistic execution and costs, out of sample?*

The strategy selects pairs with the Engle--Granger test @engle1987 on formation data only, tracks each pair's hedge ratio with a two-state Kalman filter @kalman1960, trades a z-score of the hedged spread with fills at the next day's close, and pays costs computed from each stock's own liquidity. It is evaluated in a main backtest from #m("paper.period_start_long") to #m("paper.period_end_long"), in a continuous walk-forward with #m("oos.windows") out-of-sample windows, and against two baselines run on the same footing: the distance method of #cite(<gatev2006>, form: "prose") and #m("benchmarks.random_control.n_draws") portfolios of random pairs.

The answer for #m("paper.years") is a null. A null is informative only to the extent that the test had power and the measurement was right, so most of this note is about what the sample can and cannot rule out, and about the checks that the code measures what it claims. The development period cannot test the design choices made on it; a pre-registered test on 2026 data, sealed at the date of this note, does that (@sec-holdout).

== What is new

The study uses free data only. Academic studies avoid survivorship with paid point-in-time databases; a backtest on free data usually starts from today's index members instead, and is exposed to the other familiar weaknesses of backtests: flat cost assumptions, rolling windows that drop positions at their edges, significance without power, and an untold number of designs tried. Each item below addresses one of these; the last adds a test the development data cannot provide.

- *A point-in-time universe from free SEC filings.* The complete holdings of the iShares Russell 3000 ETF (IWV) are public on Form N-PORT for the last month of each fiscal quarter; #m("paper.iwv.n") quarterly snapshots give index membership as it was at each formation date, without a paid constituent history (@sec-data). The v33 design trades this universe; the v32 run reported here does not.
- *Costs from each stock's own liquidity.* Every fill pays commission, half the typical quoted spread for the stock's dollar-volume bucket and square-root market impact on the stock's own volatility and dollar volume, at the next day's close (@sec-costs).
- *A continuous walk-forward.* The out-of-sample windows are calendar slices of one simulation with the ranker refit per window; positions carry across window boundaries instead of being discarded (@sec-method).
- *Power analysis.* Each null is reported with the Sharpe ratios it excludes, the Sharpe ratio it could have detected and the track record a given Sharpe ratio would need (@sec-inference).
- *A declared variant family.* #m("study.dev.snooping.grid_points") threshold settings and #m("study.dev.snooping.toggles") design toggles were declared on #m("paper.declared_long"), before any variant ran, for White's Reality Check, Hansen's SPA test, the Romano--Wolf stepdown, the model confidence set and the probability of backtest overfitting (@sec-snooping).
- *A pre-registered 2026 holdout.* Hypotheses, test, multiplicity correction and decision rule are fixed before any 2026 price is fetched; each strategy then runs once and its result is published whatever it is (@sec-holdout).

== Related work

The published record points one way: the classic pairs edge was large before the 2000s, has shrunk since, and is small after realistic costs (@tab-literature). The closest analogue of this study is #cite(<rad2016>, form: "prose"), who compare distance, cointegration and copula methods on US stocks; this study differs in period, cost model and inference. #cite(<avellaneda2010>, form: "prose") trade residuals of single stocks against sector ETFs and factors, the second strategy family tested here (@sec-residual).

#tablefig("literature", [Published results for pairs trading and residual reversion, as reported by their authors],
  booktab(columns: (24%, 15%, 20%, 41%), align: (left, left, left, left),
    header: ([Study], [Sample], [Method], [Reported result]),
    rows: (
      ([#cite(<gatev2006>, form: "prose")], [US, 1962–2002], [Distance method, top-20 pairs], [Annualised excess returns of up to 11% before costs, falling in later years. The baseline replicated here.]),
      ([#cite(<do2010>, form: "prose")], [US, to 2009], [Distance method], [Profitability declines over time; the strategy does best in prolonged turbulence.]),
      ([#cite(<avellaneda2010>, form: "prose")], [US, 1997–2007], [PCA and sector-ETF residual reversion], [Net Sharpe 1.44 (PCA) and 1.1 (ETF) over 1997–2007; PCA only 0.9 over 2003–2007. The second family tested here.]),
      ([#cite(<do2012>, form: "prose")], [US, 1963–2009], [Distance method with trading costs], [About 30 bp a month for well-matched pairs in refined industries after costs; largely unprofitable after 2002.]),
      ([#cite(<clegg2014>, form: "prose")], [US], [Persistence of cointegration], [Little evidence that pairs cointegrated in one year stay cointegrated the next (as summarised by secondary sources).]),
      ([#cite(<rad2016>, form: "prose")], [US, 1962–2014], [Distance, cointegration and copula methods], [91, 85 and 43 bp a month before costs; 38, 33 and 5 bp after; trading opportunities fall after 2009. The closest published analogue of this study.]),
      ([#cite(<krauss2017>, form: "prose")], [Review], [Survey of pairs-trading approaches], [Distance, cointegration, time-series, stochastic-control and other approaches compared; open problems include costs and robustness.]),
    )))

// ══════════════════════════════════════════════════════════════════════════════════════
= Data <sec-data>
// ══════════════════════════════════════════════════════════════════════════════════════

Every input is free: no account, API key or licence is needed to rebuild the study (@tab-sources). Prices are not redistributed with the code, under the vendor's terms; each run's fetch manifest lists the symbols and dates a re-run fetches.

#tablefig("sources", [Data sources, all free],
  booktab(columns: (27%, 40%, 33%), align: (left, left, left),
    header: ([Source], [What it provides], [Used for]),
    rows: (
      ([Yahoo Finance chart API], [Daily open, high, low, close and volume, splits and dividends], [Prices of the universe, the 11 sector SPDR ETFs and the VIX]),
      ([SEC EDGAR: Form N-PORT filings of IWV], [Quarterly holdings of the iShares Russell 3000 ETF], [Point-in-time index membership (v33)]),
      ([OpenFIGI mapping API], [CUSIP to ticker], [Joining holdings to price histories]),
      ([SEC EDGAR: company submissions], [SIC industry code per registrant], [Fama–French 49 industries for same-industry pairs (v33)]),
      ([Kenneth French data library], [Fama–French five factors, momentum, short- and long-term reversal, one-month T-bill], [Factor attribution (v33)]),
      ([Nasdaq stock screener], [Market capitalisation of US-listed common stocks], [The v32 universe]),
      ([Nasdaq Trader symbol directory], [Primary listing venue], [Venue-specific cost references]),
    )))

== The v32 universe

The universe of the v32 study run is the #m("paper.names_file") largest US common stocks by market capitalisation on #m("paper.universe_as_of_long"): the Russell 3000 rule applied to the Nasdaq screener, not FTSE Russell's constituent list. Daily prices from #m("paper.data_start_long") to #m("paper.data_end_long") were fetched for #m("study.dev.facts.coverage_pct") of it, and #m("paper.names_prices") names have price history in the study data. Level screens, the \$5 price floor and dollar volume, use point-in-time prices, closes with later splits undone, so that a split after the formation date cannot decide earlier membership. The #m("paper.universe_top") most liquid names by point-in-time dollar volume enter the pair search.

#claim("universe_not_point_in_time")
This universe has survivorship bias. Companies that failed, delisted or were acquired before #m("paper.universe_as_of_long") are absent, and so are the pairs that broke when one of them failed. The bias flatters a mean-reversion strategy, which makes a null result on this universe more convincing, not less (@sec-threats).

== Point-in-time membership from N-PORT filings

A registered fund reports its complete portfolio holdings on Form N-PORT, and the report for the third month of each fiscal quarter is made public on EDGAR. IWV tracks the Russell 3000, so its filings give index membership as it was, quarter by quarter, at no cost. `scripts/build_pit_universe.py` reads the equity-common holdings of #m("paper.iwv.n") snapshots from #m("paper.iwv.first_long") to #m("paper.iwv.last_long"), #m("paper.iwv.equity_min") to #m("paper.iwv.equity_max") holdings each, and maps each holding's CUSIP to a ticker through OpenFIGI (@ex-snapshots). A snapshot is in force from the date its holdings describe until the next one. Two caveats: IWV is a fund, not the index, and holds fewer names than the index; and additions and deletions within a quarter appear only at the next quarter end. Snapshots dated #m("paper.iwv.sealed_from_long") or later are listed but not downloaded: their holdings carry a market value, and so a 2026 price, for every member.

#claim("iwv_gap_shrinks")
#exhibit("snapshots",
  [Free filings give #m("paper.iwv.n") quarterly snapshots of index membership; the index weight without a usable ticker falls from #m("paper.iwv_unmapped_first_pct") to #m("paper.iwv_unmapped_last_pct")],
  sub: [Equity holdings of the iShares Russell 3000 ETF in its N-PORT filings, #m("paper.iwv_first_year")–#m("paper.iwv_last_year"), and the share of their value that cannot be mapped to a ticker],
  notes: [A holding without a usable ticker is one OpenFIGI cannot map, or one whose last ticker now belongs to another issuer and is left unmapped on purpose so that no member is joined to someone else's prices. The share is larger in older snapshots, as expected if most such holdings are securities that have since delisted; its weight is part of the survivorship gap.],
  source: [`reference/universe/index.json`, built by `scripts/build_pit_universe.py` from SEC N-PORT-P filings (iShares Trust, series S000004341) and OpenFIGI.])

== The survivorship gap

The survivorship gap at a formation date is the index weight of members a backtest cannot trade: holdings without a usable ticker, plus members with a ticker whose price history the vendor no longer serves, mostly failures and takeovers. The v32 universe has no membership to measure the gap against. From v33 on, every formation records the snapshot in force, its members, how many have price history, and the index weight of those that do not (@ex-universe).

#exhibit("universe",
  [Point-in-time universe: index members with and without price history at each formation date],
  sub: [Members of the index snapshot in force when pairs are formed, and the share of index weight the price data do not cover],
  pending: [The v32 universe is the #m("paper.names_file") largest US stocks of #m("paper.universe_as_of_long"), back-filled to #m("paper.data_first_year"), so it has no membership to report at a formation date. From v33 every formation records the index snapshot in force, its members, how many have price history, and the index weight of those that do not.],
  notes: [The index weight of members without price history, plus that of holdings with no usable ticker, is the survivorship gap at that date: a pair that includes one of them cannot be formed.],
  source: [The run's results export, `universe_by_formation`; membership from IWV's holdings in SEC N-PORT filings.],
  )

// ══════════════════════════════════════════════════════════════════════════════════════
= Method <sec-method>
// ══════════════════════════════════════════════════════════════════════════════════════

Selection sees formation data only; every trading decision on day _t_ uses data up to day _t_ and fills on day _t_ + 1; the evidence is computed after the run (@ex-pipeline). Tests change future prices and check that no past decision moves.

#let dg-box(title, lines, key: false) = block(width: 100%, height: 15.5mm, inset: (x: 4.5pt, y: 4.5pt), radius: 2pt,
  stroke: if key { 1pt + accent } else { 0.5pt + rule2 }, {
    set par(justify: false, leading: 0.4em)
    text(font: sans-sb, size: 7.2pt, fill: ink, title)
    v(0.5pt)
    text(font: sans, size: 6.4pt, fill: ink2, lines)
  })
#let dg-arrow = align(center + horizon, text(font: sans, size: 9pt, fill: ink3, sym.arrow.r))
#let dg-lane(name, sub) = grid.cell(colspan: 9, inset: (top: 3pt, bottom: 1pt),
  text(size: 7.2pt)[#text(font: sans-sb, fill: ink, name) #h(4pt) #text(font: sans, fill: ink2, sub)])
#figure(kind: "exhibit", supplement: [Exhibit],
  caption: [The pipeline, and what data each stage may see],
  placement: auto, {
    set align(left)
    set text(font: sans, size: 7.4pt, fill: ink2)
    block(below: 5pt, text(size: 7.6pt)[Framed in the accent colour: the two look-ahead boundaries, the formation cutoff and the next-day fill])
    grid(columns: (1fr, 3.5mm, 1fr, 3.5mm, 1fr, 3.5mm, 1fr, 3.5mm, 1fr), row-gutter: 3pt,
      dg-lane[Selection][formation data only],
      dg-box[Data][daily prices #m("paper.data_years") \ VIX, 11 sector ETFs], dg-arrow,
      dg-box[Universe][#m("paper.names_file") largest stocks \ point-in-time screens \ #m("paper.universe_top") most liquid], dg-arrow,
      dg-box(key: true)[Formation][Engle–Granger p < 0.05 \ half-life 4–25 days \ data to #m("paper.formation_cutoff_short")], [], [], [], [],
      dg-lane[Trading][causal: data to day _t_],
      dg-box[Spread model][two-state Kalman \ slope β and intercept], dg-arrow,
      dg-box[Signal][β-locked z-score \ enter |_z_| ≥ 1.8 \ target 0.5, stop +1.5], dg-arrow,
      dg-box(key: true)[Execution][signal at close _t_ \ fill at close _t_ + 1 \ no shared legs], dg-arrow,
      dg-box[Costs][commission, spread \ √ impact per stock \ borrow, financing], dg-arrow,
      dg-box[Accounting][daily mark-to-market \ 30% gross cap \ kill switch],
      dg-lane[Evidence][after the run],
      dg-box[Walk-forward][#m("oos.windows") windows, one \ continuous simulation \ refit per window], dg-arrow,
      dg-box[Significance][HAC t, bootstrap CI \ PSR, deflated Sharpe \ Ledoit–Wolf test], dg-arrow,
      dg-box[Baselines][Gatev distance rule \ #m("benchmarks.random_control.n_draws") random-pair draws \ same costs, _t_ + 1 fills], [], [], [], [],
    )
  }) <ex-pipeline>

#exhibit("timeline",
  [Data splits: formation, walk-forward, main backtest and the sealed holdout],
  sub: [Calendar #m("paper.data_first_year")–#m("paper.holdout_year")],
  notes: [The main backtest and the walk-forward overlap on #m("study.dev.facts.oos_overlap_days") of the main backtest's #m("study.dev.facts.main_days") days and trade the same pair pool: they are one experiment, not two confirmations.],
  source: [#path("paper.results_path")\; `pairs_trading/study_config.py` (calendar `dev`).])

== Formation

Pairs are formed once, on data to #m("paper.formation_cutoff_long"). Among the #m("paper.universe_top") most liquid names, every pair with a positive return correlation of at least 0.25 is tested for cointegration with the two-step Engle--Granger test in both directions, Bonferroni-adjusted across the two, at p < 0.05. A pair is kept if the half-life of its cointegrating residual lies between 4 and 25 trading days and a heuristic quality score passes: #m("fdr.final_selected_pairs") of #m("fdr.pairs_tested") pairs tested (@sec-multiple). Every #m("paper.v32_reselect_every") trading days the pool is re-tested; pairs can drop out but none can enter.

== Spread model

The hedge ratio is the slope state of a two-state Kalman filter on log prices,
$ log p_(1,t) = alpha_t + beta_t log p_(2,t) + epsilon_t, quad (alpha_t, beta_t) "a random walk," $
with both log prices centred on their burn-in means and the filter seeded by ordinary least squares. The intercept makes β a hedge ratio rather than a ratio of price levels, and centring makes every signal invariant to a vendor's back-adjustment of history for a later split or dividend, which shifts each log price by a constant.

== Signal and exits

One z-score drives every decision. At a signal on day _t_#sub[0] the hedge ratio is locked at its current value and the spread is standardised by its mean and standard deviation over the last 30 to 60 bars (three half-lives), both frozen at the signal:
$ s_t = log p_(1,t) - beta_(t_0) log p_(2,t), quad z_t = (s_t - mu_(t_0)) / sigma_(t_0). $
A pair is entered when |_z_| ≥ 1.8, long the spread when _z_ is negative and short when it is positive. It exits at the target when |_z_| ≤ 0.5, at the stop when _z_ has moved 1.5 further against the position, and at the time stop after clamp(2.5 × half-life, 10, 25) trading days. Entries also require a 20-day return correlation of at least 0.20 and a hedge ratio in [0.25, 4]; a pair that has just lost money cools off before it can trade again; and a regime gate on the VIX and sector dispersion scales positions and blocks new entries in stressed markets.

== Execution, accounting and risk limits

A signal computed on the close of day _t_ is filled at the close of day _t_ + 1, for entries and exits alike: in practice a market-on-close order in each stock's closing auction, so both legs print together. Share counts are fixed from the signal-day close and the legs are sized \$1~:~\$β. Positions are marked to market daily, costs are booked on fill days, and positions still open at the end of the data are closed. The book has \$#m("study.dev.facts.capital_musd")M of notional capital, 3–10% of equity per pair, a 30% cap on gross exposure, at most 8 new entries a day, no stock in two open pairs, and drawdown and daily-loss kill switches that flatten it. Idle cash earns no interest.

#claim("ranker_no_skill")
A classifier of the probability that a trade is profitable, on 30 features, only orders same-day candidates, which matters when more signals fire than the book's limits allow; it does not create signals. Its out-of-sample AUC is #m("ranker.oos_auc") (#m("ranker.wf_pooled_auc") pooled across the walk-forward windows; 0.5 is no skill), so it has no measurable skill, and v33 drops it from the primary design.

== Walk-forward

The walk-forward is one continuous out-of-sample simulation on a 252-day training / 63-day test grid from #m("paper.oos_start_month") to #m("paper.oos_end_month"). The ranker is refit on each window's training year, positions carry across window boundaries, and per-window figures are calendar slices of the one simulation (@tab-windows in the appendix). It trades the same pair pool as the main backtest and shares #m("study.dev.facts.oos_overlap_days") of its #m("study.dev.facts.main_days") days (@ex-timeline).

== Inference

Sharpe ratios are annualised from daily net returns by √252. Means are tested with the HAC t-statistic of #cite(<newey1987>, form: "prose")\; intervals for single series are circular block bootstraps with the block length of #cite(<politis2004>, form: "prose") (#m("paper.boot_resamples") resamples; blocks of #m("paper.boot_block_main") days for the main backtest and #m("paper.boot_block_oos") for the walk-forward). The probabilistic and deflated Sharpe ratios follow #cite(<bailey2012>, form: "prose") and #cite(<bailey2014>, form: "prose"), using the variance of the Sharpe estimator under non-normal returns; differences of Sharpe ratios use the studentized bootstrap of #cite(<ledoit2008>, form: "prose")\; and serial correlation enters the Sharpe ratio's standard error as in #cite(<lo2002>, form: "prose").

== Validation <sec-validation>

A backtest on real data says what a strategy did, not whether the code measures what it claims. `scripts/synthetic_validation.py` runs the real engine, with its full cost model, on synthetic markets whose answer is known (@tab-validation); continuous integration runs it on every push to the main branch and on pull requests. The test suite adds causality checks, each confirmed by re-introducing the bug it guards against: every decision dated on or before _T_ is unchanged when all prices, volumes and macro data after _T_ are replaced, with classical ranking and with a trained ranker; the regime gate's inputs are prefix-invariant; and the same trades occur at the same z-scores when the vendor back-adjusts history for a later split. The statistics are tested against reference implementations: statsmodels for Newey--West, arch for the Politis--White block length, an independent cross-validation for the probability of backtest overfitting, and the authors' code for Ledoit--Wolf.

#tablefig("validation", [Known-answer checks],
  booktab(columns: (42%, 28%, 30%), align: (left, left, left),
    header: ([Check], [What must happen], [Result]),
    rows: T("validation").map(r => (r.at(0), r.at(1), if r.at(2) == "pending" { pend[pending (committed validation run)] } else { r.at(2) }))),
  notes: if flag("validation") [Synthetic markets from `pairs_trading/synthetic.py`.] else [Results fill from `results/validation/synthetic_validation.json` once a run is committed.])

// ══════════════════════════════════════════════════════════════════════════════════════
= Development-period results <sec-results>
// ══════════════════════════════════════════════════════════════════════════════════════

The main backtest enters trades from #m("paper.period_start_long") to #m("paper.period_end_long") on \$#m("study.dev.facts.capital_musd")M of notional capital, with pairs selected on data to #m("paper.formation_cutoff_long"). Its #m("main.trades") trades returned #m("main.total_return_pct") with a maximum drawdown of #m("main.max_drawdown_pct") (@ex-equity). The book held no position on #m("study.dev.facts.flat_days") of #m("study.dev.facts.days") days and used #m("main.avg_gross_exposure_pct") of capital on average (gross), against a 30% cap.

#claim("main_negative")
#exhibit("equity",
  [Net of costs the book ends slightly below where it started; the Gatev baseline ends at #m("benchmarks.gatev.total_return_pct")],
  sub: [Cumulative net return, underwater drawdown and gross exposure; main backtest, daily, #m("paper.period_start_month") – #m("paper.period_end_month")],
  notes: [#if not flag("random_band") [No random-pair band: the v32 export holds the #m("benchmarks.random_control.n_draws") draws' Sharpe ratios (@ex-randomnull) but not their daily paths. Exports from v33 on carry each day's 5th–95th percentile of the draws' cumulative returns, and the band is then drawn here. The draws' mean path is not a substitute, because averaging #m("benchmarks.random_control.n_draws") portfolios removes most of their noise.] else [The band is each day's 5th–95th percentile of the random-pair draws' cumulative returns.] Gross exposure is rebuilt from the trades and reproduces the run's average and maximum (#m("study.dev.facts.exposure_max_pct")).],
  source: [#path("paper.results_path") (run of commit #m("paper.commit_short")); #cite(<gatev2006>, form: "prose") distance method with the same _t_ + 1 fills and cost model.])

The walk-forward tells the same story out of sample (@ex-walkforward). #m("oos.windows_positive") of #m("oos.windows") windows made money and the stitched path ends at #m("oos.total_return_pct")\; the mean window return is #m("oos.avg_window_return_pct") with a 95% interval from #m("significance.oos_windows.ci_lo_pct") to #m("significance.oos_windows.ci_hi_pct"). Two features of the main backtest deserve care. One month carries the result (@ex-monthly), and the half-year Sharpe ratios that look significant all contain that month (@ex-rolling); reading either as a regime the strategy could exploit would be fitting a rule to the test period.

#exhibit("walkforward",
  [Out of sample, #m("oos.windows_positive") of #m("oos.windows") walk-forward windows made money; the stitched path ends at #m("oos.total_return_pct")],
  sub: [Net return per 63-day test window (bars, labelled with trade counts) and the compounded path at window ends; #m("paper.oos_start_month") – #m("paper.oos_end_month")],
  notes: [The windows are calendar slices of one continuous simulation with the ranker refit per window; positions carry across window boundaries. #m("oos.windows_no_trades") windows made no trade. #m("oos.windows") windows have little power: mean #m("oos.avg_window_return_pct") per window, 95% CI #m("significance.oos_windows.ci_lo_pct") to #m("significance.oos_windows.ci_hi_pct"), p = #m("significance.oos_windows.p"). #if not flag("wf_daily") [The daily out-of-sample series is exported from v33 on; here the path is shown at window resolution.]],
  source: [#path("paper.run_dir"), `walk_forward_validation.windows`.])

#claim("best_month_exceeds_total") #claim("flat_run_exists")
#exhibit("monthly",
  [One month carries the result: #m("paper.best_month") earned #m("study.dev.facts.best_month_pct"), more than the whole period],
  sub: [Monthly net return, % of capital; the year column compounds the months shown],
  notes: [#m("study.dev.facts.months_positive") of #m("study.dev.facts.months") months were positive. The book was flat from #m("paper.flat_from") to #m("paper.flat_to")\; the regime gate blocked new entries on #m("study.dev.facts.gate_blocked_days") of the #m("study.dev.facts.days") days. This grid is the evaluated period: a rule fitted to it would be data snooping.],
  source: [#path("paper.run_dir"), `monthly_performance`.])

#claim("clearing_windows_contain_best_month")
#exhibit("rolling",
  [Half-year Sharpe ratios swing between #m("study.dev.facts.rolling_min") and #m("study.dev.facts.rolling_max")\; every window whose band clears zero contains #m("paper.best_month")],
  sub: [Rolling #m("study.dev.rolling_sharpe.window")-day Sharpe ratio, annualised, with a ±1.96 standard-error band; main backtest],
  notes: [SE = √((1 + SR²/2)/_n_) per day with _n_ = #m("study.dev.rolling_sharpe.window"), annualised #cite(<lo2002>), assuming IID returns. #m("study.dev.facts.rolling_clear_zero") of #m("study.dev.facts.rolling_windows") overlapping windows clear zero, all ending between #m("paper.clear_first_end_long") and #m("paper.clear_last_end_long")\; overlapping windows are not independent tests. Windows in which the book was flat throughout have no Sharpe ratio.],
  source: [#path("paper.run_dir") daily net returns; computed by `scripts/build_site_data.py`.])

// ══════════════════════════════════════════════════════════════════════════════════════
= Inference <sec-inference>
// ══════════════════════════════════════════════════════════════════════════════════════

#claim("every_interval_spans_zero") #claim("rejects_sharpe_1") #claim("cannot_reject_sharpe_half")
Is the result significant? No: every interval in @ex-forest contains zero. The more useful question is what the data can rule out. With #m("study.dev.facts.main_days") daily observations the standard error of the annualised Sharpe ratio is #m("study.dev.facts.sharpe_se"), so the one-sided 95% upper bound is #m("study.dev.facts.sharpe_ucb"), and a true Sharpe ratio would need to be about #m("study.dev.facts.sharpe_mde") to be detected with 80% probability. A Sharpe ratio of 1.0 is rejected (p = #m("study.dev.facts.p_sr_ge_1")); 0.5 is not (p = #m("study.dev.facts.p_sr_ge_0_5")). A strategy whose true Sharpe ratio is 0.5 needs about #m("study.dev.facts.min_trl_years_0_5") years of daily data to show as significant; at 1.0, about #m("study.dev.facts.min_trl_years_1") years.

#claim("ucb_about_one")
#exhibit("forest",
  [Every Sharpe interval spans zero; the data exclude only Sharpe ratios above about 1],
  sub: [Annualised Sharpe ratio with its 95% interval; development period, net of costs unless stated],
  notes: [Intervals are circular block bootstraps (Politis–White block length, #m("paper.boot_resamples") resamples) for single series and Ledoit–Wolf studentized bootstraps for differences; the random-pair row shows the 5th–95th percentile spread of #m("benchmarks.random_control.n_draws") draws, not a confidence interval. The Gatev interval is computed by the site builder with the run's own bootstrap. Power and the upper bound assume IID returns with the sample's skew and kurtosis. Gross-of-cost, Avellaneda–Lee and holdout rows fill when their runs exist.],
  source: [#path("paper.run_dir"), `significance` and `benchmarks`; `scripts/build_site_data.py`.])

== Power and the one-sided upper bound

A test that cannot reject zero is evidence of no edge only to the extent that it could have detected one. The power figures use the asymptotic variance of the Sharpe estimator for non-normal IID returns with the sample's skewness (#m("study.dev.facts.skew")) and non-excess kurtosis (#m("study.dev.facts.kurtosis")) @bailey2012. At this sample length the critical Sharpe ratio of a one-sided 5% test is #m("study.dev.facts.sharpe_critical") and the Sharpe ratio detected with 80% probability is #m("study.dev.facts.sharpe_mde")\; the one-sided 95% upper bound, #m("study.dev.facts.sharpe_ucb"), is the largest Sharpe ratio the data do not reject (@tab-alternatives). The sample therefore excludes a strategy of Sharpe 1.5 or 2, is borderline at 1, and says nothing useful about 0.5.

#claim("mde_above_ucb") #claim("borderline_at_sharpe_1") #claim("rejects_sharpe_1_5_and_2")
#tablefig("alternatives", [What the development sample rules out],
  booktab(columns: (30%, 35%, 35%), align: (right, right, right),
    header: ([True annual Sharpe ratio _x_], [p-value of H#sub[0]: SR ≥ _x_], [Years of data for SR = _x_ to be significant]),
    rows: T("alternatives")),
  notes: [p-values are one-sided, evaluated at the observed Sharpe ratio. The track-record length is the minimum track record length of #cite(<bailey2012>, form: "prose") at the one-sided 5% level.],
  source: [`assets/study.json`, `dev.power`.])

== Baselines

The Gatev distance method, run on the same universe and period with the same _t_ + 1 fills and cost model, returned #m("benchmarks.gatev.total_return_pct") (Sharpe #m("benchmarks.gatev.sharpe")\; 95% interval #m("study.dev.facts.gatev_lo") to #m("study.dev.facts.gatev_hi")). The difference in Sharpe ratios is #m("benchmarks.sharpe_diff_vs_gatev.diff") in the main backtest (Ledoit–Wolf p = #m("benchmarks.sharpe_diff_vs_gatev.p")) and #m("paper.diff_oos") out of sample (p = #m("paper.diff_oos_p")). Against #m("benchmarks.random_control.n_draws") portfolios of random pairs the strategy sits at the #m("paper.percentile_ordinal") percentile (@ex-randomnull).

#tablefig("significance", [Significance tests, v32 study run of #m("paper.run_date_long")],
  booktab(columns: (52%, 24%, 24%), align: (left, right, right),
    header: ([Test], [Main backtest], [Walk-forward OOS (daily)]),
    rows: T("significance")),
  notes: [Newey–West t and p test a zero mean of daily net returns. The deflated Sharpe ratio is the probability that the Sharpe ratio exceeds the expected maximum of the stated number of null trials.])

#exhibit("randomnull",
  [The strategy sits at the #m("paper.percentile_ordinal") percentile of #m("benchmarks.random_control.n_draws") random-pair portfolios],
  sub: [Annualised Sharpe ratio of random 20-pair draws traded with the distance rule under the same costs; main period],
  notes: [Median draw #m("benchmarks.random_control.median_sharpe"), 5th–95th percentile #m("benchmarks.random_control.p5_sharpe") to #m("benchmarks.random_control.p95_sharpe"). The random control trades random pairs with the Gatev distance rule, not this strategy's engine, so it is a baseline for the distance method and only a rough one for this strategy; a control on the strategy's own engine is planned.],
  source: [#path("paper.run_dir"), `benchmarks.random_control.draw_sharpes`.])

== Deflated Sharpe and data snooping <sec-snooping>

#claim("dsr_low")
Every design choice in this study was made on #m("paper.data_years") data over #m("paper.versions_count") versions. The deflated Sharpe ratio @bailey2014 asks whether the observed Sharpe ratio beats the best of _N_ independent null trials; the run reports _N_ = #m("study.dev.facts.dsr_trials"), a lower bound on the designs tried. At that _N_ the main backtest has a #m("significance.main.dsr_pct") probability of beating chance and the walk-forward #m("significance.oos_daily.dsr_pct") (@ex-dsr). #cite(<harvey2016>, form: "prose") make the same point for the factor literature, arguing that a new factor's t-statistic should clear about 3 rather than 2.

#exhibit("dsr",
  [Deflated for #m("study.dev.facts.dsr_trials") trials, the main backtest's Sharpe ratio has a #m("significance.main.dsr_pct") probability of beating chance#if not flag("snooping") [; the data-snooping tests are pending]],
  sub: [Deflated Sharpe ratio of the main backtest against the number of independent trials _N_ (log scale)],
  notes: [_N_ = 1 is the probabilistic Sharpe ratio; the run reports _N_ = #m("study.dev.facts.dsr_trials"), a lower bound on the designs tried over #m("paper.versions_count") versions. The trial Sharpe variance is the null variance of the estimator at this sample length.],
  source: [`pairs_trading.significance.deflated_sharpe_ratio` on #path("paper.run_dir") daily returns.])

_N_ is not known, and the deflated Sharpe ratio is only as good as the guess. The data-snooping tests replace the guess with a declared family. On #m("paper.declared_long"), before any variant ran, the study declared a #m("study.dev.snooping.grid_points")-point grid of the entry, exit and stop thresholds and #m("study.dev.snooping.toggles") design toggles around the v33 design (@tab-variants in the appendix); each variant runs once on the development calendar and the primary design is not re-chosen from the results. The Reality Check of #cite(<white2000>, form: "prose") and the SPA test of #cite(<hansen2005>, form: "prose") ask whether the best variant beats cash; the stepdown of #cite(<romano2005>, form: "prose") identifies which variants do, with familywise error control; the model confidence set of #cite(<hansen2011>, form: "prose") keeps the variants that cannot be told apart from the best; and the probability of backtest overfitting @bailey2017 measures how often the in-sample winner falls below the median out of sample. Resampling uses the stationary bootstrap @politis1994.

#tablefig("snooping", [Data-snooping tests over the declared variant family],
  booktab(columns: (70%, 30%), align: (left, right),
    header: ([Test], [Result]),
    rows: T("snooping").map(r => (r.at(0), if r.at(1) == "pending" { pend[pending (v33 development run)] } else { r.at(1) })))
  , notes: [#if not flag("snooping") [The family was declared on #m("paper.declared_long"), before any variant was run (`results/variant_family/declaration.json`); the tests run on the v33 development calendar.] else [Variant family declared on #m("paper.declared_long") (`results/variant_family/declaration.json`).]])

== Multiple testing in pair selection <sec-multiple>

#claim("excess_cointegration") #claim("bh_survivors_few") #claim("chance_accounts_for_most")
Pair selection is itself a multiple test. Of #m("fdr.pairs_tested") pairs tested, #m("fdr.significant_raw_p05") were "cointegrated" at p < 0.05, against #m("study.dev.funnel.pairs.1.expected") expected by chance alone. Only #m("fdr.survive_bh_fdr_q05") survives a Benjamini--Hochberg correction at q = 0.05 @benjamini1995: the excess is spread thinly over many weak relationships. Selection kept #m("fdr.final_selected_pairs") pairs, of which #m("study.dev.facts.pairs_traded") were traded (@ex-funnel).

#exhibit("funnel",
  [From #m("fdr.pairs_tested") candidate pairs to #m("study.dev.facts.pairs_traded") traded; chance alone accounts for most "cointegrated" pairs],
  sub: [Pairs at each selection stage, formation data to #m("paper.formation_cutoff_long")],
  notes: [Pairs share legs, so the tests are dependent; Benjamini–Hochberg is a diagnostic here, not a filter. Selection also requires a half-life of 4–25 days and a quality score.],
  source: [#path("paper.run_dir"), `fdr_diagnostic` and `all_trades`.])

#exhibit("pvalues",
  [Engle–Granger p-values against the uniform null],
  sub: [Histogram, 20 bins, with the height expected if no pair were cointegrated],
  pending: [The v32 export keeps the counts above but not the p-values themselves.])

// ══════════════════════════════════════════════════════════════════════════════════════
= Where the edge goes <sec-anatomy>
// ══════════════════════════════════════════════════════════════════════════════════════

#claim("gross_pnl_below_costs") #claim("break_even_below_one") #claim("stops_lost_more_than_targets_earned")
There is no gross edge for costs to remove. Before costs the #m("main.trades") trades earned \$#m("study.dev.facts.gross_usd_k")k; modelled costs were \$#m("study.dev.facts.cost_usd_k")k, #m("study.dev.facts.impact_share_pct") of it market impact (@ex-waterfall). Costs would have to fall to #m("study.dev.facts.break_even_x") their modelled level for net P&L to break even, and the gross return per trade is itself indistinguishable from zero (t = #m("study.dev.facts.gross_t")). The trades show the mechanism: the #m("main.exit_reasons.stop") stop-loss exits lost \$#m("study.dev.facts.stop_loss_usd_m")M, more than the #m("main.exit_reasons.target") target exits earned (\$#m("study.dev.facts.target_gain_usd_m")M; @ex-anatomy).

#claim("impact_largest_cost")
#exhibit("waterfall",
  [Gross P&L, itself not significant, does not cover modelled costs; market impact is the largest item],
  sub: [Implementation shortfall of the main backtest: gross P&L to net P&L by cost component, \$ thousands],
  notes: [The bars close exactly on the change in the book's value. Gross is #m("study.dev.facts.gross_bp_capital") bp of starting capital, costs #m("study.dev.facts.cost_bp_capital") bp, net #m("study.dev.facts.net_bp_capital") bp; per round trip, costs are #m("study.dev.facts.cost_bp_notional") bp of traded gross notional. The signal-close paper P&L and the cost of the one-day delay are separated from v33 on.],
  source: [#path("paper.run_dir"), `all_trades[].cost_breakdown_dollars` and the final portfolio value.])

#claim("long_gained_short_lost") #claim("short_loss_near_long_gain") #claim("sides_carry_their_sign")
#exhibit("anatomy",
  [Stops lost more than targets earned, and short-spread trades lost about what long-spread trades made],
  sub: [Net P&L of the #m("main.trades") trades by exit reason, side of the spread and |_z_| at entry, \$ millions],
  notes: [Long-spread trades made \$#m("study.dev.facts.long_gain_usd_m")M and short-spread trades lost \$#m("study.dev.facts.short_loss_usd_m")M, consistent with the net market exposure that hedge ratios below one leave in each trade (@sec-risk). Win rate #m("main.win_rate_pct") (#m("study.dev.facts.wins") of #m("study.dev.facts.trades")\; 95% interval #m("study.dev.facts.win_lo_pct")–#m("study.dev.facts.win_hi_pct")). The |_z_| buckets describe the past and are not a selection rule: a higher entry threshold read off this panel would be fitted to the test period. Buckets use the exported z-score (three decimals).],
  source: [#path("paper.run_dir"), `all_trades`.])

The anatomy the evidence layer adds from v33 on is pending (@ex-costcurve[Exhibits]–#exnum(<ex-persistence>)): the Sharpe ratio against a multiple of modelled costs, which needs each day's gross and cost split; the race between target and stop exits against a spread with no mean reversion; the decay of the same rule on the same pairs from formation to trading; and whether selected pairs stay cointegrated, the question #cite(<clegg2014>, form: "prose") studies (@tab-literature).

#let mini(id, title, sub, note) = exhibit(id, title, sub: sub, pending: note, float: false, width: 100%)
#float-row(
  mini("costcurve", [Sharpe ratio against a multiple of modelled costs], [0× to 2× costs, with the break-even multiple marked],
    [Needs each day's gross and cost split, which the v32 export does not separate. On trade sums the break-even multiple is #m("study.dev.facts.break_even_x").]),
  mini("exitrace", [Exit race: targets against stops, and against a spread with no mean reversion], [Observed exits and the count expected under the null],
    [Fills from the run's `anatomy.json` (`exit_race`).]),
)
#float-row(
  mini("decay", [In-sample to out-of-sample decay of the same rule on the same pairs], [Gross bp per trade, formation period against the trading period],
    [Fills from the run's `anatomy.json` (`decay`).]),
  mini("persistence", [Do selected pairs stay cointegrated?], [Share still cointegrated in later windows, against the 5% chance rate],
    [Fills from the run's `anatomy.json` (`persistence`).]),
)

// ══════════════════════════════════════════════════════════════════════════════════════
= Execution and costs <sec-costs>
// ══════════════════════════════════════════════════════════════════════════════════════

Every fill pays its own costs, from the stock's own liquidity on that day, and fills at the next day's close: a signal seen at the close of day _t_ trades at the close of day _t_ + 1. The average trade held #m("study.dev.facts.hold_days") trading days, and its larger leg was #m("study.dev.facts.adv_participation_pct") of that stock's dollar ADV. Annual turnover was #m("main.annual_turnover_x") capital. @tab-costs sets out the cost model against published references and what v33 changes; `docs/EXECUTION_COSTS.md` compares the model with published impact estimates at each participation rate, and `tests/test_cost_model_zoo.py` keeps it inside that band.

#tablefig("costs", [The v32 cost model against published references, and what v33 changes],
  booktab(columns: (13%, 31%, 34%, 22%), align: (left, left, left, left),
    header: ([Component], [v32 model], [Reference], [v33]),
    rows: (
      ([Commission], [\$0.002 per share, \$0.50 minimum per order], [Agency algorithmic rates are commonly quoted at 0.1–0.5¢ per share], [unchanged]),
      ([Half-spread], [Half the typical quoted spread by 20-day dollar ADV: 0.75 bp (≥ \$500M) to 40 bp (< \$5M)], [#cite(<frazzini2018>, form: "prose")], [bucket fit to be checked against measured spreads]),
      ([Market impact], [_Y_ · σ#sub[daily] · √(shares / ADV), _Y_ = 0.3, capped at 50 bp, on entry and exit], [v32 cites #cite(<almgren2005>, form: "prose") for _Y_ ≈ 0.3, which is their permanent-impact estimate; temporary-impact estimates run higher], [_Y_ stressed at 0.3, 0.6 and 1.0]),
      ([Borrow], [General-collateral fee, #m("paper.v32_borrow_bp") bp a year on the short leg], [#cite(<davolio2002>, form: "prose") on general-collateral fees; the v33 fee is a median buy-side indicative fee (`docs/EXECUTION_COSTS.md` gives the source)], [one #m("paper.v33_borrow_pct") fee a year replaces borrow plus financing]),
      ([Financing], [Prime-broker spread, #m("paper.v32_financing_bp") bp a year on the short half of gross], [Overlaps with the borrow fee (a double count)], [folded into the single fee]),
      ([Fill], [Close of _t_ + 1 for entry and exit; legs \$1~:~\$β], [—], [_t_ + 1 open as a declared variant]),
    )),
  source: [`pairs_trading/transaction_costs.py`, `pairs_trading/study_config.py`; `docs/EXECUTION_COSTS.md`.])

#claim("schedules_some_lose_rest_break_even") #claim("best_schedule_cheapest") #claim("no_schedule_significant")
How much the conclusion depends on the cost model is measured, not asserted. Re-costing and re-sizing the main backtest's own trades under #m("paper.schedules_n_word") other cost and sizing schedules (@ex-schedules, @tab-schedules) turns none of them into a significant gain. A stress table, the impact coefficient at 0.3, 0.6 and 1.0 crossed with borrow at #m("paper.v33_borrow_pct") and at a hard-to-borrow fee, is pending the v33 development run, as is a capacity curve (@ex-capacity).

#exhibit("schedules",
  [Re-costed under #m("paper.schedules_n_word") other cost schedules, the same trades lose money in #m("paper.schedules_lose_word") and break even in #m("paper.schedules_even_word")],
  sub: [Cumulative net return, % of capital, when the main backtest's trades are re-sized and re-costed; schedules A–E in order of total cost],
  notes: [Schedules are parameter sets, not descriptions of any firm; @tab-schedules lists each one's commission, half-spread, impact cap, borrow, financing and position size. Returns run from #m("paper.sched_best_ret") (schedule #m("paper.sched_best_id"), the lowest costs and smallest positions) to #m("paper.sched_worst_ret") (schedule #m("paper.sched_worst_id")). The replay keeps the main backtest's signals, entry and exit dates and daily paths, and changes sizes and costs; @tab-schedules lists the trades each schedule replays.],
  source: [#path("paper.run_dir", suffix: "/fund_type_comparison.json").])

#tablefig("schedules", [Cost schedules A–E: parameters and results of the replay],
  booktab(columns: (6%, 8%, 8%, 7%, 7%, 8%, 8%, 8%, 7%, 8%, 8%, 7%, 6%), align: (left,) + (right,) * 12, size: 7pt,
    header: ([], [Comm.], [Spread], [Impact cap], [Borrow], [Financing], [Position], [Return], [Sharpe], [Max DD], [Costs], [Peak gross], [Trades]),
    rows: T("schedules")),
  notes: [Commission, half-spread and impact cap in bp; borrow and financing in % a year; position range in % of equity; return, maximum drawdown (Max DD) and total costs in % of capital; peak gross exposure as a multiple of capital; trades replayed.],
  source: [#path("paper.run_dir", suffix: "/fund_type_comparison.json")\; returns, Sharpe ratios and drawdowns as in `headline_metrics.json`.])

#exhibit("capacity",
  [Capacity: impact cost against book size for a stated gross edge],
  sub: [Net bp per trade as notional scales],
  pending: [A break-even size computed on an insignificant gross edge would suggest an edge that has not been shown, so the curve is drawn for a stated hypothetical edge.],
  )

// ══════════════════════════════════════════════════════════════════════════════════════
= Risk and factor attribution <sec-risk>
// ══════════════════════════════════════════════════════════════════════════════════════

#claim("beta_small") #claim("beta_oos_significant") #claim("beta_main_not_significant") #claim("alpha_negative") #claim("alpha_not_significant") #claim("most_hedge_ratios_below_one") #claim("multi_factor_pending")
Market exposure is small but not zero. Against an equal-weight sector-ETF proxy the main backtest's beta is #m("study.dev.facts.beta_main") (t = #m("study.dev.facts.beta_main_t")) and the walk-forward's #m("study.dev.facts.beta_oos") (t = #m("study.dev.facts.beta_oos_t")) (@ex-factors). The hedge ratio was below one in #m("paper.beta_below_one") of #m("main.trades") trades, and with legs of \$1 and \$β such a trade is not dollar-neutral: #m("paper.long_net_long") of #m("paper.long_trades") long-spread trades were net long and #m("paper.short_net_short") of #m("paper.short_trades") short-spread trades net short. Annualised alpha is #m("study.dev.facts.alpha_main_pct") in the main backtest (t = #m("study.dev.factors.alpha.0.t")) and #m("study.dev.facts.alpha_oos_pct") out of sample (t = #m("study.dev.factors.alpha.1.t")). The multi-factor attribution, on the five factors of #cite(<fama2015>, form: "prose"), momentum @carhart1997 and short- and long-term reversal with Newey--West errors, arrives with v33.

#claim("kurtosis_fat")
#float-row(
  exhibit("factors",
    [The only loading measured so far is a small market beta, significant out of sample],
    sub: [Beta to the sector-ETF market proxy with 95% interval (Newey–West)],
    notes: [Proxy: #m("paper.proxy"). Factor rows for the five factors, momentum and reversal fill when the v33 export carries them.],
    source: [#path("paper.run_dir"), `factor_attribution`.], float: false),
  exhibit("distribution",
    [Daily returns are fat-tailed (kurtosis #m("study.dev.facts.kurtosis")) with a spike at zero from flat days],
    sub: [Distribution of daily net returns, bp of capital; main backtest],
    notes: [Skew #m("study.dev.facts.skew")\; kurtosis is non-excess (3 for a normal distribution). Fat tails widen the Sharpe ratio's standard error, which the power figures in @sec-inference account for.],
    source: [#path("paper.run_dir") daily net returns.], float: false),
)

// ══════════════════════════════════════════════════════════════════════════════════════
= A second strategy family: residual reversion <sec-residual>
// ══════════════════════════════════════════════════════════════════════════════════════

#claim("residual_pending")
A null on one rule says little about the idea. #cite(<avellaneda2010>, form: "prose") trade each stock's residual against its sector ETF when that residual, modelled as a mean-reverting process, is stretched; many small concurrent bets give the test far more power than #m("main.trades") pair trades. The parameters are taken from the paper unchanged: a 60-day regression on the sector ETF, an AR(1) fit of the cumulative residual, trades only when mean reversion is faster than 30 days, entry at |_s_| > 1.25, exits at −0.50 (long) and 0.75 (short), next-day fills and the same cost model. The arm runs on the development calendar with the v33 code and then, once, on the holdout (@sec-holdout). #if flag("residual") [On the development calendar it made #m("paper.residual.trades") trades and returned #m("paper.residual.ret_pct"), a net Sharpe ratio of #m("paper.residual.sharpe") (95% interval #m("paper.residual.lo") to #m("paper.residual.hi"); Newey–West p = #m("paper.residual.p")).] else [It has not yet run on the development calendar, so @ex-residual is pending.]

#exhibit("residual",
  [Avellaneda–Lee residual reversion against the pairs strategy, development period],
  sub: [Net Sharpe ratio with 95% interval, same universe and costs],
  pending: [Fills from `results/residual_dev/` when the arm has run on the development calendar.],
  float: false)

// ══════════════════════════════════════════════════════════════════════════════════════
= The pre-registered 2026 test <sec-holdout>
// ══════════════════════════════════════════════════════════════════════════════════════

#claim("holdout_sealed")
Every design choice in this study was made on #m("paper.data_years") data over #m("paper.versions_count") versions, so the development period cannot test those choices. The decisive test therefore runs on data none of them has seen: trading days from #m("paper.holdout_start_long"). No 2026 stock price has been fetched. The protocol is committed first; each arm then runs once, and its result is published whatever it is. At the date of this note the pre-registration (`docs/PREREGISTRATION.md`) is #m("paper.prereg_status")\; @tab-hypotheses gives the hypotheses it fixes.

#tablefig("hypotheses", [Hypotheses of the pre-registration, filed before any 2026 price is fetched],
  booktab(columns: (7%, 37%, 22%, 11%, 11%, 12%), align: (left, left, left, right, right, left),
    header: ([], [Arm], [Hypothesis], [Sharpe], [p (Holm)], [Decision]),
    rows: T("hypotheses").map(r => r.map(c => if c == "sealed" { pend[sealed] } else { c }))),
  notes: [Test: one-sided Newey–West t on daily net returns, Holm-adjusted across the three at 5%.])

For each arm _k_ the null hypothesis is that the mean daily net return over the holdout is at most zero, against the alternative that it is positive. The test is the one-sided Newey--West t-test on the daily net return series; the three p-values are adjusted with the step-down procedure of #cite(<holm1979>, form: "prose") at a familywise level of 5%, and an arm shows an edge out of sample only if its adjusted p-value is below 0.05. Whatever the outcome, each arm reports its net and gross return, its Sharpe ratio with standard error, the probabilistic Sharpe ratio, the block-bootstrap interval, the one-sided upper bound, trades and exposure, and, for the pairs arms, the Ledoit--Wolf difference against the Gatev method and the random-pair percentile on the same holdout (`scripts/evaluate_holdout.py`).

*Power, stated in advance.* About nine months of data can detect only a large Sharpe ratio. With returns shaped like the development period's (skewness #m("paper.holdout_power.skew"), non-excess kurtosis #m("paper.holdout_power.kurtosis"), lag-1 autocorrelation #m("paper.holdout_power.rho")), a one-sided 5% test with 80% power detects an annualised Sharpe ratio of about #m("paper.holdout_power.mde_189") in nine months and #m("paper.holdout_power.mde_252") in a full year (@tab-holdout-power). The holdout is therefore a falsification check, not a proof of an edge: it can reject a large edge but cannot confirm a small one, and not rejecting the null is not evidence that the edge is zero, which is why each arm's upper confidence bound is reported. Running v32 alone first would spend the holdout, so v33 is frozen before any 2026 price is fetched, and all arms run once.

#tablefig("holdout-power", [Smallest annual Sharpe ratio the holdout detects with 80% power (one-sided 5% test)],
  booktab(columns: (34%, 33%, 33%), align: (right, right, right),
    header: ([Holdout length, trading days], [Returns shaped like the development period's], [IID normal returns]),
    rows: T("holdout_power")),
  notes: [About six, nine and twelve months. The development shape uses the asymptotic Sharpe variance for non-normal returns with lag-1 autocorrelation (`pairs_trading/power.py`); computed from development returns only.],
  source: [`scripts/build_paper.py` on #path("paper.run_dir") daily net returns.])

#exhibit("holdout",
  [Cumulative net return on the 2026 holdout, by arm],
  sub: [Daily, from #m("paper.holdout_start_long")\; v33 pairs, Avellaneda–Lee and v32 frozen, same costs],
  pending: [The pre-registration (`docs/PREREGISTRATION.md`) is committed before any 2026 price is fetched; this exhibit fills from `results/holdout2026/` after the single run.],
  float: false)

// ══════════════════════════════════════════════════════════════════════════════════════
= Threats to validity <sec-threats>
// ══════════════════════════════════════════════════════════════════════════════════════

Each limitation, which way it biases the result, how large it is, and what addresses it (@tab-threats). Biases that flatter the strategy make the null more convincing, not less.

#let up = text(font: sans-md, fill: col("neg"))[↑ flatters]
#let down = text(font: sans-md, fill: col("pos"))[↓ penalises]
#let either(body) = text(font: sans-md, fill: ink2)[↕ #body]
#[
#show figure: set block(breakable: true)
#tablefig("threats", [Threats to validity of the v32 study run and the 2026 test],
  booktab(columns: (25%, 13%, 31%, 31%), align: (left, left, left, left), size: 7pt, inset-y: 2.9pt,
    header: ([Threat], [Direction of bias], [Size], [Mitigation]),
    rows: (
      ([Survivorship, and an approximate index], up, [Unmeasured: the universe is today's #m("paper.names_file") largest stocks, back-filled, so pairs broken by failures and delistings are missing], [v33: point-in-time membership from IWV holdings in SEC N-PORT filings, with the coverage gap at each formation reported (@ex-universe)]),
      ([Design choices were made on the same data], up, [#m("paper.versions_count") versions on #m("paper.data_years")\; deflated Sharpe with #m("study.dev.facts.dsr_trials") trials is a lower bound], [Pre-registered 2026 holdout; declared variant family with SPA, stepdown, MCS and PBO]),
      ([Re-selection can drop pairs but not add them], down, [The pool can only shrink after #m("paper.formation_year")], [v33: full re-formation every #m("paper.v33_reselect_every") trading days on the trailing #m("paper.v33_formation_years") years]),
      ([Borrow is general-collateral for every name], up, [Borrow was \$#m("study.dev.facts.borrow_usd_k")k of \$#m("study.dev.facts.cost_usd_k")k costs; specials and recalls are not modelled], [v33: #m("paper.v33_borrow_pct") buy-side median fee; hard-to-borrow stress]),
      ([Fills are close-to-close], either[either way], [Larger leg #m("study.dev.facts.adv_participation_pct") of ADV on average; no auction or queue model], [_t_ + 1 open variant; closing-auction cost model planned]),
      ([Ranker features include pair statistics estimated on the formation window], up, [Small: out-of-sample AUC #m("ranker.oos_auc"), no skill to inflate], [v33: the ranker becomes an ablation arm only]),
      ([The "transformer" ranker sees one 30-feature vector], either[none on P&L], [A sequence of length one: functionally a residual MLP], [v33: L2 logistic and gradient-boosted trees]),
      ([Sector features are coarse], down, [Pairs are not restricted to one industry, so many are economically unrelated], [v33: pairs within one Fama–French 49 industry]),
      ([The 126-day re-selection check has little power], down, [It removes healthy pairs and keeps noise at similar rates (see the README)], [v33: replaced by full re-formation]),
      ([The price cache used through v31 was built with a full-sample penny-stock screen], either[none for v32], [The v32 run used a freshly fetched v32 cache], [Fetch manifest and coverage check in every run]),
      (["Point-in-time" prices undo splits, not dividends], either[small, either way], [Early prices are understated by later dividends in the \$5 price and dollar-volume screens], [v33 keeps the raw close]),
      ([Splits after the data window cannot be undone], either[small, either way], [The vendor back-adjusts history for every split up to the fetch date but reports split events only inside the requested window, so names that split after it are mis-screened; returns, z-scores and hedge ratios are unaffected (a constant factor)], [Measured once the holdout opens and those split events can be fetched; disclosed]),
      ([The regime gate was tuned on windows now inside the test period], either[either way], [New entries blocked on #m("study.dev.facts.gate_blocked_days") of #m("study.dev.facts.days") days], [v33: off by default; counted as a declared variant]),
      ([Hedge ratios below one leave market exposure], either[adds beta], [Beta t = #m("study.dev.facts.beta_oos_t") out of sample (@ex-factors)], [v33: multi-factor attribution]),
      ([The main backtest and the walk-forward overlap], up, [#m("study.dev.facts.oos_overlap_days") of #m("study.dev.facts.main_days") days in common, same pair pool], [The holdout is the independent test]),
      ([The random-pair control trades a different rule], either[weakens the comparison], [Random pairs run through the Gatev rule, not this engine], [A control on the strategy's own engine is planned]),
      ([The v32 arm's universe in the holdout is membership as of #m("paper.universe_as_of_long")], up, [Look-ahead in membership for the frozen v32 arm (H3) during 2026], [Disclosed in the pre-registration; the v33 and Avellaneda–Lee arms use point-in-time membership]),
      ([Factor files from the Kenneth French library extend into 2026], either[none on trading], [No strategy reads factor data], [Every run truncates them at its own calendar's last date; no development export holds a 2026 factor return]),
      ([Renamed securities with a new CUSIP look like delistings], either[overstates the gap], [Counted in the measured survivorship gap, which is therefore conservative], [The data review remaps through N-PORT tickers and issuer successions]),
    )))
]

// ══════════════════════════════════════════════════════════════════════════════════════
= Reproducibility <sec-repro>
// ══════════════════════════════════════════════════════════════════════════════════════

Every number in this note is formatted by `scripts/build_paper.py` from `assets/study.json`, the file the research-note site's charts and checked numbers come from, and from the headline JSON that file was built from; the site's numbers are checked against the same JSON by `scripts/check_published_numbers.py`. A later price fetch will not match the cached data bit for bit, because vendors revise history; the run manifest (@tab-manifest) pins what was used, and the sha256 of every committed source the note reads is listed in @tab-hashes.

#block(width: 100%, fill: sunk, inset: (x: 9pt, y: 8pt), radius: 2pt, breakable: false,
  raw(block: true, lang: "bash", "# the study (prices are fetched from Yahoo's chart API and cached)
pip install -r requirements.txt
python scripts/build_universe.py
python -m pairs_trading.main            # writes outputs/

# publish a run: copy outputs/ to results/<run>/, then
python scripts/build_site_data.py --dev results/" + D.meta.headline.split("/").at(1) + "
python scripts/check_published_numbers.py --json " + D.meta.headline + "

# this paper (needs the optional typst package: pip install -e \".[paper]\")
python scripts/build_paper.py           # data, figures and PDF
python scripts/build_paper.py --check   # exit 1 if any of them is stale"))

#tablefig("manifest", float: true, [Run manifest],
  booktab(columns: (18%, 82%), align: (left, left), header: ([Item], [Value]),
    rows: T("manifest").map(r => (r.at(0), text(font: mono, size: 6.6pt, r.at(1)))))
  )

#tablefig("hashes", float: true, [Committed sources read by this note],
  booktab(columns: (44%, 56%), align: (left, left), header: ([File], [sha256]),
    rows: T("sources").map(r => (text(font: mono, size: 6.4pt, r.at(0)), text(font: mono, size: 6.4pt, r.at(1))))),
  notes: [The PDF is compiled with a fixed timestamp, the note's date, so a rebuild of unchanged inputs is byte-identical; `paper/build/manifest.json` records the sha256 of every compile input and of the PDF.])

#heading(numbering: none)[Disclosures]

Hypothetical, backtested results on \$#m("study.dev.facts.capital_musd")M of notional capital, not achieved by any account. Returns are net of the modelled costs described in @sec-costs unless labelled gross, earn no interest on cash, and are shown beside baselines run under the same costs. Hypothetical results have inherent limitations, including those listed in @sec-threats. This is a research project: not investment advice, not an offer of any product, and no claim of deployable performance. The cost schedules are parameter sets, not descriptions of any firm. Code under the MIT licence; IBM Plex typefaces under the SIL Open Font License 1.1.

#heading(numbering: none)[References]
#{
  set text(size: 8.4pt)
  set par(justify: false, leading: 0.5em, spacing: 0.6em, hanging-indent: 1.2em)
  bibliography("references.bib", title: none, style: "chicago-author-date")
}

// ══════════════════════════════════════════════════════════════════════════════════════
// Appendix
// ══════════════════════════════════════════════════════════════════════════════════════
#pagebreak(weak: true)
#counter(heading).update(0)
#set heading(numbering: (..n) => if n.pos().len() > 1 { "A." + str(n.pos().at(1)) })
#heading(numbering: none)[Appendix]

== Specification of the v32 study run

#tablefig("spec", [Specification of the v32 study run],
  booktab(columns: (16%, 84%), align: (left, left),
    header: ([Stage], [Rule]),
    rows: (
      ([Universe], [The #m("paper.names_file") largest US common stocks by market cap on #m("paper.universe_as_of_long") (the Russell 3000 rule applied to the Nasdaq screener), #m("study.dev.facts.coverage_pct") fetched; daily prices #m("paper.data_years")\; screens on point-in-time (split-unadjusted) price and dollar volume; the #m("paper.universe_top") most liquid enter the pair search.]),
      ([Selection], [Positive return correlation ≥ 0.25; two-direction Engle–Granger p < 0.05 (Bonferroni across directions); half-life 4–25 days on the cointegrating spread; quality score; re-selection every #m("paper.v32_reselect_every") trading days (re-test only; pairs can drop out, not enter).]),
      ([Spread], [Two-state Kalman filter (slope and intercept) on log prices centred on their burn-in means, so β is a hedge ratio and signals are invariant to vendor back-adjustment.]),
      ([Rule], [One β-locked z-score against its mean and standard deviation over the last 30–60 bars, frozen at the signal. Entry |_z_| ≥ 1.8; target |_z_| ≤ 0.5; stop 1.5 further against; time stop clamp(2.5 × half-life, 10, 25) days. Gates: 20-day correlation ≥ 0.20, β in [0.25, 4], loss cool-off, VIX and sector-dispersion regime scaling.]),
      ([Book], [\$#m("study.dev.facts.capital_musd")M notional; 3–10% of equity per pair; 30% gross cap; at most 8 entries a day; no shared legs; daily mark-to-market; drawdown and daily-loss kill switch.]),
      ([Ranker], [A classifier of P(trade profitable) on 30 features, used only to order same-day candidates; out-of-sample AUC #m("ranker.oos_auc") (#m("ranker.wf_pooled_auc") pooled across walk-forward windows; 0.5 is no skill).]),
      ([Walk-forward], [One continuous simulation on a 252-day train / 63-day test grid; the ranker is refit per window; per-window figures are calendar slices.]),
      ([Evidence], [Probabilistic and deflated Sharpe, Newey–West t, Politis–White block bootstrap, Lo (2002) adjustment, Ledoit–Wolf Sharpe-difference test, PBO; Gatev distance method and random pairs under the same costs and _t_ + 1 fills.]),
    )))

== Design changes in v33

#tablefig("profiles", [The v32 design and the pre-registered v33 design, from `pairs_trading/study_config.py`],
  booktab(columns: (18%, 38%, 44%), align: (left, left, left),
    header: ([Choice], [v32 (run reported here)], [v33 (pre-registered)]),
    rows: T("profiles")),
  notes: [None of the v33 choices was made by its effect on development-period results; the reasons are stated next to each profile setting in the code.])

== The declared variant family

#tablefig("variants", [Variants declared on #m("paper.declared_long") for the data-snooping tests],
  booktab(columns: (26%, 74%), align: (left, left),
    header: ([Variant], [What it changes]),
    rows: T("variants").map(r => (text(font: mono, size: 6.8pt, r.at(0)), r.at(1)))),
  notes: [The threshold grid covers the three hand-set trading thresholds, which were chosen across versions on this same data. Each toggle changes one setting of the v33 design.],
  source: [`results/variant_family/declaration.json`.])

== Walk-forward windows

#tablefig("windows", [Walk-forward windows: calendar slices of one continuous simulation],
  booktab(columns: (8%, 15%, 15%, 15%, 13%, 11%, 10%, 13%), align: (right, left, left, left, right, right, right, right),
    header: ([Window], [Training from], [Test from], [Test to], [Net return], [Sharpe], [Trades], [Ranker AUC]),
    rows: T("windows")),
  notes: [Each window's ranker is trained on the year before its test start. Sharpe ratios of windows without a trade are not defined.],
  source: [#path("paper.run_dir"), `walk_forward_validation.windows`.])

== Version history

#tablefig("history", [Selected versions; `docs/PROGRESS.md` has the full record, deliberately unflattering],
  booktab(columns: (16%, 84%), align: (left, left),
    header: ([Version], [Change]),
    rows: (
      ([v9–v12], [First look-ahead fixes (P&L, pair selection, Kalman β drift).]),
      ([v16–v19], [Kalman spread fixes, β-weighted P&L, PCA residual cointegration, dynamic hold.]),
      ([v24–v26.1], [Ranker trained and wired in (ranking only); controlled ablation; a label bug that had disabled training.]),
      ([v28–v29], [Significance layer and baselines; _t_ + 1 entry fills.]),
      ([v30], [Leakage audit: survivorship confirmed, selection-clean window tagging.]),
      ([v31–v31.1], [Pre-launch audit: inverted stop-loss, same-bar exits, future re-selections in the walk-forward; results withdrawn.]),
      ([v32], [Full audit and rebuild of the engine, Kalman model, accounting, walk-forward, costs, ranker, benchmarks and outputs; synthetic known-answer validation; study re-run: no detectable edge.]),
      ([v33 (in progress)], [Pre-registered design: point-in-time universe, same-industry pairs, full re-formation, regime gate off, one borrow fee, a second strategy family, the evidence layer and the sealed 2026 holdout.]),
    )))
