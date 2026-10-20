"""
PAIRS TRADING - TRANSACTION COST MODEL
======================================
Per-execution cost model for the backtest, plus the profile-aware variant used by the
cost-schedule replay.

Cost of one execution of one leg (dollars):
    commission    cents-per-share x shares (with a per-order minimum)
    half-spread   the stock's typical half-spread, from its own 20-day dollar ADV bucket
    market impact square-root law: Y x sigma_daily x sqrt(shares / ADV_shares) x notional
Holding costs of a position:
    stock borrow  general-collateral fee on the short leg, per calendar day
    carry         prime-broker spread on the short side of the book, per calendar day

v32 (audit): through v31 the model charged a flat 0.8 bp spread and ~0.09 bp commission
on every stock (the class docstring described them as "ultra-low institutional rates for
profitability"), used a hardcoded 5M-share ADV and 2% volatility for impact, set the
borrow fee from the LENGTH of the ticker symbol (GOOGL paid 2%/yr as "very hard to
borrow"), and charged SOFR + spread on 10% of gross as financing — although in a
dollar-neutral book the short proceeds fund the long and SOFR nets out. Levels are now
taken from the stock's own liquidity and published cost research (see each constant).
Hard-to-borrow specials and SEC Section 31 / FINRA TAF fees (<= 0.3 bp on sells) are not
modelled — disclosed limitations.
"""

from pairs_trading.config import np, logging, Dict

logger = logging.getLogger(__name__)

# Typical quoted FULL spread (bps) by 20-day average dollar volume — liquid US equities.
# Large caps trade at 1-2 bp, mid caps at 3-10 bp and small caps at 50 bp or more
# (docs/EXECUTION_COSTS.md; Frazzini, Israel & Moskowitz 2018,
# "Trading Costs"). The model charges HALF of the full spread per execution.
SPREAD_BUCKETS_BPS = (
    (500e6, 1.5),     # ADV >= $500M
    (100e6, 4.0),     # $100M - $500M
    (20e6, 10.0),     # $20M - $100M
    (5e6, 30.0),      # $5M - $20M
    (0.0, 80.0),      # < $5M
)


def half_spread_bps(adv_dollars: float = None) -> float:
    """Half of the typical quoted spread (bps) for a stock with this dollar ADV."""
    if adv_dollars is None or not np.isfinite(adv_dollars) or adv_dollars <= 0:
        adv_dollars = 100e6              # unknown liquidity -> mid-cap assumption
    for floor, full_bps in SPREAD_BUCKETS_BPS:
        if adv_dollars >= floor:
            return full_bps / 2.0
    return SPREAD_BUCKETS_BPS[-1][1] / 2.0


def sqrt_impact_bps(participation: float, daily_volatility: float, coefficient: float,
                    cap_bps: float) -> float:
    """Square-root market impact in bps: Y x sigma_daily x sqrt(Q / ADV), capped."""
    p = max(float(participation), 0.0)
    vol = float(daily_volatility) if daily_volatility is not None and np.isfinite(daily_volatility) \
        and daily_volatility > 0 else 0.02
    return float(min(coefficient * vol * np.sqrt(p) * 1e4, cap_bps))


class EnhancedPrimeFundTransactionCostModel:
    """Per-execution costs for the main backtest (a $100M institutional book)."""

    # Defaults used when a stock's own liquidity/volatility is unavailable.
    DEFAULT_DAILY_VOLUME_SHARES = 5e6
    DEFAULT_DAILY_VOLATILITY = 0.02

    def __init__(self, borrow_rate: float = 0.0025, pb_financing_spread: float = 0.005):
        """`borrow_rate`/`pb_financing_spread`: annual holding costs (study_config profile;
        the defaults are v32's)."""
        # Electronic institutional execution: ~0.2 cents/share all-in (0.1-0.5 cps is the
        # quoted range for algorithmic agency execution; IBKR Pro tiered is 0.35 cps).
        self.commission_per_share = 0.002
        self.min_commission_per_trade = 0.50
        # Square-root impact coefficient Y in Y x sigma_daily x sqrt(Q / ADV). Fills are
        # next-day closes, i.e. market-on-close orders in the closing auction: Goyal,
        # Jegadeesh & Wu (2025, JFQA, Table 3) measure 4.5 bp of auction impact for NYSE
        # large caps at 1% of ADV (Y ~ 0.28 at sigma_daily 1.6%) and 10.2 bp on Nasdaq
        # (Y ~ 0.64). Continuous-market estimates run higher (Kyle & Obizhaeva 2016
        # ~0.6, Toth et al. 2011 "of order one"), so the cost-sensitivity runs repeat the
        # study at Y = 0.6 and 1.0. (Almgren et al. 2005's 0.314 is their PERMANENT-impact
        # coefficient, not the temporary cost of a trade.) The cap is a safety rail.
        self.market_impact_coefficient = 0.3
        self.market_impact_cap_bps = 50.0
        # Stock-borrow fee on short notional. v32: 25 bp/yr general collateral (D'Avolio
        # 2002: GC loans average ~17 bp, a value-weighted book ~25 bp). v33: the median
        # buy-side indicative fee, 0.38%/yr (Muravyev, Pearson & Pollet 2025, Table 1).
        # Specials are not modelled; the cost-sensitivity runs stress every short at 1%
        # and 3%/yr (the p90 of their fee distribution).
        self.gc_borrow_rate = float(borrow_rate)
        # Prime-broker spread on the short half of a dollar-neutral book (v32: 50 bp; SOFR
        # itself nets between the long debit and the short credit). v33 sets it to zero:
        # for general-collateral names the haircut on the short rebate IS the borrow fee,
        # so charging both counted it twice, and the book never runs leverage.
        self.pb_financing_spread = float(pb_financing_spread)
        logger.info("Transaction cost model: per-share commission, ADV-bucket spread, "
                    "per-stock sqrt impact, GC borrow, PB carry")

    # ── one-way execution components ─────────────────────────────────────────────
    def calculate_commission_costs(self, position_size: float, price: float,
                                   monthly_volume: float = None) -> float:
        """Commission for `position_size` shares: cents-per-share with a per-order minimum.

        `monthly_volume` is accepted for backward compatibility and ignored (the old
        volume-tier discount applied the same 0.6x to every trade).
        """
        shares = abs(float(position_size))
        if shares <= 0:
            return 0.0
        return max(shares * self.commission_per_share, self.min_commission_per_trade)

    def calculate_market_impact_cost(self, position_size: float, price: float,
                                     daily_volume: float,
                                     daily_volatility: float = 0.02) -> float:
        """Square-root market impact in dollars.

        impact_fraction = coefficient x daily_volatility x sqrt(participation_rate), with
        participation = shares / ADV shares (both in the same split-adjusted units).
        v31 (audit) restored the volatility factor that had been missing.
        """
        shares = abs(float(position_size))
        trade_value = shares * float(price)
        participation = shares / daily_volume if daily_volume and daily_volume > 0 else 0.0005
        bps = sqrt_impact_bps(participation, daily_volatility, self.market_impact_coefficient,
                              self.market_impact_cap_bps)
        return trade_value * bps / 1e4

    def calculate_bid_ask_cost(self, position_size: float, price: float,
                               adv_dollars: float = None) -> float:
        """Half-spread paid on one execution, from the stock's dollar-ADV bucket."""
        trade_value = abs(float(position_size)) * float(price)
        return trade_value * half_spread_bps(adv_dollars) / 1e4

    def calculate_leg_cost(self, shares: float, price: float,
                           daily_volume_shares: float = None,
                           daily_volatility: float = None,
                           monthly_volume: float = None,
                           point_in_time_price: float = None) -> Dict[str, float]:
        """One-way cost of trading one leg: commission + half-spread + market impact.

        `shares`/`price` are in the data's split-adjusted units; `daily_volume_shares` must
        be in the same units. The backtest passes the stock's own 20-day average share
        volume and daily volatility as of the trade date, and the point-in-time
        (split-unadjusted) price, so the per-share commission is charged on the number
        of shares that would really have traded.
        """
        shares = abs(float(shares))
        price = float(price)
        zero = {'commission': 0.0, 'bid_ask': 0.0, 'market_impact': 0.0, 'total': 0.0}
        if not (shares > 0 and np.isfinite(price) and price > 0):
            return zero
        dv = daily_volume_shares
        if dv is None or not np.isfinite(dv) or dv <= 0:
            dv = self.DEFAULT_DAILY_VOLUME_SHARES
        vol = daily_volatility
        if vol is None or not np.isfinite(vol) or vol <= 0:
            vol = self.DEFAULT_DAILY_VOLATILITY
        pit = point_in_time_price
        real_shares = shares * price / pit if pit is not None and np.isfinite(pit) and pit > 0 else shares
        commission = self.calculate_commission_costs(real_shares, price)
        bid_ask = self.calculate_bid_ask_cost(shares, price, adv_dollars=dv * price)
        impact = self.calculate_market_impact_cost(shares, price, dv, vol)
        return {'commission': commission, 'bid_ask': bid_ask, 'market_impact': impact,
                'total': commission + bid_ask + impact}

    # ── holding costs ────────────────────────────────────────────────────────────
    def get_borrow_category(self, symbol: str) -> str:
        """Every name is charged the general-collateral fee (specials are not modelled).

        v32: the category used to be inferred from the ticker's length — a baseless rule
        that charged e.g. GOOGL 2%/yr as "very hard to borrow".
        """
        return 'general_collateral'

    def calculate_borrow_cost(self, short_notional: float, symbol: str, calendar_days: int) -> float:
        """Stock-borrow fee on the short leg over the holding period (calendar days)."""
        return abs(float(short_notional)) * self.gc_borrow_rate * (max(int(calendar_days), 0) / 365.0)

    def calculate_financing_cost(self, gross_notional: float, calendar_days: int) -> float:
        """Carry of a dollar-neutral position: PB spread on its short half, per calendar day."""
        return abs(float(gross_notional)) / 2.0 * self.pb_financing_spread * \
            (max(int(calendar_days), 0) / 365.0)

    # ── round trip (kept for callers that want one number) ───────────────────────
    def calculate_total_trade_costs(self, long_position: float, short_position: float,
                                    long_price: float, short_price: float,
                                    long_symbol: str, short_symbol: str,
                                    holding_days: int = 1, monthly_volume: float = None,
                                    long_adv_shares: float = None, short_adv_shares: float = None,
                                    long_daily_vol: float = None,
                                    short_daily_vol: float = None) -> Dict[str, float]:
        """Round-trip cost of a pair position held `holding_days` calendar days.

        Entry and exit are costed at the same prices (the engine itself costs each
        execution at its own price via calculate_leg_cost). Positions are share counts.
        """
        lc = self.calculate_leg_cost(long_position, long_price, long_adv_shares, long_daily_vol)
        sc = self.calculate_leg_cost(short_position, short_price, short_adv_shares, short_daily_vol)
        short_value = abs(float(short_position)) * float(short_price)
        long_value = abs(float(long_position)) * float(long_price)
        borrow = self.calculate_borrow_cost(short_value, short_symbol, holding_days) \
            if short_position > 0 else 0.0
        financing = self.calculate_financing_cost(long_value + short_value, holding_days)
        costs = {
            'long_commission': lc['commission'], 'long_market_impact': lc['market_impact'],
            'long_bid_ask': lc['bid_ask'],
            'short_commission': sc['commission'], 'short_market_impact': sc['market_impact'],
            'short_bid_ask': sc['bid_ask'], 'short_borrow': borrow,
        }
        costs['total_entry_cost'] = lc['total'] + sc['total']
        costs['exit_commission'] = lc['commission'] + sc['commission']
        costs['exit_market_impact'] = lc['market_impact'] + sc['market_impact']
        costs['exit_bid_ask'] = lc['bid_ask'] + sc['bid_ask']
        costs['total_exit_cost'] = costs['total_entry_cost']
        costs['total_borrow_cost'] = borrow
        costs['financing_cost'] = financing
        costs['total_cost'] = (costs['total_entry_cost'] + costs['total_exit_cost'] +
                               borrow + financing)
        return costs


# ──────────────────────────────────────────────────────────────────────────────
# Profile-aware cost calculator (used by the cost-schedule replay)
# ──────────────────────────────────────────────────────────────────────────────

def calculate_profile_trade_costs(
    position_value: float,       # gross notional (long leg + short leg)
    profile,                     # FundProfile instance
    holding_days: int,
    sofr: float = 0.050,
    long_symbol: str = 'AAPL',
    short_symbol: str = 'MSFT',
    long_value: float = None,
    short_value: float = None,
    daily_volatility: float = None,
    adv_dollars: float = None,
    long_adv_dollars: float = None,
    short_adv_dollars: float = None,
    long_daily_vol: float = None,
    short_daily_vol: float = None,
) -> Dict[str, float]:
    """Round-trip cost of a pair trade under a FundProfile (dollars).

    Per execution (4 = 2 legs x entry + exit): commission (profile bps), half-spread
    (profile bps), and square-root impact profile.market_impact_coeff x sigma_daily x
    sqrt(leg notional / ADV$), capped at the profile cap. Holding: the profile's GC borrow
    rate on the short leg and its financing spread on the short side (the rebate
    haircut), per calendar day. `daily_volatility`/`adv_dollars` are the traded stocks'
    own values when known (the replay passes them), else 2% and the profile's ADV. Each
    leg's impact uses that leg's own dollar ADV and volatility when given
    (long_/short_adv_dollars, long_/short_daily_vol), else the pair-level values.

    v32 (audit): impact had no volatility factor (the bug v31 fixed only in the main
    model), so every profile paid its flat cap; it was charged on entry only ("temporary
    impact reverses" — but every execution pays it); borrow came from ticker length;
    financing charged SOFR + spread on a heuristic "implied leverage" that was 0 for three
    profiles. `sofr` is accepted for backward compatibility and unused (it nets out).
    """
    half = position_value / 2.0
    if long_value is None or short_value is None:
        long_value, short_value = half, half
    days = max(int(holding_days), 0)
    commission = 2 * (long_value + short_value) * (profile.commission_bps / 10_000)
    bid_ask = 2 * (long_value + short_value) * (profile.bid_ask_bps / 10_000)
    def _pos(x):
        return x if x is not None and np.isfinite(x) and x > 0 else None

    adv = _pos(adv_dollars) or profile.daily_volume_dollars
    impact = 0.0
    for leg, leg_adv, leg_vol in ((long_value, _pos(long_adv_dollars), long_daily_vol),
                                  (short_value, _pos(short_adv_dollars), short_daily_vol)):
        vol = leg_vol if leg_vol is not None and np.isfinite(leg_vol) else daily_volatility
        bps = sqrt_impact_bps(leg / max(leg_adv or adv, 1.0), vol,
                              profile.market_impact_coeff, profile.market_impact_cap_bps)
        impact += 2 * leg * bps / 1e4                    # entry and exit executions
    borrow_cost = short_value * profile.borrow_rate_general * (days / 365.0)
    financing_cost = short_value * profile.financing_spread * (days / 365.0)
    total = commission + bid_ask + impact + borrow_cost + financing_cost
    return {
        'commission': commission,
        'bid_ask': bid_ask,
        'market_impact': impact,
        'borrow': borrow_cost,
        'financing': financing_cost,
        'total_cost': total,
        'total_bps': total / max(position_value, 1.0) * 10_000,
    }
