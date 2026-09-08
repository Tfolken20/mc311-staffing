# MC311 Call Center Staffing

**How many agents should a public call center staff, when being understaffed
and being overstaffed cost different amounts?**

|  |  |
|---|---|
| **Question** | What daily staffing level minimises the total cost of a contact center, given that idle agents and unhandled contacts cost different amounts? |
| **Data** | 6.5M phone contacts to Montgomery County MD's 311 center (2012-2026), joined to 14 years of daily weather |
| **Method** | Rolling-origin quantile forecasting, newsvendor cost optimisation, weather-triggered surge policy, sensitivity analysis on every cost assumption |
| **Result** | Staffing to the **70th percentile** of forecast demand instead of the point forecast saves **$26,000/year** and cuts missed contacts by 38%. Adding a weather-triggered surge halves shortfall on storm days at no net cost. |
| **Takeaway** | The most accurate forecast is not the most useful one. When the costs of error are asymmetric, the right target is a quantile, not a mean — and the size of that gap is worth real money. |

![Cost by staffing level](reports/cost_curve.png)

The two dashed lines are the whole argument. Idle capacity gets more expensive
as you staff up; unmet demand gets cheaper. Total cost bottoms out where their
marginal costs cross — at the 70th percentile, not the 50th. A forecast
optimised for average accuracy targets the wrong point on this curve.

## How to reproduce

    conda create -n mc311 python=3.12 -y
    conda activate mc311
    pip install pandas pyarrow requests matplotlib scikit-learn

All data is fetched by script — nothing is downloaded by hand:

    python src/fetch_daily.py        # MC311 via Socrata, server-side aggregation
    python src/fetch_weather.py      # Open-Meteo historical archive
    python src/build_series.py       # daily phone series + structural diagnostics
    python src/baselines.py          # cleaning + four rolling-origin baselines
    python src/staffing_model.py     # quantile forecasts + newsvendor costs
    python src/shortfall_profile.py  # magnitude and concentration of unmet demand
    python src/weather_response.py   # how volume responds to weather
    python src/weather_policy.py     # weather-triggered surge policies
    python src/storm_model.py        # storm-conditional staffing
    python src/make_charts.py        # figures

## The decision, framed properly

A contact center manager does not need a forecast. They need a headcount.

Those are different problems, because the costs of being wrong are not
symmetric. An idle agent costs a day's wages. An unhandled contact costs a
callback, a service failure, and a caller who tries again tomorrow. When those
costs differ, the optimal staffing level is not the *expected* demand — it is a
quantile of the demand distribution, set by the ratio of the two costs:

> optimal quantile = C_under / (C_under + C_over)

### Cost anchors

Both are published figures, and both are varied in the sensitivity analysis
below, because the ratio is the assumption a manager would push back on.

| Parameter | Value | Source |
|---|---|---|
| Agent hourly wage | $21.53 | BLS median, Customer Service Representatives, May 2025 |
| Fully-loaded multiplier | 1.35x | Standard benefits + overhead assumption |
| Cost per handled contact | $4.15 | Midpoint of the published $2.70-$5.60 industry benchmark |
| Unhandled contact multiplier | 2.5x | Base case; varied from 1.0x to 6.0x |

That gives an idle agent-day of $232 and an implied target quantile of **0.71**.

## Result

Evaluated on 3,165 weekdays (2014-2026), rolling-origin, one day ahead:

| Policy | Annual cost | Days short | Contacts missed/yr |
|---|---|---|---|
| Point forecast (mean-optimal) | $284,075 | 49.4% | 20,729 |
| **Quantile 0.70** | **$257,608** | **30.8%** | **12,951** |
| Quantile 0.80 | $266,305 | 20.5% | 9,129 |
| Quantile 0.90 | $323,716 | 11.1% | 5,516 |

The empirical optimum (0.70) matches the theoretical one (0.71) — the
newsvendor formula is doing real work here, not decorating the analysis.

### Sensitivity: does the recommendation survive the assumption?

| C_under / C_over | Implied quantile | Best policy | Annual saving vs point forecast |
|---|---|---|---|
| 1.0 | 0.50 | q50 | **-$817** |
| 1.5 | 0.60 | q60 | $2,247 |
| 2.0 | 0.66 | q70 | $10,328 |
| **2.5 (base)** | **0.71** | **q70** | **$26,468** |
| 3.0 | 0.75 | q75 | $45,523 |
| 4.0 | 0.80 | q80 | $89,979 |
| 6.0 | 0.86 | q85 | $193,972 |

Two things worth saying plainly. The chosen policy tracks the theoretical
quantile closely across the entire range, so the approach is robust even though
the exact number is not. And **at a 1.0 cost ratio the approach loses money** —
when costs are symmetric, the mean-optimal forecast is optimal and quantile
staffing is pure overhead. The method only earns its keep when the asymmetry is
real, and that boundary belongs in the recommendation.

## "31% of days are short" is a misleading sentence

Frequency and severity are different things. Under the recommended policy:

- Median shortfall on a short day: **99 contacts — 1.8 agents**
- 90th percentile shortfall: 357 contacts — 6.5 agents

More importantly, the pain is concentrated:

![Concentration of unmet demand](reports/shortfall_concentration.png)

**Half of all unmet demand comes from 5% of days.** Baseline staffing absorbs
routine variation perfectly well. The residual risk is almost entirely tail —
which means the answer is a surge plan for a handful of days, not permanent
headcount carried 250 days a year.

## The tail is weather, and weather is forecastable

Every one of the ten worst days in the series is a winter storm. January is
short on 47% of days with a mean shortfall of 168 contacts; October is short on
7% of days with a mean shortfall of 3.

**40.6% of the most extreme days follow 1+ inch of snow within three days,
against a 3.7% base rate — an 11x lift.**

Two findings shaped the feature design, and neither was the obvious choice:

**Same-day snow correlates *negatively* with volume** (r = -0.03). During the
storm the county is closed and nobody calls. Demand is deferred into the
reopening. Correlation rises monotonically with the accumulation window — 2-day
0.11, 3-day 0.21, 5-day 0.32, 7-day 0.35 — so the surge is most of a week, not
a day. When Winter Storm Jonas dropped 14.4 inches on a Saturday, the call surge
ran Monday through Thursday.

**The threshold is 8 inches, not 4.** A 4-8 inch accumulation produces a median
volume ratio of 1.02 — indistinguishable from an ordinary day. Above 8 inches
the median is 1.96. The initial 4-inch trigger was set by intuition and the data
corrected it.

### Why a generic surge undershoots

![Storm day distribution](reports/storm_distribution.png)

Staffing storm days to the 95th percentile still left a mean shortfall of 299
contacts and covered only 66% of them. The reason is structural: a quantile
estimated from the whole residual distribution describes *ordinary* variation.
Its 90th percentile is 1.14x. Storm days routinely run 1.9x and reached 2.6x.

The fix is to condition on the event — estimate the ratio from **prior storms
only**, walk-forward, and staff to a quantile of *that* distribution:

| Policy | Storm coverage | Mean storm shortfall | Annual cost |
|---|---|---|---|
| Fixed q70 | 48.5% | 409 contacts (7.4 agents) | $257,608 |
| Fixed q90 (permanent) | 60.3% | 339 contacts | $323,716 |
| Surge to q95 on snow | 66.2% | 299 contacts | $255,219 |
| **Storm model, q90 of prior storms** | **75.0%** | **195 contacts (3.5 agents)** | $254,548 |
| Storm model, q80 of prior storms | 64.7% | 292 contacts | **$254,002** |

**Storm coverage rises from 48.5% to 75.0% and shortfall halves, at slightly
lower total cost than the baseline policy.**

The honest caveat on magnitude: the total saving is ~$3,600 on a $258,000 base,
about 1.4%. Sixty-eight days out of 3,165 cannot move an annual aggregate much
no matter how well they are handled. **The value here is service quality on the
days people remember, not budget.** Compare the alternative: buying similar tail
coverage with a permanent q90 policy costs $66,000 more per year.

### An upper bound, not a delivered number

This uses **observed** weather, so it measures the value of a *perfect*
forecast. A real deployment would use an NWS forecast issued the afternoon
before, which is imperfect.

Historical forecast archives spanning 2012-2026 are not readily available for
free, so this is stated as a ceiling rather than a result. The bound is still
decision-relevant — if perfect weather knowledge did not help, an imperfect
forecast certainly would not, and the idea could be dropped cheaply. The gap is
also narrower for this variable than most: snow events of this magnitude are
forecast with high skill at 24-48 hours.

## Recommendation

1. **Staff baseline to the 70th percentile** of forecast daily demand, not the
   point forecast. Saves ~$26,000/year and cuts missed contacts by 38%.
2. **Run a storm surge protocol** triggered on 8+ inches of accumulated snow
   over the prior five days, sized from prior storms rather than from ordinary
   variation. Fires ~5 days/year, halves shortfall on those days.
3. **Revisit if the cost ratio exceeds 4x.** Above that, permanent capacity at
   the 80th percentile beats targeted surging, and the recommendation flips.

## Method notes

**Cleaning decisions, each defensible:**

- **Weekends dropped.** Weekend volume averages 102 contacts against 1,799 on
  weekdays — after-hours logging, not staffed service.
- **Closures excluded from evaluation, not imputed.** A closed office is not a
  demand event; forecasting "1 contact on Thanksgiving" would flatter every
  error metric. Closures are identified from the data (weekdays under 40% of a
  trailing median), which also catches unscheduled snow closures rather than
  only federal holidays.
- **Storm days kept.** They are real demand and they are the point. Removing
  them would improve every accuracy metric and worsen every decision.

**Leakage prevention.** Every forecast for day *t* uses only data from days
strictly before *t*. Quantiles come from trailing residual distributions; storm
multipliers come from prior storms only; closure flags use a trailing median.
No random splits anywhere.

**A complication that was tested and rejected.** Monday averages 2,075 contacts
and Friday 1,594 — a 30% spread — which suggested per-weekday quantile targets.
Coverage at q70 varied only from 0.664 to 0.704 across weekdays, a 0.040 spread.
A single quantile serves every weekday, so the policy stays simple.

## Data

**MC311 service requests**, Montgomery County MD open data portal, July 2012 to
September 2026 — 7.9M records, aggregated server-side to daily counts by
channel, request type and department.

Phone is 82% of all volume; web is 14% and every other channel is under 3%.
Only phone contacts consume agent handle time, so phone is the staffing-relevant
series: 6.5M contacts across 3,790 days.

**Weather**: Open-Meteo historical archive, Montgomery County centroid, daily
temperature, precipitation, snowfall and wind, 2012-2026.

**A field that did not do what it looked like.** The dataset carries per-request
SLA windows and breach flags, which initially looked like an ideal anchor for
the cost of understaffing. It is not: the SLA measures whether *departments
fulfil requests*, not whether the call center answers phones. Tree Maintenance
has a 245-day window and a 31% breach rate — that is DOT not removing stumps,
and no amount of call center staffing changes it. The SLA data is instead
relevant to a separate question about departmental fulfilment capacity.

## Other findings

- **Call volume is declining**, from 2,040/day in 2012 to ~1,500 in 2025, as web
  self-service absorbs routine contacts. The fulfilment share of phone contacts
  rose from 18% to 36% over the same period — the easy calls left, the complex
  ones stayed.
- **No COVID discontinuity.** 2020 volume was up 1.8% on 2019.
- **Seasonality is mild** (1.19x peak to trough) compared to the day-of-week
  effect (1.29x Monday to Friday).
- **Forecast error is growing** relative to volume — MAE rose from 114 in 2019
  to 169 in 2026 while mean volume fell. Consistent with a harder residual call
  mix, but not diagnosed.

## Limitations

- **Observed weather stands in for forecast weather.** Results involving the
  surge are an upper bound.
- **Handle time is assumed uniform** at 55 contacts per agent-day. The rising
  fulfilment share implies handle time is drifting upward, which this does not
  model.
- **Contacts, not calls.** One call can generate multiple service requests, so
  the series is a proxy for call volume rather than a direct measure.
- **Cost parameters are benchmarks, not this county's actuals.** The sensitivity
  analysis is what makes the recommendation usable despite that.
- **Intraday distribution is not modelled.** A daily headcount is the decision
  here; real scheduling also needs an intraday arrival curve.