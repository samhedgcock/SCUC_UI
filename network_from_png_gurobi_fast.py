"""Performance-optimized variant of ``network_from_png_gurobi``.

The network data, scenario structure, and constraint *semantics* are identical
to the original module (and to the PLEXOS model ``24H with 20H NA_Thermals_no
DE_hr``). What changes is the MIP formulation of the custom reserve
constraints, which in the original module introduced ~2,400 unnecessary binary
variables plus big-M constraints and made Gurobi's LP relaxation much weaker
than the PLEXOS formulation of the same model:

1. Regulation-raise requirement: PLEXOS models ``requirement =
   max(min provision, risks)`` implicitly through ``provision + shortage >=
   each candidate``. The original module instead built the exact max with one
   binary per candidate per snapshot per sample (1,440 binaries) plus big-M
   linking constraints and an equality balance. This module uses the plain
   inequalities, which are equivalent at the optimum because shortage carries
   a very large penalty (VoRS).

2. Inertia condition: the three business cases are kept explicit:
   no LM6000 on, exactly one LM6000 on, and both LM6000s on. The condition
   values are read from ``network.inertia_reserve_conditions`` so the
   both-on requirement can differ from the one-on requirement. The condition
   helpers are continuous in the fast path; on the integer trading-day window
   they exactly follow the binary LM6000 statuses.

3. Raise-reserve-solar / regulation-lower equalities are replaced by ``>=``
   constraints plus a tiny tie-break cost on reserve provision so that the
   reported provision still equals the requirement at the optimum.

4. The objective penalty terms are accumulated and added in a single
   ``add_objective`` call instead of ~20 incremental rebuilds of the whole
   objective expression (cuts model build time).

5. The unserved-energy generators are bounded at 1,000 MW instead of
   1,000,000 MW which tightens the coefficient range seen by the solver.

Variable names used by the CSV exporters (``Inertia-shortage-{sample}``,
``Regulation-lower-reserve-{sample}``, ...) are unchanged, so all standard
outputs keep working.
"""
from __future__ import annotations

import pandas as pd
import math

from network_from_png_gurobi import *  # noqa: F401,F403 - re-export the full model API
import network_from_png_gurobi as _base

# Bound for the unserved-energy generators. Far above any credible system
# load (total demand is < 200 MW) but small enough to keep solver
# coefficient ranges tight.
UNSERVED_ENERGY_P_NOM_MW = 1000.0

# Tiny $/MW cost on reserve provision so that provision settles exactly at
# requirement - shortage (replicating the equality formulation of the
# original module) without binaries. Negligible against dispatch costs and
# the 0.5% MIP gap.
RESERVE_TIE_BREAK_COST = 1e-3

# Deterministic symmetry-breaking perturbation. The 14 Bergens (and the
# LM6000/Titan130 pairs/quads) are exactly identical, so the MIP has
# astronomically many permutation-equivalent optima; branch-and-bound and
# the RINS/feasibility heuristics waste most of their effort shuffling
# between them. Adding i * SYMMETRY_BREAK_COST_PER_MWH to unit i of each
# identical class orders the units. The worst-case objective distortion is
# < 0.02% (far inside the 0.5% MIP gap) and it makes solutions repeatable.
SYMMETRY_BREAK_COST_PER_MWH = 0.002
SYMMETRY_BREAK_STANDBY_PER_H = 0.02

# PLEXOS horizons have an attribute "Integers in Look-ahead" whose default is
# "Auto": unit-commitment decisions in the look-ahead window are LP-relaxed
# unless something (e.g. min up/down times) requires integers there. The 24H
# horizon in the PLEXOS XML does not override it and the model has no min
# up/down times, so PLEXOS only enforces integer commitment over the 24-hour
# trading day. The original PyPSA model enforced integrality over the full
# 48 hours (trading day + look-ahead), which doubles the binaries and adds an
# integrality gap in the look-ahead that the branch-and-bound can never close
# to 0.5%. Setting this flag keeps integer commitment for the reported
# trading day and relaxes the look-ahead exactly like PLEXOS.
RELAX_LOOKAHEAD_INTEGRALITY = True

# Gurobi settings benchmarked for this model (90s budget, 0.5% gap):
# MIPFocus=2 + Cuts=2 push the dual bound, which is the binding side of the
# gap here; Symmetry=2 exploits the orbit structure of the identical Bergen
# units. CLI options (time limit, gap, threads) override these where they
# overlap.
GUROBI_FAST_DEFAULTS = {"MIPFocus": 2, "Cuts": 2, "Symmetry": 2}


def build_base_stochastic_dispatch_scenario(
    data_dir=_base.DEFAULT_DATA_DIR,
    nsj_sf_year: int = 2024,
    nonanticipative_hours: float = _base.GENERATION_NONANTICIPATIVE_HOURS,
):
    """Build the base scenario, then apply fast-formulation adjustments."""
    network = _base.build_base_stochastic_dispatch_scenario(
        data_dir=data_dir,
        nsj_sf_year=nsj_sf_year,
        nonanticipative_hours=nonanticipative_hours,
    )
    unserved = network.generators.index[
        network.generators.carrier == "unserved_energy"
    ]
    network.generators.loc[unserved, "p_nom"] = UNSERVED_ENERGY_P_NOM_MW
    _apply_symmetry_breaking_perturbation(network)
    network.base_scenario_extra_functionality = (
        add_base_stochastic_dispatch_constraints
    )
    return network


def _apply_symmetry_breaking_perturbation(network) -> None:
    """Order identical thermal units with a tiny deterministic cost adder.

    The adder is applied per *base* unit (the same across all five samples)
    so it does not interact with the non-anticipativity constraints, and it
    is scaled by the sample weight like every other cost in the stochastic
    network.
    """
    generators = network.generators
    for name in generators.index:
        base_name = generators.at[name, "base_name"]
        if not isinstance(base_name, str) or "-" not in base_name:
            continue
        prefix, _, suffix = base_name.rpartition("-")
        if prefix not in ("Bergen", "LM6000", "Titan130") or not suffix.isdigit():
            continue
        rank = int(suffix) - 1
        weight = float(generators.at[name, "sample_weight"])
        generators.at[name, "marginal_cost"] += (
            rank * SYMMETRY_BREAK_COST_PER_MWH * weight
        )
        generators.at[name, "stand_by_cost"] += (
            rank * SYMMETRY_BREAK_STANDBY_PER_H * weight
        )


def _inertia_penalty(network, snapshots: pd.DatetimeIndex, sample: str):
    """Business-case inertia requirement with no extra binary helpers."""
    model = network.model
    gen_status = model.variables["Generator-status"]
    sample_weight = network.stochastic_sample_weights[sample]
    lm6000_01 = stochastic_component("LM6000-01", sample)
    lm6000_02 = stochastic_component("LM6000-02", sample)
    status_1 = gen_status.sel(name=lm6000_01, snapshot=snapshots)
    status_2 = gen_status.sel(name=lm6000_02, snapshot=snapshots)

    both_on = model.add_variables(
        lower=0.0,
        upper=1.0,
        coords={"snapshot": snapshots},
        name=f"Inertia-both-lm6000-on-{sample}",
    )
    any_on = model.add_variables(
        lower=0.0,
        upper=1.0,
        coords={"snapshot": snapshots},
        name=f"Inertia-any-lm6000-on-{sample}",
    )
    shortage = model.add_variables(
        lower=0,
        coords={"snapshot": snapshots},
        name=f"Inertia-shortage-{sample}",
    )
    model.add_constraints(
        both_on <= status_1,
        name=f"Inertia-both-upper-lm6000-01-{sample}",
    )
    model.add_constraints(
        both_on <= status_2,
        name=f"Inertia-both-upper-lm6000-02-{sample}",
    )
    model.add_constraints(
        both_on >= status_1 + status_2 - 1,
        name=f"Inertia-both-lower-{sample}",
    )
    model.add_constraints(any_on >= status_1, name=f"Inertia-any-lower-lm6000-01-{sample}")
    model.add_constraints(any_on >= status_2, name=f"Inertia-any-lower-lm6000-02-{sample}")
    model.add_constraints(any_on <= status_1 + status_2, name=f"Inertia-any-upper-{sample}")

    provision_terms = []
    for base_name in GENERATORS_AT_SOLOMON:
        component = stochastic_component(base_name, sample)
        inertia_mw_s = network.generators.at[component, "inertia_mw_s"]
        provision_terms.append(
            float(inertia_mw_s) * gen_status.sel(name=component, snapshot=snapshots)
        )

    requirements = inertia_condition_requirements(network)
    exactly_one_on = any_on - both_on
    no_on = 1 - any_on
    model.add_constraints(
        sum(provision_terms)
        + shortage
        >= requirements["no_lm6000_on"] * no_on
        + requirements["any_lm6000_on"] * exactly_one_on
        + requirements["both_lm6000_on"] * both_on,
        name=f"Inertia-reserve-requirement-{sample}",
    )

    # Integer-rounding (Chvatal-Gomory) strengthening of the inertia
    # requirement. Divide the requirement row by one Bergen unit of inertia
    # and round all coefficients up. This adapts to separate no/one/both
    # LM6000 requirement values while remaining valid on the integer
    # trading-day window. The cut assumes zero inertia shortage, which holds
    # at any optimum because VoRS dwarfs the cost of committing another unit.
    cut_snapshots = _integer_commitment_snapshots(network, snapshots)
    if len(cut_snapshots) > 0:
        bergen_inertia = float(
            network.generators.at[stochastic_component("Bergen-01", sample), "inertia_mw_s"]
        )

        def rounded_count(value: float) -> float:
            return float(math.ceil((float(value) / bergen_inertia) - 1e-9))

        no_count = rounded_count(requirements["no_lm6000_on"])
        one_count = rounded_count(requirements["any_lm6000_on"])
        both_count = rounded_count(requirements["both_lm6000_on"])
        count_terms = []
        for base_name in GENERATORS_AT_SOLOMON:
            component = stochastic_component(base_name, sample)
            status = gen_status.sel(name=component, snapshot=cut_snapshots)
            inertia_mw_s = float(network.generators.at[component, "inertia_mw_s"])
            count_terms.append(rounded_count(inertia_mw_s) * status)
        model.add_constraints(
            sum(count_terms)
            >= no_count
            + (one_count - no_count) * any_on.sel(snapshot=cut_snapshots)
            + (both_count - one_count) * both_on.sel(snapshot=cut_snapshots),
            name=f"Inertia-commitment-count-cut-{sample}",
        )
    return shortage.sum() * (network.inertia_reserve_vors_per_mws * sample_weight)


def _integer_commitment_snapshots(
    network, snapshots: pd.DatetimeIndex
) -> pd.DatetimeIndex:
    """Snapshots with integer commitment (trading day when look-ahead relaxed)."""
    if not RELAX_LOOKAHEAD_INTEGRALITY:
        return snapshots
    periods = int(getattr(network, "reporting_snapshot_count", len(snapshots)))
    return snapshots[:periods]


def add_trading_day_integrality(network, snapshots: pd.DatetimeIndex) -> None:
    """Re-impose binary commitment on the trading day.

    The model is built with ``linearized_unit_commitment=True`` (all status /
    start-up / shut-down variables continuous in [0, 1], constraints
    unchanged). This hook then forces the trading-day statuses to be binary
    through equality-linked auxiliary binaries, replicating PLEXOS's
    "Integers in Look-ahead = Auto" behaviour. Start-up/shut-down variables
    take integral values automatically because they are cost-penalised
    differences of binary statuses.
    """
    snapshots = pd.DatetimeIndex(snapshots, name="snapshot")
    integer_snapshots = _integer_commitment_snapshots(network, snapshots)
    if len(integer_snapshots) == 0:
        return
    model = network.model
    status = model.variables["Generator-status"]
    names = pd.Index(status.coords["name"].values, name="name")
    binary = model.add_variables(
        coords={"snapshot": integer_snapshots, "name": names},
        binary=True,
        name="Generator-status-integer",
    )
    model.add_constraints(
        status.sel(snapshot=integer_snapshots) == binary,
        name="Generator-status-integrality",
    )


def _regulation_lower_penalty(network, snapshots: pd.DatetimeIndex, sample: str):
    model = network.model
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
    if network.regulation_lower_reserve_dynamic_risk:
        for contingency in network.regulation_lower_reserve_contingencies:
            component = stochastic_component(contingency, sample)
            model.add_constraints(
                provision + shortage >= gen_p.sel(name=component, snapshot=snapshots),
                name=f"Regulation-lower-dynamic-risk-{contingency}-{sample}",
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
    return (
        shortage.sum() * (network.regulation_lower_reserve_vors_per_mw * sample_weight)
        + reserve.sum() * (RESERVE_TIE_BREAK_COST * sample_weight)
    )


def _regulation_raise_penalty(network, snapshots: pd.DatetimeIndex, sample: str):
    """provision + shortage >= max(min provision, LM6000 output) without binaries."""
    model = network.model
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
    model.add_constraints(
        provision + shortage >= network.regulation_raise_reserve_min_provision_mw,
        name=f"Regulation-raise-requirement-min-{sample}",
    )
    if network.regulation_raise_reserve_dynamic_risk:
        for contingency in network.regulation_raise_reserve_contingencies:
            component = stochastic_component(contingency, sample)
            model.add_constraints(
                provision + shortage >= gen_p.sel(name=component, snapshot=snapshots),
                name=f"Regulation-raise-dynamic-risk-{contingency}-{sample}",
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
    return (
        shortage.sum() * (network.regulation_raise_reserve_vors_per_mw * sample_weight)
        + reserve.sum() * (RESERVE_TIE_BREAK_COST * sample_weight)
    )


def _raise_reserve_solar_penalty(network, snapshots: pd.DatetimeIndex, sample: str):
    model = network.model
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
    if network.raise_reserve_solar_dynamic_risk:
        risk_factor = series_to_linopy_da(
            monthly_risk_adjustment_factor_series(
                snapshots, network.raise_reserve_solar_risk_adjustment_factors
            )
        )
        for contingency in network.raise_reserve_solar_contingencies:
            component = stochastic_component(contingency, sample)
            model.add_constraints(
                provision + shortage
                >= gen_p.sel(name=component, snapshot=snapshots) / risk_factor,
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
    return (
        shortage.sum() * (network.raise_reserve_solar_vors_per_mw * sample_weight)
        + reserve.sum() * (RESERVE_TIE_BREAK_COST * sample_weight)
    )


def add_stochastic_reserve_constraints(
    network, snapshots: pd.DatetimeIndex
) -> None:
    """Add all reserves for all samples with one final objective update."""
    snapshots = pd.DatetimeIndex(snapshots, name="snapshot")
    model = network.model
    penalties = []
    for sample in network.stochastic_samples:
        penalties.append(_inertia_penalty(network, snapshots, sample))
        penalties.append(_regulation_lower_penalty(network, snapshots, sample))
        penalties.append(_regulation_raise_penalty(network, snapshots, sample))
        penalties.append(_raise_reserve_solar_penalty(network, snapshots, sample))

    total_penalty = penalties[0]
    for term in penalties[1:]:
        total_penalty = total_penalty + term
    model.add_objective(
        model.objective.expression + total_penalty,
        overwrite=True,
        sense="min",
    )


def add_base_stochastic_dispatch_constraints(
    network, snapshots: pd.DatetimeIndex
) -> None:
    add_generation_nonanticipativity_constraints(network, snapshots)
    add_storage_nonanticipativity_constraints(network, snapshots)
    add_stochastic_reserve_constraints(network, snapshots)


# Keep the alias used by some callers consistent with the fast formulation.
add_stochastic_dispatch_constraints = add_base_stochastic_dispatch_constraints


def optimize_with_default_simulation_settings(
    network,
    solver_name: str = DEFAULT_SOLVER_NAME,
    solver_log: bool = False,
    extra_functionality=None,
    model_transmission_losses: bool | None = None,
    gurobi_license_file=DEFAULT_GUROBI_LICENSE_FILE,
    solver_time_limit: float | None = None,
    solver_mip_gap: float | None = None,
    solver_threads: int | None = None,
    gurobi_time_limit: float | None = None,
    gurobi_mip_gap: float | None = None,
    gurobi_threads: int | None = None,
) -> tuple[str, str]:
    """Drop-in replacement for the original optimizer entry point.

    Differences: when ``RELAX_LOOKAHEAD_INTEGRALITY`` is on, the model is
    built with relaxed commitment variables and binary commitment is
    re-imposed on the trading day only (see ``add_trading_day_integrality``).
    """
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

    inner_extra_functionality = extra_functionality

    def fast_extra_functionality(n, sns):
        if RELAX_LOOKAHEAD_INTEGRALITY:
            add_trading_day_integrality(n, sns)
        if inner_extra_functionality is not None:
            inner_extra_functionality(n, sns)

    solver_options = solver_options_for(
        solver_name,
        solver_time_limit=time_limit,
        solver_mip_gap=mip_gap,
        solver_threads=threads,
    )
    if solver_name == "gurobi":
        solver_options = {**GUROBI_FAST_DEFAULTS, **(solver_options or {})}

    return network.optimize(
        snapshots=network.snapshots,
        solver_name=solver_name,
        solver_options=solver_options,
        log_to_console=solver_log,
        extra_functionality=fast_extra_functionality,
        transmission_losses=(
            network.transmission_loss_tranches if transmission_losses else False
        ),
        linearized_unit_commitment=RELAX_LOOKAHEAD_INTEGRALITY,
        assign_all_duals=False,
        include_objective_constant=False,
    )
