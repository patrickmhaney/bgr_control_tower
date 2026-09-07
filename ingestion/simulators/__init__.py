"""Stand-ins for the five real source systems.

THIS PACKAGE IS THE SEAM. Everything above it - ingestion/sources.py,
ingestion/pipeline.py, the dlt resources, the landing layout, the dbt sources -
is production code and does not change. Going live means replacing the five
modules in here with real clients and deleting this docstring.

Each simulator reads `mock_sources.duckdb` but exposes the *access pattern* of
the real system rather than the convenience of a local database: the ERP hands
back rows for a SQL predicate, HubSpot hands back a page and a cursor, Paycom
hands back a file that appeared on an SFTP server. The pipeline above cannot
tell the difference, which is the point - the shape of the problem is what
transfers, not the data.

Each module's docstring names exactly what changes in production.
"""
