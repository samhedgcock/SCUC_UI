# PyPSA Web App Codebase Handoff

This document is for a future coding agent or engineer picking up this project. It explains the current codebase, how the web app works, how model runs are launched and visualized, and where to make common changes.

## Project Purpose

This folder contains a small local web application for editing PyPSA CSV input sources, running one of several PyPSA dispatch models, and visualizing the model outputs. The app is intentionally local-only and uses Python standard-library HTTP serving plus plain HTML/CSS/JavaScript embedded in `csv_source_editor_app.py`.

The current user workflow is:

1. Edit or inspect CSV data sources.
2. Select load and solar data sources.
3. Choose a power model and solver.
4. Configure run settings such as generation non-anticipativity hours.
5. Run the model from the browser.
6. Watch live solve progress and logs.
7. View solved outputs in dashboards, input visualizations, and topology SLD views.

## Top-Level Files

| Path | Purpose |
| --- | --- |
| `csv_source_editor_app.py` | Main local web app. Contains all HTML, CSS, JavaScript, HTTP handlers, APIs, model-run orchestration, and dashboard data aggregation. |
| `network_from_png_v1.py` | Original PyPSA model module. The app runs it via `python -c` and exports several output files from the returned network. |
| `24h_dispatch_HiGHs_Gurobi.py` | CLI-capable 24h stochastic dispatch model. Supports HiGHS/Gurobi, solver controls, generation non-anticipativity hours, and several CSV exports. |
| `24h_stochastic_dispatch_HiGHs_Gurobi_withreserves.py` | CLI-capable 24h stochastic dispatch model with reserve outputs. Supports configurable generation non-anticipativity hours and exports `reserves_by_interval.csv`. |
| `pypsa_data_sources/pypsa_data_sources/` | Default data source root. Contains `manifest.csv` and grouped source CSVs. |
| `model_runs/` | Per-run folders created by the app. Each run stores selected input copies, metadata, and model outputs. |
| `gurobi.lic` | Local Gurobi license file if present. Do not assume this may be redistributed. |
| `Launch PyPSA App.bat` | Double-click Windows launcher. Starts the app on `127.0.0.1:8765` and opens the browser. |
| `csv_source_editor_app.out.log` / `.err.log` | Logs from background app launches. Safe to delete. |

There is currently no `requirements.txt`; assumed external packages are `pypsa`, `pandas`, `numpy`, `highspy`, and optionally `gurobipy`.

## Running The App

From the project root:

```powershell
python csv_source_editor_app.py --host 127.0.0.1 --port 8765
```

Then open:

```text
http://127.0.0.1:8765/
```

For Windows users, double-click:

```text
Launch PyPSA App.bat
```

The launcher tries `.venv\Scripts\python.exe`, then `py -3`, then `python`.

## App Pages

The app is served by `CsvSourceEditorHandler` in `csv_source_editor_app.py`.

| Route | HTML Constant | Purpose |
| --- | --- | --- |
| `/` | `INDEX_HTML` | CSV source editor. |
| `/runner` | `RUNNER_HTML` | Model runner with data source, model, solver, and run controls. |
| `/dashboard` | `DASHBOARD_HTML` | Output dashboard for solved model runs. |
| `/inputs` | `INPUTS_HTML` | Input data visualizer. |
| `/topology` | `TOPOLOGY_HTML` | Network topology SLD with timestep slider and branch loading colors. |

The top navigation is grouped as:

- `Model Runner`
- `Inputs`: `Visual`, `CSV Editor`
- `Outputs`: `Visual`, `Topology`

## HTTP API Endpoints

GET endpoints:

| Endpoint | Handler | Purpose |
| --- | --- | --- |
| `/api/catalog` | `handle_catalog` | Returns editable CSV catalog from data root. |
| `/api/file` | `handle_file` | Returns columns, rows, metadata, and validation for one CSV. |
| `/api/run-options` | `handle_run_options` | Returns load/solar options, solver options, power model options, and default run settings. |
| `/api/output-runs` | `handle_output_runs` | Lists model run folders and completion state. |
| `/api/dashboard-data` | `handle_dashboard_data` | Aggregates output CSVs for the dashboard. |
| `/api/input-datasets` | `handle_input_datasets` | Lists input datasets for input visualization. |
| `/api/input-dashboard-data` | `handle_input_dashboard_data` | Aggregates one input CSV for charts/tables. |
| `/api/topology-data` | `handle_topology_data` | Aggregates output data for topology SLD. |
| `/api/run-status` | `handle_run_status` | Returns state/logs for one background run job. |
| `/api/active-run` | `handle_active_run` | Returns active queued/running job if any. |

POST endpoints:

| Endpoint | Handler | Purpose |
| --- | --- | --- |
| `/api/validate` | `handle_validate` | Validates edited CSV payload. |
| `/api/save` | `handle_save` | Writes edited CSV in-place after backup and validation. |
| `/api/save-copy` | `handle_save_copy` | Saves a new CSV source and registers it in manifest. |
| `/api/start-run` | `handle_start_run` | Starts a background model run job. |
| `/api/cancel-run` | `handle_cancel_run` | Requests termination of a background model run job. |
| `/api/run-model` | `handle_run_model` | Legacy synchronous run endpoint. Most UI uses `/api/start-run`. |

## Main App Architecture

`csv_source_editor_app.py` is a monolith with these major sections:

1. Constants and model registry.
2. HTML/CSS/JS page strings.
3. CSV catalog, manifest, validation, and save helpers.
4. Model run preparation and process orchestration.
5. Dashboard, topology, and input data aggregation helpers.
6. HTTP handler class and route dispatch.
7. CLI parser and `main`.

Important constants:

```python
DEFAULT_DATA_ROOT = Path("pypsa_data_sources") / "pypsa_data_sources"
MODEL_RUNS_DIR = Path("model_runs")
OUTPUT_DIR_NAME = "pypsa_outputs_base_stochastic_v1"

THERMAL_OUTPUT = "thermal_generation_by_interval.csv"
UNSERVED_OUTPUT = "unserved_energy_by_interval.csv"
LOAD_OUTPUT = "load_by_bus_by_interval.csv"
GENERATION_OUTPUT = "generation_by_interval.csv"
GENERATOR_OUTPUT = "generator_dispatch_by_interval.csv"
LINE_FLOW_OUTPUT = "line_flow_by_interval.csv"
RESERVES_OUTPUT = "reserves_by_interval.csv"
```

## Power Model Registry

The runner dropdown is driven by `POWER_MODELS` in `csv_source_editor_app.py`.

Current models:

| Value | Script | Notes |
| --- | --- | --- |
| `network_from_png_v1` | `network_from_png_v1.py` | Original model run via inline `python -c`. App sets module simulation constants and performs extra exports. |
| `dispatch_24h_highs_gurobi` | `24h_dispatch_HiGHs_Gurobi.py` | CLI script. Defaults to Gurobi. Supports non-anticipativity hours. App captures stderr into stdout to keep solver logs together. |
| `dispatch_24h_stochastic_highs_gurobi_withreserves` | `24h_stochastic_dispatch_HiGHs_Gurobi_withreserves.py` | CLI script. Defaults to Gurobi. Supports reserve output visualization. |

When adding a model:

1. Add an entry to `POWER_MODELS`.
2. Ensure the file exists in the project root.
3. If it should run as a script, set `script_command: True`.
4. If it supports `--generation-nonanticipative-hours`, set `supports_nonanticipative_hours: True`.
5. If solver stderr should be displayed as live progress/log output, set `stderr_to_stdout: True`.
6. Ensure expected output CSVs are exported into the provided `--output-dir`.
7. Update dashboard/topology aggregators if new output files need visualization.

## Model Runner Flow

The runner page uses `/api/run-options` to populate:

- load source dropdown
- solar source dropdown
- solver dropdown
- power model dropdown
- default horizon/lookahead/non-anticipativity values

When the user clicks `RUN`:

1. Browser POSTs to `/api/start-run`.
2. `prepare_run_request` validates payload.
3. `prepare_model_run` creates a new folder under `model_runs/<timestamp>/`.
4. The selected load source is copied to:

   ```text
   model_runs/<run>/data_sources/loads/load_p_set.csv
   ```

5. The selected solar source is copied to:

   ```text
   model_runs/<run>/data_sources/renewables/nsj_sfx_v1_5_bands.csv
   ```

6. `selected_sources.json` is written with model, solver, source datasets, horizon/lookahead, and non-anticipativity hours.
7. `build_solve_command` constructs the subprocess command.
8. `start_run_job` records the job in global `RUN_JOBS` and starts `run_job_worker` in a daemon thread.
9. The browser polls `/api/run-status`.
10. Logs and progress keep updating even if the user navigates to another tab/page.

The job state intentionally lives in the app process, not in the browser page. Navigating away should not cancel a running solve.

## Model Run Folder Layout

Each run folder looks like:

```text
model_runs/
  20260528-161730-233906/
    selected_sources.json
    data_sources/
      loads/load_p_set.csv
      renewables/nsj_sfx_v1_5_bands.csv
      manifest.csv
    pypsa_outputs_base_stochastic_v1/
      simulation_settings.csv
      base_stochastic_scenario_summary.csv
      thermal_generation_by_interval.csv
      generation_by_interval.csv
      reserves_by_interval.csv
      unserved_energy_by_interval.csv
      load_by_bus_by_interval.csv
      generator_dispatch_by_interval.csv
      line_flow_by_interval.csv
      solver_summary.csv
```

Not every model writes every output. The dashboards check for files before using optional views.

Key metadata:

- `selected_sources.json` records what the UI sent to the model.
- `base_stochastic_scenario_summary.csv` records what the solved model says it used.
- For non-anticipativity debugging, compare:

  ```text
  selected_sources.json -> nonanticipative_hours
  base_stochastic_scenario_summary.csv -> nonanticipative_hours
  ```

## Generation Non-Anticipativity

The default constant in model files is:

```python
GENERATION_NONANTICIPATIVE_HOURS = 20.0
```

This is only the default. The runner sends the selected UI value as `nonanticipative_hours`.

Important paths:

- UI input: `#nonanticipative-hours-input` in `RUNNER_HTML`.
- Payload key: `nonanticipative_hours`.
- Request parser: `prepare_run_request`.
- Command builder: `build_solve_command`.
- CLI arg for script models: `--generation-nonanticipative-hours`.
- Model function: `solve_base_stochastic_dispatch_scenario(..., nonanticipative_hours=...)`.
- Scenario builder: `build_base_stochastic_dispatch_scenario(..., nonanticipative_hours=...)`.
- Constraint function: `add_generation_nonanticipativity_constraints`.

The dashboard now displays `Non-anticipativity` in the metadata strip using `selected_sources.json`.

Pitfall: `nonanticipative_generators,20` in `base_stochastic_scenario_summary.csv` is the number of tied generators, not the number of hours.

## CSV Editor

Page: `/`

The editor uses `manifest.csv` plus folder scanning to build a catalog. It supports:

- selecting a dataset
- viewing metadata
- editing cells
- row/column add/delete/rename
- search and pagination
- validation
- save in-place with backup
- save-copy into a safe relative CSV path and manifest row

Important helpers:

- `find_data_root`
- `read_manifest`
- `catalog_items`
- `find_catalog_item`
- `read_csv_rows`
- `validate_table`
- `schema_for_dataset`
- `backup_file`
- `update_manifest_counts`
- `add_manifest_row`

Validation rules are heuristic and schema-driven. The important compatibility checks for model runs are:

- `is_compatible_load_source`: needs `DateTime` and required demand bus columns.
- `is_compatible_solar_source`: needs `MONTH`, `DAY`, `PERIOD`, and sample columns `1` through `5`.

## Input Visual Page

Page: `/inputs`

This page visualizes CSV input datasets without solving the model. It classifies inputs and builds chart/table payloads via:

- `input_dataset_items`
- `input_dashboard_data`
- `classify_input`
- `input_series_options`
- `build_input_chart`
- `build_wide_datetime_chart`
- `build_long_chart`
- `build_renewable_chart`
- `build_name_value_chart`
- `build_generic_chart`
- `input_summary_tiles`
- `input_diagnostics`

Supported visual patterns include:

- time-series load profiles
- renewable sample profiles
- generic numeric columns
- average daily shape
- preview table
- column role table
- diagnostics

## Output Dashboard

Page: `/dashboard`

The dashboard reads output CSVs from selected run folders and builds a response in `dashboard_data`.

Core output files:

- `thermal_generation_by_interval.csv`
- `unserved_energy_by_interval.csv`
- `load_by_bus_by_interval.csv`

Optional output files:

- `generation_by_interval.csv`
- `generator_dispatch_by_interval.csv`
- `line_flow_by_interval.csv`
- `reserves_by_interval.csv`

Current visualizations:

- Summary tiles for thermal, solar, total generation, load, unserved energy, and solar share.
- `Fleet Mix And Load` chart showing thermal, solar, load, and unserved on one plot.
- `Generation Mix And Demand` interactive chart. User can select total fleet or a single generator.
- Load by bus bar chart.
- Generation by unit bar chart.
- Unserved energy by bus bar chart.
- Top generators table.
- Run files table.
- Conditional reserve panels if `reserves_by_interval.csv` exists.

Reserve dashboard:

- Backend: `reserve_dashboard_data`.
- Frontend: `Reserve Coverage` panel, `#reserve-select`, `drawReserveChart`, `renderReserveTables`.
- Expected reserve CSV columns:

  ```text
  DATETIME,sample,reserve,provider,value_mw,quantity
  ```

- Supported `quantity` values:

  ```text
  requirement
  provision
  shortage
  ```

- Reserves are weighted across samples when viewing `All samples`.

## Topology SLD Page

Page: `/topology`

The topology page displays a single-line diagram with timestep navigation. It updates:

- generator MW values
- load MW values
- unserved energy values
- branch flow/load colors where line-flow data exists

Important backend functions:

- `topology_data`
- `topology_output_files`
- `topology_generator_rows`
- `topology_samples`
- `aggregate_topology_bus_values`

Important constants:

- `TOPOLOGY_LINES`
- `BUS_LAYOUT`

Branch loading colors require:

```text
line_flow_by_interval.csv
```

The `24h_dispatch_HiGHs_Gurobi.py` path and `24h_stochastic_dispatch_HiGHs_Gurobi_withreserves.py` path both export line flow. Older reserve-model runs created before this fix may still lack `line_flow_by_interval.csv`; rerun the model to generate branch loading colors for those cases.

## Output File Schemas

Common output schemas:

### `thermal_generation_by_interval.csv`

```text
DATETIME,sample,generator,component,generation_mw
```

### `generation_by_interval.csv`

```text
DATETIME,sample,generator,component,generation_mw
```

### `generator_dispatch_by_interval.csv`

```text
DATETIME,sample,generator,component,bus,carrier,p_mw
```

### `load_by_bus_by_interval.csv`

```text
DATETIME,sample,bus,component,load_mw
```

### `unserved_energy_by_interval.csv`

```text
DATETIME,sample,bus,component,unserved_mw
```

### `line_flow_by_interval.csv`

```text
DATETIME,sample,line,component,bus0,bus1,p0_mw,p1_mw,limit_mw,loading_pct
```

### `reserves_by_interval.csv`

```text
DATETIME,sample,reserve,provider,value_mw,quantity
```

## PyPSA Model Scripts

The three model files share a lot of structure:

- topology constants
- generator/storage/line properties
- data readers for load and NSJ solar profiles
- stochastic sample expansion
- non-anticipativity constraints
- reserve constraints
- solve helper
- output exporters
- CLI parser and `main`

### `network_from_png_v1.py`

Original module used by the app with inline Python. It does not need the CLI route for app solves.

The app sets:

```python
m.SIMULATION_DAYS = horizon_hours / 24.0
m.SIMULATION_LOOKAHEAD_DAYS = lookahead_hours / 24.0
```

Then calls:

```python
m.solve_base_stochastic_dispatch_scenario(
    data_dir=data_dir,
    solver_name=solver_name,
    solver_log=solver_log,
    nonanticipative_hours=nonanticipative_hours,
)
```

The app then calls module exporters and adds extra app-side exports for generator dispatch and line flow.

### `24h_dispatch_HiGHs_Gurobi.py`

CLI model with Gurobi/HiGHS controls. The app invokes it roughly as:

```powershell
python -u -B 24h_dispatch_HiGHs_Gurobi.py `
  --data-dir <run data_sources> `
  --output-dir <run outputs> `
  --solver-name gurobi `
  --solver-time-limit 360 `
  --solver-mip-gap 0.005 `
  --generation-nonanticipative-hours <value> `
  --no-solution-netcdf `
  --solver-log `
  --gurobi-license-file <gurobi.lic>
```

### `24h_stochastic_dispatch_HiGHs_Gurobi_withreserves.py`

CLI model with reserve output support. It now accepts:

```text
--generation-nonanticipative-hours
```

The dashboard consumes its `reserves_by_interval.csv` when present.

## Solver And License Handling

`solver_options` checks installed Python packages:

- `highspy` for HiGHS
- `gurobipy` for Gurobi

`find_gurobi_license` looks in the project root for:

- `gurobi.lic`
- any `*gurobi*.lic`
- any `*.lic`

For Gurobi runs, `solver_environment` sets `GRB_LICENSE_FILE` if a license is found.

The UI blocks selecting Gurobi if no license file is found.

## Background Job Lifecycle

Important functions:

- `start_run_job`
- `run_job_worker`
- `read_process_stream`
- `apply_progress_from_line`
- `update_job`
- `append_job_log`
- `get_public_job`
- `cancel_run_job`
- `active_run_job`

Progress is inferred from log lines and stage markers:

- app-injected `stage=building_stochastic_scenario`
- app-injected `stage=exporting_outputs`
- app-injected `stage=complete`
- PyPSA / solver log text

The app limits retained stdout/stderr per job to avoid unlimited memory growth.

## Adding A New Output Visualization

Suggested workflow:

1. Add an output filename constant near the other `*_OUTPUT` constants.
2. Include it in `run_output_paths` if the runner should show it.
3. Include it in `output_files_json` if the dashboard file table should show it.
4. Read it in `dashboard_data` only if it exists.
5. Add an aggregation helper near `reserve_dashboard_data` or other dashboard helpers.
6. Add HTML panel markup in `DASHBOARD_HTML`.
7. Add element references to the `els` object in dashboard JavaScript.
8. Add draw/render functions in dashboard JavaScript.
9. Hide the panel when the file does not exist.
10. Verify with a run that has the file and one that does not.

## Adding A New Model

Checklist:

1. Put the `.py` file in the project root.
2. Add a `POWER_MODELS` entry.
3. Decide whether it is `script_command` or inline import.
4. If script command, make sure it supports:

   ```text
   --data-dir
   --output-dir
   --solver-name
   --solver-time-limit
   --solver-mip-gap
   --no-solution-netcdf
   --solver-log
   --gurobi-license-file
   ```

5. If it should use the runner non-anticipativity control, add support for:

   ```text
   --generation-nonanticipative-hours
   ```

6. Validate arguments before solving.
7. Export files with schemas expected by dashboard/topology, or update the aggregators.
8. Compile:

   ```powershell
   python -m py_compile csv_source_editor_app.py your_model.py
   ```

9. Check model dropdown via:

   ```powershell
   Invoke-RestMethod http://127.0.0.1:8765/api/run-options
   ```

## Verification Commands

Compile all main files:

```powershell
python -m py_compile `
  csv_source_editor_app.py `
  network_from_png_v1.py `
  24h_dispatch_HiGHs_Gurobi.py `
  24h_stochastic_dispatch_HiGHs_Gurobi_withreserves.py
```

Run app:

```powershell
python csv_source_editor_app.py --host 127.0.0.1 --port 8765
```

Check run options:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/run-options
```

Check output runs:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/output-runs
```

Check latest run metadata:

```powershell
Get-ChildItem -Directory model_runs |
  Sort-Object Name -Descending |
  Select-Object -First 1 |
  ForEach-Object { Get-Content (Join-Path $_.FullName 'selected_sources.json') -Raw }
```

Check non-anticipativity in solved summary:

```powershell
Get-ChildItem -Directory model_runs |
  Sort-Object Name -Descending |
  Select-Object -First 1 |
  ForEach-Object {
    Get-Content (Join-Path $_.FullName 'pypsa_outputs_base_stochastic_v1\base_stochastic_scenario_summary.csv') |
      Select-String -Pattern 'nonanticipative'
  }
```

## Restarting The Server Safely

Before restarting, check for active solves:

```powershell
Get-CimInstance Win32_Process -Filter "name = 'python.exe'" |
  Where-Object {
    $_.CommandLine -match 'solve_base_stochastic_dispatch_scenario|24h_dispatch_HiGHs_Gurobi|24h_stochastic_dispatch_HiGHs_Gurobi_withreserves'
  } |
  Select-Object ProcessId,CommandLine
```

If no active solve is running:

```powershell
$existing = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if ($existing) {
  $pids = $existing | Select-Object -ExpandProperty OwningProcess -Unique
  foreach ($pidValue in $pids) { Stop-Process -Id $pidValue -Force }
  Start-Sleep -Seconds 1
}
$out = Join-Path (Get-Location) 'csv_source_editor_app.out.log'
$err = Join-Path (Get-Location) 'csv_source_editor_app.err.log'
Start-Process -FilePath python `
  -ArgumentList @('csv_source_editor_app.py','--host','127.0.0.1','--port','8765') `
  -WorkingDirectory (Get-Location) `
  -WindowStyle Hidden `
  -RedirectStandardOutput $out `
  -RedirectStandardError $err
```

## Current Known Behaviors And Gotchas

- The app is local-only and has no authentication.
- `RUN_JOBS` is in memory. Active job state is lost if the app process restarts.
- Existing completed `model_runs` are durable on disk.
- Do not redistribute `gurobi.lic` unless licensing permits it.
- `reserves_by_interval.csv` panels are hidden when the file is absent.
- Topology branch loading colors require `line_flow_by_interval.csv`.
- Some older run folders may lack newer metadata fields such as `nonanticipative_hours`.
- The dashboard uses `selected_sources.json` for run settings display and output CSVs for solved values.
- The default non-anticipativity constant remains `20.0`, but runner-selected values override it.
- `nonanticipative_generators,20` means 20 generators, not 20 hours.
- The project root currently has no Git metadata in this workspace.
- Large solves can keep running in the background after navigating away from `/runner`.

## Suggested Next Improvements

High-value improvements for a future agent:

1. Add `requirements.txt` or `pyproject.toml`.
2. Split `csv_source_editor_app.py` into modules: server, pages, model runner, CSV catalog, dashboards.
3. Persist run jobs to disk so status survives app restarts.
4. Add a lightweight `/api/health` endpoint.
5. Add command/run metadata to the dashboard so users can see exact solver and model settings.
6. Add a proper test fixture run with tiny data for fast regression checks.
7. Add downloadable run bundle links from the dashboard.
8. Add clearer error recovery when a model script exits nonzero.
9. Add run comparison mode on the dashboard.

## Quick Mental Model

Think of the app as three layers:

1. **Source layer**: `pypsa_data_sources` plus manifest and CSV editor.
2. **Run layer**: selected CSVs are copied into isolated `model_runs/<run>/data_sources`, then a model script solves into `model_runs/<run>/pypsa_outputs_base_stochastic_v1`.
3. **Visualization layer**: dashboards never read the live model object; they only read output CSVs and `selected_sources.json`.

That separation is important. If a visualization is wrong, check the output CSV first. If an output CSV is wrong, check the model script/exporter. If a model setting is wrong, check `selected_sources.json`, `build_solve_command`, and the model script CLI parser.
