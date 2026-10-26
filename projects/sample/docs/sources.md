# The synthetic sources

Bluepeak Supply, a fictional distributor with three distribution centres
(Columbus OH, Phoenix AZ, Calgary AB), simulated by the architecture's
generators with this pack's `scenario.yml`: a different seed, company, sites
and volumes from Sample Project v2, and a freight platform.

| System type (requirements tool) | Simulator | Notes |
|---|---|---|
| ERP | Sage X3 (`sage_x3`) | The same high-fidelity mock as every pack: CHAR padding, sentinel dates, CDC |
| CRM | HubSpot (`hubspot`) | Cursor plus archived records; deals hand off to the ERP |
| Inventory planning | Netstock (`netstock`) | Regenerated wholesale on every sync, two days behind |
| Freight platform | Freight (`freight`) | One shipment per ERP delivery, carrier invoices days to weeks later |
| Payroll | none yet | Measures that need it stay in the backlog |

## Landmines

The ERP, CRM and planning landmines are the architecture's (see Sample
Project v2's `docs/sources.md`). The freight platform adds:

1. **Late carrier invoices.** Invoices arrive 3 to 35 days after the
   shipment, so the most recent month's Cost Per Shipment restates as they
   land. About 3% never arrive.
2. **Hand-keyed references.** About 4% of shipments carry the ERP delivery
   number lower case or without its `SDH` prefix. Staging puts both back
   before any join; `fct_shipment.is_matched_to_delivery` is tested to be 1.
3. **Carrier on the delivery.** Deliveries have no carrier in the ERP; the
   carrier comes from the shipment booked against the delivery, and is
   `UNKNOWN` where none was.
