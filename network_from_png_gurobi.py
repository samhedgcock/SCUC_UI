from __future__ import annotations

import argparse
import os
import random
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_GUROBI_LICENSE_FILE = SCRIPT_DIR / "gurobi.lic"
if "GRB_LICENSE_FILE" not in os.environ and DEFAULT_GUROBI_LICENSE_FILE.exists():
    os.environ["GRB_LICENSE_FILE"] = str(DEFAULT_GUROBI_LICENSE_FILE)

import numpy as np
import pandas as pd
import pypsa


RANDOM_SEED = 20241028
DEFAULT_SOLVER_NAME = "gurobi"
SUPPORTED_SOLVERS = ("gurobi", "highs")
DEFAULT_OUTPUT_DIR_PREFIX = "pypsa_outputs_base_stochastic"
SIMULATION_START = pd.Timestamp("2024-10-28 10:00")
SIMULATION_DAYS = 1
SIMULATION_STEP_DAYS = 1
SIMULATION_LOOKAHEAD_DAYS = 1
SIMULATION_INTERVAL_MINUTES = 30
SIMULATION_FULL_CHRONOLOGY = True
OPF_REQUESTED_METHOD = "Variable Shift Factor"
OPF_PYPSA_METHOD = "PyPSA linearized network optimization"
OPF_METHOD_NOTE = (
    "PyPSA 1.2.1 does not expose a PLEXOS-style Variable Shift Factor OPF "
    "method switch. This model uses PyPSA's linearized power-flow optimization "
    "with passive branch constraints; transmission losses can be represented "
    "with PyPSA's piecewise-linear loss approximation when enabled."
)
SINGLE_SLACK_BUS = "Solomon Hub"
ALLOW_UNSERVED_ENERGY = True
VALUE_OF_LOST_LOAD = 100000.0
TRANSMISSION_LOSS_TRANCHES = 100
TRANSMISSION_LOSSES_ENABLED_DEFAULT = False
UNIT_COMMITMENT_OPTIMALITY = "Integer"
GAS_PRICE_PER_GJ = 5.65
DEFAULT_DATA_DIR = Path("pypsa_data_sources")
LOAD_PROFILE_FILE = Path("loads") / "load_p_set.csv"
NSJ_SF_PROFILE_FILE = Path("renewables") / "nsj_sfx_v1_5_bands.csv"
NSJ_SF_NAME = "North Star Junction SF"
NSJ_SF_COMMISSION_DATE = pd.Timestamp("2024-07-01")
NSJ_SF_SAMPLE_COLUMNS = ("1", "2", "3", "4", "5")

BUSES = (
    "Solomon Hub",
    "Lambda Terminal",
    "North Star Junction Terminal",
    "North Star Substation",
    "SM FT OPF",
    "SM GF",
    "SM KV OPF",
    "SM NPI",
    "SM TLO",
    "IB GF",
    "IB NPI",
    "IB OPF",
)

BUS_REGIONS = {
    "SM FT OPF": "Solomon",
    "SM GF": "Solomon",
    "SM KV OPF": "Solomon",
    "SM NPI": "Solomon",
    "SM TLO": "Solomon",
    "Solomon Hub": "Solomon",
    "Lambda Terminal": "Solomon",
    "North Star Junction Terminal": "Iron Bridge",
    "North Star Substation": "Iron Bridge",
    "IB GF": "Iron Bridge",
    "IB NPI": "Iron Bridge",
    "IB OPF": "Iron Bridge",
}

GENERATORS_AT_SOLOMON = tuple(f"Bergen-{i:02d}" for i in range(1, 15)) + (
    "LM6000-01",
    "LM6000-02",
    "Titan130-01",
    "Titan130-02",
    "Titan130-03",
    "Titan130-04",
)

GENERATORS = tuple((name, "Solomon Hub") for name in GENERATORS_AT_SOLOMON) + (
    (NSJ_SF_NAME, "North Star Junction Terminal"),
)

BERGEN_PROPERTIES = {
    "max_capacity_mw": 11.6,
    "min_stable_level_mw": 2.0,
    "vom_charge_per_mwh": 2.02,
    "running_cost_per_hour": 136.72,
    "start_cost": 100.0,
    "inertia_constant_s": 1.375,
    "heat_rate_base_gj_per_h": 9.648308394,
    "heat_rate_incr_gj_per_mwh": 8.581335238,
    "heat_rate_incr2_gj_per_mwh2": -0.126285763,
    "heat_rate_incr3_gj_per_mwh3": 0.008667396,
}

LM6000_PROPERTIES = {
    "max_capacity_mw": 40.0,
    "min_stable_level_mw": 15.0,
    "vom_charge_per_mwh": 2.02,
    "running_cost_per_hour": 330.0,
    "start_cost": 2000.0,
    "inertia_constant_s": 2.75,
    "heat_rate_base_gj_per_h": 168.439927721,
    "heat_rate_incr_gj_per_mwh": 2.045768608,
    "heat_rate_incr2_gj_per_mwh2": 0.132732541,
    "heat_rate_incr3_gj_per_mwh3": -0.001124121,
}

TITAN130_PROPERTIES = {
    "max_capacity_mw": 12.0,
    "min_stable_level_mw": 4.64,
    "vom_charge_per_mwh": 2.02,
    "running_cost_per_hour": 325.92,
    "start_cost": 600.0,
    "inertia_constant_s": 4.0,
    "heat_rate_base_gj_per_h": 8.593596825,
    "heat_rate_incr_gj_per_mwh": 19.866675709,
    "heat_rate_incr2_gj_per_mwh2": -1.399693034,
    "heat_rate_incr3_gj_per_mwh3": 0.05498233,
}

NSS_BESS_PROPERTIES = {
    "enabled": False,
    "capacity_mwh": 7.9276,
    "max_power_mw": 31.7104 / 4.0,
    "plexos_max_power_mw": 31.7104,
    "charge_efficiency": 0.90,
    "discharge_efficiency": 0.90,
    "max_up_time_h": 0.5,
}

SOL_BESS_PROPERTIES = {
    "enabled": False,
    "capacity_mwh": 4.9547,
    "max_power_mw": 14.3687,
    "charge_efficiency": 0.90,
    "discharge_efficiency": 0.90,
    "max_up_time_h": 0.5,
}

NSJ_SF_PROPERTIES = {
    "units": 100,
    "unit_max_capacity_mw": 1.0,
    "vom_charge_per_mwh": 0.0,
    "fom_charge_per_kw_year": 0.0,
    "commission_date": NSJ_SF_COMMISSION_DATE,
    "rating_profile_file": str(NSJ_SF_PROFILE_FILE),
}

LINE_DEFAULT_PROPERTIES = {
    "active": True,
    "max_flow_mw": 1e6,
    "loss_base": 0.0,
    "loss_incr": 0.0,
    "loss_incr2": 0.0,
    "commission_date": "",
}

LINE_PROPERTIES = {
    "SOL>Lambda": {
        "max_flow_mw": 500.0,
        "loss_base": 0.2231,
        "loss_incr": 0.0011,
        "loss_incr2": 0.0001,
        "commission_date": "2022-05-01 00:00",
    },
    "Lambda>NSJ": {
        "max_flow_mw": 500.0,
        "loss_base": 0.4398,
        "loss_incr": 0.013,
        "loss_incr2": 0.0,
        "commission_date": "2022-05-01 00:00",
    },
    "NSJT>NSJS": {
        "max_flow_mw": 500.0,
        "loss_base": 0.0362,
        "loss_incr": 0.0007,
        "loss_incr2": 0.0,
        "commission_date": "2022-05-01 00:00",
    },
    "SOL>Dx>FT OPF": {
        "active": True,
        "max_flow_mw": 100.0,
        "loss_base": 0.1,
    },
    "SOL>Dx>KV OPF": {
        "active": True,
        "max_flow_mw": 100.0,
        "loss_base": 0.1,
    },
    "SOL>Dx>SM GF": {
        "active": True,
        "max_flow_mw": 100.0,
        "loss_base": 0.1,
    },
    "SOL>Dx>SM NPI": {
        "active": True,
        "max_flow_mw": 100.0,
        "loss_base": 0.1,
    },
    "SOL>Dx>SM TLO": {
        "active": True,
        "max_flow_mw": 100.0,
        "loss_base": 0.1,
    },
    "NSS>Dx>IB GF": {
        "active": True,
        "max_flow_mw": 100.0,
        "loss_base": 0.1,
    },
    "NSS>Dx>IB NPI": {
        "active": True,
        "max_flow_mw": 100.0,
        "loss_base": 0.1,
    },
    "NSS>Dx>IB OPF": {
        "active": True,
        "max_flow_mw": 100.0,
        "loss_base": 0.1,
    },
}

STORAGE_UNITS = (
    ("SOL BESS", "Solomon Hub"),
    ("NSS BESS", "North Star Substation"),
)

LINES = (
    ("SOL>Lambda", "Solomon Hub", "Lambda Terminal"),
    ("Lambda>NSJ", "Lambda Terminal", "North Star Junction Terminal"),
    (
        "NSJT>NSJS",
        "North Star Junction Terminal",
        "North Star Substation",
    ),
    ("SOL>Dx>FT OPF", "Solomon Hub", "SM FT OPF"),
    ("SOL>Dx>KV OPF", "Solomon Hub", "SM KV OPF"),
    ("SOL>Dx>SM GF", "Solomon Hub", "SM GF"),
    ("SOL>Dx>SM NPI", "Solomon Hub", "SM NPI"),
    ("SOL>Dx>SM TLO", "Solomon Hub", "SM TLO"),
    ("NSS>Dx>IB GF", "North Star Substation", "IB GF"),
    ("NSS>Dx>IB NPI", "North Star Substation", "IB NPI"),
    ("NSS>Dx>IB OPF", "North Star Substation", "IB OPF"),
)

DEMAND_BUSES = (
    "SM FT OPF",
    "SM GF",
    "SM KV OPF",
    "SM NPI",
    "SM TLO",
    "IB GF",
    "IB NPI",
    "IB OPF",
)

IB_NPI_TIMESLICE_LOAD_MW = {
    "P1-9": 1.5,
    "P10-14": 1.0,
    "P15-36": 1.0,
    "P37-40": 1.5,
    "P41-48": 1.0,
}

INERTIA_RESERVE_NAME = "Inertia"
INERTIA_RESERVE_VORS_PER_MWS = 100000.0
INERTIA_RESERVE_CONDITIONS = (
    {
        "condition": "both_lm6000_on",
        "description": "LM6000-01 and LM6000-02 are both on",
        "min_provision_mws": 174.0,
    },
    {
        "condition": "any_lm6000_on",
        "description": "At least one LM6000 is on",
        "min_provision_mws": 174.0,
    },
    {
        "condition": "no_lm6000_on",
        "description": "Neither LM6000 is on",
        "min_provision_mws": 80.0,
    },
)
REGULATION_LOWER_RESERVE_NAME = "Regulation Lower"
REGULATION_LOWER_RESERVE_MIN_PROVISION_MW = 20.0
REGULATION_LOWER_RESERVE_VORS_PER_MW = 100000.0
REGULATION_LOWER_RESERVE_DYNAMIC_RISK = True
REGULATION_LOWER_RESERVE_CONTINGENCIES = ()
REGULATION_LOWER_RESERVE_PROVIDERS = tuple(
    f"Bergen-{i:02d}" for i in range(1, 15)
) + tuple(f"Titan130-{i:02d}" for i in range(1, 5))
REGULATION_RAISE_RESERVE_NAME = "Regulation Raise"
REGULATION_RAISE_RESERVE_MIN_PROVISION_MW = 20.0
REGULATION_RAISE_RESERVE_MAX_PROVISION_MW = 40.0
REGULATION_RAISE_RESERVE_VORS_PER_MW = 100000.0
REGULATION_RAISE_RESERVE_DYNAMIC_RISK = True
REGULATION_RAISE_RESERVE_CONTINGENCIES = ("LM6000-01", "LM6000-02")
REGULATION_RAISE_RESERVE_PROVIDERS = (
    tuple(f"Bergen-{i:02d}" for i in range(1, 15))
    + tuple(f"Titan130-{i:02d}" for i in range(1, 5))
    + REGULATION_RAISE_RESERVE_CONTINGENCIES
)
RAISE_RESERVE_SOLAR_NAME = "Raise Reserve Solar"
RAISE_RESERVE_SOLAR_DYNAMIC_RISK = True
RAISE_RESERVE_SOLAR_VORS_PER_MW = 100000.0
RAISE_RESERVE_SOLAR_CONTINGENCIES = (NSJ_SF_NAME,)
RAISE_RESERVE_SOLAR_PROVIDERS = (
    tuple(f"Bergen-{i:02d}" for i in range(1, 15))
    + ("LM6000-01", "LM6000-02")
    + tuple(f"Titan130-{i:02d}" for i in range(1, 5))
)
RAISE_RESERVE_SOLAR_RISK_ADJUSTMENT_FACTORS = {
    1: 1.18,
    2: 1.82,
    3: 1.54,
    4: 1.67,
    5: 2.0,
    6: 2.5,
    7: 2.22,
    8: 1.67,
    9: 1.43,
    10: 1.25,
    11: 1.25,
    12: 1.25,
}
STOCHASTIC_SOLAR_SAMPLES = NSJ_SF_SAMPLE_COLUMNS
GENERATION_NONANTICIPATIVE_HOURS = 20.0
GENERATION_NONANTICIPATIVE_GENERATORS = GENERATORS_AT_SOLOMON
STORAGE_NONANTICIPATIVE_UNITS = tuple(name for name, _ in STORAGE_UNITS)


def build_network_from_png(
    data_dir: Path | str = DEFAULT_DATA_DIR,
    nsj_sf_sample: str = "1",
    nsj_sf_year: int = 2024,
    snapshots: pd.DatetimeIndex | None = None,
) -> pypsa.Network:
    """Build the topology shown in Network.png as a standalone PyPSA network."""
    set_random_seed()
    data_dir = Path(data_dir)
    full_nsj_sf_profiles = read_nsj_sf_rating_profiles(
        data_dir / NSJ_SF_PROFILE_FILE,
        year=nsj_sf_year,
    )
    simulation_snapshots = (
        default_simulation_snapshots() if snapshots is None else pd.DatetimeIndex(snapshots)
    )
    nsj_sf_profiles = full_nsj_sf_profiles.reindex(simulation_snapshots)
    if nsj_sf_profiles.isna().any().any():
        raise ValueError("NSJ SF rating profile is missing simulation snapshots.")
    load_profiles = read_load_profiles(data_dir / LOAD_PROFILE_FILE)
    if nsj_sf_sample not in nsj_sf_profiles.columns:
        raise KeyError(
            f"Unknown NSJ SF sample {nsj_sf_sample!r}. "
            f"Available samples: {list(nsj_sf_profiles.columns)}"
        )

    network = pypsa.Network()
    network.set_snapshots(simulation_snapshots)
    apply_snapshot_weightings(network)
    attach_default_simulation_settings(network)
    network.nsj_sf_rating_profiles = nsj_sf_profiles
    network.nsj_sf_active_sample = nsj_sf_sample
    network.load_profiles = load_profiles
    network.load_profile_source = str(data_dir / LOAD_PROFILE_FILE)
    network.inertia_reserve_name = INERTIA_RESERVE_NAME
    network.inertia_reserve_vors_per_mws = INERTIA_RESERVE_VORS_PER_MWS
    network.inertia_reserve_conditions = INERTIA_RESERVE_CONDITIONS
    network.regulation_lower_reserve_name = REGULATION_LOWER_RESERVE_NAME
    network.regulation_lower_reserve_min_provision_mw = (
        REGULATION_LOWER_RESERVE_MIN_PROVISION_MW
    )
    network.regulation_lower_reserve_vors_per_mw = REGULATION_LOWER_RESERVE_VORS_PER_MW
    network.regulation_lower_reserve_dynamic_risk = (
        REGULATION_LOWER_RESERVE_DYNAMIC_RISK
    )
    network.regulation_lower_reserve_contingencies = (
        REGULATION_LOWER_RESERVE_CONTINGENCIES
    )
    network.regulation_lower_reserve_providers = REGULATION_LOWER_RESERVE_PROVIDERS
    network.regulation_raise_reserve_name = REGULATION_RAISE_RESERVE_NAME
    network.regulation_raise_reserve_min_provision_mw = (
        REGULATION_RAISE_RESERVE_MIN_PROVISION_MW
    )
    network.regulation_raise_reserve_max_provision_mw = (
        REGULATION_RAISE_RESERVE_MAX_PROVISION_MW
    )
    network.regulation_raise_reserve_vors_per_mw = REGULATION_RAISE_RESERVE_VORS_PER_MW
    network.regulation_raise_reserve_dynamic_risk = (
        REGULATION_RAISE_RESERVE_DYNAMIC_RISK
    )
    network.regulation_raise_reserve_contingencies = (
        REGULATION_RAISE_RESERVE_CONTINGENCIES
    )
    network.regulation_raise_reserve_providers = REGULATION_RAISE_RESERVE_PROVIDERS
    network.raise_reserve_solar_name = RAISE_RESERVE_SOLAR_NAME
    network.raise_reserve_solar_dynamic_risk = RAISE_RESERVE_SOLAR_DYNAMIC_RISK
    network.raise_reserve_solar_vors_per_mw = RAISE_RESERVE_SOLAR_VORS_PER_MW
    network.raise_reserve_solar_contingencies = RAISE_RESERVE_SOLAR_CONTINGENCIES
    network.raise_reserve_solar_providers = RAISE_RESERVE_SOLAR_PROVIDERS
    network.raise_reserve_solar_risk_adjustment_factors = (
        RAISE_RESERVE_SOLAR_RISK_ADJUSTMENT_FACTORS
    )

    network.add("Carrier", "AC")
    network.add("Carrier", "gas", fuel="gas", fuel_price_per_gj=GAS_PRICE_PER_GJ)
    network.add("Carrier", "solar")
    network.add("Carrier", "battery")
    network.add("Carrier", "unserved_energy")

    for bus in BUSES:
        network.add(
            "Bus",
            bus,
            carrier="AC",
            v_nom=1.0,
            region=BUS_REGIONS[bus],
            is_slack_bus=bus == SINGLE_SLACK_BUS,
        )

    for name, bus in GENERATORS:
        is_solar = name == NSJ_SF_NAME
        is_bergen = name.startswith("Bergen-")
        is_lm6000 = name.startswith("LM6000-")
        is_titan130 = name.startswith("Titan130-")
        thermal_properties = None
        if is_bergen:
            thermal_properties = BERGEN_PROPERTIES
        elif is_lm6000:
            thermal_properties = LM6000_PROPERTIES
        elif is_titan130:
            thermal_properties = TITAN130_PROPERTIES

        if is_solar:
            p_nom = (
                NSJ_SF_PROPERTIES["units"]
                * NSJ_SF_PROPERTIES["unit_max_capacity_mw"]
            )
            p_max_pu = nsj_sf_profiles[nsj_sf_sample]
            marginal_cost = NSJ_SF_PROPERTIES["vom_charge_per_mwh"]
        else:
            p_nom = (
                thermal_properties["max_capacity_mw"] if thermal_properties else 0.0
            )
            p_max_pu = 1.0
            marginal_cost = (
                thermal_marginal_cost(thermal_properties)
                if thermal_properties
                else 0.0
            )

        generator_kwargs = {
            "bus": bus,
            "carrier": "solar" if is_solar else "gas",
            "fuel": "gas" if thermal_properties else "",
            "fuel_price_per_gj": GAS_PRICE_PER_GJ if thermal_properties else 0.0,
            "p_nom": p_nom,
            "p_min_pu": (
                thermal_properties["min_stable_level_mw"]
                / thermal_properties["max_capacity_mw"]
                if thermal_properties
                else 0.0
            ),
            "p_max_pu": p_max_pu,
            "marginal_cost": marginal_cost,
            "stand_by_cost": (
                thermal_properties["running_cost_per_hour"]
                if thermal_properties
                else 0.0
            ),
            "start_up_cost": (
                thermal_properties["start_cost"] if thermal_properties else 0.0
            ),
            "committable": thermal_properties is not None,
        }
        if thermal_properties:
            generator_kwargs.update(thermal_properties)
            generator_kwargs["inertia_mw_s"] = (
                thermal_properties["inertia_constant_s"]
                * thermal_properties["max_capacity_mw"]
            )
        if is_solar:
            generator_kwargs.update(NSJ_SF_PROPERTIES)
            generator_kwargs["commission_date"] = str(
                NSJ_SF_PROPERTIES["commission_date"].date()
            )
            generator_kwargs["active_rating_sample"] = nsj_sf_sample

        network.add(
            "Generator",
            name,
            **generator_kwargs,
        )

    for name, bus in STORAGE_UNITS:
        if name == "NSS BESS":
            properties = NSS_BESS_PROPERTIES
        elif name == "SOL BESS":
            properties = SOL_BESS_PROPERTIES
        else:
            properties = None
        network.add(
            "StorageUnit",
            name,
            bus=bus,
            carrier="battery",
            p_nom=(
                properties["max_power_mw"]
                if properties and properties["enabled"]
                else 0.0
            ),
            max_hours=(
                properties["capacity_mwh"] / properties["max_power_mw"]
                if properties
                else 0.0
            ),
            efficiency_store=(
                properties["charge_efficiency"] if properties else 1.0
            ),
            efficiency_dispatch=(
                properties["discharge_efficiency"] if properties else 1.0
            ),
            marginal_cost=0.0,
            enabled=properties["enabled"] if properties else True,
            installed_p_nom=properties["max_power_mw"] if properties else 0.0,
            installed_e_nom=properties["capacity_mwh"] if properties else 0.0,
            plexos_max_power_mw=(
                properties.get("plexos_max_power_mw", properties["max_power_mw"])
                if properties
                else 0.0
            ),
            max_up_time_h=properties["max_up_time_h"] if properties else 0.0,
        )

    for name, bus0, bus1 in LINES:
        properties = LINE_DEFAULT_PROPERTIES | LINE_PROPERTIES.get(name, {})
        network.add(
            "Line",
            name,
            bus0=bus0,
            bus1=bus1,
            carrier="AC",
            active=properties["active"],
            s_nom=properties["max_flow_mw"],
            r=0.0,
            x=1.0,
            max_flow_mw=properties["max_flow_mw"],
            loss_base=properties["loss_base"],
            loss_incr=properties["loss_incr"],
            loss_incr2=properties["loss_incr2"],
            commission_date=properties["commission_date"],
        )

    for bus in DEMAND_BUSES:
        p_set = align_series_to_snapshots(load_profiles[bus], network.snapshots)
        if bus == "IB NPI":
            p_set = apply_timeslice_values(
                p_set,
                IB_NPI_TIMESLICE_LOAD_MW,
                periods_per_day=48,
            )
        network.add(
            "Load",
            f"{bus} load",
            bus=bus,
            p_set=p_set,
            source_file=str(LOAD_PROFILE_FILE),
        )
        if ALLOW_UNSERVED_ENERGY:
            network.add(
                "Generator",
                f"Unserved Energy {bus}",
                bus=bus,
                carrier="unserved_energy",
                p_nom=1e6,
                p_min_pu=0.0,
                p_max_pu=1.0,
                marginal_cost=VALUE_OF_LOST_LOAD,
                committable=False,
                load_shedding=True,
                voll=VALUE_OF_LOST_LOAD,
            )

    return network


def default_simulation_snapshots() -> pd.DatetimeIndex:
    periods = int(
        (SIMULATION_DAYS + SIMULATION_LOOKAHEAD_DAYS)
        * 24
        * 60
        / SIMULATION_INTERVAL_MINUTES
    )
    return pd.date_range(
        start=SIMULATION_START,
        periods=periods,
        freq=f"{SIMULATION_INTERVAL_MINUTES}min",
        name="snapshot",
    )


def align_series_to_snapshots(series: pd.Series, snapshots: pd.DatetimeIndex) -> pd.Series:
    aligned_index = series.index.union(snapshots)
    return series.reindex(aligned_index).sort_index().ffill().bfill().reindex(snapshots)


def default_reporting_snapshots() -> pd.DatetimeIndex:
    periods = int(SIMULATION_DAYS * 24 * 60 / SIMULATION_INTERVAL_MINUTES)
    return pd.date_range(
        start=SIMULATION_START,
        periods=periods,
        freq=f"{SIMULATION_INTERVAL_MINUTES}min",
        name="snapshot",
    )


def apply_snapshot_weightings(network: pypsa.Network) -> None:
    duration_hours = snapshot_duration_hours(network.snapshots)
    network.snapshot_weightings.loc[:, ["objective", "stores", "generators"]] = (
        duration_hours
    )


def attach_default_simulation_settings(network: pypsa.Network) -> None:
    network.random_seed = RANDOM_SEED
    network.simulation_start = SIMULATION_START
    network.simulation_days = SIMULATION_DAYS
    network.simulation_step_days = SIMULATION_STEP_DAYS
    network.simulation_lookahead_days = SIMULATION_LOOKAHEAD_DAYS
    network.simulation_interval_minutes = SIMULATION_INTERVAL_MINUTES
    network.simulation_full_chronology = SIMULATION_FULL_CHRONOLOGY
    network.single_slack_bus = SINGLE_SLACK_BUS
    network.allow_unserved_energy = ALLOW_UNSERVED_ENERGY
    network.value_of_lost_load = VALUE_OF_LOST_LOAD
    network.unit_commitment_optimality = UNIT_COMMITMENT_OPTIMALITY
    network.opf_requested_method = OPF_REQUESTED_METHOD
    network.opf_pypsa_method = OPF_PYPSA_METHOD
    network.opf_method_note = OPF_METHOD_NOTE
    network.transmission_loss_tranches = TRANSMISSION_LOSS_TRANCHES
    network.transmission_losses_enabled_default = TRANSMISSION_LOSSES_ENABLED_DEFAULT
    network.optimization_snapshot_count = len(default_simulation_snapshots())
    network.reporting_snapshot_count = len(default_reporting_snapshots())


def stochastic_component(base_name: str, sample: str) -> str:
    return f"{base_name}__s{sample}"


def set_random_seed(seed: int | None = None) -> None:
    if seed is None:
        seed = RANDOM_SEED
    random.seed(seed)
    np.random.seed(seed)


def resolve_path_from_script(path: Path | str) -> Path:
    path = Path(path)
    if path.is_absolute():
        return path.resolve()
    return (SCRIPT_DIR / path).resolve()


def normalize_solver_name(solver_name: str) -> str:
    solver_key = solver_name.strip().lower()
    if solver_key not in SUPPORTED_SOLVERS:
        supported = ", ".join(SUPPORTED_SOLVERS)
        raise ValueError(
            f"Unsupported solver {solver_name!r}. Choose one of: {supported}."
        )
    return solver_key


def default_output_dir_for_solver(solver_name: str) -> Path:
    return Path(f"{DEFAULT_OUTPUT_DIR_PREFIX}_{normalize_solver_name(solver_name)}")


def ensure_solver_available(solver_name: str) -> None:
    solver_key = normalize_solver_name(solver_name)
    import linopy.solvers as linopy_solvers

    if solver_key not in linopy_solvers.available_solvers:
        available = ", ".join(linopy_solvers.available_solvers) or "none"
        raise RuntimeError(
            f"Solver {solver_key!r} is not available to Linopy. "
            f"Available solvers: {available}."
        )


def configure_gurobi_license(
    license_file: Path | str | None = DEFAULT_GUROBI_LICENSE_FILE,
) -> Path | None:
    if license_file is None:
        return None

    license_path = resolve_path_from_script(license_file)
    if not license_path.exists():
        raise FileNotFoundError(f"Gurobi license file not found: {license_path}")

    os.environ["GRB_LICENSE_FILE"] = str(license_path)
    return license_path


def solver_options_for(
    solver_name: str,
    solver_time_limit: float | None = None,
    solver_mip_gap: float | None = None,
    solver_threads: int | None = None,
) -> dict[str, int | float] | None:
    solver_key = normalize_solver_name(solver_name)
    if solver_key == "highs":
        options: dict[str, int | float] = {"random_seed": RANDOM_SEED}
        if solver_time_limit is not None:
            options["time_limit"] = float(solver_time_limit)
        if solver_mip_gap is not None:
            options["mip_rel_gap"] = float(solver_mip_gap)
        if solver_threads is not None:
            options["threads"] = int(solver_threads)
        return options
    if solver_key == "gurobi":
        options: dict[str, int | float] = {"Seed": RANDOM_SEED}
        if solver_time_limit is not None:
            options["TimeLimit"] = float(solver_time_limit)
        if solver_mip_gap is not None:
            options["MIPGap"] = float(solver_mip_gap)
        if solver_threads is not None:
            options["Threads"] = int(solver_threads)
        return options
    return None


def resolve_solver_controls(
    solver_time_limit: float | None = None,
    solver_mip_gap: float | None = None,
    solver_threads: int | None = None,
    gurobi_time_limit: float | None = None,
    gurobi_mip_gap: float | None = None,
    gurobi_threads: int | None = None,
) -> tuple[float | None, float | None, int | None]:
    time_limit = solver_time_limit if solver_time_limit is not None else gurobi_time_limit
    mip_gap = solver_mip_gap if solver_mip_gap is not None else gurobi_mip_gap
    threads = solver_threads if solver_threads is not None else gurobi_threads
    return time_limit, mip_gap, threads


def weight_generator_costs(attrs: dict, sample_weight: float) -> None:
    for column in ("marginal_cost", "stand_by_cost", "start_up_cost", "shut_down_cost"):
        if column in attrs and pd.notna(attrs[column]):
            attrs[column] = float(attrs[column]) * sample_weight


def weight_storage_costs(attrs: dict, sample_weight: float) -> None:
    for column in ("marginal_cost", "standing_loss"):
        if column in attrs and pd.notna(attrs[column]):
            attrs[column] = float(attrs[column]) * sample_weight


def build_stochastic_network_from_png(
    data_dir: Path | str = DEFAULT_DATA_DIR,
    samples: tuple[str, ...] = STOCHASTIC_SOLAR_SAMPLES,
    nsj_sf_year: int = 2024,
    nonanticipative_hours: float = GENERATION_NONANTICIPATIVE_HOURS,
) -> pypsa.Network:
    """Build a five-sample stochastic network using NSJ SF solar samples."""
    sample_networks = {
        sample: build_network_from_png(
            data_dir=data_dir,
            nsj_sf_sample=sample,
            nsj_sf_year=nsj_sf_year,
        )
        for sample in samples
    }
    reference = sample_networks[samples[0]]

    network = pypsa.Network()
    network.set_snapshots(reference.snapshots)
    apply_snapshot_weightings(network)
    attach_default_simulation_settings(network)
    network.stochastic_samples = samples
    network.stochastic_sample_weights = {sample: 1.0 / len(samples) for sample in samples}
    network.generation_nonanticipative_hours = nonanticipative_hours
    network.generation_nonanticipative_generators = GENERATION_NONANTICIPATIVE_GENERATORS
    network.storage_nonanticipative_hours = nonanticipative_hours
    network.storage_nonanticipative_units = STORAGE_NONANTICIPATIVE_UNITS
    network.nsj_sf_rating_profiles = reference.nsj_sf_rating_profiles
    network.load_profiles = reference.load_profiles
    network.load_profile_source = reference.load_profile_source
    copy_reserve_metadata(reference, network)

    for carrier_name, carrier in reference.carriers.iterrows():
        network.add("Carrier", carrier_name, **carrier.dropna().to_dict())

    for sample, sample_network in sample_networks.items():
        sample_weight = network.stochastic_sample_weights[sample]
        for bus_name, bus in sample_network.buses.iterrows():
            network.add(
                "Bus",
                stochastic_component(bus_name, sample),
                carrier=bus["carrier"],
                v_nom=bus["v_nom"],
                region=bus["region"],
                base_name=bus_name,
                sample=sample,
            )

        for generator_name, generator in sample_network.generators.iterrows():
            attrs = generator.dropna().to_dict()
            attrs.pop("p_max_pu", None)
            attrs["bus"] = stochastic_component(generator["bus"], sample)
            attrs["base_name"] = generator_name
            attrs["sample"] = sample
            attrs["sample_weight"] = sample_weight
            weight_generator_costs(attrs, sample_weight)
            p_max_pu = sample_network.generators_t.p_max_pu
            if generator_name in p_max_pu.columns:
                attrs["p_max_pu"] = p_max_pu[generator_name]
            network.add("Generator", stochastic_component(generator_name, sample), **attrs)

        for storage_name, storage in sample_network.storage_units.iterrows():
            attrs = storage.dropna().to_dict()
            attrs["bus"] = stochastic_component(storage["bus"], sample)
            attrs["base_name"] = storage_name
            attrs["sample"] = sample
            attrs["sample_weight"] = sample_weight
            weight_storage_costs(attrs, sample_weight)
            network.add("StorageUnit", stochastic_component(storage_name, sample), **attrs)

        for line_name, line in sample_network.lines.iterrows():
            attrs = line.dropna().to_dict()
            attrs["bus0"] = stochastic_component(line["bus0"], sample)
            attrs["bus1"] = stochastic_component(line["bus1"], sample)
            attrs["base_name"] = line_name
            attrs["sample"] = sample
            network.add("Line", stochastic_component(line_name, sample), **attrs)

        for load_name, load in sample_network.loads.iterrows():
            attrs = load.dropna().to_dict()
            attrs.pop("p_set", None)
            attrs["bus"] = stochastic_component(load["bus"], sample)
            attrs["base_name"] = load_name
            attrs["sample"] = sample
            p_set = sample_network.loads_t.p_set[load_name]
            network.add("Load", stochastic_component(load_name, sample), p_set=p_set, **attrs)

    return network


def build_base_stochastic_dispatch_scenario(
    data_dir: Path | str = DEFAULT_DATA_DIR,
    nsj_sf_year: int = 2024,
    nonanticipative_hours: float = GENERATION_NONANTICIPATIVE_HOURS,
) -> pypsa.Network:
    """Base scenario: 5-sample stochastic dispatch with thermal non-anticipativity."""
    network = build_stochastic_network_from_png(
        data_dir=data_dir,
        samples=STOCHASTIC_SOLAR_SAMPLES,
        nsj_sf_year=nsj_sf_year,
        nonanticipative_hours=nonanticipative_hours,
    )
    network.scenario_name = "base_stochastic_dispatch"
    network.scenario_description = (
        "Five-sample solar stochastic dispatch with 20-hour non-anticipativity "
        "for Bergen, LM6000, Titan130 thermal generators, and battery storage."
    )
    network.base_scenario_extra_functionality = add_stochastic_dispatch_constraints
    return network


def copy_reserve_metadata(source: pypsa.Network, target: pypsa.Network) -> None:
    for attribute in (
        "inertia_reserve_name",
        "inertia_reserve_vors_per_mws",
        "inertia_reserve_conditions",
        "regulation_lower_reserve_name",
        "regulation_lower_reserve_min_provision_mw",
        "regulation_lower_reserve_vors_per_mw",
        "regulation_lower_reserve_dynamic_risk",
        "regulation_lower_reserve_contingencies",
        "regulation_lower_reserve_providers",
        "regulation_raise_reserve_name",
        "regulation_raise_reserve_min_provision_mw",
        "regulation_raise_reserve_max_provision_mw",
        "regulation_raise_reserve_vors_per_mw",
        "regulation_raise_reserve_dynamic_risk",
        "regulation_raise_reserve_contingencies",
        "regulation_raise_reserve_providers",
        "raise_reserve_solar_name",
        "raise_reserve_solar_dynamic_risk",
        "raise_reserve_solar_vors_per_mw",
        "raise_reserve_solar_contingencies",
        "raise_reserve_solar_providers",
        "raise_reserve_solar_risk_adjustment_factors",
    ):
        setattr(target, attribute, getattr(source, attribute))


def read_nsj_sf_rating_profiles(path: Path, year: int) -> pd.DataFrame:
    df = pd.read_csv(path)
    required_columns = {"MONTH", "DAY", "PERIOD", *NSJ_SF_SAMPLE_COLUMNS}
    missing = required_columns - set(df.columns)
    if missing:
        raise KeyError(f"{path} missing columns: {sorted(missing)}")

    timestamps = pd.to_datetime(
        {
            "year": year,
            "month": df["MONTH"].astype(int),
            "day": df["DAY"].astype(int),
        },
        errors="coerce",
    )
    if timestamps.isna().any():
        bad_rows = df.loc[timestamps.isna(), ["MONTH", "DAY"]].drop_duplicates()
        raise ValueError(f"{path} contains invalid month/day rows: {bad_rows}")

    period_offsets = pd.to_timedelta((df["PERIOD"].astype(int) - 1) * 30, unit="min")
    index = pd.DatetimeIndex(timestamps + period_offsets, name="snapshot")
    profiles = df.loc[:, NSJ_SF_SAMPLE_COLUMNS].astype(float)
    profiles.index = index
    profiles = profiles.sort_index()

    commission_mask = profiles.index >= NSJ_SF_COMMISSION_DATE
    profiles.loc[~commission_mask, :] = 0.0
    return profiles


def trading_periods(snapshots: pd.DatetimeIndex, periods_per_day: int = 48) -> pd.Series:
    minutes = snapshots.hour * 60 + snapshots.minute
    period_minutes = 24 * 60 / periods_per_day
    periods = (minutes // period_minutes).astype(int) + 1
    return pd.Series(periods, index=snapshots, dtype=int)


def timeslice_mask(
    snapshots: pd.DatetimeIndex, timeslice: str, periods_per_day: int = 48
) -> pd.Series:
    text = timeslice.strip().upper()
    if not text.startswith("P"):
        raise ValueError(f"Unsupported timeslice {timeslice!r}; expected e.g. P1-9.")

    period_text = text[1:]
    periods = trading_periods(snapshots, periods_per_day=periods_per_day)
    if "-" in period_text:
        start_text, end_text = period_text.split("-", 1)
        start = int(start_text)
        end = int(end_text)
        if start > end:
            raise ValueError(f"Unsupported descending timeslice {timeslice!r}.")
        return (periods >= start) & (periods <= end)

    period = int(period_text)
    return periods == period


def apply_timeslice_values(
    series: pd.Series,
    values_by_timeslice: dict[str, float],
    periods_per_day: int = 48,
) -> pd.Series:
    result = series.copy()
    covered = pd.Series(False, index=series.index)
    for timeslice, value in values_by_timeslice.items():
        mask = timeslice_mask(series.index, timeslice, periods_per_day=periods_per_day)
        result.loc[mask] = value
        covered.loc[mask] = True
    if not covered.all():
        uncovered_periods = sorted(
            trading_periods(series.index[~covered], periods_per_day=periods_per_day)
            .unique()
            .tolist()
        )
        raise ValueError(f"Timeslices do not cover periods: {uncovered_periods}")
    return result


def inertia_condition_requirements(
    network: pypsa.Network | None = None,
) -> dict[str, float]:
    conditions = (
        getattr(network, "inertia_reserve_conditions", INERTIA_RESERVE_CONDITIONS)
        if network is not None
        else INERTIA_RESERVE_CONDITIONS
    )
    requirements = {
        condition["condition"]: float(condition["min_provision_mws"])
        for condition in conditions
    }
    required_conditions = {
        "both_lm6000_on",
        "any_lm6000_on",
        "no_lm6000_on",
    }
    missing = sorted(required_conditions - set(requirements))
    if missing:
        raise KeyError(f"Missing inertia reserve conditions: {missing}")
    return requirements


def inertia_requirement_mws(
    lm6000_01_on: bool,
    lm6000_02_on: bool,
    network: pypsa.Network | None = None,
) -> tuple[str, float]:
    requirements = inertia_condition_requirements(network)
    if lm6000_01_on and lm6000_02_on:
        condition = "both_lm6000_on"
        return condition, requirements[condition]
    if lm6000_01_on or lm6000_02_on:
        condition = "any_lm6000_on"
        return condition, requirements[condition]
    condition = "no_lm6000_on"
    return condition, requirements[condition]


def add_inertia_reserve_constraints(
    network: pypsa.Network, snapshots: pd.DatetimeIndex
) -> None:
    """Add conditional inertia reserve constraints to a PyPSA linopy model.

    Use as PyPSA's ``extra_functionality`` hook when optimizing:

    ``network.optimize(extra_functionality=add_inertia_reserve_constraints)``
    """
    model = network.model
    if "Generator-status" not in model.variables:
        raise RuntimeError(
            "Inertia reserve constraints require committable generators and "
            "PyPSA's Generator-status variable."
        )

    snapshots = pd.DatetimeIndex(snapshots, name="snapshot")
    gen_status = model.variables["Generator-status"]
    lm6000_01_status = gen_status.sel(name="LM6000-01", snapshot=snapshots)
    lm6000_02_status = gen_status.sel(name="LM6000-02", snapshot=snapshots)

    both_lm6000_on = model.add_variables(
        coords={"snapshot": snapshots},
        binary=True,
        name="Inertia-both-lm6000-on",
    )
    any_lm6000_on = model.add_variables(
        coords={"snapshot": snapshots},
        binary=True,
        name="Inertia-any-lm6000-on",
    )
    shortage = model.add_variables(
        lower=0,
        coords={"snapshot": snapshots},
        name="Inertia-shortage",
    )

    model.add_constraints(
        both_lm6000_on <= lm6000_01_status,
        name="Inertia-both-lm6000-on-upper-lm6000-01",
    )
    model.add_constraints(
        both_lm6000_on <= lm6000_02_status,
        name="Inertia-both-lm6000-on-upper-lm6000-02",
    )
    model.add_constraints(
        both_lm6000_on >= lm6000_01_status + lm6000_02_status - 1,
        name="Inertia-both-lm6000-on-lower",
    )

    model.add_constraints(
        any_lm6000_on >= lm6000_01_status,
        name="Inertia-any-lm6000-on-lower-lm6000-01",
    )
    model.add_constraints(
        any_lm6000_on >= lm6000_02_status,
        name="Inertia-any-lm6000-on-lower-lm6000-02",
    )
    model.add_constraints(
        any_lm6000_on <= lm6000_01_status + lm6000_02_status,
        name="Inertia-any-lm6000-on-upper",
    )

    one_lm6000_on = any_lm6000_on - both_lm6000_on
    no_lm6000_on = 1 - any_lm6000_on
    requirements = inertia_condition_requirements(network)
    requirement = (
        requirements["both_lm6000_on"] * both_lm6000_on
        + requirements["any_lm6000_on"] * one_lm6000_on
        + requirements["no_lm6000_on"] * no_lm6000_on
    )

    inertia_provision_terms = []
    for generator_name, generator in network.generators.iterrows():
        inertia_mw_s = generator.get("inertia_mw_s")
        if pd.isna(inertia_mw_s) or float(inertia_mw_s) <= 0.0:
            continue
        inertia_provision_terms.append(
            float(inertia_mw_s)
            * gen_status.sel(name=generator_name, snapshot=snapshots)
        )

    if not inertia_provision_terms:
        raise RuntimeError("No generators with positive inertia_mw_s are available.")

    inertia_provision = sum(inertia_provision_terms)
    model.add_constraints(
        inertia_provision + shortage >= requirement,
        name="Inertia-reserve-requirement",
    )

    shortage_penalty = (shortage * network.inertia_reserve_vors_per_mws).sum()
    model.add_objective(
        model.objective.expression + shortage_penalty,
        overwrite=True,
        sense="min",
    )


def add_regulation_lower_reserve_constraints(
    network: pypsa.Network, snapshots: pd.DatetimeIndex
) -> None:
    """Add regulation-lower reserve constraints to a PyPSA linopy model."""
    model = network.model
    if "Generator-status" not in model.variables or "Generator-p" not in model.variables:
        raise RuntimeError(
            "Regulation lower reserve constraints require Generator-status and "
            "Generator-p variables."
        )

    snapshots = pd.DatetimeIndex(snapshots, name="snapshot")
    gen_status = model.variables["Generator-status"]
    gen_p = model.variables["Generator-p"]
    providers = pd.Index(
        network.regulation_lower_reserve_providers,
        name="regulation_lower_provider",
    )

    lower_reserve = model.add_variables(
        lower=0.0,
        coords={"snapshot": snapshots, providers.name: providers},
        name="Regulation-lower-reserve",
    )
    shortage = model.add_variables(
        lower=0.0,
        coords={"snapshot": snapshots},
        name="Regulation-lower-shortage",
    )

    model.add_constraints(
        lower_reserve.sum(providers.name) + shortage
        >= network.regulation_lower_reserve_min_provision_mw,
        name="Regulation-lower-reserve-requirement",
    )
    if not network.regulation_lower_reserve_contingencies:
        model.add_constraints(
            lower_reserve.sum(providers.name) + shortage
            <= network.regulation_lower_reserve_min_provision_mw,
            name="Regulation-lower-reserve-cap",
        )

    if network.regulation_lower_reserve_dynamic_risk:
        for contingency in network.regulation_lower_reserve_contingencies:
            contingency_risk = gen_p.sel(name=contingency, snapshot=snapshots)
            model.add_constraints(
                lower_reserve.sum(providers.name) + shortage >= contingency_risk,
                name=f"Regulation-lower-dynamic-risk-{contingency}",
            )

    for generator_name in providers:
        generator = network.generators.loc[generator_name]
        status = gen_status.sel(name=generator_name, snapshot=snapshots)
        output = gen_p.sel(name=generator_name, snapshot=snapshots)
        min_output = float(generator["p_nom"]) * float(generator["p_min_pu"])
        model.add_constraints(
            lower_reserve.sel({providers.name: generator_name})
            <= output - min_output * status,
            name=f"Regulation-lower-headroom-{generator_name}",
        )

    shortage_penalty = shortage.sum() * network.regulation_lower_reserve_vors_per_mw
    model.add_objective(
        model.objective.expression + shortage_penalty,
        overwrite=True,
        sense="min",
    )


def safe_constraint_label(value: str) -> str:
    return value.replace(" ", "-").replace("/", "-").replace(">", "gt")


def add_exact_max_requirement(
    model,
    snapshots: pd.DatetimeIndex,
    name: str,
    candidates: list[tuple[str, object]],
    big_m: float,
):
    requirement = model.add_variables(
        lower=0.0,
        coords={"snapshot": snapshots},
        name=name,
    )
    if not candidates:
        model.add_constraints(requirement == 0.0, name=f"{name}-definition")
        return requirement

    if len(candidates) == 1:
        model.add_constraints(
            requirement == candidates[0][1],
            name=f"{name}-definition",
        )
        return requirement

    dim = f"{name.replace('-', '_')}_candidate"
    labels = pd.Index([label for label, _ in candidates], name=dim)
    active = model.add_variables(
        coords={"snapshot": snapshots, dim: labels},
        binary=True,
        name=f"{name}-active",
    )
    model.add_constraints(
        active.sum(dim) == 1,
        name=f"{name}-active-one",
    )
    for label, expression in candidates:
        safe_label = safe_constraint_label(label)
        selector = active.sel({dim: label})
        model.add_constraints(
            requirement >= expression,
            name=f"{name}-lower-{safe_label}",
        )
        model.add_constraints(
            requirement <= expression + big_m * (1 - selector),
            name=f"{name}-upper-{safe_label}",
        )
    return requirement


def regulation_raise_requirement_candidates(
    network: pypsa.Network,
    snapshots: pd.DatetimeIndex,
    gen_p,
    sample: str = "",
) -> list[tuple[str, object]]:
    candidates: list[tuple[str, object]] = [
        ("minimum", network.regulation_raise_reserve_min_provision_mw)
    ]
    if network.regulation_raise_reserve_dynamic_risk:
        for contingency in network.regulation_raise_reserve_contingencies:
            component = stochastic_component(contingency, sample) if sample else contingency
            candidates.append(
                (
                    contingency,
                    gen_p.sel(name=component, snapshot=snapshots),
                )
            )
    return candidates


def regulation_raise_requirement_big_m(network: pypsa.Network, sample: str = "") -> float:
    bounds = [
        network.regulation_raise_reserve_min_provision_mw,
        network.regulation_raise_reserve_max_provision_mw,
    ]
    for contingency in network.regulation_raise_reserve_contingencies:
        component = stochastic_component(contingency, sample) if sample else contingency
        if component in network.generators.index:
            bounds.append(float(network.generators.at[component, "p_nom"]))
    return max(bounds)


def add_regulation_raise_reserve_constraints(
    network: pypsa.Network, snapshots: pd.DatetimeIndex
) -> None:
    """Add regulation-raise reserve constraints with dynamic LM6000 risk."""
    model = network.model
    if "Generator-status" not in model.variables or "Generator-p" not in model.variables:
        raise RuntimeError(
            "Regulation raise reserve constraints require Generator-status and "
            "Generator-p variables."
        )

    snapshots = pd.DatetimeIndex(snapshots, name="snapshot")
    gen_status = model.variables["Generator-status"]
    gen_p = model.variables["Generator-p"]
    providers = pd.Index(
        network.regulation_raise_reserve_providers,
        name="regulation_raise_provider",
    )

    raise_reserve = model.add_variables(
        lower=0.0,
        coords={"snapshot": snapshots, providers.name: providers},
        name="Regulation-raise-reserve",
    )
    shortage = model.add_variables(
        lower=0.0,
        coords={"snapshot": snapshots},
        name="Regulation-raise-shortage",
    )
    provision = raise_reserve.sum(providers.name)

    requirement = add_exact_max_requirement(
        model,
        snapshots,
        "Regulation-raise-requirement",
        regulation_raise_requirement_candidates(network, snapshots, gen_p),
        regulation_raise_requirement_big_m(network),
    )
    model.add_constraints(
        provision + shortage == requirement,
        name="Regulation-raise-requirement-balance",
    )
    model.add_constraints(
        provision <= network.regulation_raise_reserve_max_provision_mw,
        name="Regulation-raise-max-provision",
    )

    for generator_name in providers:
        generator = network.generators.loc[generator_name]
        status = gen_status.sel(name=generator_name, snapshot=snapshots)
        output = gen_p.sel(name=generator_name, snapshot=snapshots)
        model.add_constraints(
            raise_reserve.sel({providers.name: generator_name})
            <= float(generator["p_nom"]) * status - output,
            name=f"Regulation-raise-headroom-{generator_name}",
        )

    shortage_penalty = shortage.sum() * network.regulation_raise_reserve_vors_per_mw
    model.add_objective(
        model.objective.expression + shortage_penalty,
        overwrite=True,
        sense="min",
    )


def add_raise_reserve_solar_constraints(
    network: pypsa.Network, snapshots: pd.DatetimeIndex
) -> None:
    """Add solar contingency regulation-raise reserve constraints."""
    model = network.model
    if "Generator-status" not in model.variables or "Generator-p" not in model.variables:
        raise RuntimeError(
            "Raise Reserve Solar constraints require Generator-status and "
            "Generator-p variables."
        )

    snapshots = pd.DatetimeIndex(snapshots, name="snapshot")
    gen_status = model.variables["Generator-status"]
    gen_p = model.variables["Generator-p"]
    providers = pd.Index(
        network.raise_reserve_solar_providers,
        name="raise_reserve_solar_provider",
    )

    solar_raise = model.add_variables(
        lower=0.0,
        coords={"snapshot": snapshots, providers.name: providers},
        name="Raise-reserve-solar",
    )
    shortage = model.add_variables(
        lower=0.0,
        coords={"snapshot": snapshots},
        name="Raise-reserve-solar-shortage",
    )
    provision = solar_raise.sum(providers.name)

    if network.raise_reserve_solar_dynamic_risk:
        risk_factor = series_to_linopy_da(
            monthly_risk_adjustment_factor_series(
                snapshots, network.raise_reserve_solar_risk_adjustment_factors
            )
        )
        for contingency in network.raise_reserve_solar_contingencies:
            contingency_risk = gen_p.sel(name=contingency, snapshot=snapshots) / risk_factor
            model.add_constraints(
                provision + shortage == contingency_risk,
                name=f"Raise-reserve-solar-dynamic-risk-{contingency}",
            )

    for generator_name in providers:
        generator = network.generators.loc[generator_name]
        status = gen_status.sel(name=generator_name, snapshot=snapshots)
        output = gen_p.sel(name=generator_name, snapshot=snapshots)
        reserve_sum = solar_raise.sel({providers.name: generator_name})
        model.add_constraints(
            reserve_sum <= float(generator["p_nom"]) * status - output,
            name=f"Raise-reserve-solar-headroom-{generator_name}",
        )

    shortage_penalty = shortage.sum() * network.raise_reserve_solar_vors_per_mw
    model.add_objective(
        model.objective.expression + shortage_penalty,
        overwrite=True,
        sense="min",
    )


def add_custom_reserve_constraints(
    network: pypsa.Network, snapshots: pd.DatetimeIndex
) -> None:
    """Add all custom reserve constraints currently represented in this model."""
    add_inertia_reserve_constraints(network, snapshots)
    add_regulation_lower_reserve_constraints(network, snapshots)
    add_regulation_raise_reserve_constraints(network, snapshots)
    add_raise_reserve_solar_constraints(network, snapshots)


def add_generation_nonanticipativity_constraints(
    network: pypsa.Network,
    snapshots: pd.DatetimeIndex,
    hours: float | None = None,
) -> None:
    """Tie thermal generator dispatch and commitment across stochastic samples."""
    model = network.model
    if "Generator-p" not in model.variables:
        raise RuntimeError("Generation non-anticipativity requires Generator-p.")
    if "Generator-status" not in model.variables:
        raise RuntimeError("Generation non-anticipativity requires Generator-status.")
    if not hasattr(network, "stochastic_samples"):
        raise RuntimeError("Network does not define stochastic_samples metadata.")

    snapshots = pd.DatetimeIndex(snapshots, name="snapshot")
    hours = network.generation_nonanticipative_hours if hours is None else hours
    periods = int(round(hours / snapshot_duration_hours(snapshots)))
    na_snapshots = snapshots[:periods]
    if len(na_snapshots) == 0:
        return

    gen_p = model.variables["Generator-p"]
    gen_status = model.variables["Generator-status"]
    samples = tuple(network.stochastic_samples)
    reference_sample = samples[0]

    for generator in network.generation_nonanticipative_generators:
        reference = stochastic_component(generator, reference_sample)
        for sample in samples[1:]:
            candidate = stochastic_component(generator, sample)
            model.add_constraints(
                gen_p.sel(name=candidate, snapshot=na_snapshots)
                == gen_p.sel(name=reference, snapshot=na_snapshots),
                name=f"Generation-nonanticipativity-p-{generator}-{sample}",
            )
            model.add_constraints(
                gen_status.sel(name=candidate, snapshot=na_snapshots)
                == gen_status.sel(name=reference, snapshot=na_snapshots),
                name=f"Generation-nonanticipativity-status-{generator}-{sample}",
            )


def add_storage_nonanticipativity_constraints(
    network: pypsa.Network,
    snapshots: pd.DatetimeIndex,
    hours: float | None = None,
) -> None:
    """Tie battery charge, discharge, and state of charge across stochastic samples."""
    model = network.model
    required_variables = (
        "StorageUnit-p_dispatch",
        "StorageUnit-p_store",
        "StorageUnit-state_of_charge",
    )
    missing_variables = [
        variable_name
        for variable_name in required_variables
        if variable_name not in model.variables
    ]
    if missing_variables:
        missing = ", ".join(missing_variables)
        raise RuntimeError(f"Storage non-anticipativity requires {missing}.")
    if not hasattr(network, "stochastic_samples"):
        raise RuntimeError("Network does not define stochastic_samples metadata.")

    snapshots = pd.DatetimeIndex(snapshots, name="snapshot")
    hours = getattr(network, "storage_nonanticipative_hours", None) if hours is None else hours
    if hours is None:
        hours = network.generation_nonanticipative_hours
    periods = int(round(hours / snapshot_duration_hours(snapshots)))
    na_snapshots = snapshots[:periods]
    if len(na_snapshots) == 0:
        return

    samples = tuple(network.stochastic_samples)
    reference_sample = samples[0]
    storage_units = tuple(
        getattr(network, "storage_nonanticipative_units", STORAGE_NONANTICIPATIVE_UNITS)
    )
    variable_specs = (
        ("StorageUnit-p_dispatch", "p-dispatch"),
        ("StorageUnit-p_store", "p-store"),
        ("StorageUnit-state_of_charge", "state-of-charge"),
    )

    for storage_unit in storage_units:
        reference = stochastic_component(storage_unit, reference_sample)
        for sample in samples[1:]:
            candidate = stochastic_component(storage_unit, sample)
            for variable_name, label in variable_specs:
                variable = model.variables[variable_name]
                model.add_constraints(
                    variable.sel(name=candidate, snapshot=na_snapshots)
                    == variable.sel(name=reference, snapshot=na_snapshots),
                    name=f"Storage-nonanticipativity-{label}-{storage_unit}-{sample}",
                )


def add_stochastic_dispatch_constraints(
    network: pypsa.Network, snapshots: pd.DatetimeIndex
) -> None:
    add_generation_nonanticipativity_constraints(network, snapshots)
    add_storage_nonanticipativity_constraints(network, snapshots)


def add_base_stochastic_dispatch_constraints(
    network: pypsa.Network, snapshots: pd.DatetimeIndex
) -> None:
    add_generation_nonanticipativity_constraints(network, snapshots)
    add_storage_nonanticipativity_constraints(network, snapshots)
    add_stochastic_reserve_constraints(network, snapshots)


def add_stochastic_reserve_constraints(
    network: pypsa.Network, snapshots: pd.DatetimeIndex
) -> None:
    for sample in network.stochastic_samples:
        add_stochastic_inertia_reserve_constraints(network, snapshots, sample)
        add_stochastic_regulation_lower_reserve_constraints(network, snapshots, sample)
        add_stochastic_regulation_raise_reserve_constraints(network, snapshots, sample)
        add_stochastic_raise_reserve_solar_constraints(network, snapshots, sample)


def add_stochastic_inertia_reserve_constraints(
    network: pypsa.Network, snapshots: pd.DatetimeIndex, sample: str
) -> None:
    model = network.model
    snapshots = pd.DatetimeIndex(snapshots, name="snapshot")
    gen_status = model.variables["Generator-status"]
    sample_weight = network.stochastic_sample_weights[sample]
    lm6000_01 = stochastic_component("LM6000-01", sample)
    lm6000_02 = stochastic_component("LM6000-02", sample)

    both_on = model.add_variables(
        coords={"snapshot": snapshots},
        binary=True,
        name=f"Inertia-both-lm6000-on-{sample}",
    )
    any_on = model.add_variables(
        coords={"snapshot": snapshots},
        binary=True,
        name=f"Inertia-any-lm6000-on-{sample}",
    )
    shortage = model.add_variables(
        lower=0,
        coords={"snapshot": snapshots},
        name=f"Inertia-shortage-{sample}",
    )

    status_1 = gen_status.sel(name=lm6000_01, snapshot=snapshots)
    status_2 = gen_status.sel(name=lm6000_02, snapshot=snapshots)
    model.add_constraints(both_on <= status_1, name=f"Inertia-both-upper-lm6000-01-{sample}")
    model.add_constraints(both_on <= status_2, name=f"Inertia-both-upper-lm6000-02-{sample}")
    model.add_constraints(both_on >= status_1 + status_2 - 1, name=f"Inertia-both-lower-{sample}")
    model.add_constraints(any_on >= status_1, name=f"Inertia-any-lower-lm6000-01-{sample}")
    model.add_constraints(any_on >= status_2, name=f"Inertia-any-lower-lm6000-02-{sample}")
    model.add_constraints(any_on <= status_1 + status_2, name=f"Inertia-any-upper-{sample}")

    one_on = any_on - both_on
    no_on = 1 - any_on
    requirements = inertia_condition_requirements(network)
    requirement = (
        requirements["both_lm6000_on"] * both_on
        + requirements["any_lm6000_on"] * one_on
        + requirements["no_lm6000_on"] * no_on
    )
    provision_terms = []
    for base_name in GENERATORS_AT_SOLOMON:
        component = stochastic_component(base_name, sample)
        inertia_mw_s = network.generators.at[component, "inertia_mw_s"]
        provision_terms.append(
            float(inertia_mw_s) * gen_status.sel(name=component, snapshot=snapshots)
        )
    model.add_constraints(
        sum(provision_terms) + shortage >= requirement,
        name=f"Inertia-reserve-requirement-{sample}",
    )
    model.add_objective(
        model.objective.expression
        + shortage.sum() * network.inertia_reserve_vors_per_mws * sample_weight,
        overwrite=True,
        sense="min",
    )


def add_stochastic_regulation_lower_reserve_constraints(
    network: pypsa.Network, snapshots: pd.DatetimeIndex, sample: str
) -> None:
    model = network.model
    snapshots = pd.DatetimeIndex(snapshots, name="snapshot")
    gen_status = model.variables["Generator-status"]
    gen_p = model.variables["Generator-p"]
    sample_weight = network.stochastic_sample_weights[sample]
    dim = f"regulation_lower_provider_{sample}"
    providers = pd.Index(network.regulation_lower_reserve_providers, name=dim)
    reserve = model.add_variables(
        lower=0,
        coords={"snapshot": snapshots, dim: providers},
        name=f"Regulation-lower-reserve-{sample}",
    )
    shortage = model.add_variables(
        lower=0,
        coords={"snapshot": snapshots},
        name=f"Regulation-lower-shortage-{sample}",
    )
    provision = reserve.sum(dim)
    model.add_constraints(
        provision + shortage >= network.regulation_lower_reserve_min_provision_mw,
        name=f"Regulation-lower-reserve-requirement-{sample}",
    )
    if not network.regulation_lower_reserve_contingencies:
        model.add_constraints(
            provision + shortage <= network.regulation_lower_reserve_min_provision_mw,
            name=f"Regulation-lower-reserve-cap-{sample}",
        )
    for base_name in providers:
        component = stochastic_component(base_name, sample)
        gen = network.generators.loc[component]
        status = gen_status.sel(name=component, snapshot=snapshots)
        output = gen_p.sel(name=component, snapshot=snapshots)
        min_output = float(gen["p_nom"]) * float(gen["p_min_pu"])
        model.add_constraints(
            reserve.sel({dim: base_name}) <= output - min_output * status,
            name=f"Regulation-lower-headroom-{base_name}-{sample}",
        )
    model.add_objective(
        model.objective.expression
        + shortage.sum() * network.regulation_lower_reserve_vors_per_mw * sample_weight,
        overwrite=True,
        sense="min",
    )


def add_stochastic_regulation_raise_reserve_constraints(
    network: pypsa.Network, snapshots: pd.DatetimeIndex, sample: str
) -> None:
    model = network.model
    snapshots = pd.DatetimeIndex(snapshots, name="snapshot")
    gen_status = model.variables["Generator-status"]
    gen_p = model.variables["Generator-p"]
    sample_weight = network.stochastic_sample_weights[sample]
    dim = f"regulation_raise_provider_{sample}"
    providers = pd.Index(network.regulation_raise_reserve_providers, name=dim)
    reserve = model.add_variables(
        lower=0,
        coords={"snapshot": snapshots, dim: providers},
        name=f"Regulation-raise-reserve-{sample}",
    )
    shortage = model.add_variables(
        lower=0,
        coords={"snapshot": snapshots},
        name=f"Regulation-raise-shortage-{sample}",
    )
    provision = reserve.sum(dim)
    requirement = add_exact_max_requirement(
        model,
        snapshots,
        f"Regulation-raise-requirement-{sample}",
        regulation_raise_requirement_candidates(network, snapshots, gen_p, sample),
        regulation_raise_requirement_big_m(network, sample),
    )
    model.add_constraints(
        provision + shortage == requirement,
        name=f"Regulation-raise-requirement-balance-{sample}",
    )
    model.add_constraints(
        provision <= network.regulation_raise_reserve_max_provision_mw,
        name=f"Regulation-raise-max-provision-{sample}",
    )
    for base_name in providers:
        component = stochastic_component(base_name, sample)
        gen = network.generators.loc[component]
        status = gen_status.sel(name=component, snapshot=snapshots)
        output = gen_p.sel(name=component, snapshot=snapshots)
        model.add_constraints(
            reserve.sel({dim: base_name}) <= float(gen["p_nom"]) * status - output,
            name=f"Regulation-raise-headroom-{base_name}-{sample}",
        )
    model.add_objective(
        model.objective.expression
        + shortage.sum() * network.regulation_raise_reserve_vors_per_mw * sample_weight,
        overwrite=True,
        sense="min",
    )


def add_stochastic_raise_reserve_solar_constraints(
    network: pypsa.Network, snapshots: pd.DatetimeIndex, sample: str
) -> None:
    model = network.model
    snapshots = pd.DatetimeIndex(snapshots, name="snapshot")
    gen_status = model.variables["Generator-status"]
    gen_p = model.variables["Generator-p"]
    sample_weight = network.stochastic_sample_weights[sample]
    dim = f"raise_reserve_solar_provider_{sample}"
    providers = pd.Index(network.raise_reserve_solar_providers, name=dim)
    reserve = model.add_variables(
        lower=0,
        coords={"snapshot": snapshots, dim: providers},
        name=f"Raise-reserve-solar-{sample}",
    )
    shortage = model.add_variables(
        lower=0,
        coords={"snapshot": snapshots},
        name=f"Raise-reserve-solar-shortage-{sample}",
    )
    provision = reserve.sum(dim)
    risk_factor = series_to_linopy_da(
        monthly_risk_adjustment_factor_series(
            snapshots, network.raise_reserve_solar_risk_adjustment_factors
        )
    )
    for contingency in network.raise_reserve_solar_contingencies:
        component = stochastic_component(contingency, sample)
        model.add_constraints(
            provision + shortage
            == gen_p.sel(name=component, snapshot=snapshots) / risk_factor,
            name=f"Raise-reserve-solar-dynamic-risk-{contingency}-{sample}",
        )
    for base_name in providers:
        component = stochastic_component(base_name, sample)
        gen = network.generators.loc[component]
        status = gen_status.sel(name=component, snapshot=snapshots)
        output = gen_p.sel(name=component, snapshot=snapshots)
        model.add_constraints(
            reserve.sel({dim: base_name}) <= float(gen["p_nom"]) * status - output,
            name=f"Raise-reserve-solar-headroom-{base_name}-{sample}",
        )
    model.add_objective(
        model.objective.expression
        + shortage.sum() * network.raise_reserve_solar_vors_per_mw * sample_weight,
        overwrite=True,
        sense="min",
    )


def optimize_with_default_simulation_settings(
    network: pypsa.Network,
    solver_name: str = DEFAULT_SOLVER_NAME,
    solver_log: bool = False,
    extra_functionality=None,
    model_transmission_losses: bool | None = None,
    gurobi_license_file: Path | str | None = DEFAULT_GUROBI_LICENSE_FILE,
    solver_time_limit: float | None = None,
    solver_mip_gap: float | None = None,
    solver_threads: int | None = None,
    gurobi_time_limit: float | None = None,
    gurobi_mip_gap: float | None = None,
    gurobi_threads: int | None = None,
) -> tuple[str, str]:
    set_random_seed()
    solver_name = normalize_solver_name(solver_name)
    ensure_solver_available(solver_name)
    time_limit, mip_gap, threads = resolve_solver_controls(
        solver_time_limit=solver_time_limit,
        solver_mip_gap=solver_mip_gap,
        solver_threads=solver_threads,
        gurobi_time_limit=gurobi_time_limit,
        gurobi_mip_gap=gurobi_mip_gap,
        gurobi_threads=gurobi_threads,
    )
    if solver_name == "gurobi":
        configure_gurobi_license(gurobi_license_file)

    transmission_losses = (
        network.transmission_losses_enabled_default
        if model_transmission_losses is None
        else model_transmission_losses
    )
    return network.optimize(
        snapshots=network.snapshots,
        solver_name=solver_name,
        solver_options=solver_options_for(
            solver_name,
            solver_time_limit=time_limit,
            solver_mip_gap=mip_gap,
            solver_threads=threads,
        ),
        log_to_console=solver_log,
        extra_functionality=extra_functionality,
        transmission_losses=(
            network.transmission_loss_tranches if transmission_losses else False
        ),
        linearized_unit_commitment=False,
        assign_all_duals=False,
        include_objective_constant=False,
    )


def solve_base_stochastic_dispatch_scenario(
    solver_name: str = DEFAULT_SOLVER_NAME,
    solver_log: bool = False,
    data_dir: Path | str = DEFAULT_DATA_DIR,
    nsj_sf_year: int = 2024,
    gurobi_license_file: Path | str | None = DEFAULT_GUROBI_LICENSE_FILE,
    solver_time_limit: float | None = None,
    solver_mip_gap: float | None = None,
    solver_threads: int | None = None,
    gurobi_time_limit: float | None = None,
    gurobi_mip_gap: float | None = None,
    gurobi_threads: int | None = None,
) -> tuple[pypsa.Network, tuple[str, str]]:
    solver_name = normalize_solver_name(solver_name)
    network = build_base_stochastic_dispatch_scenario(
        data_dir=data_dir,
        nsj_sf_year=nsj_sf_year,
    )
    network.solver_name = solver_name
    result = optimize_with_default_simulation_settings(
        network,
        solver_name=solver_name,
        solver_log=solver_log,
        extra_functionality=add_base_stochastic_dispatch_constraints,
        gurobi_license_file=gurobi_license_file,
        solver_time_limit=solver_time_limit,
        solver_mip_gap=solver_mip_gap,
        solver_threads=solver_threads,
        gurobi_time_limit=gurobi_time_limit,
        gurobi_mip_gap=gurobi_mip_gap,
        gurobi_threads=gurobi_threads,
    )
    return network, result


def export_thermal_generation_by_interval(
    network: pypsa.Network,
    output_path: Path | str,
    snapshots: pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    output_path = Path(output_path)
    snapshots = default_reporting_snapshots() if snapshots is None else snapshots
    rows = []
    thermal_generators = (
        tuple(f"Bergen-{i:02d}" for i in range(1, 15))
        + ("LM6000-01", "LM6000-02")
        + tuple(f"Titan130-{i:02d}" for i in range(1, 5))
    )
    samples = getattr(network, "stochastic_samples", ("",))

    for sample in samples:
        for generator in thermal_generators:
            component_name = (
                stochastic_component(generator, sample) if sample else generator
            )
            if component_name not in network.generators_t.p.columns:
                continue
            series = network.generators_t.p[component_name].reindex(snapshots)
            for snapshot, generation_mw in series.items():
                rows.append(
                    {
                        "DATETIME": snapshot,
                        "sample": sample,
                        "generator": generator,
                        "component": component_name,
                        "generation_mw": generation_mw,
                    }
                )

    df = pd.DataFrame(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    return df


def export_generation_by_interval(
    network: pypsa.Network,
    output_path: Path | str,
    snapshots: pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    output_path = Path(output_path)
    snapshots = default_reporting_snapshots() if snapshots is None else snapshots
    rows = []
    generators = (
        tuple(f"Bergen-{i:02d}" for i in range(1, 15))
        + ("LM6000-01", "LM6000-02")
        + tuple(f"Titan130-{i:02d}" for i in range(1, 5))
        + (NSJ_SF_NAME,)
    )
    samples = getattr(network, "stochastic_samples", ("",))

    for sample in samples:
        for generator in generators:
            component_name = (
                stochastic_component(generator, sample) if sample else generator
            )
            if component_name not in network.generators_t.p.columns:
                continue
            series = network.generators_t.p[component_name].reindex(snapshots)
            for snapshot, generation_mw in series.items():
                rows.append(
                    {
                        "DATETIME": snapshot,
                        "sample": sample,
                        "generator": generator,
                        "component": component_name,
                        "generation_mw": generation_mw,
                    }
                )

    df = pd.DataFrame(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    return df


def reserve_variable_to_rows(
    variable,
    reserve_name: str,
    sample: str,
    snapshots: pd.DatetimeIndex,
    provider_dim: str | None = None,
) -> list[dict]:
    rows = []
    solution = variable.solution
    if provider_dim is None:
        series = solution.sel(snapshot=snapshots).to_series()
        for snapshot, value in series.items():
            rows.append(
                {
                    "DATETIME": snapshot,
                    "sample": sample,
                    "reserve": reserve_name,
                    "provider": "",
                    "value_mw": value,
                    "quantity": "shortage",
                }
            )
        return rows

    frame = solution.sel(snapshot=snapshots).to_pandas()
    for snapshot, values in frame.iterrows():
        for provider, value in values.items():
            rows.append(
                {
                    "DATETIME": snapshot,
                    "sample": sample,
                    "reserve": reserve_name,
                    "provider": provider,
                    "value_mw": value,
                    "quantity": "provision",
                }
            )
    return rows


def generator_status_solution_series(
    network: pypsa.Network,
    component_name: str,
    snapshots: pd.DatetimeIndex,
) -> pd.Series:
    variables = getattr(getattr(network, "model", None), "variables", {})
    if "Generator-status" in variables:
        return (
            variables["Generator-status"]
            .solution.sel(name=component_name, snapshot=snapshots)
            .to_series()
            .astype(float)
        )

    status = getattr(network.generators_t, "status", pd.DataFrame())
    if component_name in status.columns:
        return status[component_name].reindex(snapshots).astype(float)

    raise RuntimeError(f"No solved Generator-status values found for {component_name}.")


def generator_dispatch_solution_series(
    network: pypsa.Network,
    component_name: str,
    snapshots: pd.DatetimeIndex,
) -> pd.Series:
    if component_name in network.generators_t.p.columns:
        return network.generators_t.p[component_name].reindex(snapshots).astype(float)

    variables = getattr(getattr(network, "model", None), "variables", {})
    if "Generator-p" in variables:
        return (
            variables["Generator-p"]
            .solution.sel(name=component_name, snapshot=snapshots)
            .to_series()
            .astype(float)
        )

    raise RuntimeError(f"No solved Generator-p values found for {component_name}.")


def reserve_requirement_to_rows(
    reserve_name: str,
    sample: str,
    requirement: pd.Series,
) -> list[dict]:
    rows = []
    for snapshot, value in requirement.items():
        rows.append(
            {
                "DATETIME": snapshot,
                "sample": sample,
                "reserve": reserve_name,
                "provider": "",
                "value_mw": max(0.0, float(value)),
                "quantity": "requirement",
            }
        )
    return rows


def inertia_reserve_to_rows(
    network: pypsa.Network,
    sample: str,
    snapshots: pd.DatetimeIndex,
) -> list[dict]:
    variables = network.model.variables
    variable_name = f"Inertia-shortage-{sample}" if sample else "Inertia-shortage"
    if variable_name not in variables:
        return []

    lm6000_01 = stochastic_component("LM6000-01", sample) if sample else "LM6000-01"
    lm6000_02 = stochastic_component("LM6000-02", sample) if sample else "LM6000-02"
    lm6000_01_status = generator_status_solution_series(network, lm6000_01, snapshots)
    lm6000_02_status = generator_status_solution_series(network, lm6000_02, snapshots)
    shortage = variables[variable_name].solution.sel(snapshot=snapshots).to_series()

    rows = []
    for snapshot in snapshots:
        _, requirement = inertia_requirement_mws(
            lm6000_01_status.at[snapshot] >= 0.5,
            lm6000_02_status.at[snapshot] >= 0.5,
            network,
        )
        shortage_value = max(0.0, float(shortage.at[snapshot]))
        provision = max(0.0, requirement - shortage_value)
        for quantity, value in (
            ("requirement", requirement),
            ("provision", provision),
            ("shortage", shortage_value),
        ):
            rows.append(
                {
                    "DATETIME": snapshot,
                    "sample": sample,
                    "reserve": "Inertia",
                    "provider": "",
                    "value_mw": value,
                    "quantity": quantity,
                }
            )
    return rows


def regulation_raise_requirement_to_rows(
    network: pypsa.Network,
    sample: str,
    snapshots: pd.DatetimeIndex,
) -> list[dict]:
    requirements = [
        pd.Series(
            network.regulation_raise_reserve_min_provision_mw,
            index=snapshots,
        )
    ]
    if network.regulation_raise_reserve_dynamic_risk:
        for contingency in network.regulation_raise_reserve_contingencies:
            component = stochastic_component(contingency, sample) if sample else contingency
            requirements.append(
                generator_dispatch_solution_series(network, component, snapshots)
            )
    requirement = pd.concat(requirements, axis=1).max(axis=1)
    return reserve_requirement_to_rows("Regulation Raise", sample, requirement)


def raise_reserve_solar_requirement_to_rows(
    network: pypsa.Network,
    sample: str,
    snapshots: pd.DatetimeIndex,
) -> list[dict]:
    if not network.raise_reserve_solar_dynamic_risk:
        return []

    risk_factor = monthly_risk_adjustment_factor_series(
        snapshots, network.raise_reserve_solar_risk_adjustment_factors
    )
    requirements = []
    for contingency in network.raise_reserve_solar_contingencies:
        component = stochastic_component(contingency, sample) if sample else contingency
        requirements.append(
            generator_dispatch_solution_series(network, component, snapshots) / risk_factor
        )
    if not requirements:
        return []

    requirement = pd.concat(requirements, axis=1).max(axis=1)
    return reserve_requirement_to_rows("Raise Reserve Solar", sample, requirement)


def export_reserves_by_interval(
    network: pypsa.Network,
    output_path: Path | str,
    snapshots: pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    output_path = Path(output_path)
    snapshots = default_reporting_snapshots() if snapshots is None else snapshots
    rows = []
    variables = network.model.variables
    reserve_specs = (
        (
            "Regulation Lower",
            "Regulation-lower-reserve-{sample}",
            "regulation_lower_provider_{sample}",
        ),
        ("Regulation Lower", "Regulation-lower-shortage-{sample}", None),
        (
            "Regulation Raise",
            "Regulation-raise-reserve-{sample}",
            "regulation_raise_provider_{sample}",
        ),
        ("Regulation Raise", "Regulation-raise-shortage-{sample}", None),
        (
            "Raise Reserve Solar",
            "Raise-reserve-solar-{sample}",
            "raise_reserve_solar_provider_{sample}",
        ),
        ("Raise Reserve Solar", "Raise-reserve-solar-shortage-{sample}", None),
    )
    for sample in network.stochastic_samples:
        rows.extend(inertia_reserve_to_rows(network, sample, snapshots))
        rows.extend(regulation_raise_requirement_to_rows(network, sample, snapshots))
        rows.extend(raise_reserve_solar_requirement_to_rows(network, sample, snapshots))
        for reserve_name, variable_template, dim_template in reserve_specs:
            variable_name = variable_template.format(sample=sample)
            if variable_name not in variables:
                continue
            provider_dim = (
                dim_template.format(sample=sample) if dim_template is not None else None
            )
            rows.extend(
                reserve_variable_to_rows(
                    variables[variable_name],
                    reserve_name,
                    sample,
                    snapshots,
                    provider_dim,
                )
            )

    df = pd.DataFrame(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    return df


def export_unserved_energy_by_interval(
    network: pypsa.Network,
    output_path: Path | str,
    snapshots: pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    output_path = Path(output_path)
    snapshots = default_reporting_snapshots() if snapshots is None else snapshots
    rows = []
    samples = getattr(network, "stochastic_samples", ("",))
    for sample in samples:
        for bus in DEMAND_BUSES:
            generator_name = f"Unserved Energy {bus}"
            component_name = (
                stochastic_component(generator_name, sample)
                if sample
                else generator_name
            )
            if component_name not in network.generators_t.p.columns:
                continue
            series = network.generators_t.p[component_name].reindex(snapshots)
            for snapshot, unserved_mw in series.items():
                rows.append(
                    {
                        "DATETIME": snapshot,
                        "sample": sample,
                        "bus": bus,
                        "component": component_name,
                        "unserved_mw": unserved_mw,
                    }
                )
    df = pd.DataFrame(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    return df


def export_load_by_bus_by_interval(
    network: pypsa.Network,
    output_path: Path | str,
    snapshots: pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    output_path = Path(output_path)
    snapshots = default_reporting_snapshots() if snapshots is None else snapshots
    rows = []
    samples = getattr(network, "stochastic_samples", ("",))
    for sample in samples:
        for bus in DEMAND_BUSES:
            load_name = f"{bus} load"
            component_name = (
                stochastic_component(load_name, sample) if sample else load_name
            )
            if component_name not in network.loads_t.p_set.columns:
                continue
            series = network.loads_t.p_set[component_name].reindex(snapshots)
            for snapshot, load_mw in series.items():
                rows.append(
                    {
                        "DATETIME": snapshot,
                        "sample": sample,
                        "bus": bus,
                        "component": component_name,
                        "load_mw": load_mw,
                    }
                )
    df = pd.DataFrame(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    return df


def export_base_stochastic_solution(
    network: pypsa.Network,
    output_dir: Path | str | None = None,
    include_network_netcdf: bool = True,
    result: tuple[str, str] | None = None,
) -> dict[str, Path]:
    if output_dir is None:
        output_dir = default_output_dir_for_solver(
            getattr(network, "solver_name", DEFAULT_SOLVER_NAME)
        )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    outputs = {
        "simulation_settings": output_dir / "simulation_settings.csv",
        "scenario_summary": output_dir / "base_stochastic_scenario_summary.csv",
        "thermal_generation": output_dir / "thermal_generation_by_interval.csv",
        "generation": output_dir / "generation_by_interval.csv",
        "reserves": output_dir / "reserves_by_interval.csv",
        "unserved_energy": output_dir / "unserved_energy_by_interval.csv",
        "load": output_dir / "load_by_bus_by_interval.csv",
    }
    simulation_settings_summary(network).to_csv(outputs["simulation_settings"])
    base_stochastic_scenario_summary(network).to_csv(outputs["scenario_summary"])
    export_thermal_generation_by_interval(network, outputs["thermal_generation"])
    export_generation_by_interval(network, outputs["generation"])
    export_reserves_by_interval(network, outputs["reserves"])
    export_unserved_energy_by_interval(network, outputs["unserved_energy"])
    export_load_by_bus_by_interval(network, outputs["load"])

    solver_model = getattr(getattr(network, "model", None), "solver_model", None)
    if result is not None or solver_model is not None:
        outputs["solver_summary"] = output_dir / "solver_summary.csv"
        rows = [("solver_name", getattr(network, "solver_name", ""))]
        if result is not None:
            status, condition = result
            rows.extend(
                [
                    ("pypsa_status", status),
                    ("termination_condition", condition),
                ]
            )
        if hasattr(network, "objective"):
            rows.append(("objective", float(network.objective)))
        if solver_model is not None:
            for label, attr in (
                ("gurobi_status", "Status"),
                ("gurobi_runtime_seconds", "Runtime"),
                ("gurobi_objective", "ObjVal"),
                ("gurobi_best_bound", "ObjBound"),
                ("gurobi_mip_gap", "MIPGap"),
                ("gurobi_node_count", "NodeCount"),
            ):
                try:
                    rows.append((label, getattr(solver_model, attr)))
                except Exception:
                    continue
        pd.DataFrame(rows, columns=["metric", "value"]).to_csv(
            outputs["solver_summary"],
            index=False,
        )

    if include_network_netcdf:
        outputs["network_solution"] = output_dir / "network_solution.nc"
        network.export_to_netcdf(outputs["network_solution"])

    return outputs


def snapshot_duration_hours(snapshots: pd.DatetimeIndex) -> float:
    if len(snapshots) < 2:
        return 0.5
    return (snapshots[1] - snapshots[0]).total_seconds() / 3600.0


def series_to_linopy_da(series: pd.Series) -> "xr.DataArray":
    import xarray as xr

    return xr.DataArray(
        series.to_numpy(dtype=float),
        dims=("snapshot",),
        coords={"snapshot": series.index},
    )


def monthly_risk_adjustment_factor_series(
    snapshots: pd.DatetimeIndex, factors_by_month: dict[int, float]
) -> pd.Series:
    missing_months = sorted(set(snapshots.month) - set(factors_by_month))
    if missing_months:
        raise KeyError(f"Missing risk adjustment factors for months: {missing_months}")
    return pd.Series(
        [factors_by_month[int(month)] for month in snapshots.month],
        index=snapshots,
        dtype=float,
    )


def read_load_profiles(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    required_columns = {"DateTime", *DEMAND_BUSES}
    missing = required_columns - set(df.columns)
    if missing:
        raise KeyError(f"{path} missing columns: {sorted(missing)}")

    parsed = df.copy()
    parsed["DateTime"] = pd.to_datetime(parsed["DateTime"], errors="coerce")
    if parsed["DateTime"].isna().any():
        bad_rows = df.loc[parsed["DateTime"].isna(), "DateTime"].head(10).tolist()
        raise ValueError(f"{path} contains invalid DateTime values: {bad_rows}")

    profiles = parsed.loc[:, ["DateTime", *DEMAND_BUSES]].set_index("DateTime")
    profiles.index.name = "snapshot"
    return profiles.sort_index().astype(float)


def average_heat_rate_gj_per_mwh(properties: dict[str, float]) -> float:
    p_nom = properties["max_capacity_mw"]
    heat_input_gj_per_h = (
        properties["heat_rate_base_gj_per_h"]
        + properties["heat_rate_incr_gj_per_mwh"] * p_nom
        + properties["heat_rate_incr2_gj_per_mwh2"] * p_nom**2
        + properties["heat_rate_incr3_gj_per_mwh3"] * p_nom**3
    )
    return heat_input_gj_per_h / p_nom


def thermal_marginal_cost(properties: dict[str, float]) -> float:
    fuel_cost = average_heat_rate_gj_per_mwh(properties) * GAS_PRICE_PER_GJ
    return fuel_cost + properties["vom_charge_per_mwh"]


def line_summary(network: pypsa.Network) -> pd.DataFrame:
    columns = [
        "bus0",
        "bus1",
        "s_nom",
        "r",
        "x",
        "active",
        "loss_base",
        "loss_incr",
        "loss_incr2",
        "commission_date",
    ]
    return network.lines.loc[:, columns].copy()


def region_summary(network: pypsa.Network) -> pd.DataFrame:
    bus_regions = network.buses["region"]
    rows = []
    for region, buses in bus_regions.groupby(bus_regions).groups.items():
        bus_index = pd.Index(buses)
        rows.append(
            {
                "region": region,
                "buses": len(bus_index),
                "generators": int(network.generators.bus.isin(bus_index).sum()),
                "storage_units": int(network.storage_units.bus.isin(bus_index).sum()),
                "loads": int(network.loads.bus.isin(bus_index).sum()),
            }
        )
    return pd.DataFrame(rows).set_index("region").sort_index()


def generator_property_summary(network: pypsa.Network) -> pd.DataFrame:
    columns = [
        "bus",
        "carrier",
        "p_nom",
        "p_min_pu",
        "marginal_cost",
        "fuel",
        "fuel_price_per_gj",
        "stand_by_cost",
        "start_up_cost",
        "committable",
        "heat_rate_base_gj_per_h",
        "heat_rate_incr_gj_per_mwh",
        "heat_rate_incr2_gj_per_mwh2",
        "heat_rate_incr3_gj_per_mwh3",
        "units",
        "unit_max_capacity_mw",
        "commission_date",
        "active_rating_sample",
    ]
    return network.generators.loc[:, columns].copy()


def storage_property_summary(network: pypsa.Network) -> pd.DataFrame:
    columns = [
        "bus",
        "carrier",
        "p_nom",
        "max_hours",
        "efficiency_store",
        "efficiency_dispatch",
        "enabled",
        "installed_p_nom",
        "installed_e_nom",
        "plexos_max_power_mw",
        "max_up_time_h",
    ]
    return network.storage_units.loc[:, columns].copy()


def simulation_settings_summary(network: pypsa.Network) -> pd.DataFrame:
    rows = [
        ("horizon_begins", network.simulation_start),
        ("random_seed", getattr(network, "random_seed", RANDOM_SEED)),
        ("simulation_days", network.simulation_days),
        ("step_days", network.simulation_step_days),
        ("additional_lookahead_days", network.simulation_lookahead_days),
        ("interval_minutes", network.simulation_interval_minutes),
        ("full_chronology", network.simulation_full_chronology),
        ("single_slack_bus", network.single_slack_bus),
        ("allow_unserved_energy", network.allow_unserved_energy),
        ("voll", network.value_of_lost_load),
        ("unit_commitment_optimality", network.unit_commitment_optimality),
        ("opf_requested_method", network.opf_requested_method),
        ("opf_pypsa_method", network.opf_pypsa_method),
        ("transmission_losses_default", network.transmission_losses_enabled_default),
        ("transmission_loss_tranches", network.transmission_loss_tranches),
        ("optimization_snapshot_count", len(network.snapshots)),
        ("reporting_snapshot_count", network.reporting_snapshot_count),
        (
            "snapshot_weighting_objective_hours",
            float(network.snapshot_weightings["objective"].iloc[0]),
        ),
        (
            "snapshot_weighting_generators_hours",
            float(network.snapshot_weightings["generators"].iloc[0]),
        ),
    ]
    return pd.DataFrame(rows, columns=["setting", "value"]).set_index("setting")


def base_stochastic_scenario_summary(network: pypsa.Network) -> pd.DataFrame:
    rows = [
        ("scenario_name", getattr(network, "scenario_name", "")),
        ("samples", ", ".join(network.stochastic_samples)),
        ("sample_weight", next(iter(network.stochastic_sample_weights.values()))),
        ("nonanticipative_hours", network.generation_nonanticipative_hours),
        (
            "nonanticipative_generators",
            len(network.generation_nonanticipative_generators),
        ),
        ("nonanticipative_storage_hours", network.storage_nonanticipative_hours),
        (
            "nonanticipative_storage_units",
            len(network.storage_nonanticipative_units),
        ),
        ("buses", len(network.buses)),
        ("generators", len(network.generators)),
        ("storage_units", len(network.storage_units)),
        ("lines", len(network.lines)),
        ("loads", len(network.loads)),
    ]
    return pd.DataFrame(rows, columns=["setting", "value"]).set_index("setting")


def load_profile_summary(network: pypsa.Network) -> pd.DataFrame:
    source_profiles = network.load_profiles
    active_profiles = network.loads_t.p_set
    rows = []
    for bus in DEMAND_BUSES:
        load_name = f"{bus} load"
        source = source_profiles[bus]
        active = active_profiles[load_name]
        rows.append(
            {
                "bus": bus,
                "load": load_name,
                "source_start": source.index.min(),
                "source_end": source.index.max(),
                "source_rows": len(source),
                "active_sum_mwh_like": active.sum(),
                "active_max_mw": active.max(),
                "snapshots_filled_from_nearest_available": int(
                    active_profiles.index.difference(source_profiles.index).size
                ),
            }
        )
    return pd.DataFrame(rows).set_index("load")


def ib_npi_timeslice_summary(network: pypsa.Network) -> pd.DataFrame:
    series = network.loads_t.p_set["IB NPI load"]
    rows = []
    for timeslice, expected_mw in IB_NPI_TIMESLICE_LOAD_MW.items():
        mask = timeslice_mask(series.index, timeslice)
        rows.append(
            {
                "timeslice": timeslice,
                "expected_mw": expected_mw,
                "min_mw": series.loc[mask].min(),
                "max_mw": series.loc[mask].max(),
                "snapshots": int(mask.sum()),
            }
        )
    return pd.DataFrame(rows).set_index("timeslice")


def inertia_reserve_summary(network: pypsa.Network) -> pd.DataFrame:
    rows = []
    for condition in network.inertia_reserve_conditions:
        rows.append(
            {
                "reserve": network.inertia_reserve_name,
                "condition": condition["condition"],
                "description": condition["description"],
                "min_provision_mws": condition["min_provision_mws"],
                "vors_per_mws": network.inertia_reserve_vors_per_mws,
            }
        )
    return pd.DataFrame(rows).set_index("condition")


def regulation_lower_reserve_summary(network: pypsa.Network) -> pd.DataFrame:
    rows = []
    for provider in network.regulation_lower_reserve_providers:
        rows.append(
            {
                "reserve": network.regulation_lower_reserve_name,
                "provider": provider,
                "is_contingency": provider
                in network.regulation_lower_reserve_contingencies,
                "dynamic_risk": network.regulation_lower_reserve_dynamic_risk,
                "min_provision_mw": network.regulation_lower_reserve_min_provision_mw,
                "vors_per_mw": network.regulation_lower_reserve_vors_per_mw,
            }
        )
    return pd.DataFrame(rows).set_index("provider")


def regulation_raise_reserve_summary(network: pypsa.Network) -> pd.DataFrame:
    rows = []
    for provider in network.regulation_raise_reserve_providers:
        rows.append(
            {
                "reserve": network.regulation_raise_reserve_name,
                "provider": provider,
                "is_contingency": provider
                in network.regulation_raise_reserve_contingencies,
                "dynamic_risk": network.regulation_raise_reserve_dynamic_risk,
                "min_provision_mw": network.regulation_raise_reserve_min_provision_mw,
                "max_provision_mw": network.regulation_raise_reserve_max_provision_mw,
                "vors_per_mw": network.regulation_raise_reserve_vors_per_mw,
            }
        )
    return pd.DataFrame(rows).set_index("provider")


def raise_reserve_solar_summary(network: pypsa.Network) -> pd.DataFrame:
    rows = []
    for provider in network.raise_reserve_solar_providers:
        rows.append(
            {
                "reserve": network.raise_reserve_solar_name,
                "provider": provider,
                "dynamic_risk": network.raise_reserve_solar_dynamic_risk,
                "contingencies": ", ".join(network.raise_reserve_solar_contingencies),
                "vors_per_mw": network.raise_reserve_solar_vors_per_mw,
            }
        )
    return pd.DataFrame(rows).set_index("provider")


def raise_reserve_solar_risk_factor_summary(network: pypsa.Network) -> pd.DataFrame:
    rows = [
        {"timeslice": f"M{month}", "month": month, "risk_adjustment_factor": factor}
        for month, factor in sorted(
            network.raise_reserve_solar_risk_adjustment_factors.items()
        )
    ]
    return pd.DataFrame(rows).set_index("timeslice")


def nsj_sf_profile_summary(network: pypsa.Network) -> pd.DataFrame:
    profiles = network.nsj_sf_rating_profiles
    active_sample = network.nsj_sf_active_sample
    summary = profiles.describe().loc[["min", "mean", "max"]].T
    summary["active"] = summary.index == active_sample
    summary["pre_commission_nonzero"] = (
        profiles.loc[profiles.index < NSJ_SF_COMMISSION_DATE].abs().sum(axis=0) > 0
    )
    return summary


def assert_expected_topology(network: pypsa.Network) -> None:
    expected_counts = {
        "buses": 12,
        "lines": 11,
        "generators": 29,
        "storage_units": 2,
        "loads": 8,
    }
    actual_counts = {
        "buses": len(network.buses),
        "lines": len(network.lines),
        "generators": len(network.generators),
        "storage_units": len(network.storage_units),
        "loads": len(network.loads),
    }
    if actual_counts != expected_counts:
        raise AssertionError(
            f"Unexpected topology counts: {actual_counts}; "
            f"expected {expected_counts}"
        )

    missing_line_buses = sorted(
        {
            bus
            for _, line in network.lines.iterrows()
            for bus in (line.bus0, line.bus1)
            if bus not in network.buses.index
        }
    )
    if missing_line_buses:
        raise AssertionError(f"Lines reference missing buses: {missing_line_buses}")

    for line_name, line_overrides in LINE_PROPERTIES.items():
        expected_line = LINE_DEFAULT_PROPERTIES | line_overrides
        line = network.lines.loc[line_name]
        if line["s_nom"] != expected_line["max_flow_mw"]:
            raise AssertionError(f"{line_name} Max Flow does not match source data.")
        for property_name in (
            "active",
            "loss_base",
            "loss_incr",
            "loss_incr2",
            "commission_date",
        ):
            if line[property_name] != expected_line[property_name]:
                raise AssertionError(
                    f"{line_name} {property_name} does not match source data."
                )

    if network.buses["region"].isna().any():
        missing_regions = network.buses.index[network.buses["region"].isna()].tolist()
        raise AssertionError(f"Buses missing region metadata: {missing_regions}")
    if network.buses["is_slack_bus"].sum() != 1:
        raise AssertionError("Exactly one slack bus should be marked.")
    if not bool(network.buses.loc[SINGLE_SLACK_BUS, "is_slack_bus"]):
        raise AssertionError(f"{SINGLE_SLACK_BUS} should be marked as the slack bus.")

    bergen = network.generators.loc[network.generators.index.str.startswith("Bergen-")]
    if len(bergen) != 14:
        raise AssertionError(f"Expected 14 Bergen generators, found {len(bergen)}")
    if not (bergen["p_nom"] == BERGEN_PROPERTIES["max_capacity_mw"]).all():
        raise AssertionError("At least one Bergen has an unexpected Max Capacity.")
    expected_p_min_pu = (
        BERGEN_PROPERTIES["min_stable_level_mw"]
        / BERGEN_PROPERTIES["max_capacity_mw"]
    )
    if not (bergen["p_min_pu"] == expected_p_min_pu).all():
        raise AssertionError("At least one Bergen has an unexpected Min Stable Level.")
    if not (bergen["fuel"] == "gas").all():
        raise AssertionError("At least one Bergen is missing gas fuel metadata.")
    if not (
        bergen["marginal_cost"] == thermal_marginal_cost(BERGEN_PROPERTIES)
    ).all():
        raise AssertionError("At least one Bergen has an unexpected marginal cost.")

    lm6000 = network.generators.loc[network.generators.index.str.startswith("LM6000-")]
    if len(lm6000) != 2:
        raise AssertionError(f"Expected 2 LM6000 generators, found {len(lm6000)}")
    if not (lm6000["p_nom"] == LM6000_PROPERTIES["max_capacity_mw"]).all():
        raise AssertionError("At least one LM6000 has an unexpected Max Capacity.")
    expected_lm6000_p_min_pu = (
        LM6000_PROPERTIES["min_stable_level_mw"]
        / LM6000_PROPERTIES["max_capacity_mw"]
    )
    if not (lm6000["p_min_pu"] == expected_lm6000_p_min_pu).all():
        raise AssertionError("At least one LM6000 has an unexpected Min Stable Level.")
    if not (lm6000["fuel"] == "gas").all():
        raise AssertionError("At least one LM6000 is missing gas fuel metadata.")
    if not (
        lm6000["marginal_cost"] == thermal_marginal_cost(LM6000_PROPERTIES)
    ).all():
        raise AssertionError("At least one LM6000 has an unexpected marginal cost.")

    titan130 = network.generators.loc[
        network.generators.index.str.startswith("Titan130-")
    ]
    if len(titan130) != 4:
        raise AssertionError(f"Expected 4 Titan130 generators, found {len(titan130)}")
    if not (titan130["p_nom"] == TITAN130_PROPERTIES["max_capacity_mw"]).all():
        raise AssertionError("At least one Titan130 has an unexpected Max Capacity.")
    expected_titan130_p_min_pu = (
        TITAN130_PROPERTIES["min_stable_level_mw"]
        / TITAN130_PROPERTIES["max_capacity_mw"]
    )
    if not (titan130["p_min_pu"] == expected_titan130_p_min_pu).all():
        raise AssertionError("At least one Titan130 has an unexpected Min Stable Level.")
    if not (titan130["fuel"] == "gas").all():
        raise AssertionError("At least one Titan130 is missing gas fuel metadata.")
    if not (
        titan130["marginal_cost"] == thermal_marginal_cost(TITAN130_PROPERTIES)
    ).all():
        raise AssertionError("At least one Titan130 has an unexpected marginal cost.")

    nss_bess = network.storage_units.loc["NSS BESS"]
    if bool(nss_bess["enabled"]):
        raise AssertionError("NSS BESS should be disabled by default.")
    if nss_bess["p_nom"] != 0.0:
        raise AssertionError("NSS BESS should have p_nom=0 while disabled.")
    if nss_bess["installed_p_nom"] != NSS_BESS_PROPERTIES["max_power_mw"]:
        raise AssertionError("NSS BESS installed power does not match source data.")
    if nss_bess["installed_e_nom"] != NSS_BESS_PROPERTIES["capacity_mwh"]:
        raise AssertionError("NSS BESS installed energy does not match source data.")

    sol_bess = network.storage_units.loc["SOL BESS"]
    if bool(sol_bess["enabled"]):
        raise AssertionError("SOL BESS should be disabled by default.")
    if sol_bess["p_nom"] != 0.0:
        raise AssertionError("SOL BESS should have p_nom=0 while disabled.")
    if sol_bess["installed_p_nom"] != SOL_BESS_PROPERTIES["max_power_mw"]:
        raise AssertionError("SOL BESS installed power does not match source data.")
    if sol_bess["installed_e_nom"] != SOL_BESS_PROPERTIES["capacity_mwh"]:
        raise AssertionError("SOL BESS installed energy does not match source data.")

    nsj_sf = network.generators.loc[NSJ_SF_NAME]
    expected_nsj_capacity = (
        NSJ_SF_PROPERTIES["units"] * NSJ_SF_PROPERTIES["unit_max_capacity_mw"]
    )
    if nsj_sf["p_nom"] != expected_nsj_capacity:
        raise AssertionError("North Star Junction SF capacity does not match source data.")
    if nsj_sf["marginal_cost"] != NSJ_SF_PROPERTIES["vom_charge_per_mwh"]:
        raise AssertionError("North Star Junction SF VO&M does not match source data.")
    if set(network.nsj_sf_rating_profiles.columns) != set(NSJ_SF_SAMPLE_COLUMNS):
        raise AssertionError("North Star Junction SF rating samples are incomplete.")
    pre_commission = network.nsj_sf_rating_profiles.loc[
        network.nsj_sf_rating_profiles.index < NSJ_SF_COMMISSION_DATE
    ]
    if pre_commission.abs().sum().sum() != 0.0:
        raise AssertionError(
            "North Star Junction SF has non-zero output before commissioning."
        )

    inertia_requirements = inertia_condition_requirements(network)
    expected_inertia_cases = {
        (True, True): (
            "both_lm6000_on",
            inertia_requirements["both_lm6000_on"],
        ),
        (True, False): (
            "any_lm6000_on",
            inertia_requirements["any_lm6000_on"],
        ),
        (False, True): (
            "any_lm6000_on",
            inertia_requirements["any_lm6000_on"],
        ),
        (False, False): (
            "no_lm6000_on",
            inertia_requirements["no_lm6000_on"],
        ),
    }
    for statuses, expected in expected_inertia_cases.items():
        if inertia_requirement_mws(*statuses) != expected:
            raise AssertionError(f"Inertia reserve case {statuses} is incorrect.")
    if network.inertia_reserve_vors_per_mws != INERTIA_RESERVE_VORS_PER_MWS:
        raise AssertionError("Inertia reserve VoRS does not match source data.")

    if network.regulation_lower_reserve_min_provision_mw != (
        REGULATION_LOWER_RESERVE_MIN_PROVISION_MW
    ):
        raise AssertionError("Regulation lower reserve requirement is incorrect.")
    if network.regulation_lower_reserve_vors_per_mw != (
        REGULATION_LOWER_RESERVE_VORS_PER_MW
    ):
        raise AssertionError("Regulation lower reserve VoRS is incorrect.")
    if network.regulation_lower_reserve_dynamic_risk != (
        REGULATION_LOWER_RESERVE_DYNAMIC_RISK
    ):
        raise AssertionError("Regulation lower dynamic risk flag is incorrect.")
    if set(network.regulation_lower_reserve_contingencies) != set(
        REGULATION_LOWER_RESERVE_CONTINGENCIES
    ):
        raise AssertionError("Regulation lower contingencies are incorrect.")
    if set(network.regulation_lower_reserve_providers) != set(
        REGULATION_LOWER_RESERVE_PROVIDERS
    ):
        raise AssertionError("Regulation lower reserve providers are incorrect.")
    if any(provider.startswith("LM6000-") for provider in network.regulation_lower_reserve_providers):
        raise AssertionError("LM6000s should not provide Regulation Lower reserve.")

    if network.regulation_raise_reserve_min_provision_mw != (
        REGULATION_RAISE_RESERVE_MIN_PROVISION_MW
    ):
        raise AssertionError("Regulation raise reserve min provision is incorrect.")
    if network.regulation_raise_reserve_max_provision_mw != (
        REGULATION_RAISE_RESERVE_MAX_PROVISION_MW
    ):
        raise AssertionError("Regulation raise reserve max provision is incorrect.")
    if network.regulation_raise_reserve_vors_per_mw != (
        REGULATION_RAISE_RESERVE_VORS_PER_MW
    ):
        raise AssertionError("Regulation raise reserve VoRS is incorrect.")
    if network.regulation_raise_reserve_dynamic_risk != (
        REGULATION_RAISE_RESERVE_DYNAMIC_RISK
    ):
        raise AssertionError("Regulation raise dynamic risk flag is incorrect.")
    if set(network.regulation_raise_reserve_contingencies) != set(
        REGULATION_RAISE_RESERVE_CONTINGENCIES
    ):
        raise AssertionError("Regulation raise contingencies are incorrect.")
    if set(network.regulation_raise_reserve_providers) != set(
        REGULATION_RAISE_RESERVE_PROVIDERS
    ):
        raise AssertionError("Regulation raise reserve providers are incorrect.")

    if network.raise_reserve_solar_dynamic_risk != RAISE_RESERVE_SOLAR_DYNAMIC_RISK:
        raise AssertionError("Raise Reserve Solar dynamic risk flag is incorrect.")
    if network.raise_reserve_solar_vors_per_mw != RAISE_RESERVE_SOLAR_VORS_PER_MW:
        raise AssertionError("Raise Reserve Solar VoRS is incorrect.")
    if set(network.raise_reserve_solar_contingencies) != set(
        RAISE_RESERVE_SOLAR_CONTINGENCIES
    ):
        raise AssertionError("Raise Reserve Solar contingencies are incorrect.")
    if set(network.raise_reserve_solar_providers) != set(
        RAISE_RESERVE_SOLAR_PROVIDERS
    ):
        raise AssertionError("Raise Reserve Solar providers are incorrect.")
    if network.raise_reserve_solar_risk_adjustment_factors != (
        RAISE_RESERVE_SOLAR_RISK_ADJUSTMENT_FACTORS
    ):
        raise AssertionError("Raise Reserve Solar risk factors are incorrect.")

    if set(network.load_profiles.columns) != set(DEMAND_BUSES):
        raise AssertionError("Load profile columns do not match demand buses.")
    for bus in DEMAND_BUSES:
        load_name = f"{bus} load"
        if load_name not in network.loads.index:
            raise AssertionError(f"Missing PyPSA Load for bus {bus}.")
        if network.loads.loc[load_name, "bus"] != bus:
            raise AssertionError(f"Load {load_name} is attached to the wrong bus.")
        source = network.load_profiles[bus]
        active_full = network.loads_t.p_set[load_name]
        if active_full.isna().any():
            raise AssertionError(f"Load profile for {bus} contains NaN values.")
        overlap = source.index.intersection(network.snapshots)
        if len(overlap) > 0:
            active = active_full.reindex(overlap)
            if bus == "IB NPI":
                expected = apply_timeslice_values(
                    source.reindex(overlap), IB_NPI_TIMESLICE_LOAD_MW
                )
                if not active.equals(expected):
                    raise AssertionError("IB NPI timeslice load override is incorrect.")
            elif not active.equals(source.reindex(overlap)):
                raise AssertionError(f"Load profile for {bus} does not match source data.")

    if ALLOW_UNSERVED_ENERGY:
        for bus in DEMAND_BUSES:
            generator_name = f"Unserved Energy {bus}"
            if generator_name not in network.generators.index:
                raise AssertionError(f"Missing unserved-energy generator for {bus}.")
            if network.generators.loc[generator_name, "marginal_cost"] != VALUE_OF_LOST_LOAD:
                raise AssertionError(f"Unserved-energy VoLL is incorrect for {bus}.")


def assert_base_stochastic_dispatch_scenario(network: pypsa.Network) -> None:
    if tuple(network.stochastic_samples) != STOCHASTIC_SOLAR_SAMPLES:
        raise AssertionError("Base scenario should use all five solar samples.")
    if len(set(network.stochastic_sample_weights.values())) != 1:
        raise AssertionError("Base scenario sample weights should be equal.")
    if sum(network.stochastic_sample_weights.values()) != 1.0:
        raise AssertionError("Base scenario sample weights should sum to 1.")
    if network.generation_nonanticipative_hours != GENERATION_NONANTICIPATIVE_HOURS:
        raise AssertionError("Base scenario non-anticipativity horizon is incorrect.")
    if network.storage_nonanticipative_hours != GENERATION_NONANTICIPATIVE_HOURS:
        raise AssertionError(
            "Base scenario storage non-anticipativity horizon is incorrect."
        )
    if tuple(network.storage_nonanticipative_units) != STORAGE_NONANTICIPATIVE_UNITS:
        raise AssertionError("Base scenario storage non-anticipativity units are incorrect.")
    expected_generators = len(GENERATORS_AT_SOLOMON) * len(STOCHASTIC_SOLAR_SAMPLES)
    actual_generators = int(
        network.generators["base_name"].isin(GENERATORS_AT_SOLOMON).sum()
    )
    if actual_generators != expected_generators:
        raise AssertionError("Base scenario thermal generator copies are incorrect.")
    expected_storage_units = len(STORAGE_NONANTICIPATIVE_UNITS) * len(
        STOCHASTIC_SOLAR_SAMPLES
    )
    actual_storage_units = int(
        network.storage_units["base_name"].isin(STORAGE_NONANTICIPATIVE_UNITS).sum()
    )
    if actual_storage_units != expected_storage_units:
        raise AssertionError("Base scenario battery storage copies are incorrect.")
    for sample, weight in network.stochastic_sample_weights.items():
        bergen = network.generators.loc[stochastic_component("Bergen-01", sample)]
        expected_cost = thermal_marginal_cost(BERGEN_PROPERTIES) * weight
        if bergen["marginal_cost"] != expected_cost:
            raise AssertionError("Base scenario generator costs are not sample-weighted.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the PyPSA topology encoded from Network.png and solve the "
            "base stochastic dispatch scenario with HiGHS or Gurobi."
        )
    )
    parser.add_argument(
        "--export-netcdf",
        default=None,
        help="Optional path for exporting the topology as a PyPSA NetCDF file.",
    )
    parser.add_argument(
        "--export-lines-csv",
        default=None,
        help="Optional path for exporting the line endpoint summary as CSV.",
    )
    parser.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help="Directory containing PyPSA data sources.",
    )
    parser.add_argument(
        "--nsj-sf-sample",
        choices=list(NSJ_SF_SAMPLE_COLUMNS),
        default="1",
        help="North Star Junction SF rating sample to use as active p_max_pu.",
    )
    parser.add_argument(
        "--nsj-sf-year",
        type=int,
        default=2024,
        help="Calendar year used to expand MONTH/DAY/PERIOD solar profiles.",
    )
    parser.add_argument(
        "--solver-name",
        default=DEFAULT_SOLVER_NAME,
        help="Linopy/PyPSA solver name: gurobi or highs. Defaults to gurobi.",
    )
    parser.add_argument(
        "--solver-log",
        action="store_true",
        help="Show solver output in the console.",
    )
    parser.add_argument(
        "--gurobi-license-file",
        default=str(DEFAULT_GUROBI_LICENSE_FILE),
        help="Path to gurobi.lic. Used when --solver-name is gurobi.",
    )
    parser.add_argument(
        "--solver-time-limit",
        type=float,
        default=None,
        help="Optional solver time limit in seconds.",
    )
    parser.add_argument(
        "--solver-mip-gap",
        type=float,
        default=None,
        help="Optional solver MIP relative gap, for example 0.01 for 1%%.",
    )
    parser.add_argument(
        "--solver-threads",
        type=int,
        default=None,
        help="Optional number of solver threads.",
    )
    parser.add_argument(
        "--gurobi-time-limit",
        type=float,
        default=None,
        help="Deprecated alias for --solver-time-limit.",
    )
    parser.add_argument(
        "--gurobi-mip-gap",
        type=float,
        default=None,
        help="Deprecated alias for --solver-mip-gap.",
    )
    parser.add_argument(
        "--gurobi-threads",
        type=int,
        default=None,
        help="Deprecated alias for --solver-threads.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Directory for solved dispatch CSV and NetCDF outputs. Defaults to "
            "pypsa_outputs_base_stochastic_<solver>."
        ),
    )
    parser.add_argument(
        "--skip-solve",
        action="store_true",
        help="Only build and report the topology; do not run optimization.",
    )
    parser.add_argument(
        "--no-solution-netcdf",
        action="store_true",
        help="Skip exporting the solved PyPSA network NetCDF file.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        solver_name = normalize_solver_name(args.solver_name)
    except ValueError as error:
        raise SystemExit(f"error: {error}")
    solver_time_limit, solver_mip_gap, solver_threads = resolve_solver_controls(
        solver_time_limit=args.solver_time_limit,
        solver_mip_gap=args.solver_mip_gap,
        solver_threads=args.solver_threads,
        gurobi_time_limit=args.gurobi_time_limit,
        gurobi_mip_gap=args.gurobi_mip_gap,
        gurobi_threads=args.gurobi_threads,
    )
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else default_output_dir_for_solver(solver_name)
    )
    network = build_network_from_png(
        data_dir=Path(args.data_dir),
        nsj_sf_sample=args.nsj_sf_sample,
        nsj_sf_year=args.nsj_sf_year,
    )
    assert_expected_topology(network)

    counts = {
        "buses": len(network.buses),
        "lines": len(network.lines),
        "generators": len(network.generators),
        "storage_units": len(network.storage_units),
        "loads": len(network.loads),
    }
    print("Topology counts:")
    for component, count in counts.items():
        print(f"  {component}: {count}")

    print("\nSimulation settings:")
    print(simulation_settings_summary(network).to_string())
    print(f"\nOPF method note: {network.opf_method_note}")

    print("\nLine summary:")
    print(line_summary(network).to_string())

    print("\nRegion summary:")
    print(region_summary(network).to_string())

    print("\nGenerator property summary:")
    print(generator_property_summary(network).to_string())

    print("\nStorage property summary:")
    print(storage_property_summary(network).to_string())

    print("\nLoad profile summary:")
    print(load_profile_summary(network).to_string())

    print("\nIB NPI timeslice load summary:")
    print(ib_npi_timeslice_summary(network).to_string())

    print("\nInertia reserve summary:")
    print(inertia_reserve_summary(network).to_string())

    print("\nRegulation lower reserve summary:")
    print(regulation_lower_reserve_summary(network).to_string())

    print("\nRegulation raise reserve summary:")
    print(regulation_raise_reserve_summary(network).to_string())

    print("\nRaise Reserve Solar summary:")
    print(raise_reserve_solar_summary(network).to_string())

    print("\nRaise Reserve Solar risk factor summary:")
    print(raise_reserve_solar_risk_factor_summary(network).to_string())

    print("\nNorth Star Junction SF rating profile summary:")
    print(nsj_sf_profile_summary(network).to_string())

    if args.export_netcdf:
        output_path = Path(args.export_netcdf).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        network.export_to_netcdf(output_path)
        print(f"\nWrote {output_path}")

    if args.export_lines_csv:
        output_path = Path(args.export_lines_csv).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        line_summary(network).to_csv(output_path)
        print(f"Wrote {output_path}")

    if args.skip_solve:
        return 0

    print("\nSolving base stochastic dispatch scenario:")
    print(f"  solver: {solver_name}")
    if solver_time_limit is not None:
        print(f"  solver time limit: {solver_time_limit:g} seconds")
    if solver_mip_gap is not None:
        print(f"  solver MIP gap: {solver_mip_gap:g}")
    if solver_threads is not None:
        print(f"  solver threads: {solver_threads}")
    gurobi_license_file = (
        Path(args.gurobi_license_file) if args.gurobi_license_file else None
    )
    if solver_name == "gurobi":
        license_path = configure_gurobi_license(gurobi_license_file)
        if license_path is not None:
            print(f"  Gurobi license: {license_path}")

    solved_network, result = solve_base_stochastic_dispatch_scenario(
        solver_name=solver_name,
        solver_log=args.solver_log,
        data_dir=Path(args.data_dir),
        nsj_sf_year=args.nsj_sf_year,
        gurobi_license_file=gurobi_license_file,
        solver_time_limit=solver_time_limit,
        solver_mip_gap=solver_mip_gap,
        solver_threads=solver_threads,
    )
    assert_base_stochastic_dispatch_scenario(solved_network)
    status, condition = result
    print(f"  status: {status}")
    print(f"  termination condition: {condition}")
    if hasattr(solved_network, "objective"):
        print(f"  objective: {solved_network.objective:.6f}")

    outputs = export_base_stochastic_solution(
        solved_network,
        output_dir=output_dir,
        include_network_netcdf=not args.no_solution_netcdf,
        result=result,
    )
    print("\nWrote solution outputs:")
    for label, path in outputs.items():
        print(f"  {label}: {path.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
