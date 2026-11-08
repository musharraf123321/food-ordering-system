# Test cases (Design Document, section 8) -> implementation

Run everything with `python -m pytest -v` (64 tests, ~30 s). "Auto" = covered by an automated test.

| UC | Test case IDs | Result implemented | Automated test |
|----|---------------|--------------------|----------------|
| UC1 Registration | TC_UC1_01-03 | account created / duplicate email error / required-field messages | `test_auth.py::test_uc1_*` |
| UC2 Browse restaurants | TC_UC2_01-03 | list, filter by location, "No restaurants found" | `test_customer.py::test_uc2_*` |
| UC3 View menu | TC_UC3_01-03 | menu shown, back link, error for missing restaurant | `test_uc3_*` |
| UC4 Add to cart | TC_UC4_01-03 | add, change quantity, out-of-stock error | `test_uc4_*` |
| UC5 Place order | TC_UC5_01-03 | order created, COD, online payment failure message | `test_uc5_*` |
| UC6 Order status | TC_UC6_01-03 | status shown, refresh, 404 for unknown order | `test_uc6_*` |
| UC7 Order history | TC_UC7_01-03 | history, filter by date/status, "No history available" | `test_uc7_*` |
| UC8 Analytics | TC_UC8_01-03 | dashboard, data loaded, empty/failed-data message | `test_insights.py::test_uc8_*` |
| UC9 Favorites | TC_UC9_01-03 | list, remove, empty message | `test_uc9_favorites` |
| UC10 Add item | TC_UC10_01-03 | add, image later, validation errors | `test_owner_admin.py::test_uc10_*` |
| UC11 Update item | TC_UC11_01-03 | update, partial update, 404 for missing item | `test_uc11_*` |
| UC12 Delete item | TC_UC12_01-03 | delete, soft delete, warning when linked to orders | `test_uc12_*` |
| UC13 Manage menu | TC_UC13_01-03 | add / update / delete reflected in menu | covered by UC10-12 |
| UC14 Customer orders | TC_UC14_01-03 | list, filter by status, empty message | `test_uc14_*` |
| UC15 Reports | TC_UC15_01-03 | daily, custom range, "no data" message | `test_uc15_daily_monthly_reports` |
| UC16 Export | TC_UC16_01-03 | CSV, Excel, error when nothing to export | `test_uc16_export_csv_and_xlsx` |
| UC17 Backup | TC_UC17_01-03 | manual, scheduled, storage-full error | `test_backup.py::test_uc17_*` |
| UC18 Restore | TC_UC18_01-03 | restore, restore selected version, corrupt file rejected | `test_uc18_*` |

Extra tests cover security (CSRF, role access, open-redirect, path traversal), stock handling,
loyalty points, ML training / baseline comparison, and per-owner data isolation.
