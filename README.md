# Canada Supply Chain Pressure Index

**A monthly Canada supply chain pressure index built only from open data.** The New York Fed publishes a Global Supply Chain Pressure Index; Canada has no open equivalent. This repository builds one from Statistics Canada and Transport Canada data, publishes it monthly by a scheduled pipeline, and keeps every vintage.

[![CI](https://github.com/msachet5/canada-supply-chain-pressure-index/actions/workflows/ci.yml/badge.svg)](https://github.com/msachet5/canada-supply-chain-pressure-index/actions/workflows/ci.yml)

![CSCPI](data/cscpi.png)

## Latest

See [`data/cscpi.csv`](data/cscpi.csv) and the [release notes](data/releases). Values are standard deviations from the average level of pressure since 2017; positive means more pressure than usual.

## How it works

1. Pull supply-side indicators (manufacturing backlogs and inventory ratios, input and freight prices, port and rail performance) and demand proxies (new orders, retail sales, freight volumes) from Statistics Canada's Web Data Service.
2. Standardise, orient so higher always means more pressure, and **purge demand effects** so the index reads supply pressure rather than the business cycle.
3. Take the first principal component, sign it, scale it, and attribute each month's value to its inputs.

Full method: [docs/methodology.md](docs/methodology.md). The structure follows the GSCPI (Benigno et al., 2022); the inputs are Canadian and open, so the two indices are related but not the same.

### The gate

If fewer than six supply inputs are current, the release is the **indicator pulse** (signed z-scores and their average) instead of the composite, and says so. `cscpi audit` shows which inputs are current.

## Run it yourself

```bash
pip install -e ".[charts]" openpyxl
cscpi audit                       # inputs, freshness, gate decision
cscpi members 16-10-0047-01       # dimensions and members of a StatCan table, for writing filters
cscpi build                       # writes data/
cscpi validate                    # correlation with the NY Fed GSCPI
```

## Use the data

```python
import polars as pl

cscpi = pl.read_csv(
    "https://raw.githubusercontent.com/msachet5/canada-supply-chain-pressure-index/main/data/cscpi.csv"
)
```

Each release is archived with a DOI on Zenodo (see the badge once the first release is out) and mirrored to Kaggle and Hugging Face.

## Cite

Mulimani, S. (2027). *Canada Supply Chain Pressure Index* [Data set and code]. https://github.com/msachet5/canada-supply-chain-pressure-index. See [CITATION.cff](CITATION.cff).

## Licence and attribution

Code: MIT. Source data: Statistics Canada and Transport Canada, reproduced and adapted under the [Statistics Canada Open Licence](https://www.statcan.gc.ca/en/reference/licence). This does not constitute an endorsement by Statistics Canada of this product.

## Author

[Sachet Mulimani](https://www.linkedin.com/in/sachet-s-mulimani), planning analytics, Toronto. Commentary on each release: LinkedIn and [CleverChainAI](https://cleverchainai.com).
