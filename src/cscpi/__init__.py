"""Canada Supply Chain Pressure Index (CSCPI).

A monthly composite of Canadian supply chain pressure built only from open
data, in the spirit of the New York Fed Global Supply Chain Pressure Index
(Benigno, di Giovanni, Groen and Noble, 2022).

    cscpi audit      # is the data current enough to build a composite?
    cscpi build      # fetch, transform, purge demand, extract the first principal component
    cscpi publish    # versioned CSV, JSON, chart and release notes
"""

__version__ = "0.1.0"
