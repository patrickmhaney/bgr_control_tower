"""Stand-ins for the real source clients. THIS PACKAGE IS THE SEAM.

Each simulator reads the mock database but exposes the access pattern of the
real system: Sage X3 hands back rows for SQL and CDC change rows by LSN,
HubSpot hands back pages behind a cursor, Netstock hands back a whole
regenerated dataset. Everything above this package (ingestion/) is production
code and cannot tell the difference. Going live means replacing these modules
with real clients; each module's docstring names exactly what changes.
"""
