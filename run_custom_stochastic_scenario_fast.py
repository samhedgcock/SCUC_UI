from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

import network_from_png_gurobi_fast as model


def enabled_choice(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"enabled", "enable", "true", "yes", "1", "on"}:
        return True
    if normalized in {"disabled", "disable", "false", "no", "0", "off"}:
        return False
    raise argparse.ArgumentTypeError(
        "Use enabled/disabled, true/false, yes/no, 1/0, or on/off."
    )


def scenario_slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name.strip()).strip("_").lower()
    return slug or "custom_stochastic_dispatch"


def default_output_dir(scenario_name: str, solver_name: str) -> Path:
    solver = model.normalize_solver_name(solver_name)
    return Path(f"pypsa_outputs_{scenario_slug(scenario_name)}_{solver}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a configurable stochastic PyPSA dispatch scenario and export "
            "the standard CSV outputs plus battery SOC by interval."
        )
    )
    parser.add_argument(
        "--scenario-name",
        default="custom_stochastic_dispatch",
        help="Scenario name recorded in the output summary and used in the default output directory.",
    )
    parser.add_argument(
        "--scenario-description",
        default=None,
        help="Optional description recorded on the solved network.",
    )
    parser.add_argument(
        "--data-dir",
        default=str(model.DEFAULT_DATA_DIR),
        help="Directory containing PyPSA data sources.",
    )
    parser.add_argument(
        "--nsj-sf-year",
        type=int,
        default=2024,
        help="Calendar year used to expand MONTH/DAY/PERIOD solar profiles.",
    )
    parser.add_argument(
        "--nonanticipative-hours",
        type=float,
        default=model.GENERATION_NONANTICIPATIVE_HOURS,
        help="Hours to tie thermal generation and battery decisions across samples.",
    )
    parser.add_argument(
        "--sol-bess",
        type=enabled_choice,
        default=model.SOL_BESS_PROPERTIES["enabled"],
        metavar="{enabled,disabled}",
        help="Enable or disable SOL BESS for this run.",
    )
    parser.add_argument(
        "--nss-bess",
        type=enabled_choice,
        default=model.NSS_BESS_PROPERTIES["enabled"],
        metavar="{enabled,disabled}",
        help="Enable or disable NSS BESS for this run.",
    )
    parser.add_argument(
        "--solver-name",
        default=model.DEFAULT_SOLVER_NAME,
        help="Linopy/PyPSA solver name: gurobi or highs. Defaults to gurobi.",
    )
    parser.add_argument(
        "--solver-log",
        action="store_true",
        help="Show solver output in the console.",
    )
    parser.add_argument(
        "--solver-time-limit",
        type=float,
        default=360.0,
        help="Optional solver time limit in seconds. Defaults to 360.",
    )
    parser.add_argument(
        "--solver-mip-gap",
        type=float,
        default=0.005,
        help="Optional solver MIP relative gap. Defaults to 0.005.",
    )
    parser.add_argument(
        "--solver-threads",
        type=int,
        default=None,
        help="Optional number of solver threads.",
    )
    parser.add_argument(
        "--gurobi-license-file",
        default=str(model.DEFAULT_GUROBI_LICENSE_FILE),
        help="Path to gurobi.lic. Used when --solver-name is gurobi.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for CSV outputs. Defaults to pypsa_outputs_<scenario>_<solver>.",
    )
    parser.add_argument(
        "--include-solution-netcdf",
        action="store_true",
        help="Also export the solved PyPSA network NetCDF file.",
    )
    parser.add_argument(
        "--skip-solve",
        action="store_true",
        help="Only build and report the scenario setup; do not run optimization.",
    )
    return parser.parse_args()


def apply_bess_settings(sol_bess_enabled: bool, nss_bess_enabled: bool) -> None:
    model.SOL_BESS_PROPERTIES["enabled"] = sol_bess_enabled
    model.NSS_BESS_PROPERTIES["enabled"] = nss_bess_enabled


def build_scenario(args: argparse.Namespace):
    apply_bess_settings(args.sol_bess, args.nss_bess)
    network = model.build_base_stochastic_dispatch_scenario(
        data_dir=Path(args.data_dir),
        nsj_sf_year=args.nsj_sf_year,
        nonanticipative_hours=args.nonanticipative_hours,
    )
    network.scenario_name = args.scenario_name
    network.scenario_description = args.scenario_description or (
        f"{args.scenario_name}: SOL BESS "
        f"{'enabled' if args.sol_bess else 'disabled'}, NSS BESS "
        f"{'enabled' if args.nss_bess else 'disabled'}, "
        f"{args.nonanticipative_hours:g}-hour non-anticipativity."
    )
    network.solver_name = model.normalize_solver_name(args.solver_name)
    return network


def export_battery_soc(network, output_dir: Path) -> Path:
    snapshots = model.default_reporting_snapshots()
    rows = []
    for sample in network.stochastic_samples:
        for battery in model.STORAGE_NONANTICIPATIVE_UNITS:
            component = model.stochastic_component(battery, sample)
            if component not in network.storage_units_t.state_of_charge.columns:
                continue
            soc = network.storage_units_t.state_of_charge[component].reindex(snapshots)
            for snapshot, value in soc.items():
                rows.append(
                    {
                        "DATETIME": snapshot,
                        "sample": sample,
                        "battery": battery,
                        "component": component,
                        "enabled": bool(network.storage_units.at[component, "enabled"]),
                        "p_nom_mw": float(network.storage_units.at[component, "p_nom"]),
                        "state_of_charge_mwh": float(value),
                    }
                )

    output_path = output_dir / "battery_soc_by_interval.csv"
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output_path, index=False)
    return output_path


def print_scenario_setup(network) -> None:
    print("Scenario:")
    print(f"  name: {network.scenario_name}")
    print(f"  description: {network.scenario_description}")
    print(f"  samples: {', '.join(network.stochastic_samples)}")
    print(f"  generator non-anticipativity hours: {network.generation_nonanticipative_hours:g}")
    print(f"  storage non-anticipativity hours: {network.storage_nonanticipative_hours:g}")
    print("\nStorage setup:")
    print(
        network.storage_units[
            ["base_name", "sample", "p_nom", "max_hours", "installed_p_nom", "enabled"]
        ].to_string()
    )


def main() -> int:
    args = parse_args()
    solver_name = model.normalize_solver_name(args.solver_name)
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else default_output_dir(args.scenario_name, solver_name)
    )
    gurobi_license_file = (
        Path(args.gurobi_license_file) if args.gurobi_license_file else None
    )

    network = build_scenario(args)
    print_scenario_setup(network)

    if args.skip_solve:
        print("\nSkip solve requested; no solution CSVs were exported.")
        return 0

    print("\nSolving stochastic dispatch scenario:")
    print(f"  solver: {solver_name}")
    print(f"  output dir: {output_dir}")
    if args.solver_time_limit is not None:
        print(f"  solver time limit: {args.solver_time_limit:g} seconds")
    if args.solver_mip_gap is not None:
        print(f"  solver MIP gap: {args.solver_mip_gap:g}")
    if args.solver_threads is not None:
        print(f"  solver threads: {args.solver_threads}")
    if solver_name == "gurobi":
        license_path = model.configure_gurobi_license(gurobi_license_file)
        if license_path is not None:
            print(f"  Gurobi license: {license_path}")

    result = model.optimize_with_default_simulation_settings(
        network,
        solver_name=solver_name,
        solver_log=args.solver_log,
        extra_functionality=model.add_base_stochastic_dispatch_constraints,
        gurobi_license_file=gurobi_license_file,
        solver_time_limit=args.solver_time_limit,
        solver_mip_gap=args.solver_mip_gap,
        solver_threads=args.solver_threads,
    )

    outputs = model.export_base_stochastic_solution(
        network,
        output_dir=output_dir,
        include_network_netcdf=args.include_solution_netcdf,
        result=result,
    )
    outputs["battery_soc"] = export_battery_soc(network, output_dir)

    status, condition = result
    print("\nSolve result:")
    print(f"  status: {status}")
    print(f"  termination condition: {condition}")
    if hasattr(network, "objective"):
        print(f"  objective: {network.objective:.6f}")

    solver_model = getattr(getattr(network, "model", None), "solver_model", None)
    if solver_model is not None:
        for label, attr in (
            ("runtime seconds", "Runtime"),
            ("MIP gap", "MIPGap"),
            ("best bound", "ObjBound"),
        ):
            try:
                print(f"  {label}: {getattr(solver_model, attr)}")
            except Exception:
                pass

    print("\nWrote solution outputs:")
    for label, path in outputs.items():
        print(f"  {label}: {Path(path).resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

