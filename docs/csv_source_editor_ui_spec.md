# CSV Source Editor UI Spec

## Purpose

Provide a local UI for reviewing and modifying CSV source files under `pypsa_data_sources`. The UI should make the editable dataset explicit through a dropdown menu, show the selected CSV in an editable grid, validate changes before saving, and preserve the manifest-driven organization already present in the data folder.

## Data Root

Default data root:

```text
pypsa_data_sources/pypsa_data_sources
```

The UI must locate `manifest.csv` at startup and use it as the source catalog. If the manifest is not found at the default path, the user can browse for a folder containing `manifest.csv`.

## Users

- Model analyst updating PyPSA input tables before running scenarios.
- Reviewer checking row counts, column names, and obvious data issues.
- Developer debugging transformed CSVs against raw source files.

## Primary Screen

The first screen is the editor itself, not a landing page.

Layout:

- Header bar with the title `PyPSA Data Sources`.
- Dataset dropdown populated from `manifest.csv`.
- Metadata strip for selected dataset: relative path, row count, column count, notes, and last modified time.
- Editable data grid for the selected CSV.
- Validation panel showing errors and warnings.
- Footer action bar with `Reload`, `Validate`, `Save`, `Save As Copy`, and `Export CSV`.

## Dataset Dropdown

The dropdown is the main navigation control.

Options should be grouped by dataset prefix:

- `loads`
- `generators`
- `renewables`
- `raw`
- `excel_exports`
- `manifest`

Each option label should use this pattern:

```text
<dataset> - <relative csv path>
```

Example options:

- `loads/load_p_set - loads/load_p_set.csv`
- `generators/derating - generators/derating.csv`
- `renewables/nsj_sfx_v1_5_bands - renewables/nsj_sfx_v1_5_bands.csv`
- `raw/Demand/09. 2w_30min_demand.csv - raw/Demand/09. 2w_30min_demand.csv`

Rules:

- Include only CSV-backed manifest rows in the main dropdown.
- Keep `manifest.csv` available but mark it as an advanced dataset.
- Show raw files, transformed files, and Excel-exported CSVs in separate groups.
- Preserve the selected dataset when the page refreshes if the file still exists.

## Editable Tables

The selected CSV is displayed in a spreadsheet-style grid.

Required grid features:

- Cell editing.
- Row add and delete.
- Column add, rename, and delete, guarded by schema validation.
- Copy and paste from spreadsheet tools.
- Sort and filter without changing saved row order unless explicitly applied.
- Search within the selected file.
- Frozen header row.
- Virtual scrolling for large files such as renewable profiles and load time series.

Recommended behavior:

- Treat all values as text while editing.
- Parse and validate typed values only when `Validate` or `Save` is selected.
- Preserve original column order by default.
- Preserve newline style and write standard comma-separated UTF-8 CSV output.

## Known File Schemas

### Load Profiles

`loads/load_p_set.csv`

- Required columns: `DateTime`, `SM FT OPF`, `SM GF`, `SM KV OPF`, `SM NPI`, `SM TLO`, `IB GF`, `IB NPI`, `IB OPF`.
- `DateTime` must parse as datetime.
- Load columns must be numeric and non-negative.
- This file is consumed by `network_from_png_v1.py` as the default load profile.

`loads/load_p_set_long.csv`

- Required columns: `DateTime`, `bus`, `p_set`.
- `bus` must match a known demand bus.
- `p_set` must be numeric and non-negative.

### Renewable Profiles

`renewables/nsj_sfx.csv`

- Required columns: `MONTH`, `DAY`, `PERIOD`, sample columns `1` through `10`.

`renewables/nsj_sfx_v1.csv`

- Required columns: `MONTH`, `DAY`, `PERIOD`, sample column `1`.

`renewables/nsj_sfx_v1_5_bands.csv`

- Required columns: `MONTH`, `DAY`, `PERIOD`, sample columns `1` through `5`.
- This file is consumed by `network_from_png_v1.py` as the default NSJ solar farm profile.

Validation:

- `MONTH` must be 1-12.
- `DAY` must be valid for the month.
- `PERIOD` must be 1-48.
- Sample values must be numeric.
- For rating-profile use, sample values should normally be between 0 and 1; values outside that range should be warnings unless the analyst confirms they are intentional.

`renewables/solar_ratio_ch.csv`

- Required columns: `DateTime`, `Value`.
- `DateTime` must parse as datetime.
- `Value` must be numeric.

### Generator Maintenance Inputs

`generators/commit.csv`

- Required first column: `DateTime`.
- Remaining columns are generator names.
- Values should be numeric commitment flags.
- Expected commitment values: `-1`, `0`, or `1`.

`generators/derating.csv`

- Required first column: `DateTime`.
- Remaining columns are generator names.
- Values must be numeric.
- Values should not exceed installed unit capacity for the corresponding generator.

`generators/units_out.csv`

- Required first column: `DateTime`.
- Remaining columns are generator names.
- Values must be numeric and non-negative.

`generators/markup.csv`

- Required columns: `Name`, `Value`.
- `Name` must be non-empty.
- `Value` must be numeric.

### Raw and Excel Export Files

Raw files should be editable, but the UI must warn before saving because transformed CSVs may need regeneration.

Excel-exported CSV files should be editable, but the UI should indicate that the `.xlsx` source is not updated by CSV edits.

## Save Workflow

Saving must be deliberate and recoverable.

1. User selects a dataset from the dropdown.
2. UI loads the CSV and records the original file hash.
3. User edits cells, rows, or columns.
4. User selects `Validate`.
5. UI displays errors and warnings.
6. `Save` is enabled only when there are no blocking errors.
7. On save, the UI rechecks the file hash to detect external edits.
8. UI writes a timestamped backup before overwriting the CSV.
9. UI updates `manifest.csv` row and column counts for the saved dataset.
10. UI shows a success message with backup path and modified timestamp.

Backup path pattern:

```text
pypsa_data_sources/pypsa_data_sources/.backups/<dataset>/<yyyyMMdd-HHmmss>/<filename>.csv
```

External edit handling:

- If the file hash changed since load, block overwrite.
- Offer `Reload`, `Save As Copy`, or `Compare Changes`.

## Validation Levels

Blocking errors:

- Missing required columns.
- Duplicate column names.
- Unparseable `DateTime` values in files that require timestamps.
- Non-numeric values in required numeric columns.
- Empty file.
- Failed CSV write permission.

Warnings:

- Row count differs from manifest.
- Column count differs from manifest.
- Time gaps or duplicate timestamps.
- Renewable profile values outside 0-1.
- Editing raw files instead of transformed files.
- Editing Excel-exported CSV without updating the original workbook.

## Manifest Behavior

The manifest is the UI catalog and should remain editable only in advanced mode.

For each save:

- Recompute `rows` and `columns` for the saved CSV.
- Preserve `dataset`, `source_file`, `output_file`, and `notes` unless the user is editing the manifest directly.
- Store paths in manifest exactly as existing rows do unless a new dataset is created.

For new CSV copies:

- Add a manifest row only if the user checks `Register in manifest`.
- Require `dataset`, relative output path, and notes.

## Technical Design

Recommended local implementation:

- Python app using Streamlit or Panel for quick deployment.
- Pandas for CSV parsing and validation.
- A grid component with virtual scrolling and copy/paste support.
- No database required; CSV files remain the system of record.

Core modules:

- `catalog.py`: reads and normalizes `manifest.csv`.
- `schemas.py`: declares known schema rules by dataset.
- `csv_store.py`: loads, hashes, backs up, and writes CSV files.
- `validators.py`: returns blocking errors and warnings.
- `app.py`: renders dropdown, metadata, grid, validation panel, and action bar.

## UI States

Initial:

- Data root detected.
- Dataset dropdown defaults to `loads/load_p_set` if present; otherwise first transformed CSV.

Clean:

- Selected CSV loaded.
- `Save` disabled until edits occur.

Dirty:

- Unsaved edits present.
- Dataset dropdown change asks whether to discard, save, or cancel.

Invalid:

- Blocking validation errors visible.
- `Save` disabled.

Saving:

- Controls disabled.
- Progress indicator visible.

Saved:

- New file hash recorded.
- Manifest counts refreshed.
- Success message visible.

## Accessibility and Usability

- Dropdown and buttons must be keyboard reachable.
- Grid cells must have visible focus states.
- Validation messages must include row number, column name, severity, and suggested fix.
- Use concise labels; do not rely on color alone to convey errors.
- Large files should show load progress and row counts.

## Acceptance Criteria

- User can choose any CSV listed in `manifest.csv` from a grouped dropdown.
- User can edit a selected CSV in a grid and save it back to disk.
- Save creates a backup before overwriting.
- Save blocks invalid required schemas.
- Manifest row and column counts update after successful save.
- External file changes are detected before overwrite.
- Default files used by `network_from_png_v1.py` are clearly marked:
  - `loads/load_p_set.csv`
  - `renewables/nsj_sfx_v1_5_bands.csv`

## Future Enhancements

- Side-by-side diff before save.
- Scenario branch copies of datasets.
- Regenerate transformed CSVs from raw inputs.
- Inline charts for time series files.
- Integration button to run `network_from_png_v1.py` validation after saving.
