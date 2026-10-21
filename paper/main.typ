// The study's paper: the research-note site in print.
//
// Every result this file prints comes from build/paper_data.json, written by
// scripts/build_paper.py from assets/study.json (the data the site's charts and checked
// numbers come from) and the headline JSON it was built from. Numbers are placed with
// #m("key"); a number that does not exist yet is null there and prints as "pending" with
// its reason. A result that does not exist yet has no exhibit or table in the body: the
// table of forthcoming results lists it until its run is committed. A sentence whose
// wording depends on the data carries #claim("name"): the compile stops if the data no
// longer support it. Build: python scripts/build_paper.py

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
// Values are never hyphenated, and dates hold together (the builder joins them with
// no-break spaces).
#let pend(reason) = text(style: "italic", fill: ink3)[#reason]
// The metadata marks the null branch for tests/test_build_paper.py (typst query <pending>).
#let m(key) = {
  let v = D.m.at(key)
  if v == none [#pend(D.why.at(key))#metadata(key) <pending>] else { text(hyphenate: false, v) }
}
// Asserts a statement of the surrounding prose against the data; prints nothing.
#let claim(name) = {
  assert(D.claims.at(name), message: "paper/main.typ: claim '" + name + "' is false for this data")
}
#let flag(name) = D.flags.at(name)
#let T(name) = D.tables.at(name)
// Whether an exhibit's data exist; an exhibit without data is listed as forthcoming.
#let has(id) = D.figures.at(id, default: none) != none
// "(Exhibit n)" for an exhibit that is drawn, else a pointer to the forthcoming results.
#let see(id) = if has(id) { ref(label("ex-" + id)) } else [forthcoming, @tab-forthcoming]
#let prereg = flag("preregistered")
// Plain text of a caption, for the exhibit's alternative text.
#let plain(c) = {
  if type(c) == str { c }
  else if c.has("text") { plain(c.text) }
  else if c.has("children") { c.children.map(plain).join() }
  else if c.has("body") { plain(c.body) }
  else if c.has("child") { plain(c.child) }
  else if c == [ ] { " " }
  else { "" }
}

// ── page ──────────────────────────────────────────────────────────────────────────────
// Running text sits on a measure of about 75 characters; exhibits, tables, the summary
// and the running heads span the full width, with one left edge for everything.
#let measure = D.layout.measure_mm * 1mm
#let full = D.layout.exhibit_width_mm * 1mm
#let margin-l = (210mm - full) / 2
#let wide(body) = block(width: full, body)
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
  margin: (left: margin-l, right: 210mm - margin-l - measure, top: 25mm, bottom: 22mm),
  header: context {
    if here().page() > 1 {
      set text(font: sans, size: 7pt, fill: ink3)
      wide({
        grid(columns: (1fr, auto), short-title, [Research note · #m("paper.paper_date_long")])
        v(-5pt)
        line(length: 100%, stroke: 0.4pt + rule)
      })
    }
  },
  footer: context {
    set text(font: sans, size: 7pt, fill: ink3)
    wide(grid(columns: (1fr, auto),
      [Hypothetical backtest. Not investment advice.],
      [#counter(page).display("1") / #counter(page).final().first()]))
  },
)
#set text(font: serif, size: 10.4pt, fill: ink, lang: "en", region: "gb",
  number-type: "lining", number-width: "tabular", hyphenate: true)
#set par(justify: true, leading: 0.72em, spacing: 1.05em)
#show strong: set text(font: serif-sb, weight: "regular")
#show link: set text(fill: accent)
#show raw: set text(font: mono, size: 1.08em)
#show raw.where(block: false): box
// Plex Serif for upright letters and digits ("log", subscripts), the math font for the
// italic variables, operators and layout
#show math.equation: set text(font: ((name: serif, covers: regex("[A-Za-z0-9]")), "New Computer Modern Math"))
#set list(indent: 0.4em, body-indent: 0.6em, marker: text(fill: ink3)[–])
#set enum(indent: 0.4em, body-indent: 0.6em)
#show ref: set text(fill: ink)
#show cite: set text(fill: ink)

// headings: numbered sections, serif, number in the accent colour
#set heading(numbering: "1.1")
#show heading.where(level: 1): it => {
  set par(justify: false)
  set text(hyphenate: false)
  block(above: 2em, below: 0.9em, sticky: true, {
    set text(font: serif-sb, size: 13.5pt, weight: "regular")
    if it.numbering != none {
      box(width: 10mm, text(font: sans-sb, size: 11pt, fill: accent, counter(heading).display(it.numbering)))
    }
    it.body
  })
}
#show heading.where(level: 2): it => {
  set par(justify: false)
  set text(hyphenate: false)
  block(above: 1.45em, below: 0.7em, sticky: true, {
    set text(font: serif-sb, size: 10.8pt, weight: "regular")
    if it.numbering != none {
      box(width: 10mm, text(font: sans-sb, size: 9.2pt, fill: accent, counter(heading).display(it.numbering)))
    }
    it.body
  })
}

// ── exhibits and tables ───────────────────────────────────────────────────────────────
#set figure(gap: 5pt)
#set place(clearance: 1.6em)
#show figure: set block(breakable: false)
#show figure: set align(left)
#show figure.where(kind: "exhibit"): set figure.caption(position: top)
#show figure.where(kind: table): set figure.caption(position: top)
#show figure.caption: it => {
  set par(justify: false, leading: 0.5em)
  set text(hyphenate: false)
  set align(left)
  block(width: 100%, below: 3pt, {
    text(font: sans-sb, size: 6.8pt, fill: accent, tracking: 0.07em,
      upper(it.supplement) + [ ] + context it.counter.display(it.numbering))
    linebreak()
    text(font: sans-sb, size: 9pt, fill: ink, it.body)
  })
}
// Notes and Source lines: grey sans, ragged right, no hyphenation; references and
// citations keep the grey of the text around them.
#let foot(notes, source) = {
  set text(font: sans, size: 7pt, fill: ink2, hyphenate: false)
  set par(justify: false, leading: 0.5em, spacing: 0.45em)
  show link: set text(fill: ink2)
  show ref: set text(fill: ink2)
  show cite: set text(fill: ink2)
  if notes != none { block(above: 6pt)[#text(font: sans-sb, fill: ink)[Notes] #h(3pt) #notes] }
  if source != none { block(above: 3pt)[#text(font: sans-sb, fill: ink)[Source] #h(3pt) #source] }
}
// The figure of an exhibit: label and takeaway title above, subtitle, the chart, notes
// and source below.
#let exhibit-figure(id, title, sub: none, notes: none, source: none) = {
  let body = {
    set align(left)
    set text(font: sans, size: 7.4pt, fill: ink2, hyphenate: false)
    set par(justify: false, leading: 0.5em)
    if sub != none { block(below: 5pt, text(size: 7.6pt, sub)) }
    image(D.figures.at(id), width: 100%, alt: plain(title))
    foot(notes, source)
  }
  [#figure(body, kind: "exhibit", supplement: [Exhibit], caption: title) #label("ex-" + id)]
}
// An exhibit at full width, floated to the top of a page (or pinned with placement:
// none): text then runs on below it, and a sentence is never split by two floats. An exhibit without data prints nothing: it is listed as forthcoming.
#let exhibit(id, title, sub: none, notes: none, source: none, placement: top) = {
  if not has(id) { return }
  let fig = wide(exhibit-figure(id, title, sub: sub, notes: notes, source: source))
  if placement == none { block(above: 1.4em, below: 1.4em, fig) } else { place(placement, float: true, block(width: 100%, fig)) }
}
// Two exhibits side by side, floated together.
#let exhibit-pair(a, b, placement: top) = {
  let cells = (a, b).filter(e => has(e.at(0)))
  if cells.len() == 0 { return }
  let figs = cells.map(e => exhibit-figure(e.at(0), e.at(1), ..e.at(2)))
  place(placement, float: true, block(width: 100%, wide(grid(columns: (1fr,) * 2, column-gutter: D.layout.column_gap_mm * 1mm, ..figs))))
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
#let tablefig(name, caption, body, notes: none, source: none, placement: none) = {
  let fig = wide[#figure(block(width: 100%, { set align(left); body; foot(notes, source) }), kind: table,
    supplement: [Table], caption: caption) #label("tab-" + name)]
  if placement == none { block(above: 1.4em, below: 1.4em, fig) } else { place(placement, float: true, block(width: 100%, fig)) }
}
#let tag(body) = box(inset: (x: 4pt, y: 1.6pt), radius: 1.5pt, stroke: 0.5pt + rule2,
  text(font: sans-md, size: 6.8pt, fill: ink2, tracking: 0.03em, upper(body)))
// The house Source line for results of the study run.
#let run-source = [Author's backtest, v#m("paper.version") study run (commit #m("paper.commit_short")); prices from Yahoo Finance]

// ══════════════════════════════════════════════════════════════════════════════════════
// Title block
// ══════════════════════════════════════════════════════════════════════════════════════

#wide({
  grid(columns: (1fr, auto), align: (left + horizon, right + horizon),
    text(font: sans-md, size: 7.4pt, fill: accent, tracking: 0.08em, upper[Research note · Statistical arbitrage]),
    tag[Hypothetical backtest])
  v(5pt)
  {
    set par(justify: false, leading: 0.42em)
    set text(hyphenate: false)
    text(font: serif-sb, size: 21pt)[No detectable edge: cointegration pairs trading on the Russell 3000, #m("paper.years")]
  }
  v(6pt)
  {
    set par(justify: false, leading: 0.55em)
    text(font: sans, size: 10pt, fill: ink2)[The #m("paper.universe_top") most liquid stocks of an approximated Russell 3000, traded as cointegrated pairs with next-day fills and a per-stock cost model, #m("paper.period_start_month") to #m("paper.period_end_month").]
  }
  v(8pt)
  text(font: sans, size: 7.8pt, fill: ink2)[
    #text(font: sans-sb, fill: ink)[Navnoor Bawa] #h(5pt)·#h(5pt) Note of #m("paper.paper_date_long") #h(5pt)·#h(5pt) Study run v#m("paper.version") of #m("paper.run_date_long"), commit #raw(D.m.at("paper.commit_short"))
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
#claim("inside_random_spread") #claim("edge_not_significant") #claim("edge_below_cost")
#claim("both_reject_sharpe_1_5_and_2") #claim("sharpe_1_rejected_only_if_iid") #claim("both_cannot_reject_sharpe_half")
#claim("holdout_sealed")
#wide(block(width: 100%, inset: (x: 12pt, y: 11pt), fill: sunk, radius: 2pt, {
  grid(columns: (1fr, auto), align: (left + horizon, right + horizon),
    text(font: serif-sb, size: 10.8pt)[Summary],
    box(inset: (x: 6pt, y: 2.5pt), radius: 1.5pt, fill: ink,
      text(font: sans-sb, size: 7pt, fill: white, tracking: 0.06em, upper[No detectable edge])))
  v(3pt)
  set par(leading: 0.66em)
  [*No detectable edge.* Net of modelled costs the strategy's Sharpe ratio was #m("main.sharpe") in the main backtest (95% interval #m("significance.main.boot_lo") to #m("significance.main.boot_hi")) and #m("oos.pooled_sharpe") in a continuous walk-forward (#m("significance.oos_daily.boot_lo") to #m("significance.oos_daily.boot_hi")), which is out of sample for pair selection and the ranker but not for the trading thresholds. Neither is distinguishable from zero, from the Gatev distance method (difference #m("benchmarks.sharpe_diff_vs_gatev.diff"), p = #m("benchmarks.sharpe_diff_vs_gatev.p")) or from random pairs traded with that method (#m("paper.percentile_ordinal") percentile). Before costs the trades earned #m("paper.edge.gross_bp")~bp of the notional they traded (t = #m("paper.edge.gross_t")), less than the #m("paper.edge.cost_bp")~bp of modelled cost: there is no detectable gross edge for costs to remove. The sample excludes Sharpe ratios of 1.5 and above; at 1.0 it is borderline (p = #m("study.dev.facts.p_sr_ge_1") assuming independent returns, #m("paper.power_ar1.p_ge_1") allowing for their autocorrelation), and it cannot tell 0 from 0.5. The decisive test is a 2026 holdout, #if prereg [pre-registered] else [to be pre-registered] before any 2026 price series is fetched.]
}))

#v(9pt)
#let kpi(label, value, sub) = block(width: 100%, inset: (top: 6pt, bottom: 2pt), stroke: (top: 0.6pt + ink), {
  set par(justify: false, leading: 0.45em)
  set text(hyphenate: false)
  text(font: sans-md, size: 6.6pt, fill: ink2, tracking: 0.05em, upper(label))
  v(3pt)
  text(font: sans-sb, size: 14pt, fill: ink, value)
  v(2pt)
  text(font: sans, size: 6.8pt, fill: ink2, sub)
})
#claim("both_bounds_about_one") #claim("both_mde_above_bound") #claim("break_even_is_edge_over_cost")
#wide(grid(columns: (1fr, 1fr, 1fr), column-gutter: 12pt, row-gutter: 9pt,
  kpi([Main backtest · net Sharpe], m("main.sharpe"),
    [95% interval #m("significance.main.boot_lo") to #m("significance.main.boot_hi") · Newey–West p = #m("significance.main.hac_p") · #m("study.dev.facts.main_days")~days]),
  kpi([Walk-forward · net Sharpe], m("oos.pooled_sharpe"),
    [95% interval #m("significance.oos_daily.boot_lo") to #m("significance.oos_daily.boot_hi") · Newey–West p = #m("significance.oos_daily.hac_p") · #m("study.dev.facts.oos_days")~days]),
  kpi([Upper bound on the Sharpe ratio], m("paper.power_ar1.ucb"),
    [One-sided 95%, allowing for autocorrelation (#m("study.dev.facts.sharpe_ucb") if independent) · 80% power only at #m("paper.power_ar1.mde")]),
  kpi([Gross edge per trade], [#m("paper.edge.gross_bp")~bp],
    [Before costs, notional-weighted · t = #m("paper.edge.gross_t") · modelled cost #m("paper.edge.cost_bp")~bp · n = #m("main.trades")]),
  kpi([Break-even cost multiple], m("study.dev.facts.break_even_x"),
    [Net P&L is zero at this fraction of modelled costs: #m("paper.edge.gross_bp") over #m("paper.edge.cost_bp")~bp]),
  kpi([Deflated Sharpe · walk-forward], m("significance.oos_daily.dsr_pct"),
    [Probability that the true Sharpe ratio exceeds the expected best of #m("study.dev.facts.dsr_trials") null trials · P(SR > 0) = #m("significance.oos_daily.psr_pct")]),
))

// ══════════════════════════════════════════════════════════════════════════════════════
= Introduction
// ══════════════════════════════════════════════════════════════════════════════════════

== The question

Pairs trading buys one stock and sells another when the spread between them is unusually wide, and closes the position when it narrows. #cite(<gatev2006>, form: "prose") documented excess returns from a simple distance rule on US stocks over four decades; later studies find that the edge has shrunk and is small after realistic costs @do2010 @do2012 @rad2016, and #cite(<krauss2017>, form: "prose") surveys the methods. This note asks one question and is built to answer it honestly: *does a cointegration pairs-trading strategy on the Russell 3000 have an edge after realistic execution and costs, out of sample?*

The strategy selects pairs with the Engle--Granger test @engle1987 on formation data only, tracks each pair's hedge ratio with a two-state Kalman filter @kalman1960, trades a z-score of the hedged spread with fills at the next day's close, and pays costs computed from each stock's own liquidity. It is evaluated in a main backtest from #m("paper.period_start_long") to #m("paper.period_end_long"), in a continuous walk-forward with #m("oos.windows") test windows, and against two baselines run on the same footing: the distance method of #cite(<gatev2006>, form: "prose") and #m("benchmarks.random_control.n_draws") portfolios of random pairs traded with that method.

The answer for #m("paper.years") is a null. A null is informative only to the extent that the test had power and the measurement was right, so most of this note is about what the sample can and cannot rule out, and about the checks that the code measures what it claims. The development period cannot test the design choices made on it; a 2026 holdout, sealed at the date of this note, does that (@sec-holdout).

== What is new

The study uses free data only. Academic studies avoid survivorship with paid point-in-time databases; a backtest on free data usually starts from today's index members instead, and is exposed to the other familiar weaknesses of backtests: flat cost assumptions, rolling windows that drop positions at their edges, significance without power, and an untold number of designs tried. Each item below addresses one of these; the last adds a test the development data cannot provide.

- *A point-in-time universe from free SEC filings.* The complete holdings of the iShares Russell 3000 ETF (IWV) are public on Form N-PORT for the last month of each fiscal quarter; #m("paper.iwv.n") quarterly snapshots give index membership as it was at each formation date, without a paid constituent history (@sec-data). The v33 design trades this universe; the v32 run reported here does not.
- *Costs from each stock's own liquidity.* Every fill pays commission, half the typical quoted spread for the stock's dollar-volume bucket and square-root market impact on the stock's own volatility and dollar volume, at the next day's close (@sec-costs).
- *A continuous walk-forward.* The test windows are calendar slices of one simulation with the ranker refit per window; positions carry across window boundaries instead of being discarded (@sec-method).
- *Power analysis.* Each null is reported with the Sharpe ratios it excludes, with and without allowance for autocorrelation, the Sharpe ratio it could have detected and the track record a given Sharpe ratio would need (@sec-inference).
- *A declared variant family.* On #m("paper.declared_long"), before any variant ran, the study declared #m("study.dev.snooping.grid_points") threshold settings and #m("study.dev.snooping.toggles") design toggles for White's Reality Check, Hansen's SPA test, the Romano--Wolf stepdown, the model confidence set and the probability of backtest overfitting (@sec-snooping).
- *A 2026 holdout.* Hypotheses, test, multiplicity correction and decision rule #if prereg [were fixed in a pre-registration] else [are to be fixed in a pre-registration] before any 2026 price series is fetched; each strategy then runs once and its result is published whatever it is (@sec-holdout).

== Related work

The published record points one way: the classic pairs edge was large before the 2000s, has shrunk since, and is small after realistic costs (@tab-literature). The closest analogue of this study is #cite(<rad2016>, form: "prose"), who compare distance, cointegration and copula methods on US stocks; this study differs in period, cost model and inference. #cite(<avellaneda2010>, form: "prose") trade residuals of single stocks against sector ETFs and factors, the second strategy family of this study (@sec-residual).

#tablefig("literature", [Published results for pairs trading and residual reversion, as reported by their authors],
  booktab(columns: (20%, 14%, 22%, 44%), align: (left, left, left, left),
    header: ([Study], [Sample], [Method], [Reported result]),
    rows: (
      ([#cite(<gatev2006>, form: "prose")], [US, 1962–2002], [Distance method, top-20 pairs], [Annualised excess returns of up to 11% before costs, falling in later years. The baseline replicated here.]),
      ([#cite(<do2010>, form: "prose")], [US, to 2009], [Distance method], [Profitability declines over time; the strategy does best in prolonged turbulence.]),
      ([#cite(<avellaneda2010>, form: "prose")], [US, 1997–2007], [PCA and sector-ETF residual reversion], [Net Sharpe 1.44 (PCA) and 1.1 (ETF) over 1997–2007; PCA only 0.9 over 2003–2007. The second family tested here.]),
      ([#cite(<do2012>, form: "prose")], [US, 1963–2009], [Distance method with trading costs], [About 30 bp a month for well-matched pairs in refined industries after costs; largely unprofitable after 2002.]),
      ([#cite(<rad2016>, form: "prose")], [US, 1962–2014], [Distance, cointegration and copula methods], [91, 85 and 43 bp a month before costs; 38, 33 and 5 bp after. From 2009 opportunities for the distance and cointegration methods fall, while the copula method's stay stable. The closest published analogue of this study.]),
      ([#cite(<krauss2017>, form: "prose")], [Review], [Survey of pairs-trading approaches], [Distance, cointegration, time-series, stochastic-control and other approaches compared; open problems include costs and robustness.]),
    )),
  source: [The studies cited.])

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
    )))

== The v32 universe

#claim("fetch_ok_is_price_history")
The universe of the v32 study run is the #m("paper.names_file") largest US common stocks by market capitalisation on #m("paper.universe_as_of_long"): the Russell 3000 rule applied to the Nasdaq screener, not FTSE Russell's constituent list. #if flag("fetch") [Dropping invalid and duplicate rows leaves #m("paper.fetch.symbols") symbols. Daily prices from #m("paper.data_start_long") to #m("paper.data_end_long") were obtained for #m("paper.fetch.ok") of them (#m("paper.fetch.ok_pct")). Of the rest, #m("paper.fetch.errors") fetches failed with HTTP errors, #m("paper.fetch.invalid") histories failed the data checks (missing or non-positive closes, or a point-in-time price below \$2 when the series starts) and #m("paper.fetch.short") were too short; the failed fetches are a shortfall of the run, not a limit of the data.] else [Daily prices from #m("paper.data_start_long") to #m("paper.data_end_long") were obtained for #m("paper.names_prices") names.] The level screens, a \$5 price floor and a dollar-volume floor, are applied to point-in-time prices: closes with later splits undone, so that a split after the formation date cannot decide earlier membership. The #m("paper.universe_top") most liquid names by point-in-time dollar volume enter the pair search.

#claim("universe_not_point_in_time")
This universe has survivorship bias. Companies that failed, delisted or were acquired before #m("paper.universe_as_of_long") are absent, and so are the pairs that broke when one of them failed. The bias flatters a mean-reversion strategy, which makes a null result on this universe more convincing, not less (@sec-threats). The ranking by market capitalisation on that date is also one of two pieces of 2026 market information in the study (@sec-holdout).

== Point-in-time membership from N-PORT filings

A registered fund reports its complete portfolio holdings on Form N-PORT, and the report for the third month of each fiscal quarter is made public on EDGAR. IWV tracks the Russell 3000, so its filings give index membership as it was, quarter by quarter, at no cost. The study reads the equity-common holdings of #m("paper.iwv.n") snapshots from #m("paper.iwv.first_long") to #m("paper.iwv.last_long"), #m("paper.iwv.equity_min") to #m("paper.iwv.equity_max") holdings each, and maps each holding's CUSIP (or ISIN) to a ticker through OpenFIGI, N-PORT's own reported tickers (filings from 2022-09-30 on), issuer successions and a check against N-PORT's value per share (@ex-snapshots). A snapshot is in force from the date its holdings describe until the next one. Two caveats: IWV is a fund, not the index, and holds fewer names than the index; and additions and deletions within a quarter appear only at the next quarter end. Snapshots dated #m("paper.iwv.sealed_from_long") or later are listed but not downloaded: their holdings carry a market value, and so a 2026 price, for every member.

#claim("iwv_gap_shrinks")
#exhibit("snapshots",
  [Free filings give #m("paper.iwv.n") quarterly snapshots of index membership; the index weight without a usable ticker falls from #m("paper.iwv_unmapped_first_pct") to #m("paper.iwv_unmapped_last_pct")],
  sub: [Equity holdings of the iShares Russell 3000 ETF in its N-PORT filings, #m("paper.iwv_first_year")–#m("paper.iwv_last_year"), and the share of their value that cannot be mapped to a ticker],
  notes: [A holding without a usable ticker is one no source maps; one whose last ticker now belongs to another issuer; one whose mapping a price check against N-PORT's value per share rejected (the ticker's line is another security's, such as the equity of a later reorganisation); or one that would take the ticker another holding of the snapshot has as its own line. The last three are left unmapped on purpose so that no member is joined to someone else's prices. The share is larger in older snapshots, as expected if most such holdings are securities that have since delisted; its weight is part of the survivorship gap.],
  source: [SEC EDGAR, Form N-PORT-P filings of the iShares Russell 3000 ETF (iShares Trust, series S000004341); tickers from OpenFIGI and N-PORT; author's calculations.])

== The survivorship gap

The survivorship gap at a formation date is the index weight of members a backtest cannot trade: holdings without a usable ticker, plus members with a ticker whose price history the vendor no longer serves, mostly failures and takeovers. The v32 universe has no membership to measure the gap against. From v33 on, every formation records the snapshot in force, its members, how many have price history, and the index weight of those that do not (#see("universe")).

#exhibit("universe",
  [Point-in-time universe: index members with and without price history at each formation date],
  sub: [Members of the index snapshot in force when pairs are formed, and the share of index weight the price data do not cover],
  notes: [The index weight of members without price history, plus that of holdings with no usable ticker, is the survivorship gap at that date: a pair that includes one of them cannot be formed.],
  source: [#run-source\; membership from IWV's holdings in SEC N-PORT filings.])

// ══════════════════════════════════════════════════════════════════════════════════════
= Method <sec-method>
// ══════════════════════════════════════════════════════════════════════════════════════

Selection sees formation data only; every trading decision on day _t_ uses data up to day _t_ and fills on day _t_ + 1; the evidence is computed after the run (@ex-pipeline). Tests change future prices and check that no past decision moves. @tab-spec in the appendix states every rule of the run on one page, and @tab-profiles sets the v32 design beside the v33 design.

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
#place(top, float: true, block(width: 100%, wide[#figure(kind: "exhibit", supplement: [Exhibit],
  caption: [The pipeline, and what data each stage may see], {
    set align(left)
    set text(font: sans, size: 7.4pt, fill: ink2, hyphenate: false)
    block(below: 5pt, text(size: 7.6pt)[Stages of one run, grouped by the data each may see])
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
      dg-box[Significance][Newey–West t, bootstrap \ PSR, deflated Sharpe \ Ledoit–Wolf test], dg-arrow,
      dg-box[Baselines][Gatev distance rule \ #m("benchmarks.random_control.n_draws") random-pair draws \ same costs, _t_ + 1 fills], [], [], [], [],
    )
    foot([Boxes framed in the accent colour mark the two look-ahead boundaries: the formation cutoff, after which selection sees no data, and the next-day fill, which separates a signal from its trade.],
      [Author's design of the v#m("paper.version") study run.])
  }) <ex-pipeline>]))

#exhibit("timeline",
  [Data splits: formation, walk-forward, main backtest and the sealed holdout],
  sub: [Calendar #m("paper.data_first_year")–#m("paper.holdout_year")],
  notes: [The main backtest and the walk-forward overlap on #m("study.dev.facts.oos_overlap_days") of the main backtest's #m("study.dev.facts.main_days") days and trade the same pair pool: they are one experiment, not two confirmations.],
  source: [Author's study calendar for the v#m("paper.version") run.])

== Formation

Pairs are formed once, on data to #m("paper.formation_cutoff_long"). Among the #m("paper.universe_top") most liquid names, every pair with a positive return correlation of at least 0.25 is tested for cointegration with the two-step Engle--Granger test in both directions, Bonferroni-adjusted across the two, at p < 0.05. A pair is kept if the half-life of its cointegrating residual lies between 4 and 25 trading days and a heuristic quality score passes: #m("fdr.final_selected_pairs") of #m("fdr.pairs_tested") pairs tested (@sec-multiple). Every #m("paper.v32_reselect_every") trading days the pool is re-tested on the trailing #m("paper.v32_formation_years") years, and a pair stays only if it is still cointegrated there and its Engle--Granger p-value on the last 126 calendar days (about 87 trading days) is at most 0.30. Pairs can drop out but none can enter.

== Spread model

The hedge ratio is the slope state of a two-state Kalman filter on log prices,
$ log p_(1,t) = alpha_t + beta_t log p_(2,t) + epsilon_t, $
where $(alpha_t, beta_t)$ follows a random walk, both log prices are centred on their burn-in means and the filter is seeded by ordinary least squares. The intercept makes β a hedge ratio rather than a ratio of price levels, and centring makes every signal invariant to a vendor's back-adjustment of history for a later split or dividend, which shifts each log price by a constant.

== Signal and exits

One z-score drives every decision. At a signal on day $t_0$ the hedge ratio is locked at its current value and the spread is standardised by its mean and standard deviation over the last 30 to 60 bars (three half-lives), both frozen at the signal:
$ s_t = log p_(1,t) - beta_(t_0) log p_(2,t), quad z_t = (s_t - mu_(t_0)) / sigma_(t_0). $
A pair is entered when |_z_| ≥ 1.8, long the spread when _z_ is negative and short when it is positive. It exits at the target once _z_ has reverted past −0.5 for a long spread or +0.5 for a short one, at the stop when _z_ has moved 1.5 further against the position, and at the time stop after clamp(2.5 × half-life, 10, 25) trading days. Entries also require a 20-day return correlation of at least 0.20 and a hedge ratio in [0.25, 4]; after three consecutive losing trades a pair is barred from new entries for 30 calendar days; and a regime gate on the VIX and sector dispersion scales positions and blocks new entries in stressed markets.

== Execution, accounting and risk limits

A signal computed on the close of day _t_ is filled at the close of day _t_ + 1, for entries and exits alike: in practice a market-on-close order in each stock's closing auction, so both legs print together. Share counts are fixed from the signal-day close and the legs are sized \$1~:~\$β. Positions are marked to market daily, costs are booked on fill days, and positions still open at the end of the data are closed. The book has \$#m("study.dev.facts.capital_musd")M of notional capital, 3–10% of equity per pair before regime scaling (#m("paper.position_min_pct") to #m("paper.position_max_pct") as traded), a 30% cap on gross exposure, at most 8 new entries a day, no stock in two open pairs, and drawdown and daily-loss kill switches that flatten it. Idle cash earns no interest.

#claim("ranker_no_skill") #claim("ranker_brier_worse_than_base")
A classifier of the probability that a trade is profitable, on 30 features, only orders same-day candidates, which matters when more signals fire than the book's limits allow; it does not create signals. It has no economically useful skill: its out-of-sample AUC is #m("ranker.oos_auc") (#m("ranker.wf_pooled_auc") pooled across the walk-forward windows, where 0.5 is no skill), and its pooled Brier score, #m("paper.ranker_brier_pooled"), is worse than the #m("paper.ranker_brier_base_pooled") of always predicting the base rate. The v33 design drops it.

== Walk-forward

#claim("last_window_longer")
The walk-forward is one continuous simulation on a 252-day training / 63-day test grid from #m("paper.oos_start_month") to #m("paper.oos_end_month")\; the last window runs to the walk-forward's last day, #m("paper.oos_end_long"), #m("paper.wf_last_days") trading days. It is out of sample for pair selection, made on data to #m("paper.formation_cutoff_long"), and for the ranker, refit on each window's training year. It is not out of sample for the entry, exit and stop thresholds, which were chosen across versions on this same data, or for the regime gate, whose thresholds were fitted on windows that now lie inside this period. This note therefore calls it the walk-forward and reserves "out of sample" for the 2026 holdout. Positions carry across window boundaries, and per-window figures are calendar slices of the one simulation (@tab-windows in the appendix). It trades the same pair pool as the main backtest and shares #m("study.dev.facts.oos_overlap_days") of its #m("study.dev.facts.main_days") days (@ex-timeline).

== Inference

Sharpe ratios are annualised from daily net returns by √252. Means are tested with the t-statistic of #cite(<newey1987>, form: "prose"). Intervals for single series are circular block bootstraps with #m("paper.boot_resamples") resamples and the block length of #cite(<politis2004>, form: "prose"), as corrected by #cite(<patton2009>, form: "prose"): blocks of #m("paper.boot_block_main") days for the main backtest and #m("paper.boot_block_oos") for the walk-forward. The probabilistic and deflated Sharpe ratios follow Bailey and López de Prado (#cite(<bailey2012>, form: "year"), #cite(<bailey2014>, form: "year")), using the variance of the Sharpe estimator under non-normal returns. Standard errors, power and the upper bound use that variance twice: assuming independent returns, and allowing for the returns' lag-1 autocorrelation (@sec-inference). The autocorrelation-adjusted annualisation of #cite(<lo2002>, form: "prose"), which the note does not otherwise use, gives #m("paper.lo_sharpe_main") for the main backtest and #m("paper.lo_sharpe_oos") for the walk-forward. Differences of Sharpe ratios use the studentized bootstrap of #cite(<ledoit2008>, form: "prose").

== Validation <sec-validation>

A backtest on real data says what a strategy did, not whether the code measures what it claims. A synthetic validation runs the real engine, with its full cost model, on markets whose answer is known: planted cointegrated pairs must show a large gross edge; correlated pairs that are not cointegrated, forced into the universe, must show none; the Kalman hedge ratio must recover the true slope; and pair selection must find the planted pairs while admitting at most 5% of unrelated ones. #if flag("validation") [@tab-validation reports the results.] else [Its committed results are forthcoming (@tab-forthcoming).] The test suite adds causality checks, each confirmed by re-introducing the bug it guards against: every decision dated on or before _T_ is unchanged when all prices, volumes and macro data after _T_ are replaced, with classical ranking and with a trained ranker; the regime gate's inputs are prefix-invariant; and the same trades occur at the same z-scores when the vendor back-adjusts history for a later split. The statistics are tested against reference implementations: statsmodels for Newey--West, arch for the Politis--White block length, an independent cross-validation for the probability of backtest overfitting, and the authors' code for Ledoit--Wolf.

#if flag("validation") {
  tablefig("validation", [Known-answer checks],
    booktab(columns: (42%, 28%, 30%), align: (left, left, left),
      header: ([Check], [What must happen], [Result]),
      rows: T("validation")),
    notes: [Synthetic markets with planted cointegrated pairs among unrelated names.],
    source: [Author's synthetic validation of the study engine.])
}

// ══════════════════════════════════════════════════════════════════════════════════════
= Development-period results <sec-results>
// ══════════════════════════════════════════════════════════════════════════════════════

The main backtest enters trades from #m("paper.period_start_long") to #m("paper.period_end_long") on \$#m("study.dev.facts.capital_musd")M of notional capital, with pairs selected on data to #m("paper.formation_cutoff_long"). Its #m("main.trades") trades returned #m("main.total_return_pct") with a maximum drawdown of #m("main.max_drawdown_pct") (@ex-equity). The book held no position on #m("study.dev.facts.flat_days") of #m("study.dev.facts.days") days and used #m("main.avg_gross_exposure_pct") of capital on average (gross), against a 30% cap. @tab-performance sets out the standard statistics of the main backtest, the walk-forward and the Gatev baseline.

#claim("main_negative")
#exhibit("equity",
  [Net of costs the book ends slightly below where it started; the Gatev baseline ends at #m("benchmarks.gatev.total_return_pct")],
  sub: [Cumulative net return, underwater drawdown and gross exposure; main backtest, daily, #m("paper.period_start_month") – #m("paper.period_end_month")],
  notes: [The two paths are on different capital bases: the Gatev return is per unit of committed per-leg notional, at #m("paper.gatev_vol_pct") annualised volatility, and the strategy's per unit of \$#m("study.dev.facts.capital_musd")M of capital, at #m("paper.main_vol_pct"). Compare their Sharpe ratios (@ex-forest), not the levels of these paths. Gross exposure is rebuilt from the trades and reproduces the run's average and maximum (#m("study.dev.facts.exposure_max_pct")).],
  source: [#run-source\; baseline: #cite(<gatev2006>, form: "prose") distance rule with the same _t_ + 1 fills and costs.])

#tablefig("performance", [Performance of the main backtest, the walk-forward and the Gatev baseline, net of costs],
  booktab(columns: (40%, 20%, 20%, 20%), align: (left, right, right, right),
    header: ([], [Main backtest], [Walk-forward], [Gatev distance method]),
    rows: T("performance")),
  notes: [Annualised returns are mean daily returns × 252 with a Newey–West 95% interval; volatility intervals are circular block bootstraps with the Sharpe ratio's block length. The walk-forward is exported as summary statistics only: its volatility is implied by its mean return and Sharpe ratio, and it has no volatility interval or drawdown length. The Gatev return is per unit of committed per-leg notional, the strategy's per unit of capital; compare Sharpe ratios across columns, not return or volatility levels. A dash marks a statistic the run does not report for that series.],
  source: [#run-source\; baseline: #cite(<gatev2006>, form: "prose") distance rule.],
  placement: top)

#claim("oos_negative")
The walk-forward points the same way (@ex-walkforward). Of its #m("oos.windows") windows, #m("oos.windows_positive") made money, and the stitched path ends at #m("oos.total_return_pct")\; the mean window return is #m("oos.avg_window_return_pct") with a 95% interval from #m("significance.oos_windows.ci_lo_pct") to #m("significance.oos_windows.ci_hi_pct"). Two features of the main backtest deserve care. One month carries the result (@ex-monthly), and every half-year window whose Sharpe ratio looks significant overlaps that month (@ex-rolling); reading either as a regime the strategy could exploit would be fitting a rule to the test period.

#claim("wf_carry_window_exists")
#exhibit("walkforward",
  [In the walk-forward, #m("oos.windows_positive") of #m("oos.windows") windows made money; the stitched path ends at #m("oos.total_return_pct")],
  sub: [Net return per test window (bars, labelled with the trades opened) and the compounded path at window ends; #m("paper.oos_start_month") – #m("paper.oos_end_month")],
  notes: [Out of sample for pair selection and the ranker only (@sec-method). The windows are calendar slices of one continuous simulation, #m("paper.wf_window_days") trading days each and #m("paper.wf_last_days") for the last; positions carry across window boundaries, so a window that opens no trade can still carry P&L from earlier positions (window #m("paper.wf_carry_windows")). No trade was opened in #m("oos.windows_no_trades") of the windows. With #m("oos.windows") windows the test has little power: mean #m("oos.avg_window_return_pct") per window, 95% interval #m("significance.oos_windows.ci_lo_pct") to #m("significance.oos_windows.ci_hi_pct"), p = #m("significance.oos_windows.p").],
  source: [#run-source.])

#claim("best_month_exceeds_total") #claim("without_best_month_lower") #claim("flat_run_exists")
#exhibit("monthly",
  [One month carries the result: #m("paper.best_month") earned #m("study.dev.facts.best_month_pct")\; without it the period returned #m("paper.without_best_pct")],
  sub: [Monthly net return, % of capital; the year column compounds the months shown],
  notes: [Of the #m("study.dev.facts.months") months, #m("study.dev.facts.months_positive") were positive; compounded, they return #m("paper.compounded_pct"). The book was flat from #m("paper.flat_from") to #m("paper.flat_to")\; the regime gate blocked new entries on #m("study.dev.facts.gate_blocked_days") of the #m("study.dev.facts.days") days. This grid is the evaluated period: a rule fitted to it would be data snooping.],
  source: [#run-source.])

#claim("clearing_windows_contain_best_month")
#exhibit("rolling",
  [Half-year Sharpe ratios swing between #m("study.dev.facts.rolling_min") and #m("study.dev.facts.rolling_max")\; every window whose band clears zero overlaps #m("paper.best_month")],
  sub: [Rolling #m("study.dev.rolling_sharpe.window")-day Sharpe ratio, annualised, with a ±1.96 standard-error band; main backtest],
  notes: [SE = √((1 + SR²/2)/_n_) per day with _n_ = #m("study.dev.rolling_sharpe.window"), annualised, the independent-returns standard error of #cite(<lo2002>, form: "prose"). Of the #m("study.dev.facts.rolling_windows") overlapping windows, #m("study.dev.facts.rolling_clear_zero") clear zero, all ending between #m("paper.clear_first_end_long") and #m("paper.clear_last_end_long")\; overlapping windows are not independent tests. Windows in which the book was flat throughout have no Sharpe ratio.],
  source: [Author's calculation from the daily net returns of the v#m("paper.version") run.])

// ══════════════════════════════════════════════════════════════════════════════════════
= Inference <sec-inference>
// ══════════════════════════════════════════════════════════════════════════════════════

#claim("every_interval_spans_zero") #claim("dependence_widens") #claim("sharpe_1_borderline_both")
Is the result significant? No: every interval in @ex-forest contains zero, and @tab-significance gives the tests. The more useful question is what the data can rule out, and the answer depends on how the standard error of the Sharpe ratio treats dependence. With #m("study.dev.facts.main_days") daily observations, assuming independent returns, the standard error of the annualised Sharpe ratio is #m("study.dev.facts.sharpe_se") and the one-sided 95% upper bound #m("study.dev.facts.sharpe_ucb")\; allowing for the returns' lag-1 autocorrelation of #m("paper.power_ar1.rho") they are #m("paper.power_ar1.se") and #m("paper.power_ar1.ucb"). Either way the sample excludes Sharpe ratios of 1.5 and above. A Sharpe ratio of 1.0 is borderline: it is rejected at the 5% level only if returns are independent (p = #m("study.dev.facts.p_sr_ge_1"), against #m("paper.power_ar1.p_ge_1") allowing for autocorrelation). A Sharpe ratio of 0.5 is not rejected (p = #m("study.dev.facts.p_sr_ge_0_5") and #m("paper.power_ar1.p_ge_0_5")). A true Sharpe ratio would need to be about #m("study.dev.facts.sharpe_mde"), or #m("paper.power_ar1.mde") allowing for autocorrelation, to be detected with 80% probability. An observed Sharpe ratio of 0.5 becomes significant only after about #m("study.dev.facts.min_trl_years_0_5") years of daily data (#m("paper.power_ar1.trl_0_5") allowing for autocorrelation), and a strategy whose true Sharpe ratio is 0.5 reaches that bar only about half the time; at 1.0 the lengths are #m("study.dev.facts.min_trl_years_1") and #m("paper.power_ar1.trl_1") years.

#claim("both_bounds_about_one")
#exhibit("forest",
  [Every Sharpe interval spans zero; the data exclude only Sharpe ratios above about 1],
  sub: [Annualised Sharpe ratio with its 95% interval; development period, net of costs],
  notes: [Intervals are circular block bootstraps (Politis–White block length, #m("paper.boot_resamples") resamples) for single series and Ledoit–Wolf studentized bootstraps for differences; the random-pair row shows the 5th–95th percentile spread of #m("benchmarks.random_control.n_draws") draws, not a confidence interval. The bound and the 80%-power line allow for lag-1 autocorrelation; assuming independent returns they are #m("study.dev.facts.sharpe_ucb") and #m("study.dev.facts.sharpe_mde"). The walk-forward's comparison with Gatev uses the #m("paper.wf_common_days") days the two series share.],
  source: [#run-source\; baseline: #cite(<gatev2006>, form: "prose") distance rule, with the run's own bootstrap.])

== Power and the one-sided upper bound

A test that cannot reject zero is evidence of no edge only to the extent that it could have detected one. The power figures use the asymptotic variance of the Sharpe estimator for non-normal returns, with the sample's skewness (#m("study.dev.facts.skew")) and non-excess kurtosis (#m("study.dev.facts.kurtosis")) @bailey2012, first for independent returns and then with the returns' lag-1 autocorrelation entering through an AR(1) extension of the same variance (@tab-alternatives). At this sample length the critical Sharpe ratio of a one-sided 5% test is #m("study.dev.facts.sharpe_critical") (#m("paper.power_ar1.critical") with autocorrelation) and the Sharpe ratio detected with 80% probability #m("study.dev.facts.sharpe_mde") (#m("paper.power_ar1.mde")); the one-sided 95% upper bound, #m("study.dev.facts.sharpe_ucb") (#m("paper.power_ar1.ucb")), is the largest Sharpe ratio the data do not reject. The sample therefore excludes a strategy of Sharpe 1.5 or 2, is borderline at 1, and says nothing useful about 0.5.

#claim("both_mde_above_bound") #claim("both_reject_sharpe_1_5_and_2")
#tablefig("alternatives", [What the development sample rules out, assuming independent returns and allowing for autocorrelation],
  booktab(columns: (16%, 21%, 21%, 21%, 21%), align: (right, right, right, right, right),
    header: ([True annual Sharpe ratio _x_], [p-value of H#sub[0]: SR ≥ _x_, independent], [p-value, lag-1 autocorrelation], [Years for an observed SR = _x_ to be significant, independent], [Years, lag-1 autocorrelation]),
    rows: T("alternatives")),
  notes: [p-values are one-sided, evaluated at the observed Sharpe ratio. The track-record length is the minimum track record length of #cite(<bailey2012>, form: "prose") at the one-sided 5% level: the years of daily data after which an observed Sharpe ratio of _x_ is significant. A strategy whose true Sharpe ratio is _x_ reaches it only about half the time; 80% power needs about #m("paper.trl_power_ratio") times as long. The autocorrelation columns use the asymptotic variance for non-normal returns with lag-1 autocorrelation ρ = #m("paper.power_ar1.rho"), (_a_ − _b_·γ#sub[3]·SR + _c_·(γ#sub[4] − 1)/4·SR²)/_T_, where _a_, _b_ and _c_ depend on ρ and equal 1 at ρ = 0 (@sec-repro gives its source).],
  source: [Author's calculation from the daily net returns of the v#m("paper.version") run.],
  placement: top)

== Baselines

The Gatev distance method, run on the same universe and period with the same _t_ + 1 fills and cost model, returned #m("benchmarks.gatev.total_return_pct") (Sharpe #m("benchmarks.gatev.sharpe")\; 95% interval #m("study.dev.facts.gatev_lo") to #m("study.dev.facts.gatev_hi")). Its return is per unit of committed per-leg notional, at #m("paper.gatev_vol_pct") annualised volatility against the strategy's #m("paper.main_vol_pct") on capital, so the Sharpe ratios, not the returns, are comparable (@tab-performance). The difference in Sharpe ratios is #m("benchmarks.sharpe_diff_vs_gatev.diff") in the main backtest (Ledoit–Wolf p = #m("benchmarks.sharpe_diff_vs_gatev.p")) and #m("paper.diff_oos") in the walk-forward, on the #m("paper.wf_common_days") days the two series share (p = #m("paper.diff_oos_p")). Against #m("benchmarks.random_control.n_draws") portfolios of random pairs, traded with the Gatev rule under the same costs, the strategy sits at the #m("paper.percentile_ordinal") percentile (@ex-randomnull).

#tablefig("significance", [Significance tests, v#m("paper.version") study run of #m("paper.run_date_long")],
  booktab(columns: (46%, 27%, 27%), align: (left, right, right),
    header: ([Test], [Main backtest], [Walk-forward (daily)]),
    rows: T("significance")),
  notes: [Newey–West t and p test a zero mean of daily net returns. The deflated Sharpe ratio is the probability that the true Sharpe ratio exceeds the expected maximum Sharpe ratio of the stated number of independent null trials. The walk-forward's comparison with Gatev uses the #m("paper.wf_common_days") days both series cover, on which the walk-forward's own Sharpe ratio is #m("paper.wf_common_sharpe")\; no interval is computed for the Gatev Sharpe ratio on those days.],
  source: [#run-source\; tests of #cite(<newey1987>, form: "prose"), #cite(<bailey2014>, form: "prose") and #cite(<ledoit2008>, form: "prose").],
  placement: top)

#exhibit("randomnull",
  [The strategy sits at the #m("paper.percentile_ordinal") percentile of #m("benchmarks.random_control.n_draws") random-pair portfolios],
  sub: [Annualised Sharpe ratio of random 20-pair draws traded with the distance rule under the same costs; main period],
  notes: [Median draw #m("benchmarks.random_control.median_sharpe"), 5th–95th percentile #m("benchmarks.random_control.p5_sharpe") to #m("benchmarks.random_control.p95_sharpe"). The control trades random pairs with the Gatev distance rule, not this strategy's engine, so it is a baseline for the distance method and only a rough one for this strategy.],
  source: [#run-source.])

== Deflated Sharpe and data snooping <sec-snooping>

#claim("dsr_low")
Every design choice in this study was made on #m("paper.data_years") data over #m("paper.versions_count") versions (@tab-history). The deflated Sharpe ratio @bailey2014 is the probability that the true Sharpe ratio exceeds the expected maximum Sharpe ratio of _N_ independent null trials; the run reports _N_ = #m("study.dev.facts.dsr_trials"), a lower bound on the designs tried. At that _N_ the probability is #m("significance.main.dsr_pct") for the main backtest and #m("significance.oos_daily.dsr_pct") for the walk-forward (@ex-dsr). #cite(<harvey2016>, form: "prose") make the same point for the factor literature, arguing that a new factor's t-statistic should clear about 3 rather than 2.

#exhibit("dsr",
  [Deflated for #m("study.dev.facts.dsr_trials") trials, the main backtest's Sharpe ratio has a #m("significance.main.dsr_pct") probability of exceeding the expected best of the null trials],
  sub: [Deflated Sharpe ratio of the main backtest against the number of independent trials _N_ (log scale)],
  notes: [_N_ = 1 is the probabilistic Sharpe ratio; the run reports _N_ = #m("study.dev.facts.dsr_trials"), a lower bound on the designs tried over #m("paper.versions_count") versions. The trial Sharpe variance is the null variance of the estimator at this sample length.],
  source: [Author's calculation from the daily net returns of the v#m("paper.version") run.])

_N_ is not known, and the deflated Sharpe ratio is only as good as the guess. The data-snooping tests replace the guess with a declared family. On #m("paper.declared_long"), before any variant ran, the study declared a #m("study.dev.snooping.grid_points")-point grid of the entry, exit and stop thresholds and #m("study.dev.snooping.toggles") design toggles around the v33 design (@tab-variants in the appendix); each variant runs once on the development calendar and the primary design is not re-chosen from the results. The Reality Check of #cite(<white2000>, form: "prose") and the SPA test of #cite(<hansen2005>, form: "prose") ask whether the best variant beats cash; the stepdown of #cite(<romano2005>, form: "prose") identifies which variants do, with familywise error control; the model confidence set of #cite(<hansen2011>, form: "prose") keeps the variants that cannot be told apart from the best; and the probability of backtest overfitting @bailey2017 measures how often the in-sample winner falls below the median out of sample. Resampling uses the stationary bootstrap @politis1994. #if flag("snooping") [@tab-snooping reports the results.] else [The results are forthcoming (@tab-forthcoming).]

#if flag("snooping") {
  tablefig("snooping", [Data-snooping tests over the declared variant family],
    booktab(columns: (70%, 30%), align: (left, right),
      header: ([Test], [Result]),
      rows: T("snooping")),
    notes: [Variant family declared on #m("paper.declared_long"), before any variant was run.],
    source: [Author's runs of the declared variants on the development calendar.])
}

== Multiple testing in pair selection <sec-multiple>

#claim("excess_cointegration") #claim("bh_survivors_few") #claim("chance_accounts_for_most")
Pair selection is itself a multiple test. Of #m("fdr.pairs_tested") pairs tested, #m("fdr.significant_raw_p05") were "cointegrated" at p < 0.05. If no pair were cointegrated, about #m("study.dev.funnel.pairs.1.expected") would be expected to pass. That count is an upper bound on chance rejections, since it treats every pair as null and the two-direction Bonferroni p-value is conservative, so up to #m("study.dev.funnel.pairs.1.expected") of the #m("fdr.significant_raw_p05"), #m("paper.chance_share_pct"), could be chance. Only #m("fdr.survive_bh_fdr_q05") pair survives a Benjamini--Hochberg correction at q = 0.05 @benjamini1995: the excess is spread thinly over many weak relationships. Selection kept #m("fdr.final_selected_pairs") pairs, of which #m("study.dev.facts.pairs_traded") were traded (@ex-funnel).

#claim("chance_count_near_selected")
#exhibit("funnel",
  [From #m("fdr.pairs_tested") candidate pairs to #m("study.dev.facts.pairs_traded") traded; chance could account for most "cointegrated" pairs],
  sub: [Pairs at each selection stage, formation data to #m("paper.formation_cutoff_long")\; log scale],
  notes: [The tick marks the count expected by chance, an upper bound. Pairs share legs, so the tests are dependent; Benjamini–Hochberg is a diagnostic here, not a filter. Selection also requires a half-life of 4–25 days and a quality score. That the #m("study.dev.funnel.pairs.1.expected") expected by chance and the #m("fdr.final_selected_pairs") pairs selected are nearly equal is a coincidence: the second count follows the half-life and quality screens.],
  source: [#run-source.])

#exhibit("pvalues",
  [Engle–Granger p-values against the uniform null],
  sub: [Histogram, 20 bins, with the height expected if no pair were cointegrated],
  source: [#run-source.])

// ══════════════════════════════════════════════════════════════════════════════════════
= Where the edge goes <sec-anatomy>
// ══════════════════════════════════════════════════════════════════════════════════════

#claim("gross_pnl_below_costs") #claim("break_even_below_one") #claim("stops_lost_more_than_targets_earned")
#claim("gross_not_significant") #claim("gross_below_cost")
There is no detectable gross edge for costs to remove. Before costs the #m("main.trades") trades earned \$#m("study.dev.facts.gross_usd_k")k, #m("paper.edge.gross_bp")~bp of the notional they traded (t = #m("paper.edge.gross_t") for the mean gross P&L per trade); modelled costs were \$#m("study.dev.facts.cost_usd_k")k, #m("paper.edge.cost_bp")~bp, #m("study.dev.facts.impact_share_pct") of it market impact (@ex-waterfall). Weighting each trade equally gives the same picture: #m("study.dev.facts.gross_bp")~bp before costs (t = #m("study.dev.facts.gross_t")) against #m("study.dev.facts.cost_bp")~bp of cost. Costs would have to fall to #m("study.dev.facts.break_even_x") their modelled level, the ratio of gross to cost, for net P&L to break even, and the gross return is itself indistinguishable from zero. The trades show the mechanism: the #m("main.exit_reasons.stop") stop-loss exits lost \$#m("study.dev.facts.stop_loss_usd_m")M, more than the #m("main.exit_reasons.target") target exits earned (\$#m("study.dev.facts.target_gain_usd_m")M; @ex-anatomy).

#claim("impact_largest_cost")
#exhibit("waterfall",
  [Gross P&L, itself not significant, does not cover modelled costs; market impact is the largest item],
  sub: [Implementation shortfall of the main backtest: gross P&L to net P&L by cost component, \$ thousands],
  notes: [The bars close exactly on the change in the book's value. Gross is #m("study.dev.facts.gross_bp_capital")~bp of starting capital, costs #m("study.dev.facts.cost_bp_capital")~bp and net #m("study.dev.facts.net_bp_capital")~bp; per unit of traded notional, gross is #m("paper.edge.gross_bp")~bp and costs #m("paper.edge.cost_bp")~bp.],
  source: [#run-source: costs of each trade by component, and the final portfolio value.])

#claim("long_gained_short_lost") #claim("short_loss_near_long_gain") #claim("sides_carry_their_sign")
#exhibit("anatomy",
  [Stops lost more than targets earned, and short-spread trades lost about what long-spread trades made],
  sub: [Net P&L of the #m("main.trades") trades by exit reason, side of the spread and |_z_| at entry, \$ millions],
  notes: [Long-spread trades made \$#m("study.dev.facts.long_gain_usd_m")M and short-spread trades lost \$#m("study.dev.facts.short_loss_usd_m")M, consistent with the net market exposure that hedge ratios below one leave in each trade (@sec-risk). Win rate #m("main.win_rate_pct") (#m("study.dev.facts.wins") of #m("study.dev.facts.trades")\; 95% interval #m("study.dev.facts.win_lo_pct")–#m("study.dev.facts.win_hi_pct")). The |_z_| buckets describe the past and are not a selection rule: a higher entry threshold read off this panel would be fitted to the test period.],
  source: [#run-source: the #m("main.trades") trades.])

// The evidence layer's anatomy of the null, drawn once its run is committed.
#let anatomy = (
  ("costcurve", [Sharpe ratio against a multiple of modelled costs], (sub: [0× to 2× costs, with the break-even multiple marked], source: run-source)),
  ("exitrace", [Exit race: targets against stops, and against a spread with no mean reversion], (sub: [Observed exits and the count expected under the null], source: run-source)),
  ("decay", [In-sample to out-of-sample decay of the same rule on the same pairs], (sub: [Gross bp per trade, formation period against the trading period], source: run-source)),
  ("persistence", [Do selected pairs stay cointegrated?], (sub: [Share still cointegrated in later windows, against the 5% chance rate], source: run-source)),
).filter(e => has(e.at(0)))
#if anatomy.len() > 0 [
  The evidence layer measures where a null comes from: the Sharpe ratio against a multiple of modelled costs, the race between target and stop exits against a spread with no mean reversion, the decay of the same rule on the same pairs from formation to trading, and whether selected pairs stay cointegrated (#anatomy.map(e => ref(label("ex-" + e.at(0)))).join(", ")).
  #for i in range(0, anatomy.len(), 2) {
    exhibit-pair(anatomy.at(i), if i + 1 < anatomy.len() { anatomy.at(i + 1) } else { ("", [], (:)) })
  }
]

// ══════════════════════════════════════════════════════════════════════════════════════
= Execution and costs <sec-costs>
// ══════════════════════════════════════════════════════════════════════════════════════

Every fill pays its own costs, from the stock's own liquidity on that day, and fills at the next day's close: a signal seen at the close of day _t_ trades at the close of day _t_ + 1. The average trade held #m("study.dev.facts.hold_days")~trading days, and its larger leg was #m("study.dev.facts.adv_participation_pct") of that stock's dollar ADV. Annual turnover was #m("main.annual_turnover_x") capital. @tab-costs sets out the cost model against published references and what v33 changes; the study's execution-cost note compares the model with published impact estimates at each participation rate (@sec-repro).

#tablefig("costs", [The v32 cost model against published references, and what v33 changes],
  booktab(columns: (12%, 30%, 38%, 20%), align: (left, left, left, left),
    header: ([Component], [v32 model], [Reference], [v33]),
    rows: (
      ([Commission], [\$0.002 per share, \$0.50 minimum per order], [Author's assumption], [unchanged]),
      ([Half-spread], [Half the typical quoted spread by 20-day dollar ADV: 0.75 bp (≥ \$500M) to 40 bp (< \$5M)], [#cite(<frazzini2018>, form: "prose")], [bucket fit to be checked against measured spreads]),
      ([Market impact], [_Y_ · σ#sub[daily] · √(shares / ADV), _Y_ = 0.3, capped at 50 bp, on entry and exit], [The 0.314 of #cite(<almgren2005>, form: "prose") is their permanent-impact coefficient, not a trading cost; their temporary-impact fit lies below this model and a square-root law with _Y_ = 1 lies above it (the execution-cost note, @sec-repro)], [_Y_ stressed at 0.3, 0.6 and 1.0]),
      ([Borrow], [General-collateral fee, #m("paper.v32_borrow_bp") bp a year on the short leg], [#cite(<davolio2002>, form: "prose") on general-collateral fees; the v33 fee is a median buy-side indicative fee, whose source the execution-cost note gives], [one #m("paper.v33_borrow_pct") fee a year replaces borrow plus financing]),
      ([Financing], [Prime-broker spread, #m("paper.v32_financing_bp") bp a year on the short half of gross], [Overlaps with the borrow fee (a double count)], [folded into the single fee]),
      ([Fill], [Close of _t_ + 1 for entry and exit; legs \$1~:~\$β], [—], [_t_ + 1 open as a declared variant]),
    )),
  source: [Author's cost model for the v32 and v33 study designs; the references cited.],
  placement: top)

#claim("schedules_some_lose_rest_break_even") #claim("best_schedule_cheapest") #claim("no_schedule_significant")
How much the conclusion depends on the cost model is measured, not asserted. Re-costing and re-sizing the main backtest's own trades under #m("paper.schedules_n_word") other cost and sizing schedules (@ex-schedules, @tab-schedules) turns none of them into a significant gain. #if not has("costcurve") [A cost-sensitivity analysis on daily gross and cost series, with a stress table and a capacity curve, is forthcoming (@tab-forthcoming).]

#exhibit("schedules",
  [Re-costed under #m("paper.schedules_n_word") other cost and sizing schedules, the same trades lose money in #m("paper.schedules_lose_word") and break even in #m("paper.schedules_even_word")],
  sub: [Cumulative net return, % of capital, when the main backtest's trades are re-sized and re-costed; schedules A–E in order of total cost],
  notes: [Schedules are parameter sets, not descriptions of any firm; @tab-schedules lists each one's parameters. Returns run from #m("paper.sched_best_ret") (schedule #m("paper.sched_best_id"), the lowest costs and smallest positions) to #m("paper.sched_worst_ret") (schedule #m("paper.sched_worst_id")). The replay keeps the main backtest's signals, entry and exit dates and daily paths, and changes sizes and costs.],
  source: [Author's replay of the v#m("paper.version") trades under schedules A–E.])

#tablefig("schedules", [Cost schedules A–E: parameters and results of the replay],
  booktab(columns: (4%, 7%, 9%, 7%, 8%, 8%, 9%, 7%, 6%, 7%, 9%, 11%, 8%), align: (left,) + (right,) * 12, size: 7pt,
    header: ([], [Comm., bp], [Half-spread, bp], [Impact cap, bp], [Borrow, % a year], [Financing, % a year], [Position, % of equity], [Return, %], [Sharpe], [Max DD, %], [Costs, % of capital], [Peak gross, × capital], [Trades replayed]),
    rows: T("schedules")),
  source: [Author's replay of the v#m("paper.version") trades under schedules A–E; returns, Sharpe ratios and drawdowns as in the run's headline results.],
  placement: top)

#exhibit("capacity",
  [Capacity: impact cost against book size for a stated gross edge],
  sub: [Net bp per trade as notional scales],
  notes: [A break-even size computed on an insignificant gross edge would suggest an edge that has not been shown, so the curve is drawn for a stated hypothetical edge.],
  source: [#run-source.])

// ══════════════════════════════════════════════════════════════════════════════════════
= Risk and factor attribution <sec-risk>
// ══════════════════════════════════════════════════════════════════════════════════════

#claim("beta_small") #claim("beta_oos_significant") #claim("beta_main_not_significant") #claim("alpha_negative") #claim("alpha_not_significant") #claim("most_hedge_ratios_below_one") #claim("sign_exceptions_near_one")
Market exposure is small but not zero. Against an equal-weight sector-ETF proxy the main backtest's beta is #m("study.dev.facts.beta_main") (t = #m("study.dev.facts.beta_main_t")) and the walk-forward's #m("study.dev.facts.beta_oos") (t = #m("study.dev.facts.beta_oos_t")\; @ex-factors). The hedge ratio was below one in #m("paper.beta_below_one") of #m("main.trades") trades, and with legs of \$1 and \$β such a trade is not dollar-neutral: a long-spread trade is net long and a short-spread trade net short. By notional at the fill, #m("paper.long_net_long") of #m("paper.long_trades") long-spread trades were net long and #m("paper.short_net_short") of #m("paper.short_trades") short-spread trades net short#if D.m.at("paper.sign_exceptions_word") != "no" [; in #m("paper.sign_exceptions_word") #if D.m.at("paper.sign_exceptions_word") == "one" [trade] else [trades] a hedge ratio just above one was reversed by share rounding]. Annualised alpha is #m("study.dev.facts.alpha_main_pct") in the main backtest (t = #m("paper.alpha_t_main")) and #m("study.dev.facts.alpha_oos_pct") in the walk-forward (t = #m("paper.alpha_t_oos")). Daily returns are fat-tailed, with a spike at zero from the days the book was flat (@ex-distribution), which widens the Sharpe ratio's standard error. #if flag("multi_factor") [@ex-factors adds the five factors of #cite(<fama2015>, form: "prose"), momentum @carhart1997 and short- and long-term reversal, with Newey--West errors.] else [The multi-factor attribution, on the five factors of #cite(<fama2015>, form: "prose"), momentum @carhart1997 and short- and long-term reversal with Newey--West errors, is forthcoming (@tab-forthcoming).]

#claim("kurtosis_fat") #claim("flat_days_reconcile")
#exhibit-pair(
  ("factors", [The only loading measured so far is a small market beta, significant in the walk-forward],
    (sub: [Beta to the sector-ETF market proxy with 95% interval (Newey–West)],
     notes: [Proxy: #m("paper.proxy").],
     source: [#run-source, including the sector SPDR ETFs.])),
  ("distribution", [Daily returns are fat-tailed (kurtosis #m("study.dev.facts.kurtosis")) with a spike at zero from flat days],
    (sub: [Distribution of daily net returns, bp of capital; main backtest],
     notes: [Skew #m("study.dev.facts.skew")\; kurtosis is non-excess (3 for a normal distribution). The book held no position at the close on #m("study.dev.facts.flat_days") days; on #m("paper.flat_nonzero_days") of them positions were closed that day, so #m("paper.zero_return_days") days have exactly zero return. Fat tails widen the Sharpe ratio's standard error, which the power figures in @sec-inference account for.],
     source: [#run-source.])),
)

// ══════════════════════════════════════════════════════════════════════════════════════
= A second strategy family: residual reversion <sec-residual>
// ══════════════════════════════════════════════════════════════════════════════════════

A null on one rule says little about the idea. #cite(<avellaneda2010>, form: "prose") trade each stock's residual against its sector ETF when that residual, modelled as a mean-reverting process, is stretched; many small concurrent bets give the test far more power than #m("main.trades") pair trades. The parameters are taken from the paper unchanged: a 60-day regression on the sector ETF, an AR(1) fit of the cumulative residual, trades only when mean reversion is faster than 30 days, entry at |_s_| > 1.25, exits at −0.50 (long) and 0.75 (short), next-day fills and the same cost model. The arm runs on the development calendar with the v33 code and then, once, on the holdout (@sec-holdout). #if flag("residual") [On the development calendar it made #m("paper.residual.trades") trades and returned #m("paper.residual.ret_pct"), a net Sharpe ratio of #m("paper.residual.sharpe") (95% interval #m("paper.residual.lo") to #m("paper.residual.hi")\; Newey–West p = #m("paper.residual.p")\; @ex-residual).] else [It has not yet run on the development calendar; its result is forthcoming (@tab-forthcoming).]

#exhibit("residual",
  [Avellaneda–Lee residual reversion against the pairs strategy, development period],
  sub: [Net Sharpe ratio with 95% interval, same universe and costs],
  source: [Author's backtests on the development calendar.])

// ══════════════════════════════════════════════════════════════════════════════════════
= #if prereg [The pre-registered 2026 test] else [The 2026 holdout test] <sec-holdout>
// ══════════════════════════════════════════════════════════════════════════════════════

#claim("holdout_sealed")
Every design choice in this study was made on #m("paper.data_years") data over #m("paper.versions_count") versions, so the development period cannot test those choices. The decisive test therefore runs on data none of them has seen: trading days from #m("paper.holdout_start_long"). No 2026 daily price series has been fetched for any stock or ETF. Two inputs do carry 2026 market information: the v32 universe ranks stocks by market capitalisation on #m("paper.universe_as_of_long"), and the factor files of the Kenneth French library extend into 2026. No strategy reads factor data, and every run truncates the files at its own calendar's last day; the ranking sets the frozen v32 arm's membership in 2026, a look-ahead disclosed in @tab-threats. The protocol is committed first; each arm then runs once, and its result is published whatever it is. At the date of this note the pre-registration is #m("paper.prereg_status")\; @tab-hypotheses gives the hypotheses it #if prereg [fixes] else [is to fix].

#tablefig("hypotheses", if prereg [Hypotheses of the pre-registration, filed before any 2026 price series was fetched] else [Hypotheses proposed for the pre-registration, to be filed before any 2026 price series is fetched],
  booktab(columns: (8%, 52%, 40%), align: (left, left, left),
    header: ([], [Arm], [Hypothesis]),
    rows: T("hypotheses")),
  notes: [Test: one-sided Newey–West t on daily net returns, Holm-adjusted across H1 and H2 at 5%. The frozen v32 arm (S3) is reported with the same statistics but tested in no family: its universe is ranked on market values inside the test period, so a rejection could reflect survivorship rather than an edge.])

For each arm _k_ the null hypothesis is that the mean daily net return over the holdout is at most zero, against the alternative that it is positive. The test is the one-sided Newey--West t-test on the daily net return series; the two confirmatory p-values (H1 and H2) are adjusted with the step-down procedure of #cite(<holm1979>, form: "prose") at a familywise level of 5%, and an arm shows an edge out of sample only if its adjusted p-value is below 0.05. The frozen v32 arm reports the same statistics but enters no test, because its universe is ranked inside the test period. Whatever the outcome, each arm reports its net and gross return, its Sharpe ratio with standard error, the probabilistic Sharpe ratio, the block-bootstrap interval, the one-sided upper bound, trades and exposure, and, for the pairs arms, the Ledoit--Wolf difference against the Gatev method and the random-pair percentile on the same holdout.

*Power, stated in advance.* About ten months of data can detect only a large Sharpe ratio. With returns shaped like the development period's (skewness #m("paper.holdout_power.skew"), non-excess kurtosis #m("paper.holdout_power.kurtosis"), lag-1 autocorrelation #m("paper.holdout_power.rho")), a test at Holm's first step (one-sided 2.5%, the level the better of the two arms must reach) with 80% power detects an annualised Sharpe ratio of about #m("paper.holdout_power.mde_200") over the registered #m("paper.holdout_power.registered_days") trading days and #m("paper.holdout_power.mde_252") in a full year (@tab-holdout-power). The holdout is therefore a falsification check, not a proof of an edge: it can reject a large edge but cannot confirm a small one, and not rejecting the null is not evidence that the edge is zero, which is why each arm's upper confidence bound is reported. Running v32 alone first would spend the holdout, so v33 is #if prereg [frozen] else [to be frozen] before any 2026 price series is fetched, and all three arms run once; two are tested.

#tablefig("holdout-power", [Smallest annual Sharpe ratio the holdout detects with 80% power at Holm's first step (one-sided 2.5%)],
  booktab(columns: (34%, 33%, 33%), align: (right, right, right),
    header: ([Holdout length, trading days], [Returns shaped like the development period's], [Independent normal returns]),
    rows: T("holdout_power")),
  notes: [Six months, the registered calendar of 2 January to 19 October 2026, and a year. The development shape uses the asymptotic Sharpe variance for non-normal returns with lag-1 autocorrelation, as in @tab-alternatives; it is computed from development returns only.],
  source: [Author's calculation from the daily net returns of the v#m("paper.version") run.],
  placement: top)

#exhibit("holdout",
  [Cumulative net return on the 2026 holdout, by arm],
  sub: [Daily, from #m("paper.holdout_start_long")\; v33 pairs, Avellaneda–Lee and v32 frozen, same costs],
  source: [Author's single run of each arm on the 2026 holdout.])

// ══════════════════════════════════════════════════════════════════════════════════════
= Threats to validity <sec-threats>
// ══════════════════════════════════════════════════════════════════════════════════════

Each limitation, which way it biases the result, how large it is, and what addresses it (@tab-threats). Biases that flatter the strategy make the null more convincing, not less.

#let up = text(font: sans-md, fill: col("neg"))[↑ flatters]
#let down = text(font: sans-md, fill: col("pos"))[↓ penalises]
#let either(body) = text(font: sans-md, fill: ink2)[· #body]
#[
#show figure: set block(breakable: true)
#tablefig("threats", [Threats to validity of the v32 study run and the 2026 test],
  booktab(columns: (24%, 14%, 31%, 31%), align: (left, left, left, left), size: 7pt, inset-y: 2.9pt,
    header: ([Threat], [Direction of bias], [Size], [Mitigation]),
    rows: (
      ([Survivorship, and an approximate index], up, [Unmeasured: the universe is the #m("paper.names_file") largest stocks of #m("paper.universe_as_of_long"), back-filled, so pairs broken by failures and delistings are missing], [v33: point-in-time membership from IWV holdings in SEC N-PORT filings, with the coverage gap at each formation reported (#see("universe"))]),
      ([Design choices were made on the same data], up, [#m("paper.versions_count") versions on #m("paper.data_years")\; deflated Sharpe with #m("study.dev.facts.dsr_trials") trials is a lower bound], [2026 holdout#if not prereg [, to be pre-registered]\; declared variant family with SPA, stepdown, MCS and PBO]),
      ([The walk-forward reuses tuned thresholds], up, [Entry, exit and stop thresholds and the regime gate were tuned on data inside the walk-forward], [Called walk-forward, not out of sample; the holdout is the out-of-sample test]),
      ([Re-selection can drop pairs but not add them], down, [The pool can only shrink after #m("paper.formation_year")], [v33: full re-formation every #m("paper.v33_reselect_every") trading days on the trailing #m("paper.v33_formation_years") years]),
      ([Borrow is general-collateral for every name], up, [Borrow was \$#m("study.dev.facts.borrow_usd_k")k of \$#m("study.dev.facts.cost_usd_k")k costs; specials and recalls are not modelled], [v33: #m("paper.v33_borrow_pct") buy-side median fee; hard-to-borrow stress]),
      ([Fills are close-to-close], either[either way], [Larger leg #m("study.dev.facts.adv_participation_pct") of ADV on average; no auction or queue model], [_t_ + 1 open variant; closing-auction cost model planned]),
      ([Ranker features include pair statistics estimated on the formation window], up, [Small: out-of-sample AUC #m("ranker.oos_auc"), no useful skill to inflate], [v33: the ranker becomes an ablation arm only]),
      ([The neural ranker sees one 30-feature vector], either[none on P&L], [A sequence of length one: functionally a residual multilayer perceptron], [v33: L2 logistic and gradient-boosted trees]),
      ([Sector features are coarse], down, [Pairs are not restricted to one industry, so many are economically unrelated], [v33: pairs within one Fama–French 49 industry]),
      ([The 126-day re-selection check has little power], down, [In simulation it passes about a quarter of non-cointegrated pairs and drops a third to two thirds of cointegrated ones], [v33: replaced by full re-formation]),
      ([The price cache used through v31 was built with a full-sample penny-stock screen], either[none for v32], [The v32 run used a freshly fetched v32 cache], [Fetch manifest and coverage check in every run]),
      (["Point-in-time" prices undo splits, not dividends], either[either way], [Early prices are understated by later dividends in the \$5 price screen and the per-share cost terms, by more than a tenth on some snapshot date for about two in five mapped names with prices (measured in `reference/README.md`)], [v33: the price level is anchored to N-PORT's value per share at every snapshot date; the v32 arm keeps the vendor's levels]),
      ([Splits after the data window cannot be undone], either[either way], [The vendor back-adjusts history for every split up to the fetch date but reports split events only inside the requested window, so the price levels of names that split later carry a constant factor and they are mis-screened (measured against N-PORT in `reference/README.md`); returns, z-scores and hedge ratios are unaffected (a constant factor)], [v33: anchored to N-PORT's value per share at every snapshot date; the v32 arm keeps the vendor's levels]),
      ([The regime gate was tuned on windows now inside the test period], either[either way], [New entries blocked on #m("study.dev.facts.gate_blocked_days") of #m("study.dev.facts.days") days], [v33: off by default; counted as a declared variant]),
      ([Hedge ratios below one leave market exposure], either[adds beta], [Beta t = #m("study.dev.facts.beta_oos_t") in the walk-forward (@ex-factors)], [v33: multi-factor attribution]),
      ([The main backtest and the walk-forward overlap], up, [#m("study.dev.facts.oos_overlap_days") of #m("study.dev.facts.main_days") days in common, same pair pool], [The holdout is the independent test]),
      ([The random-pair control trades a different rule], either[weakens the comparison], [Random pairs run through the Gatev rule, not this engine], [A control on the strategy's own engine is planned]),
      ([The v32 arm's universe in the holdout is membership as of #m("paper.universe_as_of_long")], up, [Look-ahead in membership for the frozen v32 arm (H3) during 2026], [#if prereg [Disclosed] else [To be disclosed] in the pre-registration; the v33 and Avellaneda–Lee arms use point-in-time membership]),
      ([Factor files from the Kenneth French library extend into 2026], either[none on trading], [No strategy reads factor data], [Every run truncates them at its own calendar's last date; no development export holds a 2026 factor return]),
      ([Renamed securities with a new CUSIP look like delistings], either[overstates the gap], [Before the data review, counted in the measured survivorship gap], [Remapped through N-PORT tickers, issuer successions and mappings checked against N-PORT's value per share; a search over every identifier still without a priced ticker finds no other]),
    )),
  notes: [↑ flatters the strategy; ↓ penalises it; · no single direction.])
]

// ══════════════════════════════════════════════════════════════════════════════════════
// Forthcoming results: every result still absent, with what it will show
// ══════════════════════════════════════════════════════════════════════════════════════
#if D.forthcoming.len() > 0 [
  = Forthcoming results <sec-forthcoming>

  Each analysis below is specified, and its exhibit or table is built, but its results are not yet among the committed data this note reads. When they are, the item leaves this table and appears in its section. None of them is reported here as a number.

  #tablefig("forthcoming", [Forthcoming results],
    booktab(columns: (22%, 56%, 22%), align: (left, left, left),
      header: ([Analysis], [What it will show], [Awaits]),
      rows: D.forthcoming.map(r => (text(font: sans-md, r.at(1)), r.at(2), r.at(3)))))
]

// ══════════════════════════════════════════════════════════════════════════════════════
= Reproducibility <sec-repro>
// ══════════════════════════════════════════════════════════════════════════════════════

#if D.concordance != none [The research-note site presents the same results; @tab-concordance maps its exhibit numbers to this note's.] Every number in this note is formatted by `scripts/build_paper.py` from `assets/study.json`, the file the research-note site's charts and checked numbers come from, and from the headline JSON that file was built from; the site's numbers are checked against the same JSON by `scripts/check_published_numbers.py`. Prices come from Yahoo Finance's chart API, and a later fetch will not match the cached data bit for bit, because vendors revise history. The run manifest (@tab-manifest) pins what was used, and the sha256 of every committed source the note reads is listed in @tab-hashes; both are in the appendix.

The run's universe file is not redistributed. `scripts/build_universe.py` rebuilds a universe from the Nasdaq screener on the day it runs, which gives that day's membership, not the list of #m("paper.universe_as_of_long")\; the commands below instead recreate the run's #m("paper.fetch.symbols") symbols from its fetch manifest. The execution-cost note, `docs/EXECUTION_COSTS.md`, compares the cost model with published impact estimates at each participation rate and gives the source of the v33 borrow fee; `tests/test_cost_model_zoo.py` keeps the model inside that band. The AR(1) variance of the Sharpe ratio and its source are documented in `pairs_trading/power.py`, and the synthetic validation is `scripts/synthetic_validation.py`.

#wide(block(width: 100%, fill: sunk, inset: (x: 9pt, y: 8pt), radius: 2pt, breakable: false, {
  set text(size: 8.4pt)
  raw(block: true, lang: "bash", "# the study: the v32 design on the development calendar
pip install -r requirements.txt
mkdir -p data
python - <<'EOF'      # the run's universe, from its fetch manifest
import json
symbols = sorted(json.load(open('" + D.meta.at("fetch_manifest", default: none) + "'))['outcomes'])
open('data/marketcap.csv', 'w').write('Symbol\\n' + '\\n'.join(symbols) + '\\n')
EOF
python -m pairs_trading.main --profile v32 --calendar dev   # writes outputs/

# publish a run: copy outputs/ to results/<run>/, then
python scripts/build_site_data.py --dev results/" + D.meta.headline.split("/").at(1) + "
python scripts/check_published_numbers.py --json " + D.meta.headline + "

# this paper (needs the optional typst package: pip install -e \".[paper]\")
python scripts/build_paper.py           # data, figures and PDF
python scripts/build_paper.py --check   # exit 1 if any of them is stale")
}))

// floats of the sections above are placed before the disclosures
#place.flush()

#heading(numbering: none)[Disclosures]

Hypothetical, backtested results on \$#m("study.dev.facts.capital_musd")M of notional capital, not achieved by any account. Returns are net of the modelled costs described in @sec-costs unless labelled gross, earn no interest on cash, and are shown beside baselines run under the same costs. Hypothetical results have inherent limitations, including those listed in @sec-threats. This is a research project: not investment advice, not an offer of any product, and no claim of deployable performance. The cost schedules are parameter sets, not descriptions of any firm. Code under the MIT licence; IBM Plex typefaces under the SIL Open Font License 1.1.

#heading(numbering: none)[References]
#{
  set text(size: 8.6pt, hyphenate: false)
  set par(justify: false, leading: 0.5em, spacing: 0.62em, hanging-indent: 1.2em)
  // a title that ends in "?" takes no full stop after its closing quote
  show "?’.": "?’"
  bibliography("references.bib", title: none, style: "chicago-author-date")
}

// ══════════════════════════════════════════════════════════════════════════════════════
// Appendix: tables only, each under its own caption
// ══════════════════════════════════════════════════════════════════════════════════════
#pagebreak(weak: true)
#counter(heading).update(0)
#heading(numbering: none)[Appendix]

#tablefig("spec", [Specification of the v#m("paper.version") study run],
  booktab(columns: (14%, 86%), align: (left, left),
    header: ([Stage], [Rule]),
    rows: (
      ([Universe], [The #m("paper.names_file") largest US common stocks by market cap on #m("paper.universe_as_of_long") (the Russell 3000 rule applied to the Nasdaq screener)#if flag("fetch") [; #m("paper.fetch.ok") of its #m("paper.fetch.symbols") symbols have prices]\; daily prices #m("paper.data_years")\; screens on point-in-time (split-unadjusted) price and dollar volume; the #m("paper.universe_top") most liquid enter the pair search.]),
      ([Selection], [Positive return correlation ≥ 0.25; two-direction Engle–Granger p < 0.05 (Bonferroni across directions); half-life 4–25 days on the cointegrating spread; quality score. Every #m("paper.v32_reselect_every") trading days a re-test on the trailing #m("paper.v32_formation_years") years, with the Engle–Granger p-value on the last 126 calendar days at most 0.30; pairs can drop out, not enter.]),
      ([Spread], [Two-state Kalman filter (slope and intercept) on log prices centred on their burn-in means, so β is a hedge ratio and signals are invariant to vendor back-adjustment.]),
      ([Rule], [One β-locked z-score against its mean and standard deviation over the last 30–60 bars, frozen at the signal. Entry |_z_| ≥ 1.8; target once _z_ reverts past −0.5 (long) or +0.5 (short); stop 1.5 further against; time stop clamp(2.5 × half-life, 10, 25) days. Gates: 20-day correlation ≥ 0.20, β in [0.25, 4], a 30-day bar after three consecutive losses, VIX and sector-dispersion regime scaling.]),
      ([Book], [\$#m("study.dev.facts.capital_musd")M notional; 3–10% of equity per pair before regime scaling (#m("paper.position_min_pct") to #m("paper.position_max_pct") as traded); 30% gross cap; at most 8 entries a day; no shared legs; daily mark-to-market; drawdown and daily-loss kill switch.]),
      ([Ranker], [A classifier of P(trade profitable) on 30 features, used only to order same-day candidates; out-of-sample AUC #m("ranker.oos_auc") (#m("ranker.wf_pooled_auc") pooled across walk-forward windows; 0.5 is no skill).]),
      ([Walk-forward], [One continuous simulation on a 252-day train / 63-day test grid, the last window running to #m("paper.oos_end_long")\; the ranker is refit per window; per-window figures are calendar slices.]),
      ([Evidence], [Probabilistic and deflated Sharpe, Newey–West t, Politis–White block bootstrap, Lo (2002) autocorrelation-adjusted annualisation, Ledoit–Wolf Sharpe-difference test, PBO; Gatev distance method and random pairs under the same costs and _t_ + 1 fills.]),
    )))

#claim("ranker_no_skill")
#tablefig("profiles", if prereg [The v32 design and the pre-registered v33 design] else [The v32 design and the v33 design proposed for pre-registration],
  booktab(columns: (18%, 38%, 44%), align: (left, left, left),
    header: ([Choice], [v32 (run reported here)], [v33 (#if prereg [pre-registered] else [proposed])]),
    rows: T("profiles")),
  notes: [None of the v33 choices was made by its effect on development-period P&L; the ranker was dropped for its lack of predictive skill on that period. The reasons are stated next to each setting of the study's design profiles.])

#tablefig("variants", [Variants declared on #m("paper.declared_long") for the data-snooping tests],
  booktab(columns: (26%, 74%), align: (left, left),
    header: ([Variant], [What it changes]),
    rows: T("variants").map(r => (text(font: mono, size: 6.8pt, r.at(0)), r.at(1)))),
  notes: [The threshold grid covers the three hand-set trading thresholds, which were chosen across versions on this same data. Each toggle changes one setting of the v33 design.],
  source: [The declaration of the variant family, committed on #m("paper.declared_long").])

#claim("wf_flat_window_exists")
#tablefig("windows", [Walk-forward windows: calendar slices of one continuous simulation],
  booktab(columns: (7%, 13%, 13%, 13%, 7%, 12%, 10%, 10%, 15%), align: (right, left, left, left, right, right, right, right, right),
    header: ([Window], [Training from], [Test from], [Test to], [Days], [Net return, %], [Sharpe], [Trades opened], [Ranker AUC]),
    rows: T("windows")),
  notes: [Windows are numbered in calendar order. Each window's ranker is trained on the year before its test start. Positions carry across window boundaries, so a window that opens no trade can still carry P&L from earlier positions (window #m("paper.wf_carry_windows")). Sharpe ratios are annualised and not defined for a window whose daily returns are all zero (window #m("paper.wf_flat_windows")). The last window runs to the walk-forward's last day.],
  source: [#run-source.])

#tablefig("history", [Selected versions of the study],
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
      ([v33 (in progress)], [#if prereg [Pre-registered design] else [Design proposed for pre-registration]: point-in-time universe, same-industry pairs, full re-formation, regime gate off, one borrow fee, a second strategy family, the evidence layer and the sealed 2026 holdout.]),
    )),
  notes: [Versions that only withdrew or corrected earlier results are listed with the fixes they made.])

#tablefig("manifest", [Run manifest],
  booktab(columns: (16%, 84%), align: (left, left), header: ([Item], [Value]),
    rows: T("manifest").map(r => (r.at(0), text(font: mono, size: 6.6pt, r.at(1))))))

#tablefig("hashes", [Committed sources read by this note],
  booktab(columns: (46%, 54%), align: (left, left), header: ([File], [sha256]),
    rows: T("sources").map(r => (text(font: mono, size: 6.4pt, r.at(0)), text(font: mono, size: 6.4pt, r.at(1))))),
  notes: [The PDF is compiled with a fixed timestamp, the note's date, so a rebuild of unchanged inputs is byte-identical; the build manifest records the sha256 of every compile input and of the PDF.])

#if D.concordance != none {
  tablefig("concordance", [Exhibits of the research-note site and where they appear in this note],
    booktab(columns: (10%, 70%, 20%), align: (left, left, left),
      header: ([Site], [Title on the site], [This note]),
      rows: D.concordance.map(r => ([Exhibit #r.at(0)], r.at(1),
        if r.at(2) == none [—] else if r.at(2) == "forthcoming" [forthcoming (@tab-forthcoming)] else { ref(label(r.at(2))) }))),
    notes: [The site orders its exhibits by its own sections. Titles are the site's; where this note words a finding differently (for instance, it calls the walk-forward out of sample only for pair selection and the ranker), this note's wording applies. Exhibits of this note without a site counterpart are not listed.])
}
