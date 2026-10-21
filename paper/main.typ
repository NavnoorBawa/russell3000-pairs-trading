// The study's paper: the research-note site in print.
//
// Every result this file prints comes from build/paper_data.json, written by
// scripts/build_paper.py from assets/study.json (the data the site's charts and checked
// numbers come from) and the headline JSON it was built from. Numbers are placed with
// #m("key")\; a number that does not exist yet is null there and prints as "pending" with
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
#let run-source = [Author's backtest, #m("paper.design") development run (commit #m("paper.commit_short")); prices from Yahoo Finance]

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
    text(font: sans, size: 10pt, fill: ink2)[The #m("paper.universe_top") most liquid point-in-time members of the Russell 3000, traded as same-industry cointegrated pairs re-formed every #m("paper.reselect_every") trading days, with next-day fills and a per-stock cost model, #m("paper.period_start_month") to #m("paper.period_end_month").]
  }
  v(8pt)
  text(font: sans, size: 7.8pt, fill: ink2)[
    #text(font: sans-sb, fill: ink)[Navnoor Bawa] #h(5pt)·#h(5pt) Note of #m("paper.paper_date_long") #h(5pt)·#h(5pt) #m("paper.design") development run of #m("paper.run_date_long"), commit #raw(D.m.at("paper.commit_short"))
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
#claim("persistence_at_chance") #claim("decay_in_sample_significant") #claim("decay_oos_not_significant")
#claim("exit_race_like_random_walk") #claim("exit_race_rejects_selected_reversion") #claim("residual_ci_spans_zero")
#claim("ucb_below_one") #claim("sharpe_half_not_rejected") #claim("holdout_sealed")
#wide(block(width: 100%, inset: (x: 12pt, y: 11pt), fill: sunk, radius: 2pt, {
  grid(columns: (1fr, auto), align: (left + horizon, right + horizon),
    text(font: serif-sb, size: 10.8pt)[Summary],
    box(inset: (x: 6pt, y: 2.5pt), radius: 1.5pt, fill: ink,
      text(font: sans-sb, size: 7pt, fill: white, tracking: 0.06em, upper[No detectable edge])))
  v(3pt)
  set par(leading: 0.66em)
  [*No detectable edge, before or after costs.* From #m("paper.period_start_month") to #m("paper.period_end_month") the v33 design returned #m("main.total_return_pct") net on its capital, a Sharpe ratio of #m("main.sharpe") (95% interval #m("significance.main.boot_lo") to #m("significance.main.boot_hi")); the same rule started on #m("paper.oos_start_long"), the walk-forward, has a Sharpe ratio of #m("oos.pooled_sharpe") (#m("significance.oos_daily.boot_lo") to #m("significance.oos_daily.boot_hi")). Neither is distinguishable from zero, from the Gatev distance method (difference #m("benchmarks.sharpe_diff_vs_gatev.diff"), p = #m("benchmarks.sharpe_diff_vs_gatev.p")) or from random pairs (#m("paper.percentile_ordinal") percentile). Before costs the average trade earned #m("study.dev.facts.gross_bp")~bp of its notional (t = #m("study.dev.facts.gross_t")) against #m("study.dev.facts.cost_bp")~bp of modelled cost: there is no gross edge for costs to remove.

  The trades show why. Pairs cointegrated in one year are cointegrated the next at the chance base rate (#m("study.dev.facts.pers_pct") against #m("study.dev.facts.pers_expected_pct") expected). The same rule on the same pairs earns #m("study.dev.facts.decay_form_bp")~bp a trade on the data that selected them and #m("study.dev.facts.decay_oos_bp")~bp afterwards. Out of sample, #m("study.dev.facts.er_targets") trades reached their profit target first, against #m("study.dev.facts.er_rw_expected") expected for a random-walk spread and #m("study.dev.facts.er_ou_expected") for the mean reversion the selection assumed. A second strategy family, Avellaneda–Lee residual reversion on the same universe rule and costs, agrees (Sharpe #m("study.residual.sharpe"), #m("study.residual.lo") to #m("study.residual.hi")). The sample rules out a Sharpe ratio above #m("study.dev.facts.sharpe_ucb") (one-sided 95% bound) but cannot tell 0 from 0.5. The decisive test, one run of each arm on 2026 data, is sealed: #if prereg [its pre-registration was filed before any 2026 price was fetched.] else [its pre-registration is to be filed before any 2026 price is fetched.]]
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
#claim("mde_above_bound") #claim("break_even_below_one")
#wide(grid(columns: (1fr, 1fr, 1fr), column-gutter: 12pt, row-gutter: 9pt,
  kpi([Main backtest · net Sharpe], m("main.sharpe"),
    [95% interval #m("significance.main.boot_lo") to #m("significance.main.boot_hi") · Newey–West p = #m("significance.main.hac_p") · #m("study.dev.facts.main_days")~days]),
  kpi([Walk-forward · net Sharpe], m("oos.pooled_sharpe"),
    [95% interval #m("significance.oos_daily.boot_lo") to #m("significance.oos_daily.boot_hi") · Newey–West p = #m("significance.oos_daily.hac_p") · #m("study.dev.facts.oos_days")~days]),
  kpi([Gross edge per trade], [#m("study.dev.facts.gross_bp")~bp],
    [Before costs · t = #m("study.dev.facts.gross_t") · cost #m("study.dev.facts.cost_bp")~bp · n = #m("main.trades") · net P&L breaks even at #m("study.dev.facts.break_even_x") costs]),
  kpi([Upper bound on the Sharpe ratio], m("study.dev.facts.sharpe_ucb"),
    [One-sided 95%, allowing for fat tails and autocorrelation · 80% power only at #m("study.dev.facts.sharpe_mde")]),
  kpi([Second family · net Sharpe], m("study.residual.sharpe"),
    [Avellaneda–Lee · 95% interval #m("study.residual.lo") to #m("study.residual.hi") · #m("study.residual.trades") trades]),
  kpi([2026 holdout · net Sharpe], [Sealed],
    [#if prereg [Pre-registered] else [Pre-registration to be filed] · 80% power only at a Sharpe of #m("study.dev.facts.ho_mde_025") over #m("study.dev.facts.ho_days")~days]),
))

// ══════════════════════════════════════════════════════════════════════════════════════
= Introduction
// ══════════════════════════════════════════════════════════════════════════════════════

== The question

Pairs trading buys one stock and sells another when the spread between them is unusually wide, and closes the position when it narrows. #cite(<gatev2006>, form: "prose") documented excess returns from a simple distance rule on US stocks over four decades; later studies find that the edge has shrunk and is small after realistic costs @do2010 @do2012 @rad2016, and #cite(<krauss2017>, form: "prose") surveys the methods. This note asks one question and is built to answer it honestly: *does a cointegration pairs-trading strategy on the Russell 3000 have an edge after realistic execution and costs, out of sample?*

It reports the v33 design. Pairs are selected within one Fama–French 49 industry from the point-in-time members of the Russell 3000, with the Engle--Granger test @engle1987 on formation data only, and the whole selection is re-run every #m("paper.reselect_every") trading days on the trailing #m("paper.formation_years_word") years. Each pair's hedge ratio is tracked with a two-state Kalman filter @kalman1960, a z-score of the hedged spread is traded with fills at the next day's close, and every fill pays costs computed from the stock's own liquidity. The design is evaluated in a main backtest from #m("paper.period_start_long") to #m("paper.period_end_long"), in a walk-forward that runs the same rule from #m("paper.oos_start_long"), against two baselines run on the same footing (the distance method of #cite(<gatev2006>, form: "prose") and #m("benchmarks.random_control.n_draws") portfolios of random pairs) and beside a second strategy family. The v32 study published on #m("paper.v32_run_date_long") is the history this design starts from (@sec-v32): it is kept as the record, and runs frozen and untested as the third arm of the holdout.

The answer for #m("paper.years") is a null. A null is informative only to the extent that the test had power and the measurement was right, so most of this note is about what the sample can rule out (@sec-inference), why there is no edge (@sec-anatomy) and the checks that the code measures what it claims (@sec-validation). The development period cannot test design choices made on it; a 2026 holdout, sealed at the date of this note, does that (@sec-holdout).

== What is new

The study uses free data only. Academic studies avoid survivorship with paid point-in-time databases; a backtest on free data usually starts from today's index members instead, and is exposed to the other familiar weaknesses of backtests: flat cost assumptions, significance without power, a null left unexplained, and an untold number of designs tried. Each item below addresses one of these; the last adds a test the development data cannot provide.

#claim("gap_shrinks")
- *A point-in-time universe from free SEC filings.* The complete holdings of the iShares Russell 3000 ETF (IWV) are public on Form N-PORT for the last month of each fiscal quarter; #m("paper.iwv.n") quarterly snapshots give index membership as it was at each formation date, without a paid constituent history. The survivorship gap is measured at every formation: #m("study.dev.facts.gap_first_pct") of index weight at the first, #m("study.dev.facts.gap_last_pct") at the last (@sec-data).
- *Costs from each stock's own liquidity, stressed in full re-runs.* Every fill pays commission, half the quoted spread for the stock's dollar-volume bucket and square-root market impact on the stock's own volatility and volume, at the next day's close. Each cost and capacity scenario declared in advance re-runs the whole backtest (@sec-costs).
- *An anatomy of the null.* The same rule in sample and out of sample, the persistence of cointegration, the race between targets and stops against a random-walk spread, and the traded pairs' half-lives explain the null trade by trade (@sec-anatomy).
- *Power and hurdles.* Each null is reported with the Sharpe ratios it excludes, the Sharpe ratio it could have detected, the track record a given Sharpe ratio would need and the hurdles a result must clear after #m("study.dev.facts.hurdle_tests") recorded versions (@sec-inference).
- *A second strategy family.* Avellaneda–Lee residual reversion, with the paper's parameters, on the same universe rule, fills and costs (@sec-residual).
- *A record of every trial.* Every run whose result was seen is in an append-only registry, an unpublished exploratory run included, and a variant family declared before any variant ran feeds the data-snooping tests (@sec-snooping).
- *A sealed 2026 holdout.* Hypotheses, test, multiplicity correction and decision rule #if prereg [were fixed in a pre-registration] else [are to be fixed in a pre-registration] before any 2026 price series is fetched; each arm then runs once and its result is published whatever it is (@sec-holdout).

== Related work

The published record points one way: the classic pairs edge was large before the 2000s, has shrunk since, and is small after realistic costs (@tab-literature). The closest analogue of this study is #cite(<rad2016>, form: "prose"), who compare distance, cointegration and copula methods on US stocks; this study differs in period, universe, cost model and inference. #cite(<clegg2014>, form: "prose") finds little evidence that pairs cointegrated in one year remain cointegrated in the next, the result this study's anatomy replicates (@ex-persistence). #cite(<avellaneda2010>, form: "prose") trade residuals of single stocks against sector ETFs and factors, the second strategy family of this study (@sec-residual).

#tablefig("literature", [Published results for pairs trading and residual reversion, as reported by their authors],
  booktab(columns: (20%, 14%, 22%, 44%), align: (left, left, left, left),
    header: ([Study], [Sample], [Method], [Reported result]),
    rows: (
      ([#cite(<gatev2006>, form: "prose")], [US, 1962–2002], [Distance method, top-20 pairs], [Annualised excess returns of up to 11% before costs, falling in later years. The baseline replicated here.]),
      ([#cite(<do2010>, form: "prose")], [US, to 2009], [Distance method], [Profitability declines over time; the strategy does best in prolonged turbulence.]),
      ([#cite(<avellaneda2010>, form: "prose")], [US, 1997–2007], [PCA and sector-ETF residual reversion], [Net Sharpe 1.44 (PCA) and 1.1 (ETF) over 1997–2007; PCA only 0.9 over 2003–2007. The second family tested here.]),
      ([#cite(<do2012>, form: "prose")], [US, 1963–2009], [Distance method with trading costs], [About 30 bp a month for well-matched pairs in refined industries after costs; largely unprofitable after 2002.]),
      ([#cite(<clegg2014>, form: "prose")], [US], [Persistence of cointegration], [Little evidence that pairs cointegrated in one year stay cointegrated the next. Replicated here.]),
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
      ([SEC EDGAR: Form N-PORT filings of IWV], [Quarterly holdings of the iShares Russell 3000 ETF, with each holding's value per share], [Point-in-time index membership; the anchor of point-in-time price levels]),
      ([OpenFIGI mapping API], [CUSIP to ticker], [Joining holdings to price histories]),
      ([SEC EDGAR: company submissions], [SIC industry code per registrant], [Fama–French 49 industries for same-industry pairs; sector ETFs for the second family]),
      ([Kenneth French data library], [Fama–French five factors, momentum, short- and long-term reversal, one-month T-bill], [Factor attribution]),
      ([FRED], [Three-month Treasury bill rate], [The cash comparison]),
      ([Nasdaq stock screener], [Market capitalisation of US-listed common stocks], [The v32 universe and the frozen arm S3]),
    )))

== Point-in-time membership from N-PORT filings

A registered fund reports its complete portfolio holdings on Form N-PORT, and the report for the third month of each fiscal quarter is made public on EDGAR. IWV tracks the Russell 3000, so its filings give index membership as it was, quarter by quarter, at no cost. The study reads the equity-common holdings of #m("paper.iwv.n") snapshots from #m("paper.iwv.first_long") to #m("paper.iwv.last_long"), #m("paper.iwv.equity_min") to #m("paper.iwv.equity_max") holdings each, and maps each holding's CUSIP (or ISIN) to a ticker through OpenFIGI, N-PORT's own reported tickers, issuer successions and a check against N-PORT's value per share (@ex-snapshots). A snapshot is in force from the date its holdings describe until the next one. Two caveats: IWV is a fund, not the index, and holds fewer names than the index; and additions and deletions within a quarter appear only at the next quarter end. Snapshots dated #m("paper.iwv.sealed_from_long") or later (#m("paper.iwv.sealed") filings) are listed but not downloaded: their holdings carry a market value, and so a 2026 price, for every member.

== The universe of the run

At each formation the members of the snapshot in force that have price history go through the formation screen on the trailing window: a point-in-time close of at least \$5 and a dollar volume of at least \$10M a day on average, annualised volatility between 5% and 80%, and fewer than 10% missing closes. The #m("paper.universe_top") most liquid by dollar volume enter the pair search, and a pair's two legs must share one Fama–French 49 industry, from each registrant's SEC SIC code. Daily prices from #m("paper.data_start_long") to #m("paper.data_end_long") were fetched for #m("study.dev.facts.coverage_pct") of the requested symbols, and #m("paper.names_prices") symbols have usable history.

#claim("iwv_gap_shrinks")
#exhibit("snapshots",
  [Free filings give #m("paper.iwv.n") quarterly snapshots of index membership; the index weight without a usable ticker falls from #m("paper.iwv_unmapped_first_pct") to #m("paper.iwv_unmapped_last_pct")],
  sub: [Equity holdings of the iShares Russell 3000 ETF in its N-PORT filings, #m("paper.iwv_first_year")–#m("paper.iwv_last_year"), and the share of their value that cannot be mapped to a ticker],
  notes: [A holding without a usable ticker is one no source maps; one whose last ticker now belongs to another issuer; one whose mapping a price check against N-PORT's value per share rejected; or one that would take the ticker another holding of the snapshot has as its own line. The last three are left unmapped on purpose, so that no member is joined to another security's prices. The share is larger in older snapshots, as expected if most such holdings are securities that have since delisted; its weight is part of the survivorship gap.],
  source: [SEC EDGAR, Form N-PORT-P filings of the iShares Russell 3000 ETF (iShares Trust, series S000004341); tickers from OpenFIGI and N-PORT; author's calculations.])

== The survivorship gap, measured

#claim("gap_first_is_first_formation")
The survivorship gap at a formation date is the index weight of members a backtest cannot trade: holdings without a usable ticker, plus members with a ticker whose price history the free vendor no longer serves, mostly companies acquired or delisted since. At the first formation #m("study.dev.facts.gap_first_missing") of #m("study.dev.facts.gap_first_members") members had no price history (#m("universe.missing_value_weight_pct") of index weight) and holdings without a usable ticker added #m("universe.unmapped_value_weight_pct")\; at the last, #m("study.dev.facts.gap_last_missing") of #m("study.dev.facts.gap_last_members") members had none. The gap falls from #m("study.dev.facts.gap_first_pct") to #m("study.dev.facts.gap_last_pct") (@ex-universe) because the older the snapshot, the more of its members have since left the market. Those names are the likeliest to have had deal-driven spread breaks, so the gap probably favours a convergence strategy: it flatters the result and makes the null more convincing, not less (@sec-threats).

#exhibit("universe",
  [The survivorship gap, measured: index weight without price history falls from #m("study.dev.facts.gap_first_pct") at the first formation to #m("study.dev.facts.gap_last_pct") at the last],
  sub: [Members of the index snapshot in force at each formation, and the share of index weight the price data do not cover (darker: members without price history; lighter: holdings without a usable ticker)],
  notes: [A pair that includes a member without price history cannot be formed. Shares are of each snapshot's equity value. The first two formations use the same snapshot: the initial selection at the cutoff and the first re-formation, at the first session after it.],
  source: [#run-source, universe by formation; membership from the index fund's holdings in SEC N-PORT filings.])

== Price levels anchored to N-PORT

The vendor back-applies every split and dividend up to the fetch date but reports split events only inside the requested window. Early price levels of names that split or paid dividends later are therefore rescaled, and a screen on the price level, such as the \$5 floor, or a cost term per share, would read a level the market never showed. v33 anchors the point-in-time close to N-PORT's own value per share at every snapshot date. The anchoring moved #m("study.dev.facts.anchor_moved") of #m("study.dev.facts.anchor_symbols") price histories (#m("study.dev.facts.anchor_moved_pct")) by more than 10%, with ratios from 1/#m("study.dev.facts.anchor_min_ratio_inv") to #m("study.dev.facts.anchor_max_ratio")\; the largest are splits in 2026 that the vendor had applied to the whole history. Returns, z-scores and hedge ratios are unaffected, since a constant factor cancels in each of them.

== The v32 universe

v32 drew its universe from the Nasdaq stock screener: the #m("paper.v32_universe_selected") largest US common stocks by market capitalisation on #m("paper.v32_universe_as_of_long"), back-filled to #m("paper.data_first_year"). That list holds only survivors, and its ranking uses market values from inside the 2026 test period. It is kept for one purpose: the frozen v32 arm (S3) of the holdout, which is reported but tested in no family for that reason (@sec-holdout).

// ══════════════════════════════════════════════════════════════════════════════════════
= Method <sec-method>
// ══════════════════════════════════════════════════════════════════════════════════════

Selection sees formation data only; every trading decision on day _t_ uses data up to day _t_ and fills on day _t_ + 1; the evidence is computed after the run (@ex-pipeline). Tests change future prices and check that no past decision moves. @tab-spec in the appendix states every rule of the design on one page.

== From v32 to v33 <sec-design>

#claim("exploratory_run_on_record") #claim("v32_ranker_no_skill") #claim("v32_tested_more_pairs")
The v33 design differs from the published v32 design in seven fields of the study profile, each fixed for a reason that does not depend on development-period returns (@tab-design). The thresholds, the fills and the rest of the cost model are unchanged. Every change was fixed in the profile before the first v33 run. An exploratory v33 run was seen before the published one; both carry the same design hash, so no design field changed after a v33 result was seen, and the exploratory run stays on record (@tab-trials).

== Formation

#claim("half_lives_within_rule_at_formation")
Pairs are first selected on data to #m("paper.formation_cutoff_long"), and the whole selection is re-run every #m("paper.reselect_every") trading days on the trailing #m("paper.formation_years_word") years: #m("study.dev.facts.formations") formations in the run. Among the #m("paper.universe_top") most liquid screened members, every pair within one Fama–French 49 industry with a positive return correlation of at least 0.25 is tested for cointegration with the two-step Engle--Granger test in both directions, Bonferroni-adjusted across the two, at p < 0.05. A pair is kept if the half-life of its cointegrating residual lies between 4 and 25 trading days and a quality score exceeds 0.4: at the first formation, #m("fdr.final_selected_pairs") of #m("fdr.pairs_tested") pairs tested (@sec-multiple). A formation's pairs trade until the next formation replaces them; positions already open run off.

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
      dg-box[Universe][IWV snapshot in force \ point-in-time screens \ #m("paper.universe_top") most liquid], dg-arrow,
      dg-box(key: true)[Formation][same FF49 industry \ Engle–Granger p < 0.05 \ re-run every #m("paper.reselect_every") days], [], [], [], [],
      dg-lane[Trading][causal: data to day _t_],
      dg-box[Spread model][two-state Kalman \ slope β and intercept], dg-arrow,
      dg-box[Signal][β-locked z-score \ enter |_z_| ≥ 1.8 \ target 0.5, stop +1.5], dg-arrow,
      dg-box(key: true)[Execution][signal at close _t_ \ fill at close _t_ + 1 \ no shared legs], dg-arrow,
      dg-box[Costs][commission, spread \ √ impact per stock \ one borrow fee], dg-arrow,
      dg-box[Accounting][daily mark-to-market \ 30% gross cap \ kill switch],
      dg-lane[Evidence][after the run],
      dg-box[Significance][Newey–West t, bootstrap \ PSR, deflated Sharpe \ power, hurdles], dg-arrow,
      dg-box[Anatomy][persistence, decay \ exit race, half-lives \ shortfall, capacity], dg-arrow,
      dg-box[Baselines][Gatev distance rule \ #m("benchmarks.random_control.n_draws") random-pair draws \ same costs, _t_ + 1 fills], dg-arrow,
      dg-box[Scenarios][costs and book size \ declared in advance \ each a full re-run], [], [],
    )
    foot([Boxes framed in the accent colour mark the two look-ahead boundaries: the formation cutoff, after which selection sees no data, and the next-day fill, which separates a signal from its trade.],
      [Author's design of the #m("paper.design") study profile.])
  }) <ex-pipeline>]))

#exhibit("timeline",
  [Data splits: formation and re-formations, walk-forward, main backtest and the sealed holdout],
  sub: [Calendar #m("paper.data_first_year")–#m("paper.holdout_year")],
  notes: [The main backtest and the walk-forward share #m("study.dev.facts.oos_overlap_days") of the main backtest's #m("study.dev.facts.main_days") days and trade the same pair formations: they are one experiment from two start dates, not two confirmations.],
  source: [Author's study calendar (calendar dev; the holdout is calendar holdout2026).])

#tablefig("design", [From v32 to v33: what changed and why],
  booktab(columns: (13%, 25%, 27%, 35%), align: (left, left, left, left), size: 7pt,
    header: ([Field], [v32, as published], [v33], [Why, fixed before any v33 run]),
    rows: T("design")),
  notes: [The reasons are stated beside each setting of the study profiles in `pairs_trading/study_config.py`; the execution-cost note, `docs/EXECUTION_COSTS.md`, gives the source of the borrow fee.],
  placement: top)

== Spread model

The hedge ratio is the slope state of a two-state Kalman filter on log prices,
$ log p_(1,t) = alpha_t + beta_t log p_(2,t) + epsilon_t, $
where $(alpha_t, beta_t)$ follows a random walk, both log prices are centred on their burn-in means and the filter is seeded by ordinary least squares. The intercept makes β a hedge ratio rather than a ratio of price levels, and centring makes every signal invariant to a vendor's back-adjustment of history for a later split or dividend, which shifts each log price by a constant.

== Signal and exits

One z-score drives every decision. At a signal on day $t_0$ the hedge ratio is locked at its current value and the spread is standardised by its mean and standard deviation over the last 30 to 60 bars (three half-lives), both frozen at the signal:
$ s_t = log p_(1,t) - beta_(t_0) log p_(2,t), quad z_t = (s_t - mu_(t_0)) / sigma_(t_0). $
A pair is entered when |_z_| ≥ 1.8, long the spread when _z_ is negative and short when it is positive. It exits at the target once _z_ has reverted past −0.5 for a long spread or +0.5 for a short one, at the stop when _z_ has moved 1.5 further against the position, and at the time stop after max(10, min(⌊2.5 × half-life⌋, 25)) trading days. Entries also require a pair quality of at least 0.55, a 20-day return correlation of at least 0.20 and a hedge ratio in [0.25, 4]; after three consecutive losing trades a pair is paused for 30 calendar days. Same-day candidates are ordered by signal strength times pair quality. There is no regime gate and no learned ranker.

== Execution, accounting and risk limits

A signal computed on the close of day _t_ is filled at the close of day _t_ + 1, for entries and exits alike: in practice a market-on-close order in each stock's closing auction, so both legs print together. Share counts are fixed from the signal-day close and the legs are sized \$1~:~\$β. Positions are marked to market daily, costs are booked on fill days, and positions still open at the end of the data are closed. The book has \$#m("study.dev.facts.capital_musd")M of notional capital. Each position is sized as a share of current equity, 3–10% before risk scaling (#m("paper.position_min_pct") to #m("paper.position_max_pct") as traded), scaled by the win rate of the last five closed trades and by the volatility of recent daily returns. Gross exposure is capped at 30% of equity, at most 8 new entries are taken a day, no stock is in two open pairs, and drawdown and daily-loss kill switches flatten the book. Idle cash earns no interest.

== Walk-forward

#claim("start_date_changes_path") #claim("last_window_not_shorter")
v33 has no model to refit, so its walk-forward is the main backtest's rule on the same pair formations, started on #m("paper.oos_start_long") instead of #m("paper.period_start_long") and run as one continuous simulation to #m("paper.oos_end_long"). It is cut into #m("oos.windows") test windows of #m("paper.wf_window_days") trading days (the last runs to the walk-forward's last day; @tab-windows in the appendix), and positions carry across window boundaries. It is not out of sample for the thresholds, which were chosen across versions on this same data, so this note calls it the walk-forward and reserves "out of sample" for the 2026 holdout. Over the #m("study.dev.facts.wf_common_days") days the two series share, their daily returns correlate at #m("study.dev.facts.wf_common_corr") and their Sharpe ratios are #m("study.dev.facts.wf_common_sharpe_main") and #m("study.dev.facts.wf_common_sharpe_oos"): the 30% cap binds, so which signals the book can take depends on what it already holds, and a start four months earlier changes the path.

== Inference

Sharpe ratios are annualised from daily net returns by √252. Means are tested with the t-statistic of #cite(<newey1987>, form: "prose"). Intervals for single series are circular block bootstraps with #m("paper.boot_resamples") resamples and the block length of #cite(<politis2004>, form: "prose"), as corrected by #cite(<patton2009>, form: "prose"): blocks of #m("paper.boot_block_main") days for the main backtest and #m("paper.boot_block_oos") for the walk-forward. The probabilistic and deflated Sharpe ratios follow Bailey and López de Prado (#cite(<bailey2012>, form: "year"), #cite(<bailey2014>, form: "year")). Standard errors, power and the one-sided upper bound use the asymptotic variance of the Sharpe estimator for non-normal returns, extended to returns with lag-1 autocorrelation (`pairs_trading/power.py` gives the formula and its source). The hurdles allow for the #m("study.dev.facts.hurdle_tests") recorded versions: a one-sided Bonferroni correction, the t of #m("study.dev.facts.hurdle_hlz_t") that #cite(<harvey2016>, form: "prose") propose for new factors, and the t of #m("study.dev.facts.hurdle_cgs_t") of #cite(<chordia2020>, form: "prose"). The autocorrelation-adjusted annualisation of #cite(<lo2002>, form: "prose"), which the note does not otherwise use, gives #m("paper.lo_sharpe_main") for the main backtest and #m("paper.lo_sharpe_oos") for the walk-forward. Differences of Sharpe ratios use the studentized bootstrap of #cite(<ledoit2008>, form: "prose").

== Validation <sec-validation>

#claim("validation_passes")
A backtest on real data says what a strategy did, not whether the code measures what it claims. A synthetic validation runs the real engine, with its full cost model, on markets whose answer is known, #m("study.validation.seeds") markets per scenario (@tab-validation, @ex-validation). Planted cointegrated pairs show a large gross edge; correlated pairs that are not cointegrated, forced into the universe, show none; the Kalman hedge ratio recovers the true slope; and pair selection finds every planted pair while admitting fewer than 5% of unrelated ones. The test suite adds causality checks, each confirmed by re-introducing the bug it guards against: every decision dated on or before _T_ is unchanged when all prices, volumes and macro data after _T_ are replaced; the same trades occur at the same z-scores when the vendor back-adjusts history for a later split; and the anatomy reconstructs every trade's P&L from prices to the cent. The statistics are tested against reference implementations: statsmodels for Newey--West, arch for the Politis--White block length and the model confidence set, an independent cross-validation for the probability of backtest overfitting, and the authors' code for Ledoit--Wolf and for the Sharpe-ratio power functions.

#tablefig("validation", [Known-answer checks on synthetic markets],
  booktab(columns: (36%, 24%, 40%), align: (left, left, left),
    header: ([Check], [What must happen], [Result]),
    rows: T("validation")),
  notes: [Pooled over the synthetic markets of each scenario; the edge scenario's net Sharpe ratio is the median across its markets.],
  source: [`results/validation/synthetic_validation.json` (`scripts/synthetic_validation.py`).],
  placement: top)

#exhibit("validation",
  [On synthetic markets the engine finds a planted edge (#m("study.validation.edge.mean_bp")~bp a trade) and none where there is none (#m("study.validation.forced_null.mean_bp")~bp, t = #m("study.validation.forced_null.t"))],
  sub: [Pooled gross bp per trade, planted cointegrated pairs against forced non-cointegrated pairs, with 95% intervals],
  notes: [Intervals are ±1.96 standard errors of the pooled gross return per trade across the synthetic markets.],
  source: [`results/validation/synthetic_validation.json` (`scripts/synthetic_validation.py`).])

// ══════════════════════════════════════════════════════════════════════════════════════
= Development-period results <sec-results>
// ══════════════════════════════════════════════════════════════════════════════════════

#claim("main_negative") #claim("few_flat_days") #claim("cap_close_to_binding")
The main backtest enters trades from #m("paper.period_start_long") to #m("paper.period_end_long") on \$#m("study.dev.facts.capital_musd")M of notional capital. Its pairs are formed on the point-in-time index at the end of #m("paper.formation_year") and re-formed every #m("paper.reselect_every") trading days on the trailing #m("paper.formation_years_word") years. Its #m("main.trades") trades returned #m("main.total_return_pct"), with a maximum drawdown of #m("main.max_drawdown_pct") (@ex-equity). The book was flat on #m("study.dev.facts.flat_days") of #m("study.dev.facts.days") days (v32's book, with its regime gate, on #m("study.v32.flat_days")) and used #m("main.avg_gross_exposure_pct") of capital on average, gross, against a 30% cap. @tab-performance sets out the standard statistics of the main backtest, the walk-forward and the Gatev baseline.

#claim("oos_negative") #claim("oos_windows_ci_spans_zero")
The walk-forward points the same way (@ex-walkforward). Of its #m("oos.windows") windows, #m("oos.windows_positive") made money and the stitched path ends at #m("oos.total_return_pct")\; the mean window return is #m("oos.avg_window_return_pct") with a 95% interval from #m("significance.oos_windows.ci_lo_pct") to #m("significance.oos_windows.ci_hi_pct"). No single month or half-year decides the result (@ex-monthly, @ex-rolling).

#claim("gatev_below_strategy")
#exhibit("equity",
  [Net of costs the book ends where it started, #m("main.total_return_pct") after two and a half years, with the 30% gross cap close to binding throughout],
  sub: [Cumulative net return against the Gatev baseline and random pairs, underwater drawdown and gross exposure; main backtest, daily, #m("paper.period_start_month") – #m("paper.period_end_month")],
  notes: [The baselines' returns are on committed capital (pair P&L per dollar of leg notional, equal-weighted), the strategy's on its whole capital, of which it deploys about a quarter gross: compare their Sharpe ratios (@ex-forest), which do not depend on that basis, rather than these levels. The band is the middle half, day by day, of #m("benchmarks.random_control.n_draws") random-pair portfolios traded with the distance rule under the same costs; on the last day their 5th and 95th percentiles stand at #m("study.dev.facts.random_p05_end") and #m("study.dev.facts.random_p95_end"), beyond this scale (an unhedged random pair can lose most of its committed capital). Gross exposure is the run's own daily export (maximum #m("study.dev.facts.exposure_max_pct")).],
  source: [#run-source\; baseline: #cite(<gatev2006>, form: "prose") distance rule with the same _t_ + 1 fills and costs.])

#tablefig("performance", [Performance of the main backtest, the walk-forward and the Gatev baseline, net of costs],
  booktab(columns: (40%, 20%, 20%, 20%), align: (left, right, right, right),
    header: ([], [Main backtest], [Walk-forward], [Gatev distance method]),
    rows: T("performance")),
  notes: [Annualised returns are mean daily returns × 252 with a Newey–West 95% interval; volatility intervals are circular block bootstraps with the Sharpe ratio's block length. The Gatev return is per unit of committed per-leg notional, the strategy's per unit of capital; compare Sharpe ratios across columns, not return or volatility levels. A dash marks a statistic the run does not report for that series.],
  source: [#run-source\; baseline: #cite(<gatev2006>, form: "prose") distance rule.],
  placement: top)

#exhibit("walkforward",
  [Started in #m("paper.oos_start_month"), the same rule made money in #m("oos.windows_positive") of #m("oos.windows") quarterly windows; the stitched path ends at #m("oos.total_return_pct")],
  sub: [Net return per #m("paper.wf_window_days")-day test window (bars, labelled with the trades opened) and the compounded daily path; #m("paper.oos_start_month") – #m("paper.oos_end_month")],
  notes: [The windows are calendar slices of one continuous simulation; positions carry across their boundaries. With #m("oos.windows") windows the test has little power: mean #m("oos.avg_window_return_pct") per window, 95% interval #m("significance.oos_windows.ci_lo_pct") to #m("significance.oos_windows.ci_hi_pct"), p = #m("significance.oos_windows.p").],
  source: [#run-source, walk-forward windows and daily path.])

#claim("fewer_than_half_months_positive") #claim("best_month_small")
#exhibit("monthly",
  [No single month decides the result: #m("study.dev.facts.months_positive") of #m("study.dev.facts.months") months were positive, and the best, #m("paper.best_month"), earned #m("study.dev.facts.best_month_pct")],
  sub: [Monthly net return, % of capital; the year column compounds the months shown],
  notes: [Sharpe ratio by calendar year: #m("study.dev.facts.sharpe_2023") in 2023 (from July), #m("study.dev.facts.sharpe_2024") in 2024 and #m("study.dev.facts.sharpe_2025") in 2025. This grid is the evaluated period: a rule fitted to it would be data snooping.],
  source: [#run-source, monthly performance.])

#claim("no_rolling_window_clears_zero")
#exhibit("rolling",
  [Half-year Sharpe ratios range from #m("study.dev.facts.rolling_min") to #m("study.dev.facts.rolling_max"), and no window's band clears zero],
  sub: [Rolling #m("study.dev.rolling_sharpe.window")-day Sharpe ratio, annualised, with a ±1.96 standard-error band; main backtest],
  notes: [SE = √((1 + SR²/2)/_n_) per day with _n_ = #m("study.dev.rolling_sharpe.window"), annualised, the independent-returns standard error of #cite(<lo2002>, form: "prose"). #m("study.dev.facts.rolling_clear_zero") of #m("study.dev.facts.rolling_windows") overlapping windows clear zero; overlapping windows are not independent tests.],
  source: [Author's calculation from the daily net returns of the #m("paper.design") run.])

// ══════════════════════════════════════════════════════════════════════════════════════
= Inference <sec-inference>
// ══════════════════════════════════════════════════════════════════════════════════════

#claim("every_interval_spans_zero") #claim("sharpe_1_rejected") #claim("sharpe_1_5_and_2_rejected")
Is the result significant? No: every interval in @ex-forest contains zero, gross or net, in both strategy families, and @tab-significance gives the tests. The more useful question is what the data can rule out. With #m("study.dev.facts.main_days") daily observations the standard error of the annualised Sharpe ratio is #m("study.dev.facts.sharpe_se"), allowing for the returns' fat tails (skewness #m("study.dev.facts.skew"), non-excess kurtosis #m("study.dev.facts.kurtosis")) and their lag-1 autocorrelation of #m("paper.holdout_power.rho"), so the one-sided 95% upper bound is #m("study.dev.facts.sharpe_ucb"). A true Sharpe ratio would need to be about #m("study.dev.facts.sharpe_mde") to be detected with 80% probability. A Sharpe ratio of 1.0 is rejected (p = #m("study.dev.facts.p_sr_ge_1")); 0.5 is not (p = #m("study.dev.facts.p_sr_ge_0_5")). An observed Sharpe ratio of 0.5 becomes significant only after about #m("study.dev.facts.min_trl_years_0_5") years of daily data, and a strategy whose true Sharpe ratio is 0.5 reaches that bar only about half the time; at 1.0 the length is #m("study.dev.facts.min_trl_years_1") years.

#exhibit("forest",
  [Every Sharpe interval spans zero, gross or net, in both families; the data exclude only Sharpe ratios above about #m("study.dev.facts.sharpe_ucb")],
  sub: [Annualised Sharpe ratio with its 95% interval; development period, net of costs unless stated (open markers: before costs)],
  notes: [Intervals are circular block bootstraps (Politis–White block length, #m("paper.boot_resamples") resamples) for single series and Ledoit–Wolf studentized bootstraps for differences; the random-pair row shows the 5th–95th percentile spread of #m("benchmarks.random_control.n_draws") draws, not a confidence interval. The gross-of-cost, Gatev and Avellaneda–Lee intervals use the run's own bootstrap. The bound and the 80%-power line are the main backtest's. The walk-forward's comparison with Gatev uses the #m("paper.wf_common_days") days the two series share.],
  source: [#run-source\; #cite(<gatev2006>, form: "prose") distance rule; `results/residual_dev`.])

== Power, the upper bound and the hurdles

#claim("mde_above_bound") #claim("hurdles_above_bound") #claim("oos_ucb_negative")
A test that cannot reject zero is evidence of no edge only to the extent that it could have detected one. At this sample length the critical Sharpe ratio of a one-sided 5% test is #m("study.dev.facts.sharpe_critical") and the Sharpe ratio detected with 80% probability #m("study.dev.facts.sharpe_mde")\; the one-sided 95% upper bound, #m("study.dev.facts.sharpe_ucb"), is the largest Sharpe ratio the data do not reject (@tab-alternatives). The sample therefore excludes a strategy of Sharpe 1.0 or more and says nothing useful about 0.5. Hurdles that allow for the #m("study.dev.facts.hurdle_tests") recorded versions sit higher still (@tab-hurdles): a Sharpe ratio of #m("study.dev.facts.hurdle_bonferroni") (Bonferroni, one-sided), #m("study.dev.facts.hurdle_hlz") (t = #m("study.dev.facts.hurdle_hlz_t")) or #m("study.dev.facts.hurdle_cgs") (t = #m("study.dev.facts.hurdle_cgs_t")), all above the upper bound. The walk-forward's own one-sided upper bound is #m("study.dev.facts.oos_ucb"): over its #m("study.dev.facts.oos_days") days the one-sided test rejects a Sharpe ratio of zero or more in favour of a loss (its two-sided bootstrap interval, #m("significance.oos_daily.boot_lo") to #m("significance.oos_daily.boot_hi"), just includes zero), and a loss is not an edge either.

#place(top, float: true, block(width: 100%, wide(grid(columns: (1fr, 1fr), column-gutter: D.layout.column_gap_mm * 1mm,
  [#figure(block(width: 100%, { set align(left); booktab(columns: (22%, 34%, 44%), align: (right, right, right),
      header: ([True annual Sharpe _x_], [p-value of H#sub[0]: SR ≥ _x_], [Years for an observed SR = _x_ to be significant]),
      rows: T("alternatives")); foot([One-sided, at the observed Sharpe ratio, under the non-normal AR(1) variance. A strategy whose true Sharpe ratio is _x_ reaches significance after the stated years only about half the time; 80% power needs about #m("paper.trl_power_ratio") times as long @bailey2012.], none) }),
    kind: table, supplement: [Table], caption: [What the development sample rules out]) <tab-alternatives>],
  [#figure(block(width: 100%, { set align(left); booktab(columns: (52%, 18%, 30%), align: (left, right, right),
      header: ([Hurdle], [t], [Annual Sharpe]),
      rows: T("hurdles")); foot([The annual Sharpe ratio at which the main backtest's one-sided t would clear each hurdle at this sample length, under the same variance.], [#run-source, evidence block.]) }),
    kind: table, supplement: [Table], caption: [Sharpe hurdles after #m("study.dev.facts.hurdle_tests") recorded versions]) <tab-hurdles>],
))))

== Baselines

#claim("gatev_ci_spans_zero")
The Gatev distance method, run on the same universe and period with the same _t_ + 1 fills and cost model, returned #m("benchmarks.gatev.total_return_pct") (Sharpe #m("benchmarks.gatev.sharpe")\; 95% interval #m("study.dev.facts.gatev_lo") to #m("study.dev.facts.gatev_hi")). Its return is per unit of committed per-leg notional, at #m("paper.gatev_vol_pct") annualised volatility against the strategy's #m("paper.main_vol_pct") on capital, so the Sharpe ratios, not the returns, are comparable (@tab-performance). The difference in Sharpe ratios is #m("benchmarks.sharpe_diff_vs_gatev.diff") in the main backtest (Ledoit–Wolf p = #m("benchmarks.sharpe_diff_vs_gatev.p")) and #m("paper.diff_oos") in the walk-forward, on the #m("paper.wf_common_days") days the two series share (p = #m("paper.diff_oos_p")). Against #m("benchmarks.random_control.n_draws") portfolios of random pairs, traded with the Gatev rule under the same costs, the strategy sits at the #m("paper.percentile_ordinal") percentile (@ex-randomnull).

#tablefig("significance", [Significance tests, #m("paper.design") development run of #m("paper.run_date_long")],
  booktab(columns: (46%, 27%, 27%), align: (left, right, right),
    header: ([Test], [Main backtest], [Walk-forward (daily)]),
    rows: T("significance")),
  notes: [Newey–West t and p test a zero mean of daily net returns. The deflated Sharpe ratio is the probability that the true Sharpe ratio exceeds the expected maximum Sharpe ratio of the stated number of independent null trials. Power and the upper bound use the non-normal AR(1) variance. The walk-forward's comparison with Gatev uses the #m("paper.wf_common_days") days both series cover, on which the walk-forward's own Sharpe ratio is #m("paper.wf_common_sharpe")\; no interval is computed for the Gatev Sharpe ratio on those days.],
  source: [#run-source\; tests of #cite(<newey1987>, form: "prose"), #cite(<bailey2014>, form: "prose") and #cite(<ledoit2008>, form: "prose").],
  placement: top)

#claim("dsr_low")
#exhibit-pair(
  ("randomnull", [The strategy sits at the #m("paper.percentile_ordinal") percentile of #m("benchmarks.random_control.n_draws") random-pair portfolios],
    (sub: [Annualised Sharpe ratio of random 20-pair draws traded with the distance rule under the same costs],
     notes: [Median draw #m("benchmarks.random_control.median_sharpe"), 5th–95th percentile #m("benchmarks.random_control.p5_sharpe") to #m("benchmarks.random_control.p95_sharpe"). The control trades random pairs with the Gatev rule, not this engine: a baseline for the distance method and only a rough one for this strategy.],
     source: [#run-source.])),
  ("dsr", [Deflated for #m("study.dev.facts.dsr_trials") trials, the Sharpe ratio has a #m("significance.main.dsr_pct") probability of beating the best of chance],
    (sub: [Deflated Sharpe ratio of the main backtest against the number of independent trials _N_],
     notes: [_N_ = 1 is the probabilistic Sharpe ratio; _N_ = #m("study.dev.facts.dsr_trials") counts the versions before this one, a lower bound on the designs tried.],
     source: [Author's calculation from the daily net returns.])),
)

== Deflated Sharpe, data snooping and the trial record <sec-snooping>

Every design choice in this study was made on #m("paper.data_years") data over #m("paper.versions_count") versions (@tab-history). The deflated Sharpe ratio @bailey2014 is the probability that the true Sharpe ratio exceeds the expected maximum Sharpe ratio of _N_ independent null trials; at _N_ = #m("study.dev.facts.dsr_trials"), a lower bound on the designs tried, it is #m("significance.main.dsr_pct") for the main backtest and #m("significance.oos_daily.dsr_pct") for the walk-forward (@ex-dsr). #cite(<harvey2016>, form: "prose") make the same point for the factor literature.

#claim("snooping_pending")
_N_ is not known, and the deflated Sharpe ratio is only as good as the guess. The data-snooping tests replace the guess with a declared family. On #m("paper.declared_long"), before any variant ran, the study declared a #m("study.dev.snooping.grid_points")-point grid of the entry, exit and stop thresholds and #m("study.dev.snooping.toggles") design toggles around the v33 design (@tab-variants in the appendix); each variant runs once on the development calendar, and the design is not re-chosen from the results. The Reality Check of #cite(<white2000>, form: "prose") and the SPA test of #cite(<hansen2005>, form: "prose") ask whether the best variant beats cash; the stepdown of #cite(<romano2005>, form: "prose") identifies which variants do, with familywise error control; the model confidence set of #cite(<hansen2011>, form: "prose") keeps the variants that cannot be told apart from the best; and the probability of backtest overfitting @bailey2017 measures how often the in-sample winner falls below the median out of sample. Resampling uses the stationary bootstrap @politis1994. #if flag("snooping") [@tab-snooping reports the results.] else [The family's run is in progress; its results are forthcoming (@tab-forthcoming) and will be reported whatever they show.]

#if flag("snooping") {
  tablefig("snooping", [Data-snooping tests over the declared variant family],
    booktab(columns: (70%, 30%), align: (left, right),
      header: ([Test], [Result]),
      rows: T("snooping")),
    notes: [Variant family declared on #m("paper.declared_long"), before any variant was run.],
    source: [Author's runs of the declared variants on the development calendar.])
}

Beyond the declared family, every trial whose result has been seen is on record, in the order registered (@tab-trials). The exploratory v33 run, on the first point-in-time build and before the universe review and the price anchoring, had a walk-forward Sharpe ratio of #m("study.trials.1.oos_sharpe")\; it is not published, and it stays in the record rather than being dropped. The rehearsal runs, on the holdout calendar moved one year back, are development data; no decision depends on them.

#tablefig("trials", [Every trial whose result has been seen],
  booktab(columns: (27%, 21%, 11%, 9%, 10%, 9%, 13%), align: (left, left, left, right, right, right, right), size: 7pt,
    header: ([Trial], [Design · calendar], [Commit], [Sharpe], [Return, %], [Trades], [Walk-forward Sharpe]),
    rows: T("trials").map(r => (text(font: mono, size: 6.6pt, r.at(0)), ..r.slice(1)))),
  notes: [In the order registered in the append-only `results/trial_registry.jsonl`. \* Run with uncommitted changes. The exploratory run and the published v33 run carry the same design hash; between them the point-in-time universe was reviewed and rebuilt, price levels were anchored to N-PORT, and code the profile does not record changed with them. The residual arm's line holds no run record, so its numbers are those of its published run. The variant family and the holdout will be added as one trial each.],
  source: [`results/trial_registry.jsonl`.],
  placement: top)

== Multiple testing in pair selection <sec-multiple>

#claim("excess_cointegration") #claim("bh_none_at_5pct") #claim("chance_about_half")
Pair selection is itself a multiple test. At the first formation #m("fdr.pairs_tested") same-industry pairs were tested and #m("fdr.significant_raw_p05") were "cointegrated" at p < 0.05, against #m("study.dev.funnel.pairs.1.expected") expected by chance alone. That count is an upper bound on chance rejections, since it treats every pair as null and the two-direction Bonferroni p-value is conservative, so up to #m("paper.chance_share_pct") of the "cointegrated" pairs could be chance. None survives a Benjamini--Hochberg correction @benjamini1995 at q = 0.05, and #m("fdr.survive_bh_fdr_q10") at q = 0.10: the excess is spread thinly over many weak relationships. Selection kept #m("fdr.final_selected_pairs") pairs at that formation; across all #m("study.dev.facts.formations") formations, #m("study.dev.facts.pairs_traded") distinct pairs were traded (@ex-funnel). Restricting pairs to one industry cut the tests from v32's #m("study.v32.pairs_tested").

#exhibit("funnel",
  [From #m("fdr.pairs_tested") candidate pairs to #m("study.dev.facts.pairs_traded") traded; chance alone accounts for about half the "cointegrated" pairs],
  sub: [Pairs at each selection stage of the first formation (data to #m("paper.formation_cutoff_long")), and the pairs traded across all formations; log scale],
  notes: [The tick marks the count expected by chance, an upper bound. Pairs share legs, so the tests are dependent; Benjamini–Hochberg is a diagnostic here, not a filter. Selection also requires a half-life of 4–25 days and a quality score. The exports keep these counts, not the p-values themselves, so no p-value histogram is drawn.],
  source: [#run-source, FDR diagnostic and trades.])

// ══════════════════════════════════════════════════════════════════════════════════════
= Why there is no edge <sec-anatomy>
// ══════════════════════════════════════════════════════════════════════════════════════

#claim("gross_pnl_below_costs") #claim("impact_largest_cost") #claim("gross_bp_negative") #claim("break_even_is_edge_over_cost")
There is no gross edge for costs to remove. Before costs the #m("main.trades") trades made \$#m("study.dev.facts.gross_usd_k")k; modelled costs were \$#m("study.dev.facts.cost_usd_k")k, #m("study.dev.facts.impact_share_pct") of it market impact, so costs would have to fall to #m("study.dev.facts.break_even_x") their modelled level for net P&L to break even (@ex-waterfall). Per trade, the average earned #m("study.dev.facts.gross_bp")~bp of its notional before costs (t = #m("study.dev.facts.gross_t")) against #m("study.dev.facts.cost_bp")~bp of cost; weighted by size, the larger trades did better, #m("paper.edge.gross_bp")~bp against #m("paper.edge.cost_bp")~bp (t = #m("paper.edge.gross_t") for the mean gross dollar P&L). On either basis the gross return is indistinguishable from zero and below the cost.

Four measurements of the evidence layer point to one mechanism. The cointegration the selection finds does not persist beyond what chance produces (@ex-persistence); the rule's edge on the data that selected a pair disappears afterwards (@ex-decay); and out of sample the spreads move like random walks between the target and the stop (@ex-exitrace), with half-lives longer than the rule allows (@ex-halflife). The selection, in other words, mostly finds pairs whose spreads happened to revert in the formation window.

#claim("exit_delay_costs_more_than_entry_gains")
#exhibit("waterfall",
  [From paper P&L to net: the next-day fill gives up part of the paper P&L, and costs exceed what the trades earned before them],
  sub: [Implementation shortfall of the main backtest, \$ thousands: paper P&L at the signal closes, the delay to the next-day fills, gross P&L, each cost, net P&L],
  notes: [Paper P&L at the signal closes is unattainable, because a signal is known only at the close. Filling at the next close gained \$#m("study.dev.facts.sf_entry_delay_gain_usd_k")k on entries and lost \$#m("study.dev.facts.sf_exit_delay_loss_usd_k")k on exits, leaving #m("study.dev.facts.sf_gross_bp")~bp of traded notional, weighted by size. The bars close exactly on the change in the book's value: gross #m("study.dev.facts.gross_bp_capital")~bp of starting capital, costs #m("study.dev.facts.cost_bp_capital")~bp, net #m("study.dev.facts.net_bp_capital")~bp. v33 charges no financing beyond the borrow fee. The same \$#m("study.dev.facts.capital_musd")M in three-month Treasury bills over the same dates would have earned #m("study.dev.facts.cash_tbill_pct")\; the backtest's capital earns no interest.],
  source: [`results/v33_dev/anatomy.json` (shortfall, cash; FRED three-month bill rate), reconstructed from the trades and prices and checked against the export to the cent.])

#claim("stops_offset_targets") #claim("long_gained_short_lost") #claim("most_hedge_ratios_below_one") #claim("ex_market_gross_negative") #claim("win_rate_ci_spans_half")
#exhibit("anatomy",
  [Stops lost \$#m("study.dev.facts.stop_loss_usd_m")M and targets earned \$#m("study.dev.facts.target_gain_usd_m")M: the outcomes are symmetric around zero],
  sub: [Net P&L of the #m("main.trades") trades by exit reason, side of the spread and |_z_| at entry, \$ millions; each panel on its own scale],
  notes: [Long-spread trades made \$#m("study.dev.facts.long_gain_usd_m")M and short-spread trades lost \$#m("study.dev.facts.short_loss_usd_m")M, consistent with the market exposure that hedge ratios below one leave (mean #m("study.dev.facts.hedge_mean")\; #m("study.dev.facts.hedge_below_1_pct") of trades below one): per dollar of gross, a long-spread trade carries a market beta of #m("study.dev.facts.beta_long_per_gross") and a short-spread trade #m("study.dev.facts.beta_short_per_gross"). The market component accounts for \$#m("study.dev.facts.market_usd_k")k of the \$#m("study.dev.facts.gross_usd_k")k gross; without it the gross return per trade is #m("study.dev.facts.gross_ex_market_bp")~bp (t = #m("study.dev.facts.gross_ex_market_t")). Win rate #m("main.win_rate_pct") (#m("study.dev.facts.wins") of #m("study.dev.facts.trades")\; 95% interval #m("study.dev.facts.win_lo_pct")–#m("study.dev.facts.win_hi_pct")). The |_z_| buckets describe the past and are not a selection rule.],
  source: [#run-source, trades; `results/v33_dev/anatomy.json`, exposure.])

#exhibit-pair(
  ("exitrace", [Out of sample, spreads hit their targets about as often as a random walk would, not as the selection implies],
    (sub: [Targets hit first among the #m("study.dev.facts.er_barrier") trades that reached the target or the stop, against two nulls (expected count in brackets)],
     notes: [#m("study.dev.facts.er_targets") targets and #m("study.dev.facts.er_stops") stops. A driftless random-walk spread with each trade's own volatility, entry _z_ and time stop expects #m("study.dev.facts.er_rw_expected") targets (z = #m("study.dev.facts.er_rw_z"), p = #m("study.dev.facts.er_rw_p")); a spread reverting at its pair's formation half-life (median #m("study.dev.facts.er_half_life") days) expects #m("study.dev.facts.er_ou_expected") (z = #m("study.dev.facts.er_ou_z")). #m("study.dev.facts.er_other") trades ended at the time stop or the end of data.],
     source: [`results/v33_dev/anatomy.json` (exit race; simulated paths per trade).])),
  ("decay", [The rule's edge on its own pairs is in-sample only: #m("study.dev.facts.decay_form_bp")~bp a trade on the selection data, #m("study.dev.facts.decay_oos_bp")~bp afterwards],
    (sub: [Gross bp per trade of the same rule on the #m("study.dev.facts.decay_pairs") traded pairs, with 95% intervals],
     notes: [In sample, on each pair's formation window: t = #m("study.dev.facts.decay_form_t") (#m("study.dev.facts.decay_form_tc") clustered by month). Out of sample: t = #m("study.dev.facts.decay_oos_t"). The book's own trades: t = #m("study.dev.facts.decay_engine_t"). A selection that found genuine mean reversion would keep most of its in-sample edge.],
     source: [`results/v33_dev/anatomy.json` (decay).])),
)

#claim("persistence_traded_near_chance") #claim("half_lives_lengthen")
#exhibit-pair(
  ("persistence", [Cointegration does not persist: a pair cointegrated one year is cointegrated the next at the base rate],
    (sub: [Share of pairs cointegrated in a year (p < 0.05) that are cointegrated the next: the #m("study.dev.facts.pers_symbols") most liquid names at the end of #m("paper.formation_year"), years #m("paper.data_years"), and the traded pairs out of sample],
     notes: [Ticks: the next year's base rate; dashed line: 5%. Pooled over the five pairs of years, #m("study.dev.facts.pers_count") of #m("study.dev.facts.pers_of") stayed cointegrated (#m("study.dev.facts.pers_pct"), 95% interval #m("study.dev.facts.pers_lo_pct")–#m("study.dev.facts.pers_hi_pct")), against #m("study.dev.facts.pers_expected") at the next year's base rate (z = #m("study.dev.facts.pers_z")); of the #m("study.dev.facts.pers_traded_of") traded pairs testable out of sample, #m("study.dev.facts.pers_traded_count") (#m("study.dev.facts.pers_traded_pct")). Pairs share legs, so the intervals overstate the precision. #cite(<clegg2014>, form: "prose") reports the same pattern.],
     source: [`results/v33_dev/anatomy.json` (persistence; the study's two-direction Engle–Granger test).])),
  ("halflife", [Out of sample, #m("study.dev.facts.hl_oos_above_max_pct") of the traded pairs' half-lives exceed the rule's #m("study.dev.facts.hl_max")-day maximum],
    (sub: [Spread half-life of each traded pair on its formation window and out of sample, trading days (log scale)],
     notes: [Median #m("study.dev.facts.hl_formation") days at formation, where selection admits 4 to 25, and #m("study.dev.facts.hl_oos") out of sample. The dashed line is the rule's maximum and the curve marks equal half-lives; triangles mark half-lives beyond the top of the scale or no mean reversion. The time stop is at most 25 days, so a spread whose half-life has lengthened is usually closed before it reverts.],
     source: [`results/v33_dev/anatomy.json` (traded pairs).])),
)

// ══════════════════════════════════════════════════════════════════════════════════════
= Execution and costs <sec-costs>
// ══════════════════════════════════════════════════════════════════════════════════════

Every fill pays its own costs, from the stock's own liquidity on that day, and fills at the next day's close: a signal seen at the close of day _t_ trades in the closing auction of day _t_ + 1. The average trade held #m("study.dev.facts.hold_days")~trading days, and its larger leg was #m("study.dev.facts.adv_participation_pct") of that stock's dollar ADV. Annual turnover was #m("main.annual_turnover_x") capital. The cost model was fixed before the run (@tab-costs), and its uncertain parts are stressed in scenarios declared in advance; the study's execution-cost note compares the model with published impact estimates at each participation rate (@sec-repro).

#tablefig("costs", [The v33 cost model against published references, and what changed from v32],
  booktab(columns: (12%, 31%, 37%, 20%), align: (left, left, left, left),
    header: ([Component], [v33 model], [Reference], [Change from v32]),
    rows: (
      ([Commission], [\$0.002 per share, \$0.50 minimum per order], [Author's assumption, in the range of quoted agency rates], [unchanged]),
      ([Half-spread], [Half the typical quoted spread by 20-day dollar ADV: 0.75 bp (≥ \$500M) to 40 bp (< \$5M)], [#cite(<frazzini2018>, form: "prose")], [unchanged]),
      ([Market impact], [_Y_ · σ#sub[daily] · √(shares / ADV), _Y_ = 0.3, capped at 50 bp, on entry and exit], [The 0.314 of #cite(<almgren2005>, form: "prose") is their permanent-impact coefficient, not a trading cost; _Y_ = 0.3 is at the low end of published estimates, consistent with impact in the closing auction (the execution-cost note gives the sources)], [unchanged; stressed at _Y_ = 0.6 and 1.0]),
      ([Borrow], [One fee of #m("paper.borrow_pct") a year on the short notional], [#cite(<davolio2002>, form: "prose") on general-collateral fees; the fee is a median buy-side indicative fee, whose source the execution-cost note gives], [replaces a #m("paper.v32_borrow_bp") bp general-collateral fee; stressed at 1% and 3%]),
      ([Financing], [None beyond the borrow fee], [v32's #m("paper.v32_financing_bp") bp prime-broker spread on the short half of gross double-counted the cost of shorting], [folded into the single fee]),
      ([Fill], [Close of _t_ + 1 for entry and exit, a market-on-close order; legs \$1~:~\$β, shares fixed from the signal-day close], [`docs/EXECUTION_COSTS.md`], [unchanged; _t_ + 1 open is a declared variant]),
    )),
  source: [Author's cost model for the v33 study profile; the references cited.],
  placement: top)

== Cost and capacity scenarios

#claim("every_scenario_loses") #claim("no_scenario_significant") #claim("scenario_trades_differ") #claim("small_book_fixed_positive_full_not")
How much the conclusion depends on the cost model is measured, not asserted. Each scenario declared in advance re-runs the whole backtest (@ex-scenarios, @tab-scenarios), and every re-run loses money. The re-runs do not hold the trades fixed: trade counts range from #m("study.dev.cost_sensitivity.trades_min") to #m("study.dev.cost_sensitivity.trades_max"). The code shows three reasons. Costs enter the equity path, and every position is sized as a share of current equity, scaled by the win rate of the last five closed trades and by the volatility of recent daily returns. An entry is admitted only while gross exposure stays under the 30% cap, which binds: the headline run averaged #m("study.dev.facts.avg_exposure_pct") and the cap turned away #m("study.dev.facts.rej_cap_signal") signals at signal time and #m("study.dev.facts.rej_cap_fill") more at the fill. And a pair is paused for 30 days after three net losses (#m("study.dev.facts.rej_cooloff") signals turned away). A change in costs therefore changes which signals are filled. To separate the cost from the path, the headline run's #m("main.trades") trades are also re-priced under each assumption. Re-pricing them for a \$10M book turns their P&L slightly positive (#m("study.dev.cost_sensitivity.scenarios.capital_10m.fixed.ret_pct"), Sharpe #m("study.dev.cost_sensitivity.scenarios.capital_10m.fixed.sharpe")), because impact falls with participation; the full re-run at that size does not (#m("study.dev.cost_sensitivity.scenarios.capital_10m.full.ret_pct")). Neither is distinguishable from zero, and a smaller book cannot turn a gross edge that is itself indistinguishable from zero into one.

#exhibit("scenarios",
  [Under every declared cost and capacity scenario the full re-run loses money; each one is a new path, so the trades change],
  sub: [Net Sharpe ratio under each scenario fixed in advance: the whole backtest re-run (filled) and the headline run's #m("main.trades") trades re-priced (open)],
  notes: [_Y_ is the square-root impact coefficient; the borrow scenarios charge every short 1% or 3% a year; the book sizes scale every position. @ex-costcurve extends the fixed-trade view to any cost multiple.],
  source: [`results/v33_dev/cost_sensitivity.json` (`scripts/cost_sensitivity.py`); `results/v33_dev/anatomy.json` (impact, borrow and capacity re-pricing).])

#tablefig("scenarios", [Declared scenarios: the full re-run, and the headline trades re-priced under the same assumption],
  booktab(columns: (24%, 7%, 9%, 8%, 10%, 10%, 10%, 11%, 11%), align: (left,) + (right,) * 8, size: 7pt,
    header: ([Scenario], [Trades], [Net return, %], [Sharpe], [Max drawdown, %], [Cost, bp of notional], [Larger leg, % ADV], [Same trades: return, %], [Same trades: Sharpe]),
    rows: T("scenarios")),
  notes: [The first seven columns are each scenario's full re-run; the last two hold the headline run's trades fixed and re-price them. Cost per round trip is in bp of traded gross notional, weighted by size.],
  source: [`results/v33_dev/cost_sensitivity.json`; `results/v33_dev/anatomy.json`.],
  placement: top)

#claim("cost_curve_falls") #claim("sharpe_break_even_below_one") #claim("gross_sharpe_not_significant") #claim("capacity_monotone")
#exhibit-pair(
  ("costcurve", [With the trades held fixed, net Sharpe falls from #m("study.dev.facts.cost_0x_sharpe") at zero cost to #m("study.dev.facts.cost_2x_sharpe") at twice the modelled costs],
    (sub: [Net Sharpe ratio against a multiple of modelled costs, 0× to 2×, the headline trades held fixed],
     notes: [Each day's net return is rebuilt as gross minus _k_ times that day's modelled costs. The Sharpe ratio crosses zero at #m("study.dev.facts.sharpe_break_even_x") costs (net P&L at #m("study.dev.facts.break_even_x")). Even at zero cost the Sharpe ratio is not significant (Newey–West p = #m("study.dev.facts.gross_hac_p")).],
     source: [The run's daily gross and cost series.])),
  ("capacity", [Larger books only lose more: impact grows from #m("study.dev.facts.cap_10m_impact_bp")~bp a trade at \$10M to #m("study.dev.facts.cap_5b_impact_bp")~bp at \$5B],
    (sub: [Net and impact bp per trade when the headline trades are re-priced at other book sizes],
     notes: [Each execution is re-priced at the book's size: participation grows with the book, so square-root impact per dollar grows with it, up to the 50 bp cap per execution. Net per trade: #m("study.dev.facts.cap_10m_net_bp")~bp at \$10M, #m("study.dev.facts.cap_100m_net_bp")~bp at the headline \$#m("study.dev.facts.capital_musd")M, #m("study.dev.facts.cap_1b_net_bp")~bp at \$1B and #m("study.dev.facts.cap_5b_net_bp")~bp at \$5B.],
     source: [`results/v33_dev/anatomy.json` (capacity).])),
)

#claim("all_schedules_lose") #claim("best_schedule_cheapest") #claim("no_schedule_significant")
A second check re-sizes and re-costs the same trades under #m("paper.schedules_n_word") other parameter sets of costs and position sizes (@ex-schedules; parameters in @tab-schedules in the appendix). The same trades lose money under all #m("paper.schedules_n_word").

#exhibit("schedules",
  [Re-costed under #m("paper.schedules_n_word") other cost and sizing schedules, the same trades lose money in all #m("paper.schedules_lose_word")],
  sub: [Cumulative net return, % of capital, when the main backtest's trades are re-sized and re-costed; schedules A–E in order of total cost],
  notes: [Schedules are parameter sets, not descriptions of any firm. Returns run from #m("paper.sched_best_ret") (schedule #m("paper.sched_best_id"), the lowest costs and smallest positions) to #m("paper.sched_worst_ret") (schedule #m("paper.sched_worst_id")). The replay keeps every signal, entry, exit and daily path, and changes only sizes and costs.],
  source: [`results/v33_dev/fund_type_comparison.json`.])

// ══════════════════════════════════════════════════════════════════════════════════════
= Risk and factor attribution <sec-risk>
// ══════════════════════════════════════════════════════════════════════════════════════

#claim("st_reversal_loading") #claim("momentum_against") #claim("market_loading") #claim("ff_alpha_main_not_significant") #claim("ff_alpha_oos_negative") #claim("factors_explain_little")
The book's factor exposures are the ones a convergence strategy built from hedge ratios below one should have. Against the five factors of #cite(<fama2015>, form: "prose"), momentum @carhart1997 and short- and long-term reversal, with Newey--West errors, the main backtest loads on short-term reversal (t = #m("study.dev.facts.st_rev_t_main")), on the market (t = #m("study.dev.facts.mkt_t_main")) and against momentum (t = #m("study.dev.facts.mom_t_main")) (@ex-factors). The eight factors explain R² = #m("study.dev.facts.ff_r2_main") of its daily variance and leave an alpha of #m("study.dev.facts.ff_alpha_main_pct") a year (t = #m("study.dev.facts.ff_alpha_main_t")). The walk-forward loads the same way (short-term reversal t = #m("study.dev.facts.st_rev_t_oos")) and leaves an alpha of #m("study.dev.facts.ff_alpha_oos_pct") a year (t = #m("study.dev.facts.ff_alpha_oos_t")): a loss, not an edge. Against an equal-weight sector-ETF proxy the main backtest's beta is #m("study.dev.facts.beta_main") (t = #m("study.dev.facts.beta_main_t")): small, but not zero, as the hedge ratios below one imply (@ex-anatomy).

#exhibit("factors",
  [Returns load on short-term reversal, as a convergence strategy's should, and leave no positive alpha],
  sub: [Loadings on eight daily factors with 95% intervals (Newey–West), main backtest and walk-forward],
  notes: [Alpha a year: #m("study.dev.facts.ff_alpha_main_pct") (t = #m("study.dev.facts.ff_alpha_main_t")) in the main backtest and #m("study.dev.facts.ff_alpha_oos_pct") (t = #m("study.dev.facts.ff_alpha_oos_t")) in the walk-forward; R² #m("study.dev.facts.ff_r2_main") and #m("study.dev.facts.ff_r2_oos"). Factor returns are truncated at #m("paper.factor_data_end_long") in every run although the files reach into 2026; no strategy reads them.],
  source: [#run-source, evidence block (factor attribution); factors from the Kenneth French data library.])

#claim("kurtosis_fat")
#exhibit("distribution",
  [Daily returns are fat-tailed (kurtosis #m("study.dev.facts.kurtosis"))],
  sub: [Distribution of daily net returns, bp of capital; main backtest],
  notes: [Skew #m("study.dev.facts.skew")\; kurtosis is non-excess (3 for a normal distribution). Fat tails widen the Sharpe ratio's standard error, which the power figures of @sec-inference account for.],
  source: [#run-source, daily net returns.])

// ══════════════════════════════════════════════════════════════════════════════════════
= A second strategy family: residual reversion <sec-residual>
// ══════════════════════════════════════════════════════════════════════════════════════

#claim("residual_gross_below_cost") #claim("residual_net_negative")
A null on one rule says little about the idea. #cite(<avellaneda2010>, form: "prose") trade each stock's residual against its sector ETF when that residual, modelled as a mean-reverting process, is stretched; many small concurrent bets give the test far more power than #m("main.trades") pair trades. The parameters are the paper's: a 60-day regression on the sector ETF, an AR(1) fit of the cumulative residual, trades only when mean reversion is faster than 30 days, entry at |_s_| > 1.25, exits at −0.50 (long) and 0.75 (short). Fills, costs and the universe rule are the pairs strategy's: next-day closes, the same cost model, and the #m("study.residual.universe_size") most liquid point-in-time members, re-ranked every 21 trading days. The declared deviations from the paper are next-day fills, this cost model, 11 sector ETFs instead of 15, this universe, and a fixed position size (0.5% of equity) in place of a leverage target. Over the same period it made #m("study.residual.trades") trades, held #m("study.residual.avg_positions") positions on average and returned #m("study.residual.ret_pct") (Sharpe #m("study.residual.sharpe"), 95% interval #m("study.residual.lo") to #m("study.residual.hi")\; Newey–West p = #m("study.residual.p")). Before costs it earned #m("study.residual.gross_bp")~bp a trade (t = #m("study.residual.gross_t")) against #m("study.residual.cost_bp")~bp of cost (@ex-residual).

#exhibit("residual",
  [The second family agrees: Avellaneda–Lee residual reversion has no detectable edge, gross (Sharpe #m("study.residual.gross_sharpe")) or net (#m("study.residual.sharpe"))],
  sub: [Net and gross Sharpe ratios with 95% intervals (open markers: before costs), and cumulative net return, against the pairs strategy; same universe rule, fills and costs, #m("paper.period_start_month") – #m("paper.period_end_month")],
  notes: [Gross Sharpe 95% interval #m("study.residual.gross_lo") to #m("study.residual.gross_hi") (Newey–West p = #m("study.residual.gross_p")). Costs were \$#m("study.residual.cost_usd_m")M against \$#m("study.residual.gross_usd_m")M of gross P&L at a turnover of #m("study.residual.turnover_x") capital a year; the sector-ETF hedges are netted across positions and account for \$#m("study.residual.etf_cost_usd_m")M of the costs.],
  source: [`results/residual_dev/residual_statarb.json` (`scripts/run_residual_statarb.py`, run of commit #m("paper.commit_short")); intervals by circular block bootstrap.])

// ══════════════════════════════════════════════════════════════════════════════════════
= v32: the published record and the frozen arm <sec-v32>
// ══════════════════════════════════════════════════════════════════════════════════════

#claim("v32_ci_spans_zero")
The v32 study was published on #m("paper.v32_run_date_long") (commit #m("paper.v32_commit_short")) with the same verdict: no detectable edge. v33 changes seven fields of its design for the reasons in @tab-design. Two differences explain most of the contrast in @tab-compare. v32's book was flat on #m("study.v32.flat_days") of #m("study.v32.days") days, because its regime gate blocked new entries on #m("study.v32.gate_blocked_days") days; v33's, without the gate, held positions almost every day near its 30% cap. And v32 searched any two of #m("paper.v32_universe_top") names of a survivor list, where v33 searches same-industry pairs of #m("paper.universe_top") point-in-time members. Neither run's interval excludes zero. v32 is kept as the record of what was published and is not re-run with fixes; in the holdout it runs frozen as S3, reported with the same statistics as the tested arms but tested in no family, because its universe looks ahead into the test period (@sec-holdout).

#[
#show figure: set block(breakable: true)
#tablefig("compare", [The published v32 run beside the v33 run, development period],
  booktab(columns: (46%, 27%, 27%), align: (left, right, right),
    header: ([Measure], [v32, published #m("paper.v32_run_date_long")], [v33, this note]),
    rows: T("compare")),
  notes: [Gross and cost per trade are equal-weighted across trades.],
  source: [`results/v32_dev` (commit #m("paper.v32_commit_short")); #run-source.])
]

// ══════════════════════════════════════════════════════════════════════════════════════
= #if prereg [The pre-registered 2026 test] else [The 2026 holdout test] <sec-holdout>
// ══════════════════════════════════════════════════════════════════════════════════════

Every design choice in this study was made on #m("paper.data_years") data over #m("paper.versions_count") versions, so the development period cannot test those choices. The decisive test runs on data none of them has seen: the #m("study.dev.facts.ho_days") trading days from #m("paper.holdout_start_long") to #m("paper.holdout_end_long"). No daily price history of any security for dates after 31 December 2025 has been requested, and the fetch code refuses such a request until the registered commit unseals it. The protocol is filed first; each arm then runs once from the registered commit, every attempt is recorded, and the result is published whatever it is. At the date of this note the pre-registration is #m("paper.prereg_status")\; @tab-hypotheses gives the arms and hypotheses it #if prereg [fixes] else [is to fix].

#tablefig("hypotheses", if prereg [Arms and hypotheses of the pre-registration, filed before any 2026 price series was fetched] else [Arms and hypotheses of the pre-registration, to be filed before any 2026 price series is fetched],
  booktab(columns: (12%, 52%, 36%), align: (left, left, left),
    header: ([Label], [Arm], [Hypothesis]),
    rows: T("hypotheses")),
  notes: [Test: one-sided Newey–West t on the daily net returns, Holm-adjusted across H1 and H2 at a familywise 5%. S3 is reported with the same statistics but tested in no family: its universe is ranked on market values inside the test period, so a rejection could reflect survivorship rather than an edge.])

For each tested arm the null hypothesis is that the mean daily net return over the holdout is at most zero, against the alternative that it is positive. The test is the one-sided Newey--West t-test on every daily net return the arm's export records, with nothing dropped; the two confirmatory p-values are adjusted with the step-down procedure of #cite(<holm1979>, form: "prose") at a familywise level of 5%, and an arm shows an edge out of sample only if its adjusted p-value is below 0.05. The pre-registration also discloses the simulated size of this test at the holdout's length, which departs slightly from the nominal level. Whatever the outcome, each arm reports its net and gross return, its Sharpe ratio with standard error, the probabilistic Sharpe ratio, the block-bootstrap interval, the one-sided upper bound, its trades and exposure, the Ledoit--Wolf difference against the Gatev method, the random-pair percentile and, for S1 and S2, the survivorship gap at every formation or snapshot.

*Power, stated in advance.* About ten months of data can detect only a large Sharpe ratio. With returns shaped like the development period's (skewness #m("paper.holdout_power.skew"), non-excess kurtosis #m("paper.holdout_power.kurtosis"), lag-1 autocorrelation #m("paper.holdout_power.rho")), a test at Holm's first step (one-sided 2.5%, the level the better of the two arms must reach) with 80% power detects an annualised Sharpe ratio of about #m("paper.holdout_power.mde_200") over the registered #m("paper.holdout_power.registered_days") trading days, #m("paper.holdout_power.mde_normal_200") for normal returns (@tab-holdout-power); its power against a true Sharpe ratio of 1, 2 and 3 is #m("study.dev.facts.ho_power_1"), #m("study.dev.facts.ho_power_2") and #m("study.dev.facts.ho_power_3"). The holdout is therefore a falsification check, not a proof of an edge: it can reject a large edge but cannot confirm a small one, and not rejecting the null is not evidence that the edge is zero, which is why each arm's upper bound is reported. Running v32 alone first would spend the holdout, so the three arms are frozen together and each runs once.

#tablefig("holdout-power", [Smallest annual Sharpe ratio the holdout detects with 80% power],
  booktab(columns: (25%, 25%, 25%, 25%), align: (right, right, right, right),
    header: ([Holdout length, trading days], [Development shape, one-sided 2.5%], [Development shape, one-sided 5%], [Independent normal returns, one-sided 2.5%]),
    rows: T("holdout_power")),
  notes: [Six months, the registered calendar (#m("paper.holdout_start_long") to #m("paper.holdout_end_long") on the exchange's holiday schedule) and a year. The development shape uses the asymptotic Sharpe variance for non-normal returns with lag-1 autocorrelation, as in @tab-alternatives; it is computed from development returns only.],
  source: [Author's calculation from the daily net returns of the #m("paper.design") development run.],
  placement: top)

*Inputs dated 2026.* No strategy reads a 2026 price, but some inputs carry 2026 information, and the pre-registration lists each one. The v32 universe file ranks stocks on market values of #m("paper.v32_universe_as_of_long"), which is why S3 is descriptive. The identity data (the CUSIP-to-ticker map, SEC industry codes, the listing venue) are as of October 2026: a ticker missing from the SEC's company list of that date has no industry, and in the holdout a name first held in a 2026 snapshot has one only if it is among the largest stocks of the v32 universe file, so both rules use 2026 information. The Kenneth French factor files and the FRED rates reach into 2026; every run truncates the factors at its own calendar's last date, and FRED is read only for the cash comparison. The vendor's responses carry the latest quote in their metadata, which no study code reads, and its adjusted price levels carry 2026 corporate actions, which the anchoring to N-PORT removes for S1 and S2.

// ══════════════════════════════════════════════════════════════════════════════════════
= Threats to validity <sec-threats>
// ══════════════════════════════════════════════════════════════════════════════════════

Each limitation, which way it biases the result, how large it is, and what addresses it (@tab-threats). Biases that flatter the strategy make the null more convincing, not less.

#let up = text(font: sans-md, fill: col("neg"))[↑ flatters]
#let down = text(font: sans-md, fill: col("pos"))[↓ penalises]
#let either(body) = text(font: sans-md, fill: ink2)[· #body]
#[
#show figure: set block(breakable: true)
#tablefig("threats", [Threats to validity of the v33 development run and the 2026 test],
  booktab(columns: (22%, 13%, 34%, 31%), align: (left, left, left, left), size: 7pt, inset-y: 2.9pt,
    header: ([Threat], [Direction of bias], [Size], [Mitigation]),
    rows: (
      ([Survivorship is measured, not removed], up, [#m("study.dev.facts.gap_first_pct") of index weight at the first formation and #m("study.dev.facts.gap_last_pct") at the last have no free price history, mostly companies acquired or delisted since (@ex-universe)], [Point-in-time membership; the gap reported at every formation, and at every formation and snapshot of the holdout]),
      ([Design choices were made on the same data], up, [#m("paper.versions_count") versions on #m("paper.data_years")\; the deflated Sharpe's #m("study.dev.facts.dsr_trials") trials are a lower bound; an exploratory v33 run was seen before the published one (@tab-trials)], [The pre-registered 2026 holdout; the declared variant family; the trial registry]),
      ([Vendor prices carry corporate actions after the window], either[either way], [Split events are reported only inside the window, so early levels of names that split or paid dividends later are rescaled; anchoring moved #m("study.dev.facts.anchor_moved") of #m("study.dev.facts.anchor_symbols") histories by more than 10%], [Levels anchored to N-PORT for S1 and S2; returns, z-scores and hedge ratios are unaffected; a 2026 split's effect on the \$5 screen is measured once 2026 split events can be fetched]),
      ([Some inputs are dated 2026], either[small, either way], [Identity data as of October 2026 (two industry-map rules use 2026 information), factor files and FRED rates into 2026, quote metadata in the vendor's responses, and the v32 universe file], [Rules disclosed in the pre-registration; factors truncated at each calendar's end and read by no strategy; FRED read only for the cash comparison; the quote metadata is not read]),
      ([The frozen v32 arm's universe looks ahead into 2026], up, [Its membership is ranked by market value on #m("paper.v32_universe_as_of_long"), inside the test period: a name that failed during 2026 is absent], [S3 is descriptive: reported with the same statistics, tested in no family]),
      ([Renamed securities can look delisted], either[overstates the gap], [A ticker change with a new CUSIP can read as a member without prices], [Remapped through N-PORT's reported tickers, issuer successions and price checks against N-PORT's value per share]),
      ([Borrow is one fee for every name], up, [Borrow was \$#m("study.dev.facts.borrow_usd_k")k of \$#m("study.dev.facts.cost_usd_k")k of costs; specials and recalls are not modelled], [#m("paper.borrow_pct") median fee; 1% and 3% re-runs (@ex-scenarios)]),
      ([Fills are close-to-close], either[either way], [Larger leg #m("study.dev.facts.adv_participation_pct") of ADV on average; the closing auction is assumed, with no queue or intraday model], [Impact stressed at _Y_ = 0.6 and 1.0; _t_ + 1 open fills a declared variant]),
      ([Cost parameters are published averages, not measurements], either[either way], [No free tick or quote data: spreads by ADV bucket and impact from published estimates], [Declared stress scenarios; capacity re-pricing (@ex-scenarios, @ex-capacity)]),
      ([Cost scenarios change the trades], either[either way], [Each re-run is a new path: #m("study.dev.cost_sensitivity.trades_min") to #m("study.dev.cost_sensitivity.trades_max") trades], [The headline trades re-priced beside each re-run, and the fixed-trade cost curve (@ex-costcurve)]),
      ([Hedge ratios below one leave market exposure], either[adds beta], [Mean hedge ratio #m("study.dev.facts.hedge_mean")\; market loading t = #m("study.dev.facts.mkt_t_main") (@ex-factors)], [Eight-factor attribution reported; the market component of gross P&L separated (@ex-anatomy)]),
      ([The main backtest and the walk-forward overlap], up, [#m("study.dev.facts.oos_overlap_days") of #m("study.dev.facts.main_days") days in common, the same formations; with no model to refit they are one rule from two start dates], [The holdout is the independent test]),
      ([The random-pair control trades a different rule], either[weakens the comparison], [Random pairs run through the Gatev rule, not this engine, on committed capital], [A control on the strategy's own engine is planned]),
    )),
  notes: [↑ flatters the strategy; ↓ penalises it; · no single direction.])
]

// ══════════════════════════════════════════════════════════════════════════════════════
// Forthcoming results: every result still absent, with what it will show
// ══════════════════════════════════════════════════════════════════════════════════════
#if D.forthcoming.len() > 0 [
  = Forthcoming results <sec-forthcoming>

  Each analysis below is specified and its code is committed, but its results are not yet among the committed data this note reads. When they are, the item leaves this table and appears in its section. None of them is reported here as a number.

  #tablefig("forthcoming", [Forthcoming results],
    booktab(columns: (22%, 56%, 22%), align: (left, left, left),
      header: ([Analysis], [What it will show], [Awaits]),
      rows: D.forthcoming.map(r => (text(font: sans-md, r.at(1)), r.at(2), r.at(3)))))
]

// ══════════════════════════════════════════════════════════════════════════════════════
= Reproducibility <sec-repro>
// ══════════════════════════════════════════════════════════════════════════════════════

#if D.concordance != none [The research-note site presents the same results; @tab-concordance maps its exhibit numbers to this note's.] Every number in this note is formatted by `scripts/build_paper.py` from `assets/study.json`, the file the research-note site's charts and checked numbers come from, and from the headline JSON that file was built from; the site's numbers are checked against the same JSON by `scripts/check_published_numbers.py`. Sentences whose wording depends on the data are asserted against it when the note is compiled. Prices come from Yahoo Finance's chart API, and a later fetch will not match the cached data bit for bit, because vendors revise history. The run manifest (@tab-manifest) pins what was used, and the sha256 of every committed source the note reads is listed in @tab-hashes; both are in the appendix.

The runbooks clear every `PAIRS_*` switch, fix the hash seed, refuse an environment that differs from `requirements.txt` and record the commit in every export. The execution-cost note, `docs/EXECUTION_COSTS.md`, compares the cost model with published impact estimates at each participation rate and gives the source of the borrow fee. The AR(1) variance of the Sharpe ratio and its source are documented in `pairs_trading/power.py`; the evidence layer is `pairs_trading/anatomy.py` and `pairs_trading/evidence.py`; the synthetic validation is `scripts/synthetic_validation.py`.

#wide(block(width: 100%, fill: sunk, inset: (x: 9pt, y: 8pt), radius: 2pt, breakable: false, {
  set text(size: 7.8pt)
  raw(block: true, lang: "bash", "# the environment pinned in requirements.txt
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt

# the development-period studies behind this note, in order:
# main, anatomy, costs, residual, variants, validation, publish
PYTHON=.venv/bin/python bash scripts/run_dev_studies.sh

# the site's data, the check of every marked number, and this paper
.venv/bin/python scripts/build_site_data.py           # " + D.meta.run_dir + "
.venv/bin/python scripts/check_published_numbers.py   # README.md, index.html
.venv/bin/python scripts/build_paper.py               # needs pip install -e \".[paper]\"
.venv/bin/python scripts/build_paper.py --check

# the pre-registered 2026 test: once, from a full clone
# at the registered commit, after the pre-registration
PYTHON=.venv/bin/python bash scripts/run_holdout.sh")
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

#tablefig("spec", [Specification of the #m("paper.design") design (study profile #m("paper.design"), hash #m("paper.profile_hash"))],
  booktab(columns: (14%, 86%), align: (left, left),
    header: ([Stage], [Rule]),
    rows: T("spec")))

#tablefig("variants", [Variants declared on #m("paper.declared_long") for the data-snooping tests],
  booktab(columns: (26%, 74%), align: (left, left),
    header: ([Variant], [What it changes]),
    rows: T("variants").map(r => (text(font: mono, size: 6.8pt, r.at(0)), r.at(1)))),
  notes: [The threshold grid covers the three hand-set trading thresholds, which were chosen across versions on this same data. Each toggle changes one setting of the v33 design.],
  source: [The declaration of the variant family, `results/variant_family/declaration.json`, committed on #m("paper.declared_long").])

#tablefig("windows", [Walk-forward windows: calendar slices of one continuous simulation],
  booktab(columns: (9%, 15%, 15%, 9%, 13%, 10%, 9%, 10%, 10%), align: (right, left, left, right, right, right, right, right, right),
    header: ([Window], [Test from], [Test to], [Days], [Net return, %], [Sharpe], [Trades opened], [Win rate, %], [Max drawdown, %]),
    rows: T("windows")),
  notes: [Windows are numbered in calendar order. Positions carry across window boundaries. Sharpe ratios are annualised. The last window runs to the walk-forward's last day.],
  source: [#run-source.])

#tablefig("schedules", [Cost schedules A–E: parameters and results of the replay],
  booktab(columns: (4%, 7%, 9%, 7%, 8%, 8%, 9%, 7%, 6%, 7%, 9%, 11%, 8%), align: (left,) + (right,) * 12, size: 7pt,
    header: ([], [Comm., bp], [Half-spread, bp], [Impact cap, bp], [Borrow, % a year], [Financing, % a year], [Position, % of equity], [Return, %], [Sharpe], [Max DD, %], [Costs, % of capital], [Peak gross, × capital], [Trades replayed]),
    rows: T("schedules")),
  source: [Author's replay of the #m("paper.design") trades under schedules A–E; returns, Sharpe ratios and drawdowns as in the run's headline results.])

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
      ([v32], [Full audit and rebuild of the engine, Kalman model, accounting, walk-forward, costs, ranker, benchmarks and outputs; synthetic known-answer validation; study run of #m("paper.v32_run_date_long"): no detectable edge. Kept as the published record, and as the frozen descriptive arm of the holdout.]),
      ([v33], [#if prereg [The pre-registered design] else [The design to be pre-registered]: point-in-time universe from N-PORT, same-industry pairs, full re-formation, regime gate and ranker off, one borrow fee; the evidence layer, a second strategy family, the trial registry and the sealed 2026 holdout. Development run of #m("paper.run_date_long"): no detectable edge.]),
    )),
  notes: [Versions that only withdrew or corrected earlier results are listed with the fixes they made; `docs/PROGRESS.md` has the full record.])

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
    notes: [The site orders its exhibits by its own sections. Titles are the site's; where this note words a finding differently, this note's wording applies. Exhibits of this note without a site counterpart are not listed.])
}
