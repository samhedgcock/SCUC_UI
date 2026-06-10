# SCUC UI Handoff - Fast Single Model Branch

This branch intentionally simplifies the app to run one model path only:

```text
run_custom_stochastic_scenario_fast.py
  imports network_from_png_gurobi_fast.py
    imports and patches network_from_png_gurobi.py
```

The older selectable model paths have been removed from this branch. The model
runner no longer exposes a power-model dropdown; it shows a fixed model summary
and always posts the fast scenario model key to the backend.

## Top-Level Files

| Path | Purpose |
| --- | --- |
| `csv_source_editor_app.py` | Local web app, embedded HTML/CSS/JS, API handlers, run orchestration, and output visualizations. |
| `network_from_png_gurobi.py` | Base stochastic Gurobi model module. Required by the fast patch module. |
| `network_from_png_gurobi_fast.py` | Performance patch module. Re-exports the base model API and overrides the faster formulation pieces. |
| `run_custom_stochastic_scenario_fast.py` | CLI scenario runner used by the UI. Exports standard outputs plus battery SOC. |
| `pypsa_data_sources/pypsa_data_sources/` | Default data source root. Contains `manifest.csv` and grouped source CSVs. |
| `model_runs/` | Runtime output directory created by the app. Ignored by Git. |
| `Launch PyPSA App.bat` | Windows launcher for the local web app. |
| `docs/csv_source_editor_ui_spec.md` | Original UI/data-source editor spec. Some details are historical, but the CSV editor behavior still applies. |

Do not commit local license files such as `gurobi.lic`; `.gitignore` excludes
license files, logs, Python caches, and model run outputs.

## Gurobi License

The app detects Gurobi as available only when both `gurobipy` is installed and a
license file can be found. License discovery checks:

1. `GRB_LICENSE_FILE` if it points to an existing file.
2. `gurobi.lic` in the app working directory.
3. Any `*gurobi*.lic` or `*.lic` file in the app working directory.

For local testing, place `gurobi.lic` beside `csv_source_editor_app.py` or set
`GRB_LICENSE_FILE` before launching the app. Do not commit the license.

## Running The App

From the project root:

```powershell
python csv_source_editor_app.py --host 127.0.0.1 --port 8765
```

Then open:

```text
http://127.0.0.1:8765/runner
```

The Windows launcher runs the same app with local Python discovery.

## Direct CLI Equivalent

The UI is meant to mirror this fast scenario command while still copying the
selected load and solar inputs into a per-run data folder:

```powershell
python -B run_custom_stochastic_scenario_fast.py `
  --scenario-name sol_bess_enabled_nss_disabled_nonanticipative `
  --sol-bess enabled `
  --nss-bess disabled `
  --nonanticipative-hours 20 `
  --solver-name gurobi `
  --solver-time-limit 360 `
  --solver-mip-gap 0.005 `
  --output-dir pypsa_outputs_sol_bess_nonanticipative_gurobi
```

The UI adds:

- `--data-dir <model_runs/run_id/data_sources>`
- `--output-dir <model_runs/run_id/pypsa_outputs_base_stochastic_v1>`
- `--gurobi-license-file <path>` when a local license is found
- `--solver-log` only when the user enables the solver log checkbox

## Model Runner Behavior

The visible runner controls are:

- Load profile source
- NSJ solar rating profile source
- Solver
- Solver log checkbox
- Reporting horizon hours
- Lookahead hours
- Generation non-anticipativity hours
- Solver time limit seconds
- Solver MIP gap
- Run/cancel controls

There is no user-facing power-model dropdown on this branch. Backend metadata is
still represented by `POWER_MODELS` so the existing `/api/run-options` and
background job machinery can stay simple, but the registry contains one entry:

```python
DEFAULT_POWER_MODEL = "network_from_png_gurobi_fast_custom_scenario"
POWER_MODELS = {
    "network_from_png_gurobi_fast_custom_scenario": {
        "script": "network_from_png_gurobi_fast.py",
        "required_scripts": ["network_from_png_gurobi.py"],
        "command_script": "run_custom_stochastic_scenario_fast.py",
        "custom_scenario_command": True,
        "default_solver": "gurobi",
        "scenario_name": "sol_bess_enabled_nss_disabled_nonanticipative",
        "sol_bess": "enabled",
        "nss_bess": "disabled",
        "solver_time_limit": 360,
        "solver_mip_gap": 0.005,
    }
}
```

`build_solve_command()` now supports only this custom scenario command path.

## Output Visualizations

The dashboard/topology/input visualizer pages remain from the main app. They
expect the scenario runner to write the standard CSV outputs into the run output
directory, including where available:

- `thermal_generation_by_interval.csv`
- `generation_by_interval.csv`
- `generator_dispatch_by_interval.csv`
- `load_by_bus_by_interval.csv`
- `unserved_energy_by_interval.csv`
- `line_flow_by_interval.csv`
- `reserves_by_interval.csv`
- `battery_soc_by_interval.csv`
- `simulation_settings.csv`
- `solver_summary.csv`
- `base_stochastic_scenario_summary.csv`

If a visualization panel is blank, first confirm the corresponding output CSV
exists in the selected run folder.

## Useful Checks

Compile the active app/model path:

```powershell
python -m py_compile `
  csv_source_editor_app.py `
  run_custom_stochastic_scenario_fast.py `
  network_from_png_gurobi_fast.py `
  network_from_png_gurobi.py
```

Inspect the generated command without launching a full solve by importing
`csv_source_editor_app.build_solve_command()` in a short Python snippet.

Run the scenario parser check:

```powershell
python -B run_custom_stochastic_scenario_fast.py --help
```

For frontend verification, run the app on an unused local port and open
`/runner`. Confirm the fixed power model card is visible and there is no power
model dropdown.
