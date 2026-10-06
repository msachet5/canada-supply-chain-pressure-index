# Methodology

## Purpose

The Canada Supply Chain Pressure Index (CSCPI) summarises, in one monthly number, how stretched Canadian supply chains are relative to their own history. It is designed to be reproducible from open data by anyone, and to separate supply pressure from swings in demand.

## Relationship to the GSCPI

The Federal Reserve Bank of New York's Global Supply Chain Pressure Index (Benigno, di Giovanni, Groen and Noble, 2022) combines transportation cost measures (Baltic Dry Index, Harpex, US airfreight price indices) with supply chain components of manufacturing PMIs in seven economies (delivery times, backlogs, purchased stocks). PMI components are first purged of demand effects using PMI new orders and quantity purchased, and the index is the first principal component of the purged panel.

The CSCPI keeps that structure but uses only Canadian open data, because PMI microdata and container freight rates are proprietary. The inputs are therefore different and the index is not a Canadian slice of the GSCPI.

## Inputs

Defined in `series.yaml`. Each input has a role:

* **supply**: enters the index after purging (backlogs, inventory ratios, input and freight prices, port and rail performance);
* **demand**: used only to purge (manufacturing new orders, retail sales, freight volumes);
* **benchmark**: used only to validate (the GSCPI).

`cscpi audit` reports for every input whether its filter resolves to exactly one published series, its first and last month, and whether it is current (last observation no more than `max_staleness_months` old).

### The gate

If fewer than `min_current_series` (default 6) supply inputs are current, a principal component would be dominated by a handful of series, so the release falls back to the **indicator pulse**: each input as a signed z-score and their equal-weighted mean. The pulse is labelled as such everywhere it is published.

## Steps

1. **Transform.** Ratios and dwell times enter in levels; prices and volumes as 12-month percent changes. Weekly series are averaged to months; quarterly series repeat within the quarter.
2. **Orient.** Each supply input is multiplied by its sign so that higher always means more pressure.
3. **Standardise** each input to mean 0 and standard deviation 1 over the estimation sample (from `start`, default January 2017).
4. **Purge demand.** Each standardised supply input is regressed on the standardised demand inputs (with a constant) over months where all demand inputs exist; the residual is kept. In the latest months, where demand data may not yet be published, the unpurged value is used (ragged edge) and flagged by the `series_available` column.
5. **Extract the common factor.** The first principal component of the purged, re-standardised panel. Missing cells (late starters, late publishers) are filled iteratively with the rank-one reconstruction until convergence, a standard expectation-maximisation approach to PCA with missing data.
6. **Sign and scale.** The component is signed to correlate positively with the reference input (manufacturing unfilled orders to sales) and scaled to mean 0, standard deviation 1. A value of +1.5 reads "1.5 standard deviations above the average level of pressure since 2017".
7. **Attribute.** Each month's value is decomposed into contributions (input value × loading / scale), so releases can say what moved the index.

## Revisions and vintages

Like the GSCPI, the whole history is re-estimated each month: new data changes standardisation, purging and loadings. Every vintage is kept in `data/releases/` and never overwritten. Errors in a published vintage are recorded in the corrections log in `data/README.md`.

## Validation

`cscpi validate` reports the correlation of the CSCPI with the GSCPI at lags of 0, 1, 3 and 6 months. Co-movement is expected (Canada imports global pressure) but not identity; a large and persistent divergence is a finding to explain, not an error to tune away.

## Limitations

* Fewer and different inputs than the GSCPI, and no survey-based delivery-time measure: Canadian PMI microdata are not open.
* Some Transport Canada performance indicators have irregular update schedules; the audit decides each month whether they enter.
* Principal components are sensitive to the input set. Adding or removing an input is a methodology change, announced in the release notes and versioned.
* The index measures pressure relative to Canada's own recent history, not an absolute level of disruption.

## References

* Benigno, G., di Giovanni, J., Groen, J. J. J. and Noble, A. I. (2022). The GSCPI: A New Barometer of Global Supply Chain Pressures. Federal Reserve Bank of New York Staff Reports, no. 1017.
* Statistics Canada. Monthly Survey of Manufacturing, table 16-10-0047-01.
* Statistics Canada. Industrial product price index (18-10-0266-01) and Raw materials price index (18-10-0268-01).
* Statistics Canada. Railway carloadings (23-10-0216-01); For-hire motor carrier freight services price index (18-10-0281-01).
* Transport Canada via Statistics Canada. Transportation supply chain performance indicators (23-10-0271-01) and weekly rail terminal performance (23-10-0274-01).
