# Methods

Technical detail for [MC311 Call Center Staffing](README.md).

## The decision framework

This is a newsvendor problem. Demand is uncertain, capacity is committed before
demand is observed, and the costs of over- and under-committing differ. The
optimal service level is the critical ratio:

    q* = C_under / (C_under + C_over)

Expressed per contact:

    C_over  = (hourly wage x loaded multiplier x shift hours) / contacts per agent-day
            = ($21.53 x 1.35 x 8) / 55
            = $4.23 per contact of capacity

    C_under = cost per contact x unhandled multiplier
            = $4.15 x 2.5
            = $10.38 per unhandled contact

    q*      = 10.38 / (10.38 + 4.23) = 0.710

Evaluation uses pinball loss at the target quantile rather than RMSE or MAPE.
Point-accuracy metrics score the wrong objective when the loss function is
asymmetric.

## Forecasting approach

**Point forecast.** Trailing 8-observation median for the same weekday. Selected
by rolling-origin comparison against three alternatives:

| Forecast | MAE | RMSE | MAPE |
|---|---|---|---|
| Seasonal naive (same weekday, last week) | 197.4 | 334.5 | 11.02% |
| Trailing weekday mean | 156.5 | 239.4 | 8.83% |
| **Trailing weekday median** | **147.4** | **228.9** | **8.31%** |
| Weekday level x month index | 151.3 | 226.3 | 8.70% |

The median beating the mean is informative: storm spikes pull a mean-based
forecast around.

**Quantile forecasts.** Trailing 250-day distribution of the ratio
`actual / point forecast`, applied multiplicatively. Ratios rather than
differences, because error scales with volume. A 200-contact miss on a
2,400-contact Monday is not the same event as on a 1,500-contact Friday.

Coverage check on 3,165 days:

| Nominal | Actual | Gap |
|---|---|---|
| 0.50 | 0.493 | -0.007 |
| 0.70 | 0.692 | -0.008 |
| 0.80 | 0.795 | -0.005 |
| 0.90 | 0.889 | -0.011 |
| 0.95 | 0.946 | -0.004 |

Every quantile lands within 1.1 points of nominal.

## Leakage prevention

Every value used to forecast day *t* comes from days strictly before *t*.

- Quantiles come from a trailing residual window, shifted one day.
- Storm multipliers use only storms that already happened. State updates occur
  after each row is scored.
- Closure flags use a trailing 60-day median, shifted.
- No random train/test split anywhere. Evaluation is rolling-origin throughout.

## Cleaning decisions

**Weekends dropped.** Weekend volume averages 102 contacts against 1,799 on
weekdays. That is after-hours logging, not staffed service. There is no staffing
decision to make on a day the center is closed.

**Closures excluded from evaluation, not imputed.** A closed office is not a
demand event. Forecasting "1 contact on Thanksgiving" is trivially easy and
would flatter every error metric.

Closures are identified from the data rather than from a federal holiday
calendar: any weekday below 40% of its trailing 60-day median. This catches 40
days (1.1%), including unscheduled snow closures and partial days that a
hardcoded calendar would miss.

**Storm days kept.** They are real demand and they are the point of the
analysis. Removing them would improve every accuracy metric and worsen every
decision.

## Weather features

The naive feature is same-day snowfall. It is wrong, and the diagnostic shows
why.

Correlation between snow accumulation and the volume ratio:

| Window | All days | Days with snow |
|---|---|---|
| Same day | **-0.033** | -0.133 |
| 2-day | 0.115 | 0.224 |
| 3-day | 0.206 | 0.356 |
| 5-day | 0.322 | 0.462 |
| 7-day | 0.349 | 0.486 |

Same-day snow is negatively correlated. The county closes during the storm.
Correlation rises monotonically with the window because demand is deferred into
the reopening and stays elevated for most of a week.

Lag structure after 2+ inches:

| Days after snow | Mean volume ratio | Share above 1.2x |
|---|---|---|
| 0 | 0.931 | 12% |
| 1 | 1.228 | 40% |
| 2 | 1.196 | 38% |
| 3 | 1.245 | 21% |
| 4 | 1.210 | 22% |
| 5 | 1.218 | 30% |

Baseline across all days is 1.012 with 5.8% above 1.2x.

Dose response on 3-day accumulation:

| Accumulation | Days | Mean ratio | Median ratio |
|---|---|---|---|
| None | 2,768 | 1.009 | 0.999 |
| Trace to 0.5" | 227 | 1.001 | 0.991 |
| 0.5-1" | 53 | 1.036 | 0.997 |
| 1-2" | 39 | 1.011 | 1.020 |
| 2-4" | 42 | 1.041 | 1.021 |
| 4-8" | 31 | 1.171 | 1.031 |
| **8"+** | **5** | **1.669** | **1.619** |

The response is a threshold, not a gradient. Below 4 inches, nothing. The
initial 4-inch trigger was set by intuition; the data moved it to 8.

**Cold is a separate signal.** 119 days below 20°F show a mean ratio of 1.135
without snow necessarily present. Frozen pipes, heating complaints, water main
breaks.

## Storm-conditional staffing

Storm days are drawn from a different distribution:

| Quantile | All days | Storm days |
|---|---|---|
| 50th | 0.999 | 1.055 |
| 70th | 1.048 | 1.254 |
| 80th | 1.081 | 1.445 |
| 90th | 1.142 | 1.932 |
| 95th | 1.215 | 2.309 |

By accumulation band:

| Band | n | Mean ratio | Median ratio |
|---|---|---|---|
| 4-8 inches | 60 | 1.153 | 1.021 |
| 8+ inches | 8 | 1.842 | 1.963 |

**Estimator.** For each triggered day, take the q-th quantile of the ratio from
all *prior* storm days, split by accumulation band once at least 8 prior storms
exist in that band, otherwise pooled. Days without enough history fall back to
the fixed-quantile policy. 60 of 68 storm days had sufficient history.

Sample size is the binding constraint. With 68 events in twelve years, anything
more elaborate than a trailing quantile would fit noise. No regression, no
tuning parameters.

## A complication tested and rejected

Monday averages 2,075 contacts and Friday 1,594, a 30% spread. That suggested
per-weekday quantile targets might beat a single fixed quantile.

Coverage at the 70th percentile by weekday:

| Weekday | Coverage |
|---|---|
| Monday | 0.704 |
| Tuesday | 0.699 |
| Wednesday | 0.664 |
| Thursday | 0.695 |
| Friday | 0.697 |

Spread of 0.040. A single quantile serves every weekday, so the policy stays
simple.

## Data notes

**Channel selection.** MC311 records 18 contact channels. Phone is 82.2% of
volume, web is 13.9%, and everything else is under 3%. Only phone contacts
consume agent handle time. Walk-in exists but is 0.18% of volume.

**Aggregation.** The source has 7.9M individual service requests. Socrata
aggregates server-side, so daily counts by channel, request type and department
come back in three queries rather than 160 pages of raw records.

**Weekday-only operation.** 3,790 days carry phone volume across a 5,179-day
calendar span, which is 73%, consistent with weekdays only.

**Request mix drift.** The fulfillment share of phone contacts rose from 18.4%
in 2012 to 36.1% in 2026. Handle time is modeled as constant at 55 contacts per
agent-day, which this drift suggests is optimistic for recent years.

**Forecast error drift.** MAE rose from 114 in 2019 to 169 in 2026 while mean
volume fell. Relative error is worsening. Consistent with a harder residual call
mix, not diagnosed further.