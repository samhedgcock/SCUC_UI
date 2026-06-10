from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import io
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse


APP_TITLE = "PyPSA Data Sources"
DEFAULT_DATA_ROOT = Path("pypsa_data_sources") / "pypsa_data_sources"
MANIFEST_NAME = "manifest.csv"
MODEL_RUNS_DIR = Path("model_runs")
OUTPUT_DIR_NAME = "pypsa_outputs_base_stochastic_v1"
MODEL_WINDOW_START = datetime(2024, 10, 28, 10, 0)
MODEL_WINDOW_YEAR = 2024
MODEL_WINDOW_INTERVAL_MINUTES = 30
THERMAL_OUTPUT = "thermal_generation_by_interval.csv"
UNSERVED_OUTPUT = "unserved_energy_by_interval.csv"
LOAD_OUTPUT = "load_by_bus_by_interval.csv"
GENERATION_OUTPUT = "generation_by_interval.csv"
GENERATOR_OUTPUT = "generator_dispatch_by_interval.csv"
LINE_FLOW_OUTPUT = "line_flow_by_interval.csv"
RESERVES_OUTPUT = "reserves_by_interval.csv"
RUN_OUTPUT_LOG = "run_output.log"
BATTERY_SOC_OUTPUT = "battery_soc_by_interval.csv"
RUN_JOBS: dict[str, dict[str, Any]] = {}
RUN_JOBS_LOCK = threading.Lock()
RUN_LOG_LOCK = threading.Lock()
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
RUN_STAGE_PROGRESS = {
    "Queued": 4,
    "Preparing data bundle": 10,
    "Starting solve process": 16,
    "Building stochastic scenario": 25,
    "Writing optimization model": 38,
    "Running solver": 55,
    "Solver finished": 82,
    "Exporting outputs": 90,
    "Complete": 100,
    "Failed": 100,
    "Cancelled": 100,
}

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

THERMAL_GENERATORS = tuple(f"Bergen-{i:02d}" for i in range(1, 16)) + (
    "LM6000-01",
    "LM6000-02",
    "Titan130-01",
    "Titan130-02",
    "Titan130-03",
    "Titan130-04",
)

GENERATOR_BUSES = {
    **{name: "Solomon Hub" for name in THERMAL_GENERATORS},
    "North Star Junction SF": "North Star Junction Terminal",
}

NETWORK_LINES = (
    ("SOL>Lambda", "Solomon Hub", "Lambda Terminal", 500.0),
    ("Lambda>NSJ", "Lambda Terminal", "North Star Junction Terminal", 500.0),
    ("NSJT>NSJS", "North Star Junction Terminal", "North Star Substation", 500.0),
    ("SOL>Dx>FT OPF", "Solomon Hub", "SM FT OPF", 100.0),
    ("SOL>Dx>KV OPF", "Solomon Hub", "SM KV OPF", 100.0),
    ("SOL>Dx>SM GF", "Solomon Hub", "SM GF", 100.0),
    ("SOL>Dx>SM NPI", "Solomon Hub", "SM NPI", 100.0),
    ("SOL>Dx>SM TLO", "Solomon Hub", "SM TLO", 100.0),
    ("NSS>Dx>IB GF", "North Star Substation", "IB GF", 100.0),
    ("NSS>Dx>IB NPI", "North Star Substation", "IB NPI", 100.0),
    ("NSS>Dx>IB OPF", "North Star Substation", "IB OPF", 100.0),
)

BUS_LAYOUT = {
    "Solomon Hub": {"x": 180, "y": 330, "type": "hub"},
    "Lambda Terminal": {"x": 390, "y": 330, "type": "hub"},
    "North Star Junction Terminal": {"x": 600, "y": 330, "type": "hub"},
    "North Star Substation": {"x": 810, "y": 330, "type": "hub"},
    "SM FT OPF": {"x": 90, "y": 110, "type": "load"},
    "SM GF": {"x": 120, "y": 180, "type": "load"},
    "SM KV OPF": {"x": 110, "y": 250, "type": "load"},
    "SM NPI": {"x": 120, "y": 430, "type": "load"},
    "SM TLO": {"x": 90, "y": 500, "type": "load"},
    "IB GF": {"x": 920, "y": 210, "type": "load"},
    "IB NPI": {"x": 940, "y": 330, "type": "load"},
    "IB OPF": {"x": 920, "y": 450, "type": "load"},
}

DEFAULT_POWER_MODEL = "network_from_png_gurobi_fast_custom_scenario"
POWER_MODELS: dict[str, dict[str, Any]] = {
    "network_from_png_gurobi_fast_custom_scenario": {
        "label": "network_from_png_gurobi_fast.py - fast patch scenario",
        "script": "network_from_png_gurobi_fast.py",
        "required_scripts": ["network_from_png_gurobi.py"],
        "command_script": "run_custom_stochastic_scenario_fast.py",
        "default_solver": "gurobi",
        "uses_horizon": False,
        "custom_scenario_command": True,
        "stderr_to_stdout": True,
        "supports_nonanticipative_hours": True,
        "scenario_name": "sol_bess_enabled_nss_disabled_nonanticipative",
        "sol_bess": "enabled",
        "nss_bess": "disabled",
        "solver_time_limit": 360,
        "solver_mip_gap": 0.005,
    },
}

RENEWABLE_DAY_LIMITS = {
    1: 31,
    2: 29,
    3: 31,
    4: 30,
    5: 31,
    6: 30,
    7: 31,
    8: 31,
    9: 30,
    10: 31,
    11: 30,
    12: 31,
}


@dataclass(frozen=True)
class CatalogItem:
    dataset: str
    path: Path
    relative_path: str
    group: str
    rows: str
    columns: str
    notes: str
    source_file: str
    advanced: bool = False


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PyPSA Data Sources</title>
  <style>
    :root {
      --bg: #f5f7f8;
      --panel: #ffffff;
      --line: #d8dee4;
      --line-strong: #b7c0c8;
      --text: #17202a;
      --muted: #5e6b76;
      --blue: #1f6feb;
      --blue-dark: #1554b5;
      --green: #207a4b;
      --amber: #9a6700;
      --red: #b42318;
      --cell: #fbfcfd;
      --shadow: 0 10px 24px rgba(27, 39, 51, 0.08);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
    }

    button,
    input,
    select {
      font: inherit;
    }

    button {
      border: 1px solid var(--line-strong);
      background: #ffffff;
      color: var(--text);
      border-radius: 6px;
      min-height: 34px;
      padding: 0 12px;
      cursor: pointer;
    }

    button:hover:not(:disabled) {
      border-color: var(--blue);
      color: var(--blue-dark);
    }

    button:disabled {
      opacity: 0.52;
      cursor: not-allowed;
    }

    button.primary {
      background: var(--blue);
      border-color: var(--blue);
      color: #ffffff;
    }

    button.primary:hover:not(:disabled) {
      background: var(--blue-dark);
      color: #ffffff;
    }

    button.danger:hover:not(:disabled) {
      border-color: var(--red);
      color: var(--red);
    }

    input,
    select {
      border: 1px solid var(--line-strong);
      border-radius: 6px;
      background: #ffffff;
      color: var(--text);
      min-height: 34px;
      padding: 6px 9px;
      min-width: 0;
    }

    input:focus,
    select:focus,
    button:focus {
      outline: 2px solid rgba(31, 111, 235, 0.25);
      outline-offset: 1px;
    }

    .app {
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto auto 1fr auto;
    }

    .topbar {
      display: grid;
      grid-template-columns: minmax(190px, 240px) minmax(260px, 1fr) minmax(260px, 420px) auto;
      gap: 12px;
      align-items: end;
      padding: 14px 16px;
      background: var(--panel);
      border-bottom: 1px solid var(--line);
      position: sticky;
      top: 0;
      z-index: 10;
    }

    .brand {
      display: grid;
      gap: 3px;
      align-self: center;
    }

    .brand h1 {
      margin: 0;
      font-size: 18px;
      line-height: 1.2;
      letter-spacing: 0;
    }

    .brand .subtitle {
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .nav-links {
      display: flex;
      gap: 10px;
      align-items: center;
      font-size: 12px;
      font-weight: 650;
    }

    .nav-links a {
      color: var(--blue-dark);
      text-decoration: none;
    }

    .nav-links a:hover {
      text-decoration: underline;
    }

    .topbar {
      grid-template-columns: minmax(220px, 300px) minmax(360px, 1fr) minmax(220px, 360px) auto;
      gap: 10px 14px;
      align-items: center;
      padding: 12px 16px 10px;
      background: linear-gradient(180deg, #fbfcfe 0%, #eef3f7 100%);
      box-shadow: 0 1px 0 rgba(17, 24, 39, 0.04);
    }

    .nav-links {
      justify-self: stretch;
      flex-wrap: wrap;
      gap: 6px;
      padding: 6px;
      border: 1px solid #d4dde6;
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.82);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.85);
    }

    .nav-links a {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 30px;
      padding: 0 10px;
      border: 1px solid transparent;
      border-radius: 6px;
      color: #243548;
      text-decoration: none;
      white-space: nowrap;
    }

    .nav-links a:hover {
      border-color: #c8d4df;
      background: #f5f8fb;
      text-decoration: none;
    }

    .nav-links a[aria-current="page"] {
      border-color: rgba(31, 111, 235, 0.2);
      background: var(--blue);
      color: #ffffff;
      box-shadow: 0 1px 2px rgba(31, 111, 235, 0.18);
    }

    .nav-primary {
      font-weight: 750;
    }

    .nav-group {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 2px 0 2px 8px;
      border-left: 1px solid #d9e2eb;
    }

    .nav-group span {
      color: var(--muted);
      font-size: 10px;
      font-weight: 750;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      margin-right: 2px;
      white-space: nowrap;
    }

    .root-tools {
      grid-column: 2 / -1;
      display: grid;
      grid-template-columns: auto minmax(280px, 1fr) auto minmax(160px, 0.6fr);
      gap: 8px;
      align-items: center;
      padding: 7px 8px;
      border: 1px solid #d8e1ea;
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.62);
    }

    .root-tools label,
    .root-status {
      color: var(--muted);
      font-size: 11px;
      font-weight: 650;
    }

    .root-tools input {
      min-height: 28px;
      padding: 4px 8px;
      font-size: 12px;
    }

    .root-tools button {
      min-height: 28px;
      padding: 4px 10px;
      font-size: 12px;
    }

    .root-status {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .field {
      display: grid;
      gap: 5px;
    }

    .field label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
    }

    .field select,
    .field input {
      width: 100%;
    }

    .meta {
      display: grid;
      grid-template-columns: repeat(5, minmax(120px, 1fr));
      gap: 10px;
      padding: 10px 16px;
      border-bottom: 1px solid var(--line);
      background: #eef2f5;
    }

    .metric {
      min-width: 0;
      display: grid;
      gap: 2px;
    }

    .metric span {
      color: var(--muted);
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
    }

    .metric strong {
      font-size: 13px;
      font-weight: 650;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .workspace {
      min-height: 0;
      display: grid;
      grid-template-columns: minmax(0, 1fr) 340px;
      gap: 14px;
      padding: 14px 16px;
    }

    .editor-panel,
    .validation-panel {
      min-width: 0;
      min-height: 0;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      display: grid;
      grid-template-rows: auto 1fr;
    }

    .panel-toolbar {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
      padding: 10px;
      border-bottom: 1px solid var(--line);
    }

    .panel-toolbar .spacer {
      flex: 1 1 auto;
    }

    .search {
      width: min(280px, 100%);
    }

    .grid-wrap {
      min-height: 0;
      overflow: auto;
      background: #ffffff;
      border-bottom-left-radius: 8px;
      border-bottom-right-radius: 8px;
    }

    table {
      border-collapse: separate;
      border-spacing: 0;
      width: max-content;
      min-width: 100%;
      table-layout: fixed;
    }

    th,
    td {
      border-right: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
      min-width: 132px;
      max-width: 240px;
      height: 34px;
      padding: 0;
      background: #ffffff;
    }

    th {
      position: sticky;
      top: 0;
      z-index: 2;
      background: #f0f3f6;
      color: #26323d;
      font-size: 12px;
      text-align: left;
      font-weight: 650;
    }

    th.row-head,
    td.row-head {
      position: sticky;
      left: 0;
      z-index: 3;
      min-width: 84px;
      max-width: 84px;
      width: 84px;
      text-align: center;
      background: #f0f3f6;
    }

    td.row-head {
      color: var(--muted);
      font-size: 12px;
    }

    .column-label {
      display: flex;
      gap: 6px;
      align-items: center;
      min-height: 34px;
      padding: 0 8px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .cell-input {
      width: 100%;
      min-height: 33px;
      border: 0;
      border-radius: 0;
      background: var(--cell);
      padding: 6px 8px;
    }

    .cell-input:focus {
      outline: 2px solid rgba(31, 111, 235, 0.32);
      outline-offset: -2px;
      background: #ffffff;
    }

    .row-select {
      width: 16px;
      height: 16px;
      min-height: 0;
      vertical-align: middle;
    }

    .validation-panel {
      grid-template-rows: auto auto 1fr;
    }

    .validation-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 12px;
      border-bottom: 1px solid var(--line);
    }

    .validation-head h2 {
      margin: 0;
      font-size: 15px;
      letter-spacing: 0;
    }

    .status-pill {
      border-radius: 999px;
      border: 1px solid var(--line-strong);
      padding: 3px 8px;
      font-size: 12px;
      color: var(--muted);
      background: #ffffff;
      white-space: nowrap;
    }

    .status-pill.ok {
      color: var(--green);
      border-color: rgba(32, 122, 75, 0.45);
      background: #edf8f1;
    }

    .status-pill.bad {
      color: var(--red);
      border-color: rgba(180, 35, 24, 0.4);
      background: #fff1f0;
    }

    .counts {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
    }

    .count-box {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px;
      background: #fafbfc;
    }

    .count-box span {
      display: block;
      color: var(--muted);
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
    }

    .count-box strong {
      font-size: 20px;
      line-height: 1.2;
    }

    .messages {
      overflow: auto;
      min-height: 0;
      padding: 10px 12px;
      display: grid;
      align-content: start;
      gap: 8px;
    }

    .message {
      border: 1px solid var(--line);
      border-left-width: 4px;
      border-radius: 6px;
      padding: 8px;
      background: #ffffff;
      display: grid;
      gap: 3px;
    }

    .message.error {
      border-left-color: var(--red);
    }

    .message.warning {
      border-left-color: var(--amber);
    }

    .message .where {
      color: var(--muted);
      font-size: 12px;
    }

    .message .text {
      font-size: 13px;
    }

    .empty {
      color: var(--muted);
      font-size: 13px;
      padding: 8px 0;
    }

    .footer {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px 16px;
      border-top: 1px solid var(--line);
      background: var(--panel);
      position: sticky;
      bottom: 0;
      z-index: 10;
    }

    .footer .spacer {
      flex: 1 1 auto;
    }

    .toast {
      color: var(--muted);
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 13px;
    }

    .toast.error {
      color: var(--red);
    }

    .toast.ok {
      color: var(--green);
    }

    .pager {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 13px;
    }

    @media (max-width: 1100px) {
      .topbar {
        grid-template-columns: 1fr 1fr;
      }

      .workspace {
        grid-template-columns: 1fr;
      }

      .validation-panel {
        min-height: 320px;
      }
    }

    @media (max-width: 760px) {
      .topbar,
      .meta {
        grid-template-columns: 1fr;
      }

      .root-tools {
        grid-column: 1 / -1;
        grid-template-columns: auto minmax(0, 1fr) auto;
      }

      .root-status {
        grid-column: 1 / -1;
      }

      .workspace {
        padding: 10px;
      }

      .footer {
        flex-wrap: wrap;
      }
    }
  </style>
</head>
<body>
  <div class="app">
    <header class="topbar">
      <div class="brand">
        <h1>PyPSA Data Sources</h1>
        <div class="subtitle">Source CSV editor</div>
      </div>
      <nav class="nav-links" aria-label="Application navigation">
        <a class="nav-primary" href="/runner">Model Runner</a>
        <div class="nav-group" aria-label="Input pages">
          <span>Inputs</span>
          <a href="/inputs">Visual</a>
          <a href="/" aria-current="page">CSV Editor</a>
        </div>
        <div class="nav-group" aria-label="Output pages">
          <span>Outputs</span>
          <a href="/dashboard">Visual</a>
          <a href="/topology">Topology</a>
        </div>
      </nav>
      <div class="field">
        <label for="dataset-select">Dataset</label>
        <select id="dataset-select"></select>
      </div>
      <div class="root-tools" aria-label="Data root">
        <label for="root-input">Data root</label>
        <input id="root-input" autocomplete="off">
        <button id="load-root-btn">Load</button>
        <span class="root-status" id="dirty-state">Loading data root</span>
      </div>
    </header>

    <section class="meta" aria-label="Selected dataset metadata">
      <div class="metric"><span>Path</span><strong id="meta-path">-</strong></div>
      <div class="metric"><span>Rows</span><strong id="meta-rows">-</strong></div>
      <div class="metric"><span>Columns</span><strong id="meta-cols">-</strong></div>
      <div class="metric"><span>Modified</span><strong id="meta-modified">-</strong></div>
      <div class="metric"><span>Notes</span><strong id="meta-notes">-</strong></div>
    </section>

    <main class="workspace">
      <section class="editor-panel" aria-label="CSV editor">
        <div class="panel-toolbar">
          <input class="search" id="search-input" placeholder="Search rows" autocomplete="off">
          <button id="add-row-btn">Add Row</button>
          <button id="delete-row-btn" class="danger">Delete Rows</button>
          <button id="add-column-btn">Add Column</button>
          <button id="rename-column-btn">Rename Column</button>
          <button id="delete-column-btn" class="danger">Delete Column</button>
          <div class="spacer"></div>
          <div class="pager">
            <button id="prev-page-btn">Prev</button>
            <span id="page-label">-</span>
            <button id="next-page-btn">Next</button>
            <select id="page-size-select" aria-label="Rows per page">
              <option>50</option>
              <option selected>100</option>
              <option>250</option>
              <option>500</option>
            </select>
          </div>
        </div>
        <div class="grid-wrap" id="grid-wrap">
          <table id="data-grid"></table>
        </div>
      </section>

      <aside class="validation-panel" aria-label="Validation">
        <div class="validation-head">
          <h2>Validation</h2>
          <span class="status-pill" id="validation-status">Not checked</span>
        </div>
        <div class="counts">
          <div class="count-box"><span>Errors</span><strong id="error-count">0</strong></div>
          <div class="count-box"><span>Warnings</span><strong id="warning-count">0</strong></div>
        </div>
        <div class="messages" id="validation-messages">
          <div class="empty">No validation results yet.</div>
        </div>
      </aside>
    </main>

    <footer class="footer">
      <button id="reload-btn">Reload</button>
      <button id="validate-btn">Validate</button>
      <button id="export-btn">Export CSV</button>
      <button id="save-copy-btn">Save As Copy</button>
      <div class="spacer"></div>
      <div class="toast" id="toast">Ready</div>
      <button id="save-btn" class="primary" disabled>Save</button>
    </footer>
  </div>

  <script>
    const state = {
      root: "",
      catalog: [],
      selected: "",
      currentItem: null,
      columns: [],
      rows: [],
      originalHash: "",
      dirty: false,
      selectedRows: new Set(),
      validation: null,
      page: 0,
      pageSize: 100,
      search: ""
    };

    const els = {
      dataset: document.getElementById("dataset-select"),
      root: document.getElementById("root-input"),
      dirty: document.getElementById("dirty-state"),
      metaPath: document.getElementById("meta-path"),
      metaRows: document.getElementById("meta-rows"),
      metaCols: document.getElementById("meta-cols"),
      metaModified: document.getElementById("meta-modified"),
      metaNotes: document.getElementById("meta-notes"),
      grid: document.getElementById("data-grid"),
      search: document.getElementById("search-input"),
      pageLabel: document.getElementById("page-label"),
      pageSize: document.getElementById("page-size-select"),
      validationStatus: document.getElementById("validation-status"),
      errorCount: document.getElementById("error-count"),
      warningCount: document.getElementById("warning-count"),
      messages: document.getElementById("validation-messages"),
      toast: document.getElementById("toast"),
      save: document.getElementById("save-btn")
    };

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }

    function setToast(message, kind = "") {
      els.toast.textContent = message;
      els.toast.className = "toast" + (kind ? " " + kind : "");
    }

    function api(path, options = {}) {
      const headers = options.headers || {};
      if (options.body && !headers["Content-Type"]) {
        headers["Content-Type"] = "application/json";
      }
      return fetch(path, { ...options, headers }).then(async response => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.ok === false) {
          throw new Error(data.error || response.statusText);
        }
        return data;
      });
    }

    function catalogGroups() {
      return state.catalog.reduce((groups, item) => {
        if (!groups[item.group]) groups[item.group] = [];
        groups[item.group].push(item);
        return groups;
      }, {});
    }

    function renderCatalog() {
      const groups = catalogGroups();
      const order = ["loads", "generators", "renewables", "raw", "excel_exports", "manifest"];
      const groupNames = [
        ...order.filter(name => groups[name]),
        ...Object.keys(groups).filter(name => !order.includes(name)).sort()
      ];
      els.dataset.innerHTML = groupNames.map(group => {
        const options = groups[group].map(item => {
          const label = `${item.dataset} - ${item.relative_path}`;
          return `<option value="${escapeHtml(item.dataset)}">${escapeHtml(label)}</option>`;
        }).join("");
        return `<optgroup label="${escapeHtml(group)}">${options}</optgroup>`;
      }).join("");
      els.dataset.value = state.selected;
    }

    function filteredIndices() {
      const q = state.search.trim().toLowerCase();
      if (!q) return state.rows.map((_, index) => index);
      const result = [];
      for (let i = 0; i < state.rows.length; i += 1) {
        const row = state.rows[i];
        if (row.some(cell => String(cell ?? "").toLowerCase().includes(q))) {
          result.push(i);
        }
      }
      return result;
    }

    function renderGrid() {
      const indices = filteredIndices();
      const pageCount = Math.max(1, Math.ceil(indices.length / state.pageSize));
      state.page = Math.min(state.page, pageCount - 1);
      const start = state.page * state.pageSize;
      const visible = indices.slice(start, start + state.pageSize);

      const headers = [
        `<th class="row-head"><span class="column-label">Row</span></th>`,
        ...state.columns.map((column, index) => (
          `<th><span class="column-label" title="${escapeHtml(column)}">${escapeHtml(column || `(Column ${index + 1})`)}</span></th>`
        ))
      ].join("");

      const body = visible.map(rowIndex => {
        const row = state.rows[rowIndex] || [];
        const cells = state.columns.map((_, colIndex) => {
          const value = row[colIndex] ?? "";
          return `<td><input class="cell-input" data-row="${rowIndex}" data-col="${colIndex}" value="${escapeHtml(value)}"></td>`;
        }).join("");
        const checked = state.selectedRows.has(rowIndex) ? "checked" : "";
        return `<tr><td class="row-head"><input class="row-select" type="checkbox" data-row-select="${rowIndex}" ${checked}> ${rowIndex + 1}</td>${cells}</tr>`;
      }).join("");

      els.grid.innerHTML = `<thead><tr>${headers}</tr></thead><tbody>${body}</tbody>`;
      els.pageLabel.textContent = `${indices.length ? start + 1 : 0}-${Math.min(start + state.pageSize, indices.length)} of ${indices.length}`;
      document.getElementById("prev-page-btn").disabled = state.page <= 0;
      document.getElementById("next-page-btn").disabled = state.page >= pageCount - 1;
    }

    function renderMeta(file) {
      const item = state.currentItem || {};
      els.metaPath.textContent = item.relative_path || "-";
      els.metaRows.textContent = String(state.rows.length);
      els.metaCols.textContent = String(state.columns.length);
      els.metaModified.textContent = file?.modified || "-";
      els.metaNotes.textContent = item.notes || "-";
      els.dirty.textContent = state.dirty ? "Unsaved edits" : `Root: ${state.root}`;
      els.save.disabled = !state.dirty || hasBlockingErrors();
    }

    function hasBlockingErrors() {
      return !!state.validation && state.validation.errors && state.validation.errors.length > 0;
    }

    function renderValidation() {
      const validation = state.validation;
      if (!validation) {
        els.validationStatus.textContent = "Not checked";
        els.validationStatus.className = "status-pill";
        els.errorCount.textContent = "0";
        els.warningCount.textContent = "0";
        els.messages.innerHTML = `<div class="empty">No validation results yet.</div>`;
        els.save.disabled = !state.dirty;
        return;
      }

      const errors = validation.errors || [];
      const warnings = validation.warnings || [];
      els.errorCount.textContent = String(errors.length);
      els.warningCount.textContent = String(warnings.length);
      els.validationStatus.textContent = errors.length ? "Blocked" : "Ready";
      els.validationStatus.className = "status-pill " + (errors.length ? "bad" : "ok");

      const messages = [
        ...errors.map(message => ({ ...message, severity: "error" })),
        ...warnings.map(message => ({ ...message, severity: "warning" }))
      ];

      els.messages.innerHTML = messages.length
        ? messages.map(message => {
            const where = [message.row ? `row ${message.row}` : "", message.column || ""].filter(Boolean).join(", ");
            return `<div class="message ${message.severity}">
              <div class="where">${escapeHtml(message.severity.toUpperCase())}${where ? " - " + escapeHtml(where) : ""}</div>
              <div class="text">${escapeHtml(message.message)}</div>
            </div>`;
          }).join("")
        : `<div class="empty">No errors or warnings.</div>`;

      els.save.disabled = !state.dirty || errors.length > 0;
    }

    function markDirty() {
      state.dirty = true;
      state.validation = null;
      renderMeta();
      renderValidation();
    }

    async function loadCatalog(preferredDataset = "") {
      setToast("Loading catalog");
      const rootParam = els.root.value.trim();
      const data = await api(`/api/catalog${rootParam ? `?root=${encodeURIComponent(rootParam)}` : ""}`);
      state.root = data.data_root;
      state.catalog = data.datasets;
      state.selected = preferredDataset || data.default_dataset || data.datasets[0]?.dataset || "";
      els.root.value = state.root;
      renderCatalog();
      await loadSelected();
    }

    async function loadSelected() {
      if (!state.selected) return;
      setToast("Loading CSV");
      const data = await api(`/api/file?root=${encodeURIComponent(state.root)}&dataset=${encodeURIComponent(state.selected)}`);
      state.currentItem = state.catalog.find(item => item.dataset === state.selected) || null;
      state.columns = data.columns;
      state.rows = data.rows;
      state.originalHash = data.hash;
      state.dirty = false;
      state.selectedRows = new Set();
      state.validation = data.validation || null;
      state.page = 0;
      state.search = "";
      els.search.value = "";
      renderCatalog();
      renderMeta(data.file);
      renderGrid();
      renderValidation();
      setToast(`Loaded ${state.selected}`, "ok");
    }

    function payload() {
      return {
        root: state.root,
        dataset: state.selected,
        columns: state.columns,
        rows: state.rows,
        original_hash: state.originalHash
      };
    }

    async function validateCurrent() {
      setToast("Validating");
      const data = await api("/api/validate", {
        method: "POST",
        body: JSON.stringify(payload())
      });
      state.validation = data.validation;
      renderValidation();
      renderMeta();
      setToast(data.validation.errors.length ? "Validation blocked save" : "Validation passed", data.validation.errors.length ? "error" : "ok");
      return data.validation;
    }

    async function saveCurrent() {
      const validation = await validateCurrent();
      if (validation.errors.length) return;
      setToast("Saving");
      const data = await api("/api/save", {
        method: "POST",
        body: JSON.stringify(payload())
      });
      state.originalHash = data.hash;
      state.dirty = false;
      state.validation = data.validation;
      await loadCatalog(state.selected);
      setToast(`Saved. Backup: ${data.backup_relative_path}`, "ok");
    }

    function csvText() {
      const quote = value => {
        const text = String(value ?? "");
        if (/[",\r\n]/.test(text)) return `"${text.replaceAll('"', '""')}"`;
        return text;
      };
      return [state.columns, ...state.rows].map(row => row.map(quote).join(",")).join("\r\n") + "\r\n";
    }

    function exportCsv() {
      const blob = new Blob([csvText()], { type: "text/csv;charset=utf-8" });
      const link = document.createElement("a");
      const safeName = `${state.selected.replaceAll("/", "_").replaceAll("\\", "_") || "dataset"}.csv`;
      link.href = URL.createObjectURL(blob);
      link.download = safeName;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(link.href);
      setToast(`Exported ${safeName}`, "ok");
    }

    async function saveCopy() {
      const suggested = state.selected.endsWith(".csv") ? state.selected : `${state.selected}_copy.csv`;
      const relativePath = window.prompt("Relative CSV path for the copy", suggested);
      if (!relativePath) return;
      const register = window.confirm("Register this copy in manifest?");
      const dataset = register ? window.prompt("Manifest dataset name", relativePath.replace(/\.csv$/i, "")) : "";
      const data = await api("/api/save-copy", {
        method: "POST",
        body: JSON.stringify({
          ...payload(),
          relative_path: relativePath,
          register,
          new_dataset: dataset,
          notes: `Copy of ${state.selected}`
        })
      });
      await loadCatalog(data.dataset || state.selected);
      setToast(`Saved copy: ${data.relative_path}`, "ok");
    }

    function addRow() {
      state.rows.push(state.columns.map(() => ""));
      state.page = Math.max(0, Math.ceil(filteredIndices().length / state.pageSize) - 1);
      markDirty();
      renderGrid();
    }

    function deleteRows() {
      if (!state.selectedRows.size) {
        setToast("Select rows to delete");
        return;
      }
      if (!window.confirm(`Delete ${state.selectedRows.size} selected row(s)?`)) return;
      state.rows = state.rows.filter((_, index) => !state.selectedRows.has(index));
      state.selectedRows = new Set();
      state.page = 0;
      markDirty();
      renderGrid();
    }

    function addColumn() {
      const name = window.prompt("New column name", `column_${state.columns.length + 1}`);
      if (!name) return;
      state.columns.push(name);
      state.rows.forEach(row => row.push(""));
      markDirty();
      renderGrid();
    }

    function chooseColumn(action) {
      const name = window.prompt(`Column to ${action}`, state.columns[0] || "");
      if (!name) return -1;
      const index = state.columns.indexOf(name);
      if (index === -1) setToast(`Column not found: ${name}`, "error");
      return index;
    }

    function renameColumn() {
      const index = chooseColumn("rename");
      if (index < 0) return;
      const name = window.prompt("New column name", state.columns[index]);
      if (!name) return;
      state.columns[index] = name;
      markDirty();
      renderGrid();
    }

    function deleteColumn() {
      const index = chooseColumn("delete");
      if (index < 0) return;
      if (!window.confirm(`Delete column ${state.columns[index]}?`)) return;
      state.columns.splice(index, 1);
      state.rows.forEach(row => row.splice(index, 1));
      markDirty();
      renderGrid();
    }

    els.grid.addEventListener("input", event => {
      const input = event.target.closest(".cell-input");
      if (!input) return;
      const row = Number(input.dataset.row);
      const col = Number(input.dataset.col);
      state.rows[row][col] = input.value;
      markDirty();
    });

    els.grid.addEventListener("change", event => {
      const checkbox = event.target.closest("[data-row-select]");
      if (!checkbox) return;
      const row = Number(checkbox.dataset.rowSelect);
      if (checkbox.checked) state.selectedRows.add(row);
      else state.selectedRows.delete(row);
    });

    els.dataset.addEventListener("change", async event => {
      if (state.dirty && !window.confirm("Discard unsaved edits?")) {
        els.dataset.value = state.selected;
        return;
      }
      state.selected = event.target.value;
      await loadSelected();
    });

    els.root.addEventListener("keydown", event => {
      if (event.key === "Enter") document.getElementById("load-root-btn").click();
    });

    document.getElementById("load-root-btn").addEventListener("click", async () => loadCatalog());
    document.getElementById("reload-btn").addEventListener("click", async () => {
      if (state.dirty && !window.confirm("Discard unsaved edits?")) return;
      await loadSelected();
    });
    document.getElementById("validate-btn").addEventListener("click", validateCurrent);
    document.getElementById("save-btn").addEventListener("click", saveCurrent);
    document.getElementById("export-btn").addEventListener("click", exportCsv);
    document.getElementById("save-copy-btn").addEventListener("click", saveCopy);
    document.getElementById("add-row-btn").addEventListener("click", addRow);
    document.getElementById("delete-row-btn").addEventListener("click", deleteRows);
    document.getElementById("add-column-btn").addEventListener("click", addColumn);
    document.getElementById("rename-column-btn").addEventListener("click", renameColumn);
    document.getElementById("delete-column-btn").addEventListener("click", deleteColumn);
    document.getElementById("prev-page-btn").addEventListener("click", () => {
      state.page = Math.max(0, state.page - 1);
      renderGrid();
    });
    document.getElementById("next-page-btn").addEventListener("click", () => {
      state.page += 1;
      renderGrid();
    });
    els.pageSize.addEventListener("change", event => {
      state.pageSize = Number(event.target.value);
      state.page = 0;
      renderGrid();
    });
    els.search.addEventListener("input", event => {
      state.search = event.target.value;
      state.page = 0;
      renderGrid();
    });

    loadCatalog().catch(error => {
      setToast(error.message, "error");
      els.dirty.textContent = "Catalog failed";
    });
  </script>
</body>
</html>
"""


RUNNER_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PyPSA Model Runner</title>
  <style>
    :root {
      --bg: #f5f7f8;
      --panel: #ffffff;
      --line: #d8dee4;
      --line-strong: #b7c0c8;
      --text: #17202a;
      --muted: #5e6b76;
      --blue: #1f6feb;
      --blue-dark: #1554b5;
      --green: #207a4b;
      --red: #b42318;
      --amber: #9a6700;
      --shadow: 0 10px 24px rgba(27, 39, 51, 0.08);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
    }

    button,
    input,
    select {
      font: inherit;
    }

    button {
      border: 1px solid var(--line-strong);
      background: #ffffff;
      color: var(--text);
      border-radius: 6px;
      min-height: 34px;
      padding: 0 12px;
      cursor: pointer;
    }

    button:hover:not(:disabled) {
      border-color: var(--blue);
      color: var(--blue-dark);
    }

    button:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }

    button.primary {
      min-height: 42px;
      padding: 0 22px;
      background: var(--blue);
      border-color: var(--blue);
      color: #ffffff;
      font-weight: 750;
      letter-spacing: 0;
    }

    button.primary:hover:not(:disabled) {
      background: var(--blue-dark);
      color: #ffffff;
    }

    input,
    select {
      width: 100%;
      min-height: 34px;
      padding: 6px 9px;
      border: 1px solid var(--line-strong);
      border-radius: 6px;
      background: #ffffff;
      color: var(--text);
      min-width: 0;
    }

    input[type="checkbox"] {
      width: 16px;
      min-height: 16px;
    }

    input:focus,
    select:focus,
    button:focus {
      outline: 2px solid rgba(31, 111, 235, 0.25);
      outline-offset: 1px;
    }

    .app {
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto auto 1fr;
    }

    .topbar {
      display: grid;
      grid-template-columns: minmax(210px, 280px) minmax(300px, 1fr) auto;
      gap: 12px;
      align-items: end;
      padding: 14px 16px;
      background: var(--panel);
      border-bottom: 1px solid var(--line);
      position: sticky;
      top: 0;
      z-index: 10;
    }

    .brand {
      display: grid;
      gap: 3px;
      align-self: center;
    }

    h1,
    h2 {
      margin: 0;
      letter-spacing: 0;
    }

    h1 {
      font-size: 18px;
      line-height: 1.2;
    }

    h2 {
      font-size: 15px;
      line-height: 1.3;
    }

    .subtitle {
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .nav-links {
      display: flex;
      gap: 10px;
      align-items: center;
      font-size: 12px;
      font-weight: 650;
    }

    .nav-links a {
      color: var(--blue-dark);
      text-decoration: none;
    }

    .nav-links a:hover {
      text-decoration: underline;
    }

    .topbar {
      grid-template-columns: minmax(220px, 300px) minmax(360px, 1fr);
      gap: 10px 14px;
      align-items: center;
      padding: 12px 16px 10px;
      background: linear-gradient(180deg, #fbfcfe 0%, #eef3f7 100%);
      box-shadow: 0 1px 0 rgba(17, 24, 39, 0.04);
    }

    .nav-links {
      justify-self: stretch;
      flex-wrap: wrap;
      gap: 6px;
      padding: 6px;
      border: 1px solid #d4dde6;
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.82);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.85);
    }

    .nav-links a {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 30px;
      padding: 0 10px;
      border: 1px solid transparent;
      border-radius: 6px;
      color: #243548;
      text-decoration: none;
      white-space: nowrap;
    }

    .nav-links a:hover {
      border-color: #c8d4df;
      background: #f5f8fb;
      text-decoration: none;
    }

    .nav-links a[aria-current="page"] {
      border-color: rgba(31, 111, 235, 0.2);
      background: var(--blue);
      color: #ffffff;
      box-shadow: 0 1px 2px rgba(31, 111, 235, 0.18);
    }

    .nav-primary {
      font-weight: 750;
    }

    .nav-group {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 2px 0 2px 8px;
      border-left: 1px solid #d9e2eb;
    }

    .nav-group span {
      color: var(--muted);
      font-size: 10px;
      font-weight: 750;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      margin-right: 2px;
      white-space: nowrap;
    }

    .root-tools {
      grid-column: 2 / -1;
      display: grid;
      grid-template-columns: auto minmax(280px, 1fr) auto minmax(160px, 0.6fr);
      gap: 8px;
      align-items: center;
      padding: 7px 8px;
      border: 1px solid #d8e1ea;
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.62);
    }

    .root-tools label,
    .root-status {
      color: var(--muted);
      font-size: 11px;
      font-weight: 650;
    }

    .root-tools input {
      min-height: 28px;
      padding: 4px 8px;
      font-size: 12px;
    }

    .root-tools button {
      min-height: 28px;
      padding: 4px 10px;
      font-size: 12px;
    }

    .root-status {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .field {
      display: grid;
      gap: 5px;
    }

    .field label,
    .check-row span {
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }

    .status-strip {
      display: grid;
      grid-template-columns: repeat(4, minmax(120px, 1fr));
      gap: 10px;
      padding: 10px 16px;
      border-bottom: 1px solid var(--line);
      background: #eef2f5;
    }

    .metric {
      min-width: 0;
      display: grid;
      gap: 2px;
    }

    .metric span {
      color: var(--muted);
      font-size: 11px;
      font-weight: 650;
      text-transform: uppercase;
    }

    .metric strong {
      min-width: 0;
      font-size: 13px;
      font-weight: 650;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .workspace {
      min-height: 0;
      display: grid;
      grid-template-columns: minmax(320px, 420px) minmax(0, 1fr);
      gap: 14px;
      padding: 14px 16px;
    }

    .panel {
      min-width: 0;
      min-height: 0;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }

    .control-panel {
      display: grid;
      align-content: start;
      gap: 14px;
      padding: 14px;
    }

    .section {
      display: grid;
      gap: 10px;
      padding-bottom: 14px;
      border-bottom: 1px solid var(--line);
    }

    .section:last-child {
      border-bottom: 0;
      padding-bottom: 0;
    }

    .check-row {
      display: flex;
      align-items: center;
      gap: 8px;
      min-height: 28px;
    }

    .fixed-model {
      display: grid;
      gap: 4px;
      padding: 10px;
      border: 1px solid #cfd9e2;
      border-radius: 8px;
      background: #f7fafc;
    }

    .fixed-model span {
      color: var(--muted);
      font-size: 11px;
      font-weight: 750;
      text-transform: uppercase;
    }

    .fixed-model strong {
      color: var(--ink);
      font-size: 13px;
      font-weight: 750;
    }

    .fixed-model small {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
    }

    .run-row {
      display: flex;
      gap: 8px;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
    }

    .progress-area {
      display: grid;
      gap: 7px;
    }

    .progress-track {
      width: 100%;
      height: 10px;
      border-radius: 999px;
      background: #e7ebef;
      border: 1px solid var(--line);
      overflow: hidden;
    }

    .progress-bar {
      width: 0%;
      height: 100%;
      background: var(--blue);
      transition: width 240ms ease;
    }

    .progress-text {
      color: var(--muted);
      font-size: 12px;
      min-height: 16px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .pill {
      border-radius: 999px;
      border: 1px solid var(--line-strong);
      padding: 4px 9px;
      font-size: 12px;
      color: var(--muted);
      background: #ffffff;
      white-space: nowrap;
    }

    .pill.ok {
      color: var(--green);
      border-color: rgba(32, 122, 75, 0.45);
      background: #edf8f1;
    }

    .pill.bad {
      color: var(--red);
      border-color: rgba(180, 35, 24, 0.4);
      background: #fff1f0;
    }

    .output-panel {
      display: grid;
      grid-template-rows: auto auto 1fr;
    }

    .output-head {
      display: flex;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
      padding: 12px;
      border-bottom: 1px solid var(--line);
    }

    .command {
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      background: #fafbfc;
      color: var(--muted);
      font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .logs {
      min-height: 0;
      display: grid;
      grid-template-rows: 1fr 180px;
    }

    .log-block {
      min-height: 0;
      display: grid;
      grid-template-rows: auto 1fr;
      border-bottom: 1px solid var(--line);
    }

    .log-block:last-child {
      border-bottom: 0;
    }

    .log-label {
      padding: 8px 12px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
      background: #f0f3f6;
      border-bottom: 1px solid var(--line);
    }

    pre {
      margin: 0;
      padding: 12px;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
      font-size: 12px;
      line-height: 1.45;
      background: #ffffff;
    }

    @media (max-width: 1020px) {
      .topbar,
      .status-strip,
      .workspace {
        grid-template-columns: 1fr;
      }

      .root-tools {
        grid-column: 1 / -1;
        grid-template-columns: auto minmax(0, 1fr) auto;
      }

      .root-status {
        grid-column: 1 / -1;
      }

      .logs {
        grid-template-rows: minmax(260px, 1fr) 180px;
      }
    }
  </style>
</head>
<body>
  <div class="app">
    <header class="topbar">
      <div class="brand">
        <h1>PyPSA Model Runner</h1>
        <div class="subtitle">Fast stochastic scenario solve controls</div>
      </div>
      <nav class="nav-links" aria-label="Application navigation">
        <a class="nav-primary" href="/runner" aria-current="page">Model Runner</a>
        <div class="nav-group" aria-label="Input pages">
          <span>Inputs</span>
          <a href="/inputs">Visual</a>
          <a href="/">CSV Editor</a>
        </div>
        <div class="nav-group" aria-label="Output pages">
          <span>Outputs</span>
          <a href="/dashboard">Visual</a>
          <a href="/topology">Topology</a>
        </div>
      </nav>
      <div class="root-tools" aria-label="Data root">
        <label for="root-input">Data root</label>
        <input id="root-input" autocomplete="off">
        <button id="load-root-btn">Load</button>
        <span class="root-status" id="root-status">Loading data root</span>
      </div>
    </header>

    <section class="status-strip" aria-label="Run status">
      <div class="metric"><span>Script</span><strong id="script-path">-</strong></div>
      <div class="metric"><span>Run directory</span><strong id="run-dir">-</strong></div>
      <div class="metric"><span>Return code</span><strong id="return-code">-</strong></div>
      <div class="metric"><span>Duration</span><strong id="duration">-</strong></div>
    </section>

    <main class="workspace">
      <section class="panel control-panel" aria-label="Model run controls">
        <div class="section">
          <h2>Data Sources</h2>
          <div class="field">
            <label for="load-select">Load profile</label>
            <select id="load-select"></select>
          </div>
          <div class="field">
            <label for="solar-select">NSJ SF rating profile</label>
            <select id="solar-select"></select>
          </div>
        </div>

        <div class="section">
          <h2>Solve Settings</h2>
          <div class="fixed-model">
            <span>Power model</span>
            <strong id="power-model-label">network_from_png_gurobi_fast.py</strong>
            <small id="power-model-note">Runs the fast custom stochastic scenario.</small>
          </div>
          <select id="power-model-select" hidden aria-hidden="true" style="display:none"></select>
          <div class="field">
            <label for="solver-select">Solver</label>
            <select id="solver-select"></select>
          </div>
          <label class="check-row">
            <input id="solver-log" type="checkbox">
            <span>Solver log</span>
          </label>
          <div class="field">
            <label for="horizon-hours-input">Reporting horizon hours</label>
            <input id="horizon-hours-input" type="number" min="1" max="8760" step="1" value="24">
          </div>
          <div class="field">
            <label for="lookahead-hours-input">Lookahead hours</label>
            <input id="lookahead-hours-input" type="number" min="0" max="8760" step="1" value="24">
          </div>
          <div class="field">
            <label for="nonanticipative-hours-input">Generation non-anticipativity hours</label>
            <input id="nonanticipative-hours-input" type="number" min="0" max="8760" step="0.5" value="20">
          </div>
          <div class="field">
            <label for="solver-time-limit-input">Solver time limit seconds</label>
            <input id="solver-time-limit-input" type="number" min="1" step="1" value="360">
          </div>
          <div class="field">
            <label for="solver-mip-gap-input">Solver MIP gap</label>
            <input id="solver-mip-gap-input" type="number" min="0" max="1" step="0.0005" value="0.005">
          </div>
        </div>

        <div class="section">
          <div class="run-row">
            <button class="primary" id="run-btn">RUN</button>
            <button id="cancel-run-btn" disabled>Cancel</button>
            <span class="pill" id="run-status">Ready</span>
          </div>
          <div class="progress-area">
            <div class="progress-track" aria-label="Solve progress"><div class="progress-bar" id="progress-bar"></div></div>
            <div class="progress-text" id="progress-text">Ready.</div>
          </div>
        </div>
      </section>

      <section class="panel output-panel" aria-label="Model run output">
        <div class="output-head">
          <h2>Run Output</h2>
          <span class="pill" id="output-status">No run yet</span>
        </div>
        <div class="command" id="command-line">Command will appear after a run.</div>
        <div class="logs">
          <div class="log-block">
            <div class="log-label">Standard Output</div>
            <pre id="stdout">Waiting for RUN.</pre>
          </div>
          <div class="log-block">
            <div class="log-label">Standard Error</div>
            <pre id="stderr"></pre>
          </div>
        </div>
      </section>
    </main>
  </div>

  <script>
    const els = {
      root: document.getElementById("root-input"),
      rootStatus: document.getElementById("root-status"),
      scriptPath: document.getElementById("script-path"),
      runDir: document.getElementById("run-dir"),
      returnCode: document.getElementById("return-code"),
      duration: document.getElementById("duration"),
      load: document.getElementById("load-select"),
      solar: document.getElementById("solar-select"),
      powerModel: document.getElementById("power-model-select"),
      powerModelLabel: document.getElementById("power-model-label"),
      powerModelNote: document.getElementById("power-model-note"),
      solver: document.getElementById("solver-select"),
      solverLog: document.getElementById("solver-log"),
      horizonHours: document.getElementById("horizon-hours-input"),
      lookaheadHours: document.getElementById("lookahead-hours-input"),
      nonanticipativeHours: document.getElementById("nonanticipative-hours-input"),
      solverTimeLimit: document.getElementById("solver-time-limit-input"),
      solverMipGap: document.getElementById("solver-mip-gap-input"),
      run: document.getElementById("run-btn"),
      cancel: document.getElementById("cancel-run-btn"),
      runStatus: document.getElementById("run-status"),
      outputStatus: document.getElementById("output-status"),
      command: document.getElementById("command-line"),
      progressBar: document.getElementById("progress-bar"),
      progressText: document.getElementById("progress-text"),
      stdout: document.getElementById("stdout"),
      stderr: document.getElementById("stderr")
    };

    const runnerState = { jobId: "", pollTimer: null, modelOptions: [] };
    const runnerWindowSettingsKey = "pypsaRunnerWindowSettings";

    function saveRunnerWindowSettings() {
      const settings = {
        horizon_hours: Number(els.horizonHours.value || 24),
        lookahead_hours: Number(els.lookaheadHours.value || 24),
        nonanticipative_hours: Number(els.nonanticipativeHours.value || 20),
        solver_time_limit: Number(els.solverTimeLimit.value || 360),
        solver_mip_gap: Number(els.solverMipGap.value || 0.005)
      };
      localStorage.setItem(runnerWindowSettingsKey, JSON.stringify(settings));
      return settings;
    }

    function restoreRunnerWindowSettings(defaultHorizon, defaultLookahead, defaultNonanticipative) {
      let settings = {};
      try {
        settings = JSON.parse(localStorage.getItem(runnerWindowSettingsKey) || "{}") || {};
      } catch (_error) {
        settings = {};
      }
      els.horizonHours.value = Number.isFinite(Number(settings.horizon_hours)) ? settings.horizon_hours : defaultHorizon;
      els.lookaheadHours.value = Number.isFinite(Number(settings.lookahead_hours)) ? settings.lookahead_hours : defaultLookahead;
      els.nonanticipativeHours.value = Number.isFinite(Number(settings.nonanticipative_hours)) ? settings.nonanticipative_hours : defaultNonanticipative;
      els.solverTimeLimit.value = Number.isFinite(Number(settings.solver_time_limit)) ? settings.solver_time_limit : 360;
      els.solverMipGap.value = Number.isFinite(Number(settings.solver_mip_gap)) ? settings.solver_mip_gap : 0.005;
      saveRunnerWindowSettings();
    }

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }

    function api(path, options = {}) {
      const headers = options.headers || {};
      if (options.body && !headers["Content-Type"]) {
        headers["Content-Type"] = "application/json";
      }
      return fetch(path, { ...options, headers }).then(async response => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.ok === false) {
          throw new Error(data.error || response.statusText);
        }
        return data;
      });
    }

    function setStatus(text, kind = "") {
      els.runStatus.textContent = text;
      els.runStatus.className = "pill" + (kind ? " " + kind : "");
    }

    function setOutputStatus(text, kind = "") {
      els.outputStatus.textContent = text;
      els.outputStatus.className = "pill" + (kind ? " " + kind : "");
    }

    function setProgress(percent, text) {
      els.progressBar.style.width = `${Math.max(0, Math.min(100, Number(percent || 0)))}%`;
      els.progressText.textContent = text || "";
    }

    function optionLabel(item) {
      return `${item.dataset} - ${item.relative_path}`;
    }

    function renderOptions(select, items, selected) {
      select.innerHTML = items.map(item => (
        `<option value="${escapeHtml(item.dataset)}">${escapeHtml(optionLabel(item))}</option>`
      )).join("");
      select.value = selected;
    }

    function renderSolverOptions(options, selected) {
      els.solver.innerHTML = options.map(item => (
        `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`
      )).join("");
      els.solver.value = selected;
    }

    function renderPowerModelOptions(options, selected) {
      runnerState.modelOptions = options;
      els.powerModel.innerHTML = options.map(item => (
        `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`
      )).join("");
      els.powerModel.value = selected;
      const model = selectedPowerModel();
      if (els.powerModelLabel) {
        els.powerModelLabel.textContent = model.label || "network_from_png_gurobi_fast.py";
      }
      if (els.powerModelNote) {
        els.powerModelNote.textContent = "Runs the fast custom stochastic scenario with the matching network_from_png_gurobi base module.";
      }
      updatePowerModelControls(true);
    }

    function selectedPowerModel() {
      return runnerState.modelOptions.find(item => item.value === els.powerModel.value) || runnerState.modelOptions[0] || {};
    }

    function powerModelPathText(model) {
      const script = model.script_path || model.script || "-";
      const required = Array.isArray(model.required_script_paths) && model.required_script_paths.length
        ? `; requires ${model.required_script_paths.join(", ")}`
        : "";
      const runner = model.command_script_path ? ` via ${model.command_script_path}` : "";
      return `${script}${required}${runner}`;
    }

    function updatePowerModelControls(resetSolver = false) {
      const model = selectedPowerModel();
      els.scriptPath.textContent = powerModelPathText(model);
      els.horizonHours.disabled = model.uses_horizon === false;
      els.lookaheadHours.disabled = model.uses_horizon === false;
      if (resetSolver && model.default_solver) {
        els.solver.value = model.default_solver;
      }
      if (resetSolver) {
        els.solverTimeLimit.value = model.solver_time_limit ?? 360;
        els.solverMipGap.value = model.solver_mip_gap ?? 0.005;
        saveRunnerWindowSettings();
      }
    }

    async function loadOptions() {
      setStatus("Loading");
      const rootParam = els.root.value.trim();
      const data = await api(`/api/run-options${rootParam ? `?root=${encodeURIComponent(rootParam)}` : ""}`);
      els.root.value = data.data_root;
      els.rootStatus.textContent = `Root: ${data.data_root}`;
      renderOptions(els.load, data.load_options, data.default_load);
      renderOptions(els.solar, data.solar_options, data.default_solar);
      renderSolverOptions(data.solver_options, data.default_solver);
      renderPowerModelOptions(data.power_model_options, data.default_power_model);
      restoreRunnerWindowSettings(data.default_horizon_hours, data.default_lookahead_hours, data.default_nonanticipative_hours);
      setStatus("Ready", "ok");
    }

    async function runModel() {
      setStatus("Running");
      setOutputStatus("Running");
      els.run.disabled = true;
      els.cancel.disabled = true;
      els.stdout.textContent = "";
      els.stderr.textContent = "";
      els.command.textContent = `Starting ${selectedPowerModel().label || "power model"}`;
      els.returnCode.textContent = "-";
      els.duration.textContent = "-";
      setProgress(4, "Queued.");
      saveRunnerWindowSettings();
      try {
        const data = await api("/api/start-run", {
          method: "POST",
          body: JSON.stringify({
            root: els.root.value.trim(),
            power_model: els.powerModel.value,
            load_dataset: els.load.value,
            solar_dataset: els.solar.value,
            solver_name: els.solver.value,
            solver_log: els.solverLog.checked,
            horizon_hours: Number(els.horizonHours.value),
            lookahead_hours: Number(els.lookaheadHours.value),
            nonanticipative_hours: Number(els.nonanticipativeHours.value),
            solver_time_limit: Number(els.solverTimeLimit.value),
            solver_mip_gap: Number(els.solverMipGap.value)
          })
        });
        runnerState.jobId = data.job_id;
        sessionStorage.setItem("pypsaActiveRunJobId", data.job_id);
        renderJob(data.job);
        startPolling();
      } catch (error) {
        setStatus("Failed", "bad");
        setOutputStatus("Request failed", "bad");
        els.stderr.textContent = error.message;
        els.run.disabled = false;
        els.cancel.disabled = true;
        setProgress(100, "Request failed.");
      }
    }

    function startPolling() {
      if (runnerState.pollTimer) clearInterval(runnerState.pollTimer);
      runnerState.pollTimer = setInterval(pollJob, 1000);
      pollJob();
    }

    function stopPolling() {
      if (runnerState.pollTimer) clearInterval(runnerState.pollTimer);
      runnerState.pollTimer = null;
    }

    async function pollJob() {
      if (!runnerState.jobId) return;
      try {
        const data = await api(`/api/run-status?job_id=${encodeURIComponent(runnerState.jobId)}`);
        renderJob(data.job);
      } catch (error) {
        setStatus("Failed", "bad");
        setOutputStatus("Polling failed", "bad");
        els.stderr.textContent = error.message;
        stopPolling();
        els.run.disabled = false;
        els.cancel.disabled = true;
      }
    }

    function renderJob(job) {
      els.runDir.textContent = job.run_dir || "-";
      els.returnCode.textContent = job.returncode === null || job.returncode === undefined ? "-" : String(job.returncode);
      els.duration.textContent = job.duration_seconds === null || job.duration_seconds === undefined ? "-" : `${Number(job.duration_seconds).toFixed(2)}s`;
      els.command.textContent = job.command || "-";
      els.stdout.textContent = job.stdout || "";
      els.stderr.textContent = job.stderr || "";
      const hasPowerModelOption = Array.from(els.powerModel.options).some(option => option.value === job.power_model);
      if (job.power_model && hasPowerModelOption) {
        els.powerModel.value = job.power_model;
        updatePowerModelControls(false);
      }
      els.stdout.scrollTop = els.stdout.scrollHeight;
      els.stderr.scrollTop = els.stderr.scrollHeight;
      setProgress(job.progress || 0, job.stage_detail || job.stage || "");

      if (job.status === "complete") {
        setStatus("Complete", "ok");
        setOutputStatus("Succeeded", "ok");
        stopPolling();
        sessionStorage.removeItem("pypsaActiveRunJobId");
        els.run.disabled = false;
        els.cancel.disabled = true;
      } else if (job.status === "failed") {
        setStatus(job.timed_out ? "Timed out" : "Failed", "bad");
        setOutputStatus(job.timed_out ? "Timed out" : "Failed", "bad");
        stopPolling();
        sessionStorage.removeItem("pypsaActiveRunJobId");
        els.run.disabled = false;
        els.cancel.disabled = true;
      } else if (job.status === "cancelled") {
        setStatus("Cancelled", "bad");
        setOutputStatus("Cancelled", "bad");
        stopPolling();
        sessionStorage.removeItem("pypsaActiveRunJobId");
        els.run.disabled = false;
        els.cancel.disabled = true;
      } else {
        setStatus("Running");
        setOutputStatus(job.stage || "Running");
        els.run.disabled = true;
        els.cancel.disabled = false;
      }
    }

    async function cancelRun() {
      if (!runnerState.jobId) return;
      els.cancel.disabled = true;
      setProgress(95, "Cancelling solve process.");
      try {
        await api("/api/cancel-run", {
          method: "POST",
          body: JSON.stringify({ job_id: runnerState.jobId })
        });
      } catch (error) {
        els.stderr.textContent += `\nCancel failed: ${error.message}`;
      }
    }

    async function reattachActiveRun() {
      const storedJobId = sessionStorage.getItem("pypsaActiveRunJobId");
      if (storedJobId) {
        try {
          const data = await api(`/api/run-status?job_id=${encodeURIComponent(storedJobId)}`);
          if (["queued", "running"].includes(data.job.status)) {
            runnerState.jobId = storedJobId;
            renderJob(data.job);
            startPolling();
            return;
          }
          sessionStorage.removeItem("pypsaActiveRunJobId");
        } catch (_error) {
          sessionStorage.removeItem("pypsaActiveRunJobId");
        }
      }

      try {
        const data = await api("/api/active-run");
        if (data.job && ["queued", "running"].includes(data.job.status)) {
          runnerState.jobId = data.job.job_id;
          sessionStorage.setItem("pypsaActiveRunJobId", data.job.job_id);
          renderJob(data.job);
          startPolling();
        }
      } catch (_error) {
        // No active run to reattach.
      }
    }

    document.getElementById("load-root-btn").addEventListener("click", () => {
      loadOptions().catch(error => setStatus(error.message, "bad"));
    });
    els.root.addEventListener("keydown", event => {
      if (event.key === "Enter") document.getElementById("load-root-btn").click();
    });
    els.powerModel.addEventListener("change", () => updatePowerModelControls(true));
    els.horizonHours.addEventListener("input", saveRunnerWindowSettings);
    els.lookaheadHours.addEventListener("input", saveRunnerWindowSettings);
    els.nonanticipativeHours.addEventListener("input", saveRunnerWindowSettings);
    els.solverTimeLimit.addEventListener("input", saveRunnerWindowSettings);
    els.solverMipGap.addEventListener("input", saveRunnerWindowSettings);
    els.horizonHours.addEventListener("change", saveRunnerWindowSettings);
    els.lookaheadHours.addEventListener("change", saveRunnerWindowSettings);
    els.nonanticipativeHours.addEventListener("change", saveRunnerWindowSettings);
    els.solverTimeLimit.addEventListener("change", saveRunnerWindowSettings);
    els.solverMipGap.addEventListener("change", saveRunnerWindowSettings);
    els.run.addEventListener("click", runModel);
    els.cancel.addEventListener("click", cancelRun);

    loadOptions().then(reattachActiveRun).catch(error => {
      els.rootStatus.textContent = "Catalog failed";
      setStatus(error.message, "bad");
    });
  </script>
</body>
</html>
"""


DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PyPSA Output Dashboard</title>
  <style>
    :root {
      --bg: #f5f7f8;
      --panel: #ffffff;
      --line: #d8dee4;
      --line-strong: #b7c0c8;
      --text: #17202a;
      --muted: #5e6b76;
      --blue: #1f6feb;
      --blue-dark: #1554b5;
      --green: #207a4b;
      --red: #b42318;
      --amber: #9a6700;
      --teal: #087f8c;
      --violet: #6f42c1;
      --shadow: 0 10px 24px rgba(27, 39, 51, 0.08);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
    }

    button,
    input,
    select {
      font: inherit;
    }

    button,
    select {
      min-height: 34px;
      border: 1px solid var(--line-strong);
      border-radius: 6px;
      background: #ffffff;
      color: var(--text);
      padding: 6px 10px;
    }

    button {
      cursor: pointer;
    }

    button:hover {
      border-color: var(--blue);
      color: var(--blue-dark);
    }

    select:focus,
    button:focus {
      outline: 2px solid rgba(31, 111, 235, 0.25);
      outline-offset: 1px;
    }

    .app {
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto auto 1fr;
    }

    .topbar {
      display: grid;
      grid-template-columns: minmax(220px, 300px) minmax(280px, 1fr) minmax(120px, 180px) auto;
      gap: 12px;
      align-items: end;
      padding: 14px 16px;
      background: var(--panel);
      border-bottom: 1px solid var(--line);
      position: sticky;
      top: 0;
      z-index: 10;
    }

    .brand {
      display: grid;
      gap: 3px;
      align-self: center;
    }

    h1,
    h2,
    h3 {
      margin: 0;
      letter-spacing: 0;
    }

    h1 {
      font-size: 18px;
      line-height: 1.2;
    }

    h2 {
      font-size: 15px;
      line-height: 1.3;
    }

    h3 {
      font-size: 13px;
      color: var(--muted);
      font-weight: 650;
    }

    .subtitle {
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .nav-links {
      display: flex;
      gap: 10px;
      align-items: center;
      font-size: 12px;
      font-weight: 650;
    }

    .nav-links a {
      color: var(--blue-dark);
      text-decoration: none;
    }

    .nav-links a:hover {
      text-decoration: underline;
    }

    .topbar {
      grid-template-columns: minmax(220px, 300px) minmax(360px, 1fr) minmax(160px, 280px) minmax(130px, 200px) auto;
      gap: 10px 14px;
      align-items: center;
      padding: 12px 16px 10px;
      background: linear-gradient(180deg, #fbfcfe 0%, #eef3f7 100%);
      box-shadow: 0 1px 0 rgba(17, 24, 39, 0.04);
    }

    .nav-links {
      justify-self: stretch;
      flex-wrap: wrap;
      gap: 6px;
      padding: 6px;
      border: 1px solid #d4dde6;
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.82);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.85);
    }

    .nav-links a {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 30px;
      padding: 0 10px;
      border: 1px solid transparent;
      border-radius: 6px;
      color: #243548;
      text-decoration: none;
      white-space: nowrap;
    }

    .nav-links a:hover {
      border-color: #c8d4df;
      background: #f5f8fb;
      text-decoration: none;
    }

    .nav-links a[aria-current="page"] {
      border-color: rgba(31, 111, 235, 0.2);
      background: var(--blue);
      color: #ffffff;
      box-shadow: 0 1px 2px rgba(31, 111, 235, 0.18);
    }

    .nav-primary {
      font-weight: 750;
    }

    .nav-group {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 2px 0 2px 8px;
      border-left: 1px solid #d9e2eb;
    }

    .nav-group span {
      color: var(--muted);
      font-size: 10px;
      font-weight: 750;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      margin-right: 2px;
      white-space: nowrap;
    }

    .field {
      min-width: 0;
      display: grid;
      gap: 5px;
    }

    .field label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }

    .field select {
      width: 100%;
    }

    .status-strip {
      display: grid;
      grid-template-columns: repeat(5, minmax(130px, 1fr));
      gap: 10px;
      padding: 10px 16px;
      background: #eef2f5;
      border-bottom: 1px solid var(--line);
    }

    .metric {
      min-width: 0;
      display: grid;
      gap: 2px;
    }

    .metric span {
      color: var(--muted);
      font-size: 11px;
      font-weight: 650;
      text-transform: uppercase;
    }

    .metric strong {
      min-width: 0;
      font-size: 13px;
      font-weight: 650;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .workspace {
      min-height: 0;
      padding: 14px 16px;
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(12, minmax(0, 1fr));
      align-content: start;
    }

    .summary {
      grid-column: 1 / -1;
      display: grid;
      grid-template-columns: repeat(6, minmax(130px, 1fr));
      gap: 10px;
    }

    .tile,
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }

    .tile {
      min-width: 0;
      padding: 12px;
      display: grid;
      gap: 4px;
    }

    .tile span {
      color: var(--muted);
      font-size: 11px;
      font-weight: 650;
      text-transform: uppercase;
    }

    .tile strong {
      font-size: 22px;
      line-height: 1.15;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .tile small {
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .panel {
      min-width: 0;
      min-height: 320px;
      display: grid;
      grid-template-rows: auto 1fr;
    }

    .panel.wide {
      grid-column: span 8;
    }

    .panel.full {
      grid-column: 1 / -1;
    }

    .panel.side {
      grid-column: span 4;
    }

    .panel.half {
      grid-column: span 6;
    }

    [hidden] {
      display: none !important;
    }

    .panel-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      padding: 12px;
      border-bottom: 1px solid var(--line);
    }

    .legend {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 12px;
    }

    .legend span {
      display: inline-flex;
      align-items: center;
      gap: 5px;
    }

    .chart-controls {
      min-width: min(280px, 100%);
      display: flex;
      gap: 8px;
      align-items: center;
      justify-content: flex-end;
      flex-wrap: wrap;
    }

    .chart-controls label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }

    .chart-controls select {
      width: min(260px, 100%);
    }

    .dot {
      width: 10px;
      height: 10px;
      border-radius: 999px;
      display: inline-block;
    }

    .panel-body {
      min-height: 0;
      padding: 10px;
      overflow: auto;
    }

    svg {
      display: block;
      width: 100%;
      height: 280px;
      overflow: visible;
    }

    .axis {
      stroke: #aeb7c2;
      stroke-width: 1;
    }

    .grid {
      stroke: #e7ebef;
      stroke-width: 1;
    }

    .label {
      fill: var(--muted);
      font-size: 11px;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }

    th,
    td {
      text-align: left;
      border-bottom: 1px solid var(--line);
      padding: 7px 8px;
      white-space: nowrap;
    }

    th {
      color: var(--muted);
      font-weight: 650;
      background: #f0f3f6;
      position: sticky;
      top: 0;
    }

    td.num {
      text-align: right;
      font-variant-numeric: tabular-nums;
    }

    .empty {
      color: var(--muted);
      padding: 12px;
      font-size: 13px;
    }

    @media (max-width: 1180px) {
      .topbar,
      .status-strip,
      .summary {
        grid-template-columns: 1fr 1fr;
      }

      .panel.wide,
      .panel.full,
      .panel.side,
      .panel.half {
        grid-column: 1 / -1;
      }
    }

    @media (max-width: 760px) {
      .topbar,
      .status-strip,
      .summary {
        grid-template-columns: 1fr;
      }

      .workspace {
        padding: 10px;
      }
    }
  </style>
</head>
<body>
  <div class="app">
    <header class="topbar">
      <div class="brand">
        <h1>PyPSA Output Dashboard</h1>
        <div class="subtitle" id="dashboard-status">Loading runs</div>
      </div>
      <nav class="nav-links" aria-label="Application navigation">
        <a class="nav-primary" href="/runner">Model Runner</a>
        <div class="nav-group" aria-label="Input pages">
          <span>Inputs</span>
          <a href="/inputs">Visual</a>
          <a href="/">CSV Editor</a>
        </div>
        <div class="nav-group" aria-label="Output pages">
          <span>Outputs</span>
          <a href="/dashboard" aria-current="page">Visual</a>
          <a href="/topology">Topology</a>
        </div>
      </nav>
      <div class="field">
        <label for="run-select">Run</label>
        <select id="run-select"></select>
      </div>
      <div class="field">
        <label for="sample-select">Sample</label>
        <select id="sample-select"></select>
      </div>
      <button id="refresh-btn">Refresh</button>
    </header>

    <section class="status-strip" aria-label="Dashboard metadata">
      <div class="metric"><span>Output folder</span><strong id="output-dir">-</strong></div>
      <div class="metric"><span>Snapshots</span><strong id="snapshots">-</strong></div>
      <div class="metric"><span>Samples</span><strong id="samples">-</strong></div>
      <div class="metric"><span>Interval</span><strong id="interval">-</strong></div>
      <div class="metric"><span>Non-anticipativity</span><strong id="nonanticipativity">-</strong></div>
    </section>

    <main class="workspace">
      <section class="summary" id="summary"></section>

      <section class="panel full">
        <div class="panel-head">
          <h2>Fleet Mix And Load</h2>
          <div class="legend">
            <span><i class="dot" style="background: var(--blue)"></i> Thermal</span>
            <span><i class="dot" style="background: var(--amber)"></i> Solar</span>
            <span><i class="dot" style="background: var(--green)"></i> Load</span>
            <span><i class="dot" style="background: var(--red)"></i> Unserved</span>
          </div>
        </div>
        <div class="panel-body"><svg id="mix-chart" role="img" aria-label="Thermal generation, solar generation, load, and unserved energy over time"></svg></div>
      </section>

      <section class="panel wide">
        <div class="panel-head">
          <h2>Generation Mix And Demand</h2>
          <div class="chart-controls">
            <div class="legend">
              <span><i class="dot" style="background: var(--blue)"></i> Generation samples</span>
              <span><i class="dot" style="background: var(--green)"></i> Load</span>
              <span><i class="dot" style="background: var(--red)"></i> Unserved</span>
            </div>
            <label for="dispatch-series-select">Graph series</label>
            <select id="dispatch-series-select"></select>
          </div>
        </div>
        <div class="panel-body"><svg id="timeseries-chart" role="img" aria-label="Thermal generation, solar generation, load, and unserved energy over time"></svg></div>
      </section>

      <section class="panel wide" id="reserve-panel" hidden>
        <div class="panel-head">
          <h2>Reserve Coverage</h2>
          <div class="chart-controls">
            <div class="legend">
              <span><i class="dot" style="background: #1f6feb"></i>S1</span>
              <span><i class="dot" style="background: #087f8c"></i>S2</span>
              <span><i class="dot" style="background: #6f42c1"></i>S3</span>
              <span><i class="dot" style="background: #b7791f"></i>S4</span>
              <span><i class="dot" style="background: #c2410c"></i>S5</span>
            </div>
            <label for="reserve-select">Reserve</label>
            <select id="reserve-select"></select>
            <label for="reserve-quantity-select">Quantity</label>
            <select id="reserve-quantity-select"></select>
          </div>
        </div>
        <div class="panel-body"><svg id="reserve-chart" role="img" aria-label="Reserve requirement, provision, and shortage over time"></svg></div>
      </section>

      <section class="panel wide" id="battery-panel" hidden>
        <div class="panel-head">
          <h2>BESS State Of Charge</h2>
          <div class="chart-controls">
            <div class="legend">
              <span><i class="dot" style="background: #1f6feb"></i>S1</span>
              <span><i class="dot" style="background: #087f8c"></i>S2</span>
              <span><i class="dot" style="background: #6f42c1"></i>S3</span>
              <span><i class="dot" style="background: #b7791f"></i>S4</span>
              <span><i class="dot" style="background: #c2410c"></i>S5</span>
            </div>
            <label for="battery-select">Battery</label>
            <select id="battery-select"></select>
          </div>
        </div>
        <div class="panel-body"><svg id="battery-soc-chart" role="img" aria-label="BESS state of charge over time"></svg></div>
      </section>

      <section class="panel side" id="reserve-summary-panel" hidden>
        <div class="panel-head"><h2>Reserve Summary</h2></div>
        <div class="panel-body">
          <table id="reserve-summary-table"></table>
          <table id="reserve-provider-table"></table>
        </div>
      </section>

      <section class="panel side">
        <div class="panel-head"><h2>Load By Bus</h2></div>
        <div class="panel-body"><svg id="load-chart" role="img" aria-label="Load by bus"></svg></div>
      </section>

      <section class="panel half">
        <div class="panel-head"><h2>Generation By Unit</h2></div>
        <div class="panel-body"><svg id="thermal-chart" role="img" aria-label="Generation by unit"></svg></div>
      </section>

      <section class="panel half">
        <div class="panel-head"><h2>Unserved Energy By Bus</h2></div>
        <div class="panel-body"><svg id="unserved-chart" role="img" aria-label="Unserved energy by bus"></svg></div>
      </section>

      <section class="panel wide">
        <div class="panel-head"><h2>Top Generators</h2></div>
        <div class="panel-body"><table id="thermal-table"></table></div>
      </section>

      <section class="panel side">
        <div class="panel-head"><h2>Run Files</h2></div>
        <div class="panel-body"><table id="files-table"></table></div>
      </section>
    </main>
  </div>

  <script>
    const els = {
      status: document.getElementById("dashboard-status"),
      run: document.getElementById("run-select"),
      sample: document.getElementById("sample-select"),
      dispatchSeries: document.getElementById("dispatch-series-select"),
      reservePanel: document.getElementById("reserve-panel"),
      reserveSummaryPanel: document.getElementById("reserve-summary-panel"),
      reserveSelect: document.getElementById("reserve-select"),
      reserveQuantity: document.getElementById("reserve-quantity-select"),
      batteryPanel: document.getElementById("battery-panel"),
      batterySelect: document.getElementById("battery-select"),
      outputDir: document.getElementById("output-dir"),
      snapshots: document.getElementById("snapshots"),
      samples: document.getElementById("samples"),
      interval: document.getElementById("interval"),
      nonanticipativity: document.getElementById("nonanticipativity"),
      summary: document.getElementById("summary"),
      mixChart: document.getElementById("mix-chart"),
      timeseries: document.getElementById("timeseries-chart"),
      reserveChart: document.getElementById("reserve-chart"),
      batterySocChart: document.getElementById("battery-soc-chart"),
      loadChart: document.getElementById("load-chart"),
      thermalChart: document.getElementById("thermal-chart"),
      unservedChart: document.getElementById("unserved-chart"),
      thermalTable: document.getElementById("thermal-table"),
      reserveSummaryTable: document.getElementById("reserve-summary-table"),
      reserveProviderTable: document.getElementById("reserve-provider-table"),
      filesTable: document.getElementById("files-table")
    };

    let latestReserveData = null;
    let latestBatterySocData = null;

    function api(path) {
      return fetch(path).then(async response => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.ok === false) {
          throw new Error(data.error || response.statusText);
        }
        return data;
      });
    }

    function esc(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }

    function fmt(value, digits = 1) {
      const number = Number(value || 0);
      return number.toLocaleString(undefined, { maximumFractionDigits: digits });
    }

    function fmtEnergy(value) {
      return `${fmt(value, 1)} MWh`;
    }

    function renderRunOptions(runs, selected) {
      els.run.innerHTML = runs.map(run => {
        const label = `${run.name} - ${run.status}`;
        return `<option value="${esc(run.name)}">${esc(label)}</option>`;
      }).join("");
      els.run.value = selected || runs[0]?.name || "";
    }

    function renderSampleOptions(samples, selected) {
      const options = ["all", ...samples];
      els.sample.innerHTML = options.map(sample => {
        const label = sample === "all" ? "All samples" : `Sample ${sample}`;
        return `<option value="${esc(sample)}">${esc(label)}</option>`;
      }).join("");
      els.sample.value = selected || "all";
    }

    function renderDispatchOptions(options, selected) {
      els.dispatchSeries.innerHTML = options.map(option => (
        `<option value="${esc(option.value)}">${esc(option.label)}</option>`
      )).join("");
      els.dispatchSeries.value = selected || "__fleet__";
    }

    function renderReserveQuantityOptions(reserveData, selectedReserve) {
      const reserve = reserveData?.series_by_reserve?.[selectedReserve] || {};
      const available = new Set(reserve.available_quantities || []);
      const options = (reserveData?.quantity_options || []).filter(option => !available.size || available.has(option.value));
      const current = els.reserveQuantity.value;
      els.reserveQuantity.innerHTML = options.map(option => (
        `<option value="${esc(option.value)}">${esc(option.label)}</option>`
      )).join("");
      els.reserveQuantity.value = options.some(option => option.value === current)
        ? current
        : reserve.default_quantity || reserveData?.selected_quantity || options[0]?.value || "provision";
    }

    function renderSummary(summary) {
      const solarNote = summary.has_generator_dispatch ? `Peak ${fmt(summary.peak_solar_mw)} MW` : "Run again to include solar";
      const tiles = [
        ["Total Thermal", fmtEnergy(summary.total_thermal_mwh), `Peak ${fmt(summary.peak_thermal_mw)} MW`],
        ["Total Solar", fmtEnergy(summary.total_solar_mwh), solarNote],
        ["Total Generation", fmtEnergy(summary.total_generation_mwh), `Peak ${fmt(summary.peak_generation_mw)} MW`],
        ["Total Load", fmtEnergy(summary.total_load_mwh), `Peak ${fmt(summary.peak_load_mw)} MW`],
        ["Unserved Energy", fmtEnergy(summary.total_unserved_mwh), `Peak ${fmt(summary.peak_unserved_mw, 4)} MW`],
        ["Solar Share", `${fmt(summary.solar_generation_pct, 2)}%`, "Solar over generation"]
      ];
      els.summary.innerHTML = tiles.map(([label, value, note]) => (
        `<div class="tile"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`
      )).join("");
    }

    function svgEl(tag, attrs = {}) {
      const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
      for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
      return node;
    }

    function clear(svg) {
      while (svg.firstChild) svg.removeChild(svg.firstChild);
    }

    function drawFleetMixChart(svg, rows) {
      clear(svg);
      if (!rows.length) {
        svg.appendChild(svgEl("text", { x: 16, y: 32, class: "label" })).textContent = "No time-series data.";
        return;
      }
      const width = svg.clientWidth || 960;
      const height = 280;
      const margin = { top: 16, right: 18, bottom: 34, left: 54 };
      const innerW = width - margin.left - margin.right;
      const innerH = height - margin.top - margin.bottom;
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      const thermal = row => Number(row.thermal_mw || 0);
      const solar = row => Number(row.solar_mw || 0);
      const totalGeneration = row => thermal(row) + solar(row);
      const maxY = Math.max(1, ...rows.flatMap(row => [totalGeneration(row), row.load_mw, row.unserved_mw]));
      const x = index => margin.left + (rows.length === 1 ? 0 : index * innerW / (rows.length - 1));
      const y = value => margin.top + innerH - (Number(value || 0) / maxY) * innerH;
      const hasSolarSeries = rows.some(row => Math.abs(Number(row.solar_mw || 0)) > 0.0001);

      for (let i = 0; i <= 4; i += 1) {
        const gy = margin.top + innerH * i / 4;
        svg.appendChild(svgEl("line", { x1: margin.left, y1: gy, x2: width - margin.right, y2: gy, class: "grid" }));
        svg.appendChild(svgEl("text", { x: 8, y: gy + 4, class: "label" })).textContent = fmt(maxY * (1 - i / 4), 0);
      }
      svg.appendChild(svgEl("line", { x1: margin.left, y1: margin.top, x2: margin.left, y2: margin.top + innerH, class: "axis" }));
      svg.appendChild(svgEl("line", { x1: margin.left, y1: margin.top + innerH, x2: width - margin.right, y2: margin.top + innerH, class: "axis" }));

      function drawArea(lower, upper, color, opacity) {
        if (rows.length < 2) return;
        const upperPoints = rows.map((row, index) => `${x(index)},${y(upper(row))}`);
        const lowerPoints = rows.slice().reverse().map((row, reverseIndex) => {
          const index = rows.length - 1 - reverseIndex;
          return `${x(index)},${y(lower(row))}`;
        });
        svg.appendChild(svgEl("polygon", { points: [...upperPoints, ...lowerPoints].join(" "), fill: color, opacity }));
      }

      drawArea(() => 0, thermal, "var(--blue)", "0.14");
      if (hasSolarSeries) drawArea(thermal, totalGeneration, "var(--amber)", "0.24");

      const series = [
        [thermal, "var(--blue)", 1.9],
        [totalGeneration, hasSolarSeries ? "var(--amber)" : "var(--blue)", 2.6],
        [row => row.load_mw, "var(--green)", 2.7],
        [row => row.unserved_mw, "var(--red)", 2]
      ];
      for (const [valueFn, color, strokeWidth] of series) {
        const points = rows.map((row, index) => `${x(index)},${y(valueFn(row))}`).join(" ");
        svg.appendChild(svgEl("polyline", { points, fill: "none", stroke: color, "stroke-width": strokeWidth, "stroke-linejoin": "round", "stroke-linecap": "round" }));
      }
      const first = rows[0].time_label || rows[0].time;
      const last = rows[rows.length - 1].time_label || rows[rows.length - 1].time;
      svg.appendChild(svgEl("text", { x: margin.left, y: height - 10, class: "label" })).textContent = first;
      const endLabel = svgEl("text", { x: width - margin.right, y: height - 10, class: "label", "text-anchor": "end" });
      endLabel.textContent = last;
      svg.appendChild(endLabel);
    }

    function drawDispatchChart(svg, chart) {
      clear(svg);
      const traces = chart?.traces || [];
      const timestamps = chart?.timestamps || [];
      if (!traces.length || !timestamps.length) {
        svg.appendChild(svgEl("text", { x: 16, y: 32, class: "label" })).textContent = "No time-series data.";
        return;
      }
      const width = svg.clientWidth || 760;
      const height = 280;
      const margin = { top: 16, right: 84, bottom: 34, left: 54 };
      const innerW = width - margin.left - margin.right;
      const innerH = height - margin.top - margin.bottom;
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      const maxY = Math.max(1, Number(chart.max_y || 0), ...traces.flatMap(trace => trace.points.map(point => Number(point.value_mw || 0))));
      const x = index => margin.left + (timestamps.length === 1 ? 0 : index * innerW / (timestamps.length - 1));
      const y = value => margin.top + innerH - (Number(value || 0) / maxY) * innerH;

      for (let i = 0; i <= 4; i += 1) {
        const gy = margin.top + innerH * i / 4;
        svg.appendChild(svgEl("line", { x1: margin.left, y1: gy, x2: width - margin.right, y2: gy, class: "grid" }));
        svg.appendChild(svgEl("text", { x: 8, y: gy + 4, class: "label" })).textContent = fmt(maxY * (1 - i / 4), 0);
      }
      svg.appendChild(svgEl("line", { x1: margin.left, y1: margin.top, x2: margin.left, y2: margin.top + innerH, class: "axis" }));
      svg.appendChild(svgEl("line", { x1: margin.left, y1: margin.top + innerH, x2: width - margin.right, y2: margin.top + innerH, class: "axis" }));

      traces.forEach((trace, traceIndex) => {
        const points = trace.points.map((point, index) => `${x(index)},${y(point.value_mw)}`).join(" ");
        const attrs = {
          points,
          fill: "none",
          stroke: trace.color || "var(--blue)",
          "stroke-width": trace.kind === "load" ? 2.8 : 2.2,
          "stroke-linejoin": "round",
          "stroke-linecap": "round",
          opacity: trace.kind === "unserved" ? 0.95 : 0.9
        };
        if (trace.dash) attrs["stroke-dasharray"] = trace.dash;
        svg.appendChild(svgEl("polyline", attrs));
        const finalPoint = trace.points[trace.points.length - 1] || { value_mw: 0 };
        if (traceIndex < 8) {
          const label = svgEl("text", {
            x: width - margin.right + 8,
            y: Math.max(margin.top + 10, Math.min(margin.top + innerH - 4, y(finalPoint.value_mw))),
            class: "label"
          });
          label.textContent = trace.name;
          svg.appendChild(label);
        }
      });

      const title = svgEl("text", { x: margin.left, y: margin.top - 3, class: "label" });
      title.textContent = chart.title || "";
      svg.appendChild(title);
      const first = timestamps[0]?.time_label || timestamps[0]?.time || "";
      const last = timestamps[timestamps.length - 1]?.time_label || timestamps[timestamps.length - 1]?.time || "";
      svg.appendChild(svgEl("text", { x: margin.left, y: height - 10, class: "label" })).textContent = first;
      const endLabel = svgEl("text", { x: width - margin.right, y: height - 10, class: "label", "text-anchor": "end" });
      endLabel.textContent = last;
      svg.appendChild(endLabel);
    }

    function drawReserveChart(svg, reserveData, selectedReserve, selectedQuantity) {
      clear(svg);
      const chart = reserveData?.series_by_reserve?.[selectedReserve]?.series_by_quantity?.[selectedQuantity];
      const traces = chart?.traces || [];
      const timestamps = chart?.timestamps || [];
      if (!traces.length || !timestamps.length) {
        svg.appendChild(svgEl("text", { x: 16, y: 32, class: "label" })).textContent = "No reserve interval data.";
        return;
      }
      const width = svg.clientWidth || 760;
      const height = 280;
      const margin = { top: 16, right: 90, bottom: 34, left: 54 };
      const innerW = width - margin.left - margin.right;
      const innerH = height - margin.top - margin.bottom;
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      const maxY = Math.max(1, Number(chart.max_y || 0), ...traces.flatMap(trace => trace.points.map(point => Number(point.value_mw || 0))));
      const x = index => margin.left + (timestamps.length === 1 ? 0 : index * innerW / (timestamps.length - 1));
      const y = value => margin.top + innerH - (Number(value || 0) / maxY) * innerH;

      for (let i = 0; i <= 4; i += 1) {
        const gy = margin.top + innerH * i / 4;
        svg.appendChild(svgEl("line", { x1: margin.left, y1: gy, x2: width - margin.right, y2: gy, class: "grid" }));
        svg.appendChild(svgEl("text", { x: 8, y: gy + 4, class: "label" })).textContent = fmt(maxY * (1 - i / 4), 0);
      }
      svg.appendChild(svgEl("line", { x1: margin.left, y1: margin.top, x2: margin.left, y2: margin.top + innerH, class: "axis" }));
      svg.appendChild(svgEl("line", { x1: margin.left, y1: margin.top + innerH, x2: width - margin.right, y2: margin.top + innerH, class: "axis" }));

      traces.forEach((trace, traceIndex) => {
        const points = trace.points.map((point, index) => `${x(index)},${y(point.value_mw)}`).join(" ");
        const attrs = {
          points,
          fill: "none",
          stroke: trace.color || "var(--blue)",
          "stroke-width": selectedQuantity === "shortage" ? 2.2 : 2.6,
          "stroke-linejoin": "round",
          "stroke-linecap": "round",
          opacity: selectedQuantity === "shortage" ? 0.95 : 0.9
        };
        if (trace.dash) attrs["stroke-dasharray"] = trace.dash;
        svg.appendChild(svgEl("polyline", attrs));
        const finalPoint = trace.points[trace.points.length - 1] || { value_mw: 0 };
        const label = svgEl("text", {
          x: width - margin.right + 8,
          y: Math.max(margin.top + 10, Math.min(margin.top + innerH - 4, y(finalPoint.value_mw) + traceIndex * 6)),
          class: "label"
        });
        label.textContent = trace.name;
        svg.appendChild(label);
      });

      const title = svgEl("text", { x: margin.left, y: margin.top - 3, class: "label" });
      title.textContent = chart.title || selectedReserve || "";
      svg.appendChild(title);
      const first = timestamps[0]?.time_label || timestamps[0]?.time || "";
      const last = timestamps[timestamps.length - 1]?.time_label || timestamps[timestamps.length - 1]?.time || "";
      svg.appendChild(svgEl("text", { x: margin.left, y: height - 10, class: "label" })).textContent = first;
      const endLabel = svgEl("text", { x: width - margin.right, y: height - 10, class: "label", "text-anchor": "end" });
      endLabel.textContent = last;
      svg.appendChild(endLabel);
    }

    function drawBatterySocChart(svg, batteryData, selectedBattery) {
      clear(svg);
      const chart = batteryData?.series_by_battery?.[selectedBattery];
      const traces = chart?.traces || [];
      const timestamps = chart?.timestamps || [];
      if (!traces.length || !timestamps.length) {
        svg.appendChild(svgEl("text", { x: 16, y: 32, class: "label" })).textContent = "No BESS state of charge data.";
        return;
      }
      const width = svg.clientWidth || 760;
      const height = 280;
      const margin = { top: 16, right: 90, bottom: 34, left: 54 };
      const innerW = width - margin.left - margin.right;
      const innerH = height - margin.top - margin.bottom;
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      const maxY = Math.max(1, Number(chart.max_y || 0), ...traces.flatMap(trace => trace.points.map(point => Number(point.value_mw || 0))));
      const x = index => margin.left + (timestamps.length === 1 ? 0 : index * innerW / (timestamps.length - 1));
      const y = value => margin.top + innerH - (Number(value || 0) / maxY) * innerH;

      for (let i = 0; i <= 4; i += 1) {
        const gy = margin.top + innerH * i / 4;
        svg.appendChild(svgEl("line", { x1: margin.left, y1: gy, x2: width - margin.right, y2: gy, class: "grid" }));
        svg.appendChild(svgEl("text", { x: 8, y: gy + 4, class: "label" })).textContent = fmt(maxY * (1 - i / 4), 0);
      }
      svg.appendChild(svgEl("line", { x1: margin.left, y1: margin.top, x2: margin.left, y2: margin.top + innerH, class: "axis" }));
      svg.appendChild(svgEl("line", { x1: margin.left, y1: margin.top + innerH, x2: width - margin.right, y2: margin.top + innerH, class: "axis" }));

      traces.forEach((trace, traceIndex) => {
        const points = trace.points.map((point, index) => `${x(index)},${y(point.value_mw)}`).join(" ");
        svg.appendChild(svgEl("polyline", {
          points,
          fill: "none",
          stroke: trace.color || "var(--blue)",
          "stroke-width": 2.6,
          "stroke-linejoin": "round",
          "stroke-linecap": "round",
          opacity: 0.92
        }));
        const finalPoint = trace.points[trace.points.length - 1] || { value_mw: 0 };
        const label = svgEl("text", {
          x: width - margin.right + 8,
          y: Math.max(margin.top + 10, Math.min(margin.top + innerH - 4, y(finalPoint.value_mw) + traceIndex * 6)),
          class: "label"
        });
        label.textContent = trace.name;
        svg.appendChild(label);
      });

      const title = svgEl("text", { x: margin.left, y: margin.top - 3, class: "label" });
      title.textContent = chart.title || selectedBattery || "";
      svg.appendChild(title);
      const first = timestamps[0]?.time_label || timestamps[0]?.time || "";
      const last = timestamps[timestamps.length - 1]?.time_label || timestamps[timestamps.length - 1]?.time || "";
      svg.appendChild(svgEl("text", { x: margin.left, y: height - 10, class: "label" })).textContent = first;
      const endLabel = svgEl("text", { x: width - margin.right, y: height - 10, class: "label", "text-anchor": "end" });
      endLabel.textContent = last;
      svg.appendChild(endLabel);
    }

    function drawBarChart(svg, rows, valueKey, labelKey, color) {
      clear(svg);
      const data = rows.filter(row => Number(row[valueKey]) > 0).slice(0, 15);
      if (!data.length) {
        svg.appendChild(svgEl("text", { x: 16, y: 32, class: "label" })).textContent = "No non-zero values.";
        return;
      }
      const width = svg.clientWidth || 500;
      const height = Math.max(280, data.length * 25 + 40);
      const margin = { top: 12, right: 18, bottom: 22, left: 128 };
      const innerW = width - margin.left - margin.right;
      const maxValue = Math.max(...data.map(row => Number(row[valueKey] || 0)), 1);
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      data.forEach((row, index) => {
        const y = margin.top + index * 25;
        const barW = Number(row[valueKey] || 0) / maxValue * innerW;
        const label = String(row[labelKey] || "");
        svg.appendChild(svgEl("text", { x: margin.left - 8, y: y + 15, class: "label", "text-anchor": "end" })).textContent = label;
        svg.appendChild(svgEl("rect", { x: margin.left, y, width: Math.max(1, barW), height: 17, rx: 3, fill: color }));
        svg.appendChild(svgEl("text", { x: margin.left + barW + 6, y: y + 14, class: "label" })).textContent = fmt(row[valueKey], 1);
      });
    }

    function renderThermalTable(rows) {
      const head = "<thead><tr><th>Generator</th><th class=\"num\">MWh</th><th class=\"num\">Peak MW</th></tr></thead>";
      const body = rows.slice(0, 18).map(row => (
        `<tr><td>${esc(row.generator)}</td><td class="num">${fmt(row.total_mwh, 1)}</td><td class="num">${fmt(row.peak_mw, 1)}</td></tr>`
      )).join("");
      els.thermalTable.innerHTML = head + `<tbody>${body}</tbody>`;
    }

    function renderReserveTables(reserveData, selectedReserve) {
      const summaryRows = (reserveData?.summary || []).filter(row => row.reserve === selectedReserve);
      const summaryHead = "<thead><tr><th>Metric</th><th class=\"num\">MW</th></tr></thead>";
      const summary = summaryRows[0] || {};
      const summaryBody = [
        ["Avg requirement", summary.avg_requirement_mw],
        ["Peak requirement", summary.peak_requirement_mw],
        ["Avg provision", summary.avg_provision_mw],
        ["Peak provision", summary.peak_provision_mw],
        ["Peak shortage", summary.peak_shortage_mw],
        ["Shortage MWh", summary.shortage_mwh]
      ].map(([label, value]) => `<tr><td>${esc(label)}</td><td class="num">${fmt(value, label === "Shortage MWh" ? 2 : 1)}</td></tr>`).join("");
      els.reserveSummaryTable.innerHTML = summaryHead + `<tbody>${summaryBody}</tbody>`;

      const providers = (reserveData?.providers || []).filter(row => row.reserve === selectedReserve).slice(0, 8);
      const providerHead = "<thead><tr><th>Provider</th><th class=\"num\">Avg MW</th><th class=\"num\">Peak MW</th></tr></thead>";
      const providerBody = providers.length
        ? providers.map(row => `<tr><td>${esc(row.provider)}</td><td class="num">${fmt(row.avg_mw, 1)}</td><td class="num">${fmt(row.peak_mw, 1)}</td></tr>`).join("")
        : `<tr><td colspan="3" class="empty">No provider-level provision rows.</td></tr>`;
      els.reserveProviderTable.innerHTML = providerHead + `<tbody>${providerBody}</tbody>`;
    }

    function renderReserveSection(reserveData) {
      latestReserveData = reserveData;
      const available = Boolean(reserveData?.available);
      els.reservePanel.hidden = !available;
      els.reserveSummaryPanel.hidden = !available;
      if (!available) {
        if (els.reserveSelect) els.reserveSelect.innerHTML = "";
        if (els.reserveQuantity) els.reserveQuantity.innerHTML = "";
        return;
      }
      const options = reserveData.reserve_options || [];
      const current = els.reserveSelect.value;
      els.reserveSelect.innerHTML = options.map(option => `<option value="${esc(option.value)}">${esc(option.label)}</option>`).join("");
      els.reserveSelect.value = options.some(option => option.value === current) ? current : options[0]?.value || "";
      renderReserveQuantityOptions(reserveData, els.reserveSelect.value);
      drawReserveChart(els.reserveChart, reserveData, els.reserveSelect.value, els.reserveQuantity.value);
      renderReserveTables(reserveData, els.reserveSelect.value);
    }

    function renderBatterySocSection(batteryData) {
      latestBatterySocData = batteryData;
      const available = Boolean(batteryData?.available);
      els.batteryPanel.hidden = !available;
      if (!available) {
        if (els.batterySelect) els.batterySelect.innerHTML = "";
        return;
      }
      const options = batteryData.battery_options || [];
      const current = els.batterySelect.value;
      els.batterySelect.innerHTML = options.map(option => `<option value="${esc(option.value)}">${esc(option.label)}</option>`).join("");
      els.batterySelect.value = options.some(option => option.value === current)
        ? current
        : batteryData.default_battery || options[0]?.value || "";
      drawBatterySocChart(els.batterySocChart, batteryData, els.batterySelect.value);
    }

    function renderFilesTable(files) {
      const head = "<thead><tr><th>File</th><th class=\"num\">Size</th></tr></thead>";
      const body = files.map(file => {
        const label = esc(file.name);
        const fileCell = file.exists && file.url
          ? `<a href="${esc(file.url)}" target="_blank" rel="noopener">${label}</a>`
          : label;
        const size = file.exists ? (file.size_bytes > 2 ? `${fmt(file.size_bytes / 1024, 1)} KB` : "Empty") : "Missing";
        return `<tr><td>${fileCell}</td><td class="num">${size}</td></tr>`;
      }).join("");
      els.filesTable.innerHTML = head + `<tbody>${body}</tbody>`;
    }

    async function loadRuns(preferredRun = "", preferredSample = "all", preferredDispatchSeries = "__fleet__") {
      els.status.textContent = "Loading runs";
      const data = await api("/api/output-runs");
      const completeRuns = data.runs.filter(run => run.status === "complete");
      renderRunOptions(data.runs, preferredRun || data.default_run);
      if (!completeRuns.length) {
        els.status.textContent = "No complete solved runs found";
        return;
      }
      await loadDashboard(els.run.value || data.default_run, preferredSample, preferredDispatchSeries);
    }

    async function loadDashboard(runName, sample, dispatchSeries = "__fleet__") {
      if (!runName) return;
      els.status.textContent = "Loading dashboard";
      const data = await api(`/api/dashboard-data?run=${encodeURIComponent(runName)}&sample=${encodeURIComponent(sample || "all")}&series=${encodeURIComponent(dispatchSeries || "__fleet__")}`);
      renderSampleOptions(data.samples, data.selected_sample);
      renderDispatchOptions(data.dispatch_chart.generator_options, data.dispatch_chart.selected_generator);
      els.outputDir.textContent = data.output_dir;
      els.snapshots.textContent = fmt(data.snapshot_count, 0);
      els.samples.textContent = data.samples.join(", ");
      els.interval.textContent = `${fmt(data.interval_hours, 2)} h`;
      els.nonanticipativity.textContent = data.run_settings?.nonanticipative_hours == null ? "-" : `${fmt(data.run_settings.nonanticipative_hours, 2)} h`;
      renderSummary(data.summary);
      drawFleetMixChart(els.mixChart, data.series);
      drawDispatchChart(els.timeseries, data.dispatch_chart);
      renderReserveSection(data.reserves);
      renderBatterySocSection(data.battery_soc);
      const generationRows = data.generation_by_generator || data.thermal_by_generator;
      drawBarChart(els.loadChart, data.load_by_bus, "total_mwh", "bus", "var(--green)");
      drawBarChart(els.thermalChart, generationRows, "total_mwh", "generator", "var(--blue)");
      drawBarChart(els.unservedChart, data.unserved_by_bus, "total_mwh", "bus", "var(--red)");
      renderThermalTable(generationRows);
      renderFilesTable(data.files);
      els.status.textContent = `Loaded ${data.run}`;
    }

    document.getElementById("refresh-btn").addEventListener("click", () => {
      loadRuns(els.run.value, els.sample.value, els.dispatchSeries.value).catch(error => {
        els.status.textContent = error.message;
      });
    });

    els.run.addEventListener("change", () => {
      loadDashboard(els.run.value, "all", "__fleet__").catch(error => {
        els.status.textContent = error.message;
      });
    });

    els.sample.addEventListener("change", () => {
      loadDashboard(els.run.value, els.sample.value, els.dispatchSeries.value).catch(error => {
        els.status.textContent = error.message;
      });
    });

    els.dispatchSeries.addEventListener("change", () => {
      loadDashboard(els.run.value, els.sample.value, els.dispatchSeries.value).catch(error => {
        els.status.textContent = error.message;
      });
    });

    els.reserveQuantity.addEventListener("change", () => {
      drawReserveChart(els.reserveChart, latestReserveData, els.reserveSelect.value, els.reserveQuantity.value);
    });

    els.reserveSelect.addEventListener("change", () => {
      renderReserveQuantityOptions(latestReserveData, els.reserveSelect.value);
      drawReserveChart(els.reserveChart, latestReserveData, els.reserveSelect.value, els.reserveQuantity.value);
      renderReserveTables(latestReserveData, els.reserveSelect.value);
    });

    els.batterySelect.addEventListener("change", () => {
      drawBatterySocChart(els.batterySocChart, latestBatterySocData, els.batterySelect.value);
    });

    window.addEventListener("resize", () => {
      loadDashboard(els.run.value, els.sample.value, els.dispatchSeries.value).catch(() => {});
    });

    loadRuns().catch(error => {
      els.status.textContent = error.message;
    });
  </script>
</body>
</html>
"""


INPUTS_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PyPSA Input Dashboard</title>
  <style>
    :root {
      --bg: #f5f7f8;
      --panel: #ffffff;
      --line: #d8dee4;
      --line-strong: #b7c0c8;
      --text: #17202a;
      --muted: #5e6b76;
      --blue: #1f6feb;
      --blue-dark: #1554b5;
      --green: #207a4b;
      --red: #b42318;
      --amber: #9a6700;
      --teal: #087f8c;
      --shadow: 0 10px 24px rgba(27, 39, 51, 0.08);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; background: var(--bg); color: var(--text); }
    button, input, select { font: inherit; }
    button, input, select {
      min-height: 34px;
      border: 1px solid var(--line-strong);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      padding: 6px 10px;
      min-width: 0;
    }
    button { cursor: pointer; }
    button:hover { border-color: var(--blue); color: var(--blue-dark); }
    button:focus, input:focus, select:focus { outline: 2px solid rgba(31,111,235,.25); outline-offset: 1px; }
    .app { min-height: 100vh; display: grid; grid-template-rows: auto auto 1fr; }
    .topbar {
      display: grid;
      grid-template-columns: minmax(220px, 300px) minmax(360px, 1fr) minmax(180px, 280px) minmax(130px, 220px) auto;
      gap: 10px 14px;
      align-items: center;
      padding: 12px 16px 10px;
      background: linear-gradient(180deg, #fbfcfe 0%, #eef3f7 100%);
      border-bottom: 1px solid var(--line);
      position: sticky;
      top: 0;
      z-index: 10;
      box-shadow: 0 1px 0 rgba(17, 24, 39, 0.04);
    }
    .brand { display: grid; gap: 3px; align-self: center; }
    h1, h2 { margin: 0; letter-spacing: 0; }
    h1 { font-size: 18px; line-height: 1.2; }
    h2 { font-size: 15px; line-height: 1.3; }
    .subtitle { color: var(--muted); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .nav-links { display: flex; gap: 6px; align-items: center; font-size: 12px; font-weight: 650; flex-wrap: wrap; justify-self: stretch; padding: 6px; border: 1px solid #d4dde6; border-radius: 8px; background: rgba(255,255,255,.82); box-shadow: inset 0 1px 0 rgba(255,255,255,.85); }
    .nav-links a { display: inline-flex; align-items: center; justify-content: center; min-height: 30px; padding: 0 10px; border: 1px solid transparent; border-radius: 6px; color: #243548; text-decoration: none; white-space: nowrap; }
    .nav-links a:hover { border-color: #c8d4df; background: #f5f8fb; text-decoration: none; }
    .nav-links a[aria-current="page"] { border-color: rgba(31,111,235,.2); background: var(--blue); color: #fff; box-shadow: 0 1px 2px rgba(31,111,235,.18); }
    .nav-primary { font-weight: 750; }
    .nav-group { display: inline-flex; align-items: center; gap: 4px; padding: 2px 0 2px 8px; border-left: 1px solid #d9e2eb; }
    .nav-group span { color: var(--muted); font-size: 10px; font-weight: 750; letter-spacing: .06em; text-transform: uppercase; margin-right: 2px; white-space: nowrap; }
    .field { min-width: 0; display: grid; gap: 5px; }
    .field label { color: var(--muted); font-size: 12px; font-weight: 650; }
    .field select, .field input { width: 100%; }
    .status-strip {
      display: grid;
      grid-template-columns: repeat(5, minmax(140px, 1fr));
      gap: 10px;
      padding: 10px 16px;
      background: #eef2f5;
      border-bottom: 1px solid var(--line);
    }
    .metric { min-width: 0; display: grid; gap: 2px; }
    .metric span, .tile span { color: var(--muted); font-size: 11px; font-weight: 650; text-transform: uppercase; }
    .metric strong { min-width: 0; font-size: 13px; font-weight: 650; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .switch-row { display: flex; gap: 8px; align-items: center; min-width: 0; }
    .switch { position: relative; display: inline-flex; width: 40px; height: 22px; flex: 0 0 auto; }
    .switch input { position: absolute; opacity: 0; inset: 0; width: 100%; height: 100%; margin: 0; cursor: pointer; }
    .switch-track { position: absolute; inset: 0; border-radius: 999px; background: #cfd8e3; border: 1px solid #b7c0c8; transition: background 160ms ease, border-color 160ms ease; }
    .switch-track::after { content: ""; position: absolute; width: 16px; height: 16px; left: 2px; top: 2px; border-radius: 50%; background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,.22); transition: transform 160ms ease; }
    .switch input:checked + .switch-track { background: var(--blue); border-color: var(--blue-dark); }
    .switch input:checked + .switch-track::after { transform: translateX(18px); }
    .switch-text { min-width: 0; font-size: 12px; font-weight: 650; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .workspace { min-height: 0; padding: 14px 16px; display: grid; gap: 14px; grid-template-columns: repeat(12, minmax(0, 1fr)); align-content: start; }
    .summary { grid-column: 1 / -1; display: grid; grid-template-columns: repeat(6, minmax(130px, 1fr)); gap: 10px; }
    .tile, .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow); }
    .tile { min-width: 0; padding: 12px; display: grid; gap: 4px; }
    .tile strong { font-size: 22px; line-height: 1.15; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .tile small { color: var(--muted); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .panel { min-width: 0; min-height: 320px; display: grid; grid-template-rows: auto 1fr; }
    .panel.wide { grid-column: span 8; }
    .panel.side { grid-column: span 4; }
    .panel.half { grid-column: span 6; }
    .panel-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 12px; border-bottom: 1px solid var(--line); }
    .panel-body { min-height: 0; padding: 10px; overflow: auto; }
    svg { display: block; width: 100%; height: 280px; overflow: visible; }
    .axis { stroke: #aeb7c2; stroke-width: 1; }
    .grid { stroke: #e7ebef; stroke-width: 1; }
    .label { fill: var(--muted); font-size: 11px; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; }
    th, td { text-align: left; border-bottom: 1px solid var(--line); padding: 7px 8px; white-space: nowrap; }
    th { color: var(--muted); font-weight: 650; background: #f0f3f6; position: sticky; top: 0; }
    td.num { text-align: right; font-variant-numeric: tabular-nums; }
    .empty { color: var(--muted); padding: 12px; font-size: 13px; }
    @media (max-width: 1180px) {
      .topbar, .status-strip, .summary { grid-template-columns: 1fr 1fr; }
      .panel.wide, .panel.side, .panel.half { grid-column: 1 / -1; }
    }
    @media (max-width: 760px) {
      .topbar, .status-strip, .summary { grid-template-columns: 1fr; }
      .workspace { padding: 10px; }
    }
  </style>
</head>
<body>
  <div class="app">
    <header class="topbar">
      <div class="brand">
        <h1>PyPSA Input Dashboard</h1>
        <div class="subtitle" id="input-status">Loading inputs</div>
      </div>
      <nav class="nav-links" aria-label="Application navigation">
        <a class="nav-primary" href="/runner">Model Runner</a>
        <div class="nav-group" aria-label="Input pages">
          <span>Inputs</span>
          <a href="/inputs" aria-current="page">Visual</a>
          <a href="/">CSV Editor</a>
        </div>
        <div class="nav-group" aria-label="Output pages">
          <span>Outputs</span>
          <a href="/dashboard">Visual</a>
          <a href="/topology">Topology</a>
        </div>
      </nav>
      <div class="field">
        <label for="dataset-select">Input dataset</label>
        <select id="dataset-select"></select>
      </div>
      <div class="field">
        <label for="series-select">Series</label>
        <select id="series-select"></select>
      </div>
      <button id="refresh-btn">Refresh</button>
    </header>

    <section class="status-strip" aria-label="Input metadata">
      <div class="metric"><span>Kind</span><strong id="kind">-</strong></div>
      <div class="metric"><span>Path</span><strong id="path">-</strong></div>
      <div class="metric"><span>Rows</span><strong id="rows">-</strong></div>
      <div class="metric"><span>Columns</span><strong id="columns">-</strong></div>
      <div class="metric">
        <span>Model window</span>
        <label class="switch-row">
          <span class="switch">
            <input id="model-window-toggle" type="checkbox">
            <span class="switch-track"></span>
          </span>
          <strong class="switch-text" id="model-window-label">Full file</strong>
        </label>
      </div>
    </section>

    <main class="workspace">
      <section class="summary" id="summary"></section>

      <section class="panel wide">
        <div class="panel-head"><h2 id="line-title">Input Profile</h2></div>
        <div class="panel-body"><svg id="line-chart" role="img" aria-label="Input time series"></svg></div>
      </section>

      <section class="panel side">
        <div class="panel-head"><h2 id="bar-title">Breakdown</h2></div>
        <div class="panel-body"><svg id="bar-chart" role="img" aria-label="Input breakdown"></svg></div>
      </section>

      <section class="panel half">
        <div class="panel-head"><h2>Daily Shape</h2></div>
        <div class="panel-body"><svg id="shape-chart" role="img" aria-label="Average value by period"></svg></div>
      </section>

      <section class="panel half">
        <div class="panel-head"><h2>Diagnostics</h2></div>
        <div class="panel-body"><table id="diagnostics-table"></table></div>
      </section>

      <section class="panel wide">
        <div class="panel-head"><h2>Preview</h2></div>
        <div class="panel-body"><table id="preview-table"></table></div>
      </section>

      <section class="panel side">
        <div class="panel-head"><h2>Columns</h2></div>
        <div class="panel-body"><table id="columns-table"></table></div>
      </section>
    </main>
  </div>

  <script>
    const els = {
      status: document.getElementById("input-status"),
      dataset: document.getElementById("dataset-select"),
      series: document.getElementById("series-select"),
      kind: document.getElementById("kind"),
      path: document.getElementById("path"),
      rows: document.getElementById("rows"),
      columns: document.getElementById("columns"),
      modelWindowToggle: document.getElementById("model-window-toggle"),
      modelWindowLabel: document.getElementById("model-window-label"),
      summary: document.getElementById("summary"),
      lineTitle: document.getElementById("line-title"),
      barTitle: document.getElementById("bar-title"),
      lineChart: document.getElementById("line-chart"),
      barChart: document.getElementById("bar-chart"),
      shapeChart: document.getElementById("shape-chart"),
      diagnosticsTable: document.getElementById("diagnostics-table"),
      previewTable: document.getElementById("preview-table"),
      columnsTable: document.getElementById("columns-table")
    };

    const runnerWindowSettingsKey = "pypsaRunnerWindowSettings";
    const inputModelWindowToggleKey = "pypsaInputModelWindowEnabled";

    function api(path) {
      return fetch(path).then(async response => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.ok === false) throw new Error(data.error || response.statusText);
        return data;
      });
    }

    function esc(value) {
      return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
    }

    function fmt(value, digits = 1) {
      return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: digits });
    }

    function runnerWindowSettings() {
      let settings = {};
      try {
        settings = JSON.parse(localStorage.getItem(runnerWindowSettingsKey) || "{}") || {};
      } catch (_error) {
        settings = {};
      }
      const horizon = Number(settings.horizon_hours);
      const lookahead = Number(settings.lookahead_hours);
      return {
        horizon_hours: Number.isFinite(horizon) && horizon > 0 ? horizon : 24,
        lookahead_hours: Number.isFinite(lookahead) && lookahead >= 0 ? lookahead : 24
      };
    }

    function modelWindowHours() {
      const settings = runnerWindowSettings();
      return settings.horizon_hours + settings.lookahead_hours;
    }

    function updateModelWindowLabel() {
      if (els.modelWindowToggle.checked) {
        const settings = runnerWindowSettings();
        els.modelWindowLabel.textContent = `${fmt(settings.horizon_hours + settings.lookahead_hours, 1)} h`;
      } else {
        els.modelWindowLabel.textContent = "Full file";
      }
    }

    function renderDatasetOptions(items, selected) {
      const groups = items.reduce((acc, item) => {
        if (!acc[item.group]) acc[item.group] = [];
        acc[item.group].push(item);
        return acc;
      }, {});
      const order = ["loads", "renewables", "generators", "raw", "excel_exports", "manifest"];
      const names = [...order.filter(name => groups[name]), ...Object.keys(groups).filter(name => !order.includes(name)).sort()];
      els.dataset.innerHTML = names.map(group => {
        const options = groups[group].map(item => `<option value="${esc(item.dataset)}">${esc(item.dataset)} - ${esc(item.relative_path)}</option>`).join("");
        return `<optgroup label="${esc(group)}">${options}</optgroup>`;
      }).join("");
      els.dataset.value = selected || items[0]?.dataset || "";
    }

    function renderSeriesOptions(options, selected) {
      els.series.innerHTML = options.map(item => `<option value="${esc(item)}">${esc(item)}</option>`).join("");
      els.series.value = selected || options[0] || "";
    }

    function svgEl(tag, attrs = {}) {
      const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
      for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
      return node;
    }

    function clear(svg) {
      while (svg.firstChild) svg.removeChild(svg.firstChild);
    }

    function drawLineChart(svg, rows, key, color) {
      clear(svg);
      if (!rows.length) {
        svg.appendChild(svgEl("text", { x: 16, y: 32, class: "label" })).textContent = "No chartable data.";
        return;
      }
      const width = svg.clientWidth || 760;
      const height = 280;
      const margin = { top: 16, right: 18, bottom: 34, left: 54 };
      const innerW = width - margin.left - margin.right;
      const innerH = height - margin.top - margin.bottom;
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      const values = rows.map(row => Number(row[key] || 0));
      const maxY = Math.max(1, ...values);
      const minY = Math.min(0, ...values);
      const span = maxY - minY || 1;
      const x = index => margin.left + (rows.length === 1 ? 0 : index * innerW / (rows.length - 1));
      const y = value => margin.top + innerH - ((Number(value || 0) - minY) / span) * innerH;
      for (let i = 0; i <= 4; i += 1) {
        const gy = margin.top + innerH * i / 4;
        const label = maxY - span * i / 4;
        svg.appendChild(svgEl("line", { x1: margin.left, y1: gy, x2: width - margin.right, y2: gy, class: "grid" }));
        svg.appendChild(svgEl("text", { x: 8, y: gy + 4, class: "label" })).textContent = fmt(label, 1);
      }
      svg.appendChild(svgEl("line", { x1: margin.left, y1: margin.top, x2: margin.left, y2: margin.top + innerH, class: "axis" }));
      svg.appendChild(svgEl("line", { x1: margin.left, y1: margin.top + innerH, x2: width - margin.right, y2: margin.top + innerH, class: "axis" }));
      const points = rows.map((row, index) => `${x(index)},${y(row[key])}`).join(" ");
      svg.appendChild(svgEl("polyline", { points, fill: "none", stroke: color, "stroke-width": 2.5, "stroke-linejoin": "round", "stroke-linecap": "round" }));
      svg.appendChild(svgEl("text", { x: margin.left, y: height - 10, class: "label" })).textContent = rows[0].label || rows[0].x || "";
      const end = svgEl("text", { x: width - margin.right, y: height - 10, class: "label", "text-anchor": "end" });
      end.textContent = rows[rows.length - 1].label || rows[rows.length - 1].x || "";
      svg.appendChild(end);
    }

    function drawBarChart(svg, rows, valueKey, labelKey, color) {
      clear(svg);
      const data = rows.filter(row => Number(row[valueKey]) !== 0).slice(0, 18);
      if (!data.length) {
        svg.appendChild(svgEl("text", { x: 16, y: 32, class: "label" })).textContent = "No non-zero values.";
        return;
      }
      const width = svg.clientWidth || 500;
      const height = Math.max(280, data.length * 25 + 40);
      const margin = { top: 12, right: 18, bottom: 22, left: 130 };
      const innerW = width - margin.left - margin.right;
      const maxValue = Math.max(...data.map(row => Math.abs(Number(row[valueKey] || 0))), 1);
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      data.forEach((row, index) => {
        const y = margin.top + index * 25;
        const value = Number(row[valueKey] || 0);
        const barW = Math.abs(value) / maxValue * innerW;
        svg.appendChild(svgEl("text", { x: margin.left - 8, y: y + 15, class: "label", "text-anchor": "end" })).textContent = String(row[labelKey] || "");
        svg.appendChild(svgEl("rect", { x: margin.left, y, width: Math.max(1, barW), height: 17, rx: 3, fill: color }));
        svg.appendChild(svgEl("text", { x: margin.left + barW + 6, y: y + 14, class: "label" })).textContent = fmt(value, 1);
      });
    }

    function renderSummary(summary) {
      const tiles = summary.map(item => `<div class="tile"><span>${esc(item.label)}</span><strong>${esc(item.value)}</strong><small>${esc(item.note || "")}</small></div>`);
      els.summary.innerHTML = tiles.join("");
    }

    function renderTable(table, columns, rows) {
      if (!rows.length) {
        table.innerHTML = `<tbody><tr><td class="empty">No rows.</td></tr></tbody>`;
        return;
      }
      const head = `<thead><tr>${columns.map(column => `<th>${esc(column)}</th>`).join("")}</tr></thead>`;
      const body = rows.map(row => `<tr>${columns.map(column => `<td${typeof row[column] === "number" ? ' class="num"' : ""}>${esc(typeof row[column] === "number" ? fmt(row[column], 3) : row[column])}</td>`).join("")}</tr>`).join("");
      table.innerHTML = head + `<tbody>${body}</tbody>`;
    }

    async function loadDatasets(preferred = "") {
      els.status.textContent = "Loading inputs";
      const data = await api("/api/input-datasets");
      renderDatasetOptions(data.datasets, preferred || data.default_dataset);
      await loadDashboard(els.dataset.value, "");
    }

    async function loadDashboard(dataset, series) {
      if (!dataset) return;
      els.status.textContent = "Loading input dashboard";
      updateModelWindowLabel();
      const params = new URLSearchParams({
        dataset,
        series: series || ""
      });
      if (els.modelWindowToggle.checked) {
        params.set("model_window_hours", String(modelWindowHours()));
      }
      const data = await api(`/api/input-dashboard-data?${params.toString()}`);
      renderSeriesOptions(data.series_options, data.selected_series);
      els.kind.textContent = data.kind_label;
      els.path.textContent = data.relative_path;
      els.rows.textContent = fmt(data.row_count, 0);
      els.columns.textContent = fmt(data.column_count, 0);
      if (data.window?.enabled) {
        els.modelWindowLabel.textContent = `${fmt(data.window.hours, 1)} h`;
      }
      els.lineTitle.textContent = data.line_title;
      els.barTitle.textContent = data.bar_title;
      renderSummary(data.summary);
      drawLineChart(els.lineChart, data.series, "value", "var(--blue)");
      drawBarChart(els.barChart, data.breakdown, "value", "label", "var(--green)");
      drawLineChart(els.shapeChart, data.shape, "value", "var(--teal)");
      renderTable(els.diagnosticsTable, ["Metric", "Value"], data.diagnostics);
      renderTable(els.previewTable, data.preview_columns, data.preview_rows);
      renderTable(els.columnsTable, ["Column", "Role"], data.column_roles);
      els.status.textContent = `Loaded ${data.dataset}`;
    }

    document.getElementById("refresh-btn").addEventListener("click", () => {
      loadDashboard(els.dataset.value, els.series.value).catch(error => { els.status.textContent = error.message; });
    });
    els.dataset.addEventListener("change", () => {
      loadDashboard(els.dataset.value, "").catch(error => { els.status.textContent = error.message; });
    });
    els.series.addEventListener("change", () => {
      loadDashboard(els.dataset.value, els.series.value).catch(error => { els.status.textContent = error.message; });
    });
    els.modelWindowToggle.checked = localStorage.getItem(inputModelWindowToggleKey) === "true";
    updateModelWindowLabel();
    els.modelWindowToggle.addEventListener("change", () => {
      localStorage.setItem(inputModelWindowToggleKey, els.modelWindowToggle.checked ? "true" : "false");
      updateModelWindowLabel();
      loadDashboard(els.dataset.value, els.series.value).catch(error => { els.status.textContent = error.message; });
    });
    window.addEventListener("resize", () => {
      loadDashboard(els.dataset.value, els.series.value).catch(() => {});
    });
    loadDatasets().catch(error => { els.status.textContent = error.message; });
  </script>
</body>
</html>
"""


TOPOLOGY_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PyPSA Topology SLD</title>
  <style>
    :root {
      --bg: #f5f7f8;
      --panel: #ffffff;
      --line: #d8dee4;
      --line-strong: #b7c0c8;
      --text: #17202a;
      --muted: #5e6b76;
      --blue: #1f6feb;
      --blue-dark: #1554b5;
      --green: #207a4b;
      --amber: #b7791f;
      --red: #b42318;
      --shadow: 0 10px 24px rgba(27, 39, 51, 0.08);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; background: var(--bg); color: var(--text); }
    button, input, select { font: inherit; }
    button, select, input[type="range"] { min-height: 34px; }
    button, select {
      border: 1px solid var(--line-strong);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      padding: 6px 10px;
      min-width: 0;
    }
    button { cursor: pointer; }
    button:hover { border-color: var(--blue); color: var(--blue-dark); }
    select:focus, button:focus, input:focus { outline: 2px solid rgba(31,111,235,.25); outline-offset: 1px; }
    .app { min-height: 100vh; display: grid; grid-template-rows: auto auto 1fr; }
    .topbar {
      display: grid;
      grid-template-columns: minmax(220px, 300px) minmax(360px, 1fr) minmax(160px, 280px) minmax(130px, 200px) auto;
      gap: 10px 14px;
      align-items: center;
      padding: 12px 16px 10px;
      background: linear-gradient(180deg, #fbfcfe 0%, #eef3f7 100%);
      border-bottom: 1px solid var(--line);
      position: sticky;
      top: 0;
      z-index: 10;
      box-shadow: 0 1px 0 rgba(17, 24, 39, 0.04);
    }
    .brand { display: grid; gap: 3px; align-self: center; }
    h1, h2 { margin: 0; letter-spacing: 0; }
    h1 { font-size: 18px; line-height: 1.2; }
    h2 { font-size: 15px; line-height: 1.3; }
    .subtitle { color: var(--muted); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .nav-links { display: flex; gap: 6px; align-items: center; font-size: 12px; font-weight: 650; flex-wrap: wrap; justify-self: stretch; padding: 6px; border: 1px solid #d4dde6; border-radius: 8px; background: rgba(255,255,255,.82); box-shadow: inset 0 1px 0 rgba(255,255,255,.85); }
    .nav-links a { display: inline-flex; align-items: center; justify-content: center; min-height: 30px; padding: 0 10px; border: 1px solid transparent; border-radius: 6px; color: #243548; text-decoration: none; white-space: nowrap; }
    .nav-links a:hover { border-color: #c8d4df; background: #f5f8fb; text-decoration: none; }
    .nav-links a[aria-current="page"] { border-color: rgba(31,111,235,.2); background: var(--blue); color: #fff; box-shadow: 0 1px 2px rgba(31,111,235,.18); }
    .nav-primary { font-weight: 750; }
    .nav-group { display: inline-flex; align-items: center; gap: 4px; padding: 2px 0 2px 8px; border-left: 1px solid #d9e2eb; }
    .nav-group span { color: var(--muted); font-size: 10px; font-weight: 750; letter-spacing: .06em; text-transform: uppercase; margin-right: 2px; white-space: nowrap; }
    .field { display: grid; gap: 5px; min-width: 0; }
    .field label { color: var(--muted); font-size: 12px; font-weight: 650; }
    .field select { width: 100%; }
    .status-strip {
      display: grid;
      grid-template-columns: repeat(5, minmax(120px, 1fr));
      gap: 10px;
      padding: 10px 16px;
      background: #eef2f5;
      border-bottom: 1px solid var(--line);
    }
    .metric { min-width: 0; display: grid; gap: 2px; }
    .metric span { color: var(--muted); font-size: 11px; font-weight: 650; text-transform: uppercase; }
    .metric strong { min-width: 0; font-size: 13px; font-weight: 650; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .workspace { min-height: 0; padding: 14px 16px; display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; }
    .panel { min-width: 0; min-height: 0; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow); display: grid; grid-template-rows: auto 1fr; }
    .panel-head { display: flex; justify-content: space-between; gap: 10px; align-items: center; padding: 12px; border-bottom: 1px solid var(--line); }
    .legend { display: flex; gap: 10px; flex-wrap: wrap; color: var(--muted); font-size: 12px; }
    .legend span { display: inline-flex; gap: 5px; align-items: center; }
    .dot { width: 10px; height: 10px; border-radius: 999px; display: inline-block; }
    .map-panel { grid-template-rows: auto auto 1fr; }
    .map-wrap { min-height: 0; display: grid; grid-template-rows: 1fr auto; }
    .time-readout { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 10px 12px; border-bottom: 1px solid var(--line); background: #f7fafc; }
    .time-readout span { color: var(--muted); font-size: 11px; font-weight: 750; letter-spacing: .05em; text-transform: uppercase; white-space: nowrap; }
    .time-readout input { min-width: 240px; padding: 8px 10px; border: 1px solid #c8d4df; border-radius: 6px; background: #fff; color: var(--text); font-size: 15px; font-variant-numeric: tabular-nums; text-align: center; }
    svg { width: 100%; min-height: 620px; display: block; background: #fbfcfd; }
    .slider-bar { display: grid; grid-template-columns: auto auto 1fr auto auto; gap: 12px; align-items: center; padding: 12px; border-top: 1px solid var(--line); background: #fff; }
    .slider-bar input { width: 100%; }
    .time-index { color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .play-button { min-width: 68px; font-weight: 700; }
    .play-button[aria-pressed="true"] { border-color: rgba(31,111,235,.32); background: var(--blue); color: #fff; }
    .details { min-height: 0; overflow: auto; padding: 10px; display: grid; gap: 12px; align-content: start; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; }
    th, td { border-bottom: 1px solid var(--line); padding: 6px 7px; text-align: left; white-space: nowrap; }
    th { color: var(--muted); background: #f0f3f6; position: sticky; top: 0; }
    td.num { text-align: right; font-variant-numeric: tabular-nums; }
    .warn { color: var(--amber); font-size: 12px; padding: 0 12px 10px; }
    .busbar { fill: #17202a; }
    .bus-label { fill: #17202a; font-size: 12px; font-weight: 650; }
    .value-label { fill: #17202a; font-size: 11px; }
    .small-label { fill: var(--muted); font-size: 10px; }
    .badge { fill: #ffffff; stroke: #c8d0d8; stroke-width: 1; }
    .branch-label { fill: #17202a; font-size: 10px; paint-order: stroke; stroke: #fff; stroke-width: 3px; }
    @media (max-width: 1100px) {
      .topbar, .status-strip, .workspace { grid-template-columns: 1fr; }
      svg { min-height: 360px; }
    }
  </style>
</head>
<body>
  <div class="app">
    <header class="topbar">
      <div class="brand">
        <h1>PyPSA Topology SLD</h1>
        <div class="subtitle" id="topology-status">Loading topology</div>
      </div>
      <nav class="nav-links" aria-label="Application navigation">
        <a class="nav-primary" href="/runner">Model Runner</a>
        <div class="nav-group" aria-label="Input pages">
          <span>Inputs</span>
          <a href="/inputs">Visual</a>
          <a href="/">CSV Editor</a>
        </div>
        <div class="nav-group" aria-label="Output pages">
          <span>Outputs</span>
          <a href="/dashboard">Visual</a>
          <a href="/topology" aria-current="page">Topology</a>
        </div>
      </nav>
      <div class="field">
        <label for="run-select">Run</label>
        <select id="run-select"></select>
      </div>
      <div class="field">
        <label for="sample-select">Sample</label>
        <select id="sample-select"></select>
      </div>
      <button id="refresh-btn">Refresh</button>
    </header>

    <section class="status-strip" aria-label="Topology metadata">
      <div class="metric"><span>Snapshot</span><strong id="snapshot-label">-</strong></div>
      <div class="metric"><span>Total Generation</span><strong id="total-generation">-</strong></div>
      <div class="metric"><span>Total Load</span><strong id="total-load">-</strong></div>
      <div class="metric"><span>Unserved</span><strong id="total-unserved">-</strong></div>
      <div class="metric"><span>Max Branch Loading</span><strong id="max-loading">-</strong></div>
    </section>

    <main class="workspace">
      <section class="panel map-panel">
        <div class="panel-head">
          <h2>Single Line Diagram</h2>
          <div class="legend">
            <span><i class="dot" style="background:#8a96a3"></i>No data</span>
            <span><i class="dot" style="background:#207a4b"></i>&lt; 50%</span>
            <span><i class="dot" style="background:#b7791f"></i>50-80%</span>
            <span><i class="dot" style="background:#b42318"></i>&gt; 80%</span>
          </div>
        </div>
        <div class="time-readout">
          <span>Date and time</span>
          <input id="topology-time-label" type="text" value="-" readonly aria-live="polite">
        </div>
        <div class="map-wrap">
          <svg id="sld" viewBox="0 0 1040 640" role="img" aria-label="Network single line diagram"></svg>
          <div class="warn" id="line-flow-warning"></div>
          <div class="slider-bar">
            <button class="play-button" id="play-pause-btn" aria-pressed="false">Play</button>
            <button id="prev-btn">Prev</button>
            <input id="time-slider" type="range" min="0" max="0" value="0">
            <span class="time-index" id="time-index-label">0 / 0</span>
            <button id="next-btn">Next</button>
          </div>
        </div>
      </section>

      <aside class="panel">
        <div class="panel-head"><h2>Selected Timestep</h2></div>
        <div class="details">
          <div>
            <h2>Generators</h2>
            <table id="generators-table"></table>
          </div>
          <div>
            <h2>Loads</h2>
            <table id="loads-table"></table>
          </div>
          <div>
            <h2>Branches</h2>
            <table id="branches-table"></table>
          </div>
        </div>
      </aside>
    </main>
  </div>

  <script>
    const els = {
      status: document.getElementById("topology-status"),
      run: document.getElementById("run-select"),
      sample: document.getElementById("sample-select"),
      snapshot: document.getElementById("snapshot-label"),
      totalGeneration: document.getElementById("total-generation"),
      totalLoad: document.getElementById("total-load"),
      totalUnserved: document.getElementById("total-unserved"),
      maxLoading: document.getElementById("max-loading"),
      warning: document.getElementById("line-flow-warning"),
      svg: document.getElementById("sld"),
      slider: document.getElementById("time-slider"),
      timeIndex: document.getElementById("time-index-label"),
      timeLabel: document.getElementById("topology-time-label"),
      playPause: document.getElementById("play-pause-btn"),
      generatorsTable: document.getElementById("generators-table"),
      loadsTable: document.getElementById("loads-table"),
      branchesTable: document.getElementById("branches-table")
    };
    const PLAY_INTERVAL_MS = 500;
    const state = { runs: [], data: null, frameIndex: 0, playTimer: null };

    function api(path) {
      return fetch(path).then(async response => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.ok === false) throw new Error(data.error || response.statusText);
        return data;
      });
    }

    function esc(value) {
      return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
    }

    function fmt(value, digits = 1) {
      return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: digits });
    }

    function mw(value) { return `${fmt(value, 1)} MW`; }

    function svgEl(tag, attrs = {}) {
      const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
      for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
      return node;
    }

    function branchColor(loading) {
      if (loading === null || loading === undefined || loading === "") return "#8a96a3";
      const value = Number(loading);
      if (value >= 80) return "#b42318";
      if (value >= 50) return "#b7791f";
      return "#207a4b";
    }

    function branchWidth(loading) {
      if (loading === null || loading === undefined || loading === "") return 4;
      return 4 + Math.min(7, Number(loading) / 18);
    }

    function renderRuns(runs, selected) {
      els.run.innerHTML = runs.map(run => `<option value="${esc(run.name)}">${esc(run.name)} - ${esc(run.status)}</option>`).join("");
      els.run.value = selected || runs.find(run => run.status === "complete")?.name || runs[0]?.name || "";
    }

    function renderSamples(samples, selected) {
      els.sample.innerHTML = samples.map(sample => `<option value="${esc(sample)}">Sample ${esc(sample)}</option>`).join("");
      els.sample.value = selected || samples[0] || "";
    }

    async function loadRuns() {
      els.status.textContent = "Loading runs";
      const data = await api("/api/output-runs");
      state.runs = data.runs;
      renderRuns(data.runs, data.default_run);
      await loadTopology(els.run.value, "");
    }

    async function loadTopology(run, sample) {
      if (!run) return;
      stopPlayback();
      els.status.textContent = "Loading topology";
      const data = await api(`/api/topology-data?run=${encodeURIComponent(run)}&sample=${encodeURIComponent(sample || "")}`);
      state.data = data;
      state.frameIndex = 0;
      renderSamples(data.samples, data.selected_sample);
      els.slider.min = "0";
      els.slider.max = String(Math.max(0, data.frames.length - 1));
      els.slider.value = "0";
      els.warning.textContent = data.has_line_flows ? "" : "Branch loading colours require line_flow_by_interval.csv. Run the model again to generate branch loading output.";
      renderFrame();
      els.status.textContent = `Loaded ${data.run}`;
    }

    function renderFrame() {
      const data = state.data;
      if (!data || !data.frames.length) return;
      state.frameIndex = Math.max(0, Math.min(data.frames.length - 1, Number(els.slider.value || 0)));
      const frame = data.frames[state.frameIndex];
      els.timeIndex.textContent = `${state.frameIndex + 1} / ${data.frames.length}`;
      els.timeLabel.value = frame.time || frame.time_label || "-";
      els.snapshot.textContent = frame.time_label;
      els.totalGeneration.textContent = mw(frame.summary.total_generation_mw);
      els.totalLoad.textContent = mw(frame.summary.total_load_mw);
      els.totalUnserved.textContent = mw(frame.summary.total_unserved_mw);
      els.maxLoading.textContent = frame.summary.max_loading_pct === null ? "No line flow data" : `${fmt(frame.summary.max_loading_pct, 1)}%`;
      drawSld(data, frame);
      renderTables(frame);
    }

    function setPlaybackButton(isPlaying) {
      els.playPause.textContent = isPlaying ? "Pause" : "Play";
      els.playPause.setAttribute("aria-pressed", isPlaying ? "true" : "false");
    }

    function stopPlayback() {
      if (state.playTimer) {
        window.clearInterval(state.playTimer);
        state.playTimer = null;
      }
      setPlaybackButton(false);
    }

    function advancePlaybackFrame() {
      if (!state.data || !state.data.frames.length) {
        stopPlayback();
        return;
      }
      const max = Number(els.slider.max || 0);
      const current = Number(els.slider.value || 0);
      if (current >= max) {
        stopPlayback();
        return;
      }
      els.slider.value = String(current + 1);
      renderFrame();
    }

    function startPlayback() {
      if (!state.data || state.data.frames.length <= 1) return;
      if (Number(els.slider.value || 0) >= Number(els.slider.max || 0)) {
        els.slider.value = "0";
        renderFrame();
      }
      stopPlayback();
      state.playTimer = window.setInterval(advancePlaybackFrame, PLAY_INTERVAL_MS);
      setPlaybackButton(true);
    }

    function togglePlayback() {
      if (state.playTimer) {
        stopPlayback();
      } else {
        startPlayback();
      }
    }

    function drawSld(data, frame) {
      while (els.svg.firstChild) els.svg.removeChild(els.svg.firstChild);
      const layout = data.layout;

      for (const branch of frame.branches) {
        const a = layout[branch.bus0];
        const b = layout[branch.bus1];
        if (!a || !b) continue;
        const line = svgEl("line", {
          x1: a.x, y1: a.y, x2: b.x, y2: b.y,
          stroke: branchColor(branch.loading_pct),
          "stroke-width": branchWidth(branch.loading_pct),
          "stroke-linecap": "round"
        });
        els.svg.appendChild(line);
        const midX = (a.x + b.x) / 2;
        const midY = (a.y + b.y) / 2;
        const label = branch.loading_pct === null ? `${branch.name}` : `${branch.name} ${fmt(branch.p0_mw, 1)} MW / ${fmt(branch.loading_pct, 0)}%`;
        const text = svgEl("text", { x: midX, y: midY - 8, "text-anchor": "middle", class: "branch-label" });
        text.textContent = label;
        els.svg.appendChild(text);
      }

      const generationByBus = Object.fromEntries(frame.generation_by_bus.map(row => [row.bus, row.p_mw]));
      const loadByBus = Object.fromEntries(frame.loads.map(row => [row.bus, row.load_mw]));
      for (const [bus, point] of Object.entries(layout)) {
        const group = svgEl("g");
        els.svg.appendChild(group);
        group.appendChild(svgEl("rect", { x: point.x - 5, y: point.y - 32, width: 10, height: 64, rx: 3, class: "busbar" }));
        const name = svgEl("text", { x: point.x, y: point.y + 48, "text-anchor": "middle", class: "bus-label" });
        name.textContent = bus;
        group.appendChild(name);
        const gen = generationByBus[bus] || 0;
        const load = loadByBus[bus] || 0;
        if (gen || load) {
          const badge = svgEl("rect", { x: point.x - 58, y: point.y - 62, width: 116, height: 28, rx: 6, class: "badge" });
          group.appendChild(badge);
          const value = svgEl("text", { x: point.x, y: point.y - 44, "text-anchor": "middle", class: "value-label" });
          value.textContent = `${gen ? `G ${fmt(gen, 1)}` : ""}${gen && load ? " / " : ""}${load ? `L ${fmt(load, 1)}` : ""} MW`;
          group.appendChild(value);
        }
      }

      drawGeneratorBadges(frame.generators);
      drawLoadBadges(frame.loads);
    }

    function drawGeneratorBadges(generators) {
      const solomon = generators.filter(row => row.bus === "Solomon Hub" && Math.abs(row.p_mw) > 0.01).slice(0, 12);
      const others = generators.filter(row => row.bus !== "Solomon Hub" && Math.abs(row.p_mw) > 0.01);
      drawBadgeList(20, 40, "Generators", [...solomon, ...others].map(row => `${row.generator}: ${fmt(row.p_mw, 1)} MW`), "#edf8f1");
    }

    function drawLoadBadges(loads) {
      const rows = loads.filter(row => Math.abs(row.load_mw) > 0.01).map(row => `${row.bus}: ${fmt(row.load_mw, 1)} MW`);
      drawBadgeList(850, 40, "Loads", rows.slice(0, 10), "#eef5ff");
    }

    function drawBadgeList(x, y, title, rows, fill) {
      const height = 28 + rows.length * 18;
      els.svg.appendChild(svgEl("rect", { x, y, width: 170, height, rx: 8, fill, stroke: "#c8d0d8" }));
      const titleText = svgEl("text", { x: x + 10, y: y + 18, class: "bus-label" });
      titleText.textContent = title;
      els.svg.appendChild(titleText);
      rows.forEach((row, index) => {
        const text = svgEl("text", { x: x + 10, y: y + 38 + index * 18, class: "small-label" });
        text.textContent = row;
        els.svg.appendChild(text);
      });
    }

    function renderTables(frame) {
      renderTable(els.generatorsTable, ["Generator", "Bus", "MW"], frame.generators.slice().sort((a,b) => Math.abs(b.p_mw) - Math.abs(a.p_mw)).map(row => ({ Generator: row.generator, Bus: row.bus, MW: row.p_mw })));
      renderTable(els.loadsTable, ["Load", "MW", "Unserved"], frame.loads.map(row => ({ Load: row.bus, MW: row.load_mw, Unserved: row.unserved_mw })));
      renderTable(els.branchesTable, ["Branch", "MW", "Loading"], frame.branches.map(row => ({ Branch: row.name, MW: row.p0_mw, Loading: row.loading_pct === null ? "No data" : `${fmt(row.loading_pct, 1)}%` })));
    }

    function renderTable(table, columns, rows) {
      const head = `<thead><tr>${columns.map(column => `<th>${esc(column)}</th>`).join("")}</tr></thead>`;
      const body = rows.map(row => `<tr>${columns.map(column => {
        const value = row[column];
        const numeric = typeof value === "number";
        return `<td${numeric ? ' class="num"' : ""}>${esc(numeric ? fmt(value, 2) : value)}</td>`;
      }).join("")}</tr>`).join("");
      table.innerHTML = head + `<tbody>${body}</tbody>`;
    }

    document.getElementById("refresh-btn").addEventListener("click", () => loadTopology(els.run.value, els.sample.value).catch(error => els.status.textContent = error.message));
    els.playPause.addEventListener("click", togglePlayback);
    document.getElementById("prev-btn").addEventListener("click", () => { stopPlayback(); els.slider.value = String(Math.max(0, Number(els.slider.value) - 1)); renderFrame(); });
    document.getElementById("next-btn").addEventListener("click", () => { stopPlayback(); els.slider.value = String(Math.min(Number(els.slider.max), Number(els.slider.value) + 1)); renderFrame(); });
    els.slider.addEventListener("input", () => { stopPlayback(); renderFrame(); });
    els.run.addEventListener("change", () => loadTopology(els.run.value, "").catch(error => els.status.textContent = error.message));
    els.sample.addEventListener("change", () => loadTopology(els.run.value, els.sample.value).catch(error => els.status.textContent = error.message));
    loadRuns().catch(error => els.status.textContent = error.message);
  </script>
</body>
</html>
"""


class AppError(Exception):
    def __init__(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        super().__init__(message)
        self.status = status


def find_data_root(root_arg: str | None = None) -> Path:
    candidates: list[Path] = []
    if root_arg:
        candidates.append(Path(root_arg).expanduser())
    candidates.extend(
        [
            DEFAULT_DATA_ROOT,
            Path("pypsa_data_sources"),
            Path.cwd() / DEFAULT_DATA_ROOT,
            Path.cwd() / "pypsa_data_sources",
        ]
    )

    for candidate in candidates:
        candidate = candidate.resolve()
        if (candidate / MANIFEST_NAME).is_file():
            return candidate

    raise AppError(
        "Could not find manifest.csv. Set Data root to the folder containing it.",
        HTTPStatus.NOT_FOUND,
    )


def ensure_inside(root: Path, path: Path) -> Path:
    root_resolved = root.resolve()
    path_resolved = path.resolve()
    if path_resolved != root_resolved and root_resolved not in path_resolved.parents:
        raise AppError("Path is outside the selected data root.")
    return path_resolved


def read_text(path: Path) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return path.read_text(encoding=encoding), encoding
        except UnicodeDecodeError:
            continue
    raise AppError(f"Could not decode {path.name}.")


def file_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def read_csv_rows(path: Path) -> tuple[list[str], list[list[str]], str]:
    text, encoding = read_text(path)
    reader = csv.reader(io.StringIO(text))
    try:
        columns = next(reader)
    except StopIteration:
        return [], [], encoding
    rows = [normalize_row(row, len(columns)) for row in reader]
    return columns, rows, encoding


def read_csv_header(path: Path) -> list[str]:
    text, _encoding = read_text(path)
    reader = csv.reader(io.StringIO(text))
    try:
        return next(reader)
    except StopIteration:
        return []


def normalize_row(row: list[str], width: int) -> list[str]:
    if len(row) < width:
        return row + [""] * (width - len(row))
    return row[:width]


def write_csv_rows(path: Path, columns: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\r\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow(normalize_row([str(value) for value in row], len(columns)))


def relative_path_for_dataset(dataset: str) -> str:
    normalized = dataset.replace("\\", "/").strip("/")
    if normalized == "manifest":
        return MANIFEST_NAME
    if normalized.lower().endswith(".csv"):
        return normalized
    return f"{normalized}.csv"


def resolve_dataset_path(root: Path, dataset: str, manifest_row: dict[str, str] | None = None) -> Path:
    candidates = [root / relative_path_for_dataset(dataset)]
    if manifest_row:
        output_file = manifest_row.get("output_file", "")
        if output_file:
            raw = Path(output_file.replace("\\", "/"))
            if not raw.is_absolute():
                candidates.append(root / raw)
            parts = list(raw.parts)
            for index, part in enumerate(parts):
                if part == "pypsa_data_sources" and index + 1 < len(parts):
                    candidates.append(root / Path(*parts[index + 1 :]))

    for candidate in candidates:
        try:
            candidate = ensure_inside(root, candidate)
        except AppError:
            continue
        if candidate.is_file() and candidate.suffix.lower() == ".csv":
            return candidate

    return ensure_inside(root, candidates[0])


def read_manifest(root: Path) -> tuple[list[str], list[dict[str, str]]]:
    manifest_path = root / MANIFEST_NAME
    columns, rows, _encoding = read_csv_rows(manifest_path)
    return columns, [dict(zip(columns, normalize_row(row, len(columns)))) for row in rows]


def catalog_items(root: Path) -> list[CatalogItem]:
    _columns, rows = read_manifest(root)
    items: list[CatalogItem] = []
    for row in rows:
        dataset = row.get("dataset", "").strip()
        if not dataset:
            continue
        path = resolve_dataset_path(root, dataset, row)
        if path.suffix.lower() != ".csv" or not path.exists():
            continue
        relative_path = path.relative_to(root).as_posix()
        group = dataset.split("/", 1)[0] if "/" in dataset else Path(relative_path).parts[0]
        items.append(
            CatalogItem(
                dataset=dataset,
                path=path,
                relative_path=relative_path,
                group=group,
                rows=row.get("rows", ""),
                columns=row.get("columns", ""),
                notes=row.get("notes", ""),
                source_file=row.get("source_file", ""),
            )
        )

    items.append(
        CatalogItem(
            dataset="manifest",
            path=root / MANIFEST_NAME,
            relative_path=MANIFEST_NAME,
            group="manifest",
            rows="",
            columns="",
            notes="Advanced catalog file.",
            source_file="",
            advanced=True,
        )
    )
    return items


def find_catalog_item(root: Path, dataset: str) -> CatalogItem:
    for item in catalog_items(root):
        if item.dataset == dataset:
            return item
    raise AppError(f"Unknown dataset: {dataset}", HTTPStatus.NOT_FOUND)


def item_to_json(item: CatalogItem) -> dict[str, Any]:
    return {
        "dataset": item.dataset,
        "relative_path": item.relative_path,
        "group": item.group,
        "rows": item.rows,
        "columns": item.columns,
        "notes": item.notes,
        "source_file": item.source_file,
        "advanced": item.advanced,
    }


def default_dataset(items: list[CatalogItem]) -> str:
    for preferred in ("loads/load_p_set", "renewables/nsj_sfx_v1_5_bands"):
        if any(item.dataset == preferred for item in items):
            return preferred
    for item in items:
        if not item.advanced and item.group != "raw":
            return item.dataset
    return items[0].dataset if items else ""


def compatible_run_options(root: Path) -> dict[str, Any]:
    items = [item for item in catalog_items(root) if not item.advanced]
    load_options = [item for item in items if is_compatible_load_source(item)]
    solar_options = [item for item in items if is_compatible_solar_source(item)]
    if not load_options:
        raise AppError("No load profile CSVs contain the columns required by the fast stochastic model.")
    if not solar_options:
        raise AppError("No NSJ SF rating profile CSVs contain MONTH, DAY, PERIOD, and samples 1-5.")
    return {
        "load_options": load_options,
        "solar_options": solar_options,
        "default_load": preferred_dataset(load_options, "loads/load_p_set"),
        "default_solar": preferred_dataset(solar_options, "renewables/nsj_sfx_v1_5_bands"),
    }


def solver_options() -> list[dict[str, Any]]:
    options = [{"value": "highs", "label": "HiGHS", "available": True}]
    license_path = find_gurobi_license()
    gurobipy_available = python_package_available("gurobipy")
    if license_path:
        label = "Gurobi"
        if not gurobipy_available:
            label = "Gurobi (license found)"
        options.append(
            {
                "value": "gurobi",
                "label": label,
                "available": True,
                "license_found": True,
                "python_package_available": gurobipy_available,
            }
        )
    else:
        options.append(
            {
                "value": "gurobi",
                "label": "Gurobi (license not found)",
                "available": False,
                "license_found": False,
                "python_package_available": gurobipy_available,
            }
        )
    return options


def solver_values() -> set[str]:
    return {option["value"] for option in solver_options()}


def power_model_options() -> list[dict[str, Any]]:
    options = []
    for value, model in POWER_MODELS.items():
        script_path = Path.cwd() / str(model["script"])
        required_scripts = [str(script) for script in model.get("required_scripts", [])]
        required_script_paths = [Path.cwd() / script for script in required_scripts]
        command_script = str(model.get("command_script", ""))
        command_script_path = Path.cwd() / command_script if command_script else None
        available = (
            script_path.is_file()
            and all(path.is_file() for path in required_script_paths)
            and (command_script_path is None or command_script_path.is_file())
        )
        options.append(
            {
                "value": value,
                "label": str(model["label"]),
                "script": str(model["script"]),
                "script_path": str(script_path.resolve()),
                "required_scripts": required_scripts,
                "required_script_paths": [str(path.resolve()) for path in required_script_paths],
                "command_script": command_script,
                "command_script_path": str(command_script_path.resolve()) if command_script_path else "",
                "available": available,
                "default_solver": str(model["default_solver"]),
                "uses_horizon": bool(model.get("uses_horizon", False)),
                "solver_time_limit": model.get("solver_time_limit", 360),
                "solver_mip_gap": model.get("solver_mip_gap", 0.005),
            }
        )
    return options


def power_model_config(value: str) -> dict[str, Any]:
    model_key = value or DEFAULT_POWER_MODEL
    if model_key not in POWER_MODELS:
        raise AppError("Selected power model is not supported.")
    config = dict(POWER_MODELS[model_key])
    config["value"] = model_key
    script_path = Path.cwd() / str(config["script"])
    if not script_path.is_file():
        raise AppError(f"Power model script was not found: {config['script']}", HTTPStatus.NOT_FOUND)
    config["script_path"] = script_path.resolve()
    required_script_paths = []
    for required_script in config.get("required_scripts", []):
        required_script_path = Path.cwd() / str(required_script)
        if not required_script_path.is_file():
            raise AppError(f"Required model script was not found: {required_script}", HTTPStatus.NOT_FOUND)
        required_script_paths.append(required_script_path.resolve())
    config["required_script_paths"] = required_script_paths
    if config.get("command_script"):
        command_script_path = Path.cwd() / str(config["command_script"])
        if not command_script_path.is_file():
            raise AppError(f"Scenario runner script was not found: {config['command_script']}", HTTPStatus.NOT_FOUND)
        config["command_script_path"] = command_script_path.resolve()
    return config


def find_gurobi_license() -> Path | None:
    candidates = [
        Path.cwd() / "gurobi.lic",
        *sorted(Path.cwd().glob("*gurobi*.lic")),
        *sorted(Path.cwd().glob("*.lic")),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def python_package_available(package_name: str) -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec(package_name) is not None
    except Exception:
        return False


def preferred_dataset(items: list[CatalogItem], preferred: str) -> str:
    for item in items:
        if item.dataset == preferred:
            return item.dataset
    return items[0].dataset


def is_compatible_load_source(item: CatalogItem) -> bool:
    columns = set(read_csv_header(item.path))
    return {"DateTime", *DEMAND_BUSES}.issubset(columns)


def is_compatible_solar_source(item: CatalogItem) -> bool:
    columns = set(read_csv_header(item.path))
    return {"MONTH", "DAY", "PERIOD", "1", "2", "3", "4", "5"}.issubset(columns)


def modified_time(path: Path) -> str:
    if not path.exists():
        return "-"
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")


def clean_table(columns: Any, rows: Any) -> tuple[list[str], list[list[str]]]:
    if not isinstance(columns, list) or not all(isinstance(item, str) for item in columns):
        raise AppError("Columns must be a list of strings.")
    if not isinstance(rows, list):
        raise AppError("Rows must be a list.")
    cleaned_rows: list[list[str]] = []
    for row in rows:
        if not isinstance(row, list):
            raise AppError("Each row must be a list.")
        cleaned_rows.append(normalize_row([str(value) if value is not None else "" for value in row], len(columns)))
    return [str(column) for column in columns], cleaned_rows


def make_message(message: str, row: int | None = None, column: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"message": message}
    if row is not None:
        result["row"] = row
    if column:
        result["column"] = column
    return result


def is_number(value: str) -> bool:
    if value == "":
        return False
    try:
        float(value)
    except ValueError:
        return False
    return True


def parse_number(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def parses_datetime(value: str) -> bool:
    if not value.strip():
        return False
    text = value.strip().replace("/", "-")
    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%d-%m-%Y",
    )
    for fmt in formats:
        try:
            datetime.strptime(text, fmt)
            return True
        except ValueError:
            pass
    try:
        datetime.fromisoformat(value.strip())
        return True
    except ValueError:
        return False


def validate_table(
    dataset: str,
    columns: list[str],
    rows: list[list[str]],
    item: CatalogItem | None = None,
) -> dict[str, list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if not columns:
        errors.append(make_message("CSV must include a header row."))
        return {"errors": errors, "warnings": warnings}

    duplicates = sorted({column for column in columns if columns.count(column) > 1})
    for column in duplicates:
        errors.append(make_message("Duplicate column name.", column=column))

    if not rows:
        errors.append(make_message("CSV must include at least one data row."))

    schema = schema_for_dataset(dataset)
    required = schema.get("required", [])
    for column in required:
        if column not in columns:
            errors.append(make_message("Missing required column.", column=column))

    if item and item.rows not in ("", None) and str(len(rows)) != str(int(float(item.rows)) if is_number(str(item.rows)) else item.rows):
        warnings.append(make_message(f"Row count differs from manifest value {item.rows}."))
    if item and item.columns not in ("", None) and str(len(columns)) != str(int(float(item.columns)) if is_number(str(item.columns)) else item.columns):
        warnings.append(make_message(f"Column count differs from manifest value {item.columns}."))

    if item and item.group == "raw":
        warnings.append(make_message("This is a raw source file; transformed CSVs may need regeneration."))
    if item and item.group == "excel_exports":
        warnings.append(make_message("This CSV was exported from Excel; the original workbook is not updated."))

    for datetime_column in schema.get("datetime", []):
        if datetime_column not in columns:
            continue
        col_index = columns.index(datetime_column)
        seen: dict[str, int] = {}
        for row_index, row in enumerate(rows, start=2):
            value = row[col_index].strip()
            if not parses_datetime(value):
                errors.append(make_message("Value must parse as a datetime.", row=row_index, column=datetime_column))
                if len(errors) > 100:
                    break
            elif value in seen:
                warnings.append(make_message(f"Duplicate timestamp also appears on row {seen[value]}.", row=row_index, column=datetime_column))
            else:
                seen[value] = row_index

    for column in schema.get("numeric", []):
        if column not in columns:
            continue
        col_index = columns.index(column)
        for row_index, row in enumerate(rows, start=2):
            value = row[col_index].strip()
            if not is_number(value):
                errors.append(make_message("Value must be numeric.", row=row_index, column=column))
                if len(errors) > 100:
                    break
            elif column in schema.get("nonnegative", []) and float(value) < 0:
                errors.append(make_message("Value must be non-negative.", row=row_index, column=column))

    if schema.get("renewable_period"):
        validate_renewable_period(columns, rows, errors)

    if schema.get("renewable_samples"):
        for column in schema["renewable_samples"]:
            if column not in columns:
                continue
            col_index = columns.index(column)
            for row_index, row in enumerate(rows, start=2):
                value = row[col_index].strip()
                number = parse_number(value)
                if number is None:
                    errors.append(make_message("Sample value must be numeric.", row=row_index, column=column))
                elif number < 0 or number > 1:
                    warnings.append(make_message("Sample value is outside the expected 0-1 range.", row=row_index, column=column))
                if len(errors) > 100 or len(warnings) > 100:
                    break

    if dataset.endswith("commit.csv") or dataset == "generators/commit":
        for column in [col for col in columns if col != "DateTime"]:
            col_index = columns.index(column)
            for row_index, row in enumerate(rows, start=2):
                value = row[col_index].strip()
                if value and value not in ("-1", "0", "1", "-1.0", "0.0", "1.0"):
                    warnings.append(make_message("Expected commitment flag -1, 0, or 1.", row=row_index, column=column))

    return {"errors": errors[:200], "warnings": warnings[:200]}


def validate_renewable_period(
    columns: list[str],
    rows: list[list[str]],
    errors: list[dict[str, Any]],
) -> None:
    indexes = {name: columns.index(name) for name in ("MONTH", "DAY", "PERIOD") if name in columns}
    if set(indexes) != {"MONTH", "DAY", "PERIOD"}:
        return
    for row_index, row in enumerate(rows, start=2):
        month = parse_int(row[indexes["MONTH"]])
        day = parse_int(row[indexes["DAY"]])
        period = parse_int(row[indexes["PERIOD"]])
        if month is None or month < 1 or month > 12:
            errors.append(make_message("MONTH must be 1-12.", row=row_index, column="MONTH"))
        if day is None or month is None or month not in RENEWABLE_DAY_LIMITS or day < 1 or day > RENEWABLE_DAY_LIMITS[month]:
            errors.append(make_message("DAY is not valid for MONTH.", row=row_index, column="DAY"))
        if period is None or period < 1 or period > 48:
            errors.append(make_message("PERIOD must be 1-48.", row=row_index, column="PERIOD"))
        if len(errors) > 100:
            break


def parse_int(value: str) -> int | None:
    try:
        number = float(value)
    except ValueError:
        return None
    if not number.is_integer():
        return None
    return int(number)


def schema_for_dataset(dataset: str) -> dict[str, Any]:
    normalized = dataset.replace("\\", "/")

    if normalized in ("loads/load_p_set", "raw/Demand/09. 2w_30min_demand.csv"):
        return {
            "required": ["DateTime", *DEMAND_BUSES],
            "datetime": ["DateTime"],
            "numeric": list(DEMAND_BUSES),
            "nonnegative": list(DEMAND_BUSES),
        }
    if normalized == "loads/load_p_set_long":
        return {
            "required": ["DateTime", "bus", "p_set"],
            "datetime": ["DateTime"],
            "numeric": ["p_set"],
            "nonnegative": ["p_set"],
        }
    if normalized in ("renewables/nsj_sfx", "raw/Renewable load profile/NSJ-SFX.csv"):
        samples = [str(i) for i in range(1, 11)]
        return {
            "required": ["MONTH", "DAY", "PERIOD", *samples],
            "numeric": ["MONTH", "DAY", "PERIOD", *samples],
            "renewable_samples": samples,
            "renewable_period": True,
        }
    if normalized in ("renewables/nsj_sfx_v1", "raw/Renewable load profile/NSJ-SFXv1.csv"):
        return {
            "required": ["MONTH", "DAY", "PERIOD", "1"],
            "numeric": ["MONTH", "DAY", "PERIOD", "1"],
            "renewable_samples": ["1"],
            "renewable_period": True,
        }
    if normalized in (
        "renewables/nsj_sfx_v1_5_bands",
        "raw/Renewable load profile/NSJ-SFXv1_5 bands.csv",
    ):
        samples = [str(i) for i in range(1, 6)]
        return {
            "required": ["MONTH", "DAY", "PERIOD", *samples],
            "numeric": ["MONTH", "DAY", "PERIOD", *samples],
            "renewable_samples": samples,
            "renewable_period": True,
        }
    if normalized in (
        "renewables/solar_ratio_ch",
        "raw/Solar Profile CH/Solar Ratio CH.csv",
        "excel_exports/Solar Ratio CH/Solar Ratio CH",
    ):
        return {
            "required": ["DateTime", "Value"],
            "datetime": ["DateTime"],
            "numeric": ["Value"],
        }
    if normalized in (
        "generators/commit",
        "generators/derating",
        "generators/units_out",
        "raw/Maintenance/Commit.csv",
        "raw/Maintenance/Derating.csv",
        "raw/Maintenance/UnitsOut.csv",
    ):
        return {
            "required": ["DateTime", *THERMAL_GENERATORS],
            "datetime": ["DateTime"],
            "numeric": list(THERMAL_GENERATORS),
        }
    if normalized in ("generators/markup", "raw/Maintenance/Markup.csv"):
        return {
            "required": ["Name", "Value"],
            "numeric": ["Value"],
        }
    if normalized == "manifest":
        return {
            "required": ["dataset", "source_file", "output_file", "rows", "columns", "notes"],
        }
    return {"required": []}


def backup_file(root: Path, item: CatalogItem) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dataset_folder = sanitize_backup_part(item.dataset)
    backup_path = root / ".backups" / dataset_folder / timestamp / item.path.name
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(item.path, backup_path)
    return backup_path


def sanitize_backup_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip("/\\"))
    return cleaned or "dataset"


def update_manifest_counts(root: Path, dataset: str, rows_count: int, columns_count: int) -> None:
    if dataset == "manifest":
        return
    manifest_path = root / MANIFEST_NAME
    columns, rows, _encoding = read_csv_rows(manifest_path)
    if not columns:
        raise AppError("Manifest is empty.")
    dataset_index = columns.index("dataset") if "dataset" in columns else -1
    if dataset_index < 0:
        raise AppError("Manifest is missing dataset column.")
    rows_index = ensure_manifest_column(columns, "rows")
    columns_index = ensure_manifest_column(columns, "columns")

    for row in rows:
        normalized = normalize_row(row, len(columns))
        if normalized[dataset_index] == dataset:
            normalized[rows_index] = str(rows_count)
            normalized[columns_index] = str(columns_count)
            row[:] = normalized
            write_csv_rows(manifest_path, columns, rows)
            return


def ensure_manifest_column(columns: list[str], name: str) -> int:
    if name not in columns:
        columns.append(name)
    return columns.index(name)


def add_manifest_row(
    root: Path,
    source_item: CatalogItem,
    dataset: str,
    relative_path: str,
    rows_count: int,
    columns_count: int,
    notes: str,
) -> None:
    manifest_path = root / MANIFEST_NAME
    columns, rows, _encoding = read_csv_rows(manifest_path)
    required_columns = ["dataset", "source_file", "output_file", "rows", "columns", "notes"]
    for column in required_columns:
        if column not in columns:
            columns.append(column)
            for row in rows:
                row.append("")

    record = {column: "" for column in columns}
    record["dataset"] = dataset
    record["source_file"] = source_item.source_file
    record["output_file"] = str((root / relative_path).resolve())
    record["rows"] = str(rows_count)
    record["columns"] = str(columns_count)
    record["notes"] = notes
    rows.append([record.get(column, "") for column in columns])
    write_csv_rows(manifest_path, columns, rows)


def safe_relative_csv_path(value: str) -> str:
    if not value:
        raise AppError("Copy path is required.")
    normalized = value.replace("\\", "/").strip("/")
    if posixpath.isabs(normalized) or ".." in normalized.split("/"):
        raise AppError("Copy path must stay inside the data root.")
    if not normalized.lower().endswith(".csv"):
        normalized += ".csv"
    return normalized


def parse_positive_float(value: Any, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise AppError(f"{label} must be a number.")
    if parsed <= 0:
        raise AppError(f"{label} must be greater than zero.")
    return parsed


def parse_nonnegative_float(value: Any, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise AppError(f"{label} must be a number.")
    if parsed < 0:
        raise AppError(f"{label} must be zero or greater.")
    return parsed


def prepare_model_run(
    root: Path,
    load_item: CatalogItem,
    solar_item: CatalogItem,
    power_model: str,
    solver_name: str,
    solver_log: bool,
    horizon_hours: float,
    lookahead_hours: float,
    nonanticipative_hours: float,
    solver_time_limit: float,
    solver_mip_gap: float,
) -> tuple[Path, Path, Path]:
    model_config = power_model_config(power_model)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    run_dir = Path.cwd() / MODEL_RUNS_DIR / run_id
    data_dir = run_dir / "data_sources"
    outputs_dir = run_dir / OUTPUT_DIR_NAME
    data_dir.mkdir(parents=True, exist_ok=False)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    load_target = data_dir / "loads" / "load_p_set.csv"
    solar_target = data_dir / "renewables" / "nsj_sfx_v1_5_bands.csv"
    load_target.parent.mkdir(parents=True, exist_ok=True)
    solar_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(load_item.path, load_target)
    shutil.copy2(solar_item.path, solar_target)

    selected_sources = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_data_root": str(root),
        "power_model": power_model,
        "power_model_script": str(model_config["script"]),
        "power_model_command_script": str(model_config.get("command_script", "")),
        "scenario_name": str(model_config.get("scenario_name", "")),
        "sol_bess": str(model_config.get("sol_bess", "")),
        "nss_bess": str(model_config.get("nss_bess", "")),
        "solver_name": solver_name,
        "solver_log": solver_log,
        "horizon_hours": horizon_hours,
        "lookahead_hours": lookahead_hours,
        "nonanticipative_hours": nonanticipative_hours,
        "solver_time_limit": solver_time_limit,
        "solver_mip_gap": solver_mip_gap,
        "inputs": {
            "loads/load_p_set.csv": {
                "dataset": load_item.dataset,
                "source_path": str(load_item.path),
            },
            "renewables/nsj_sfx_v1_5_bands.csv": {
                "dataset": solar_item.dataset,
                "source_path": str(solar_item.path),
            },
        },
    }
    (run_dir / "selected_sources.json").write_text(
        json.dumps(selected_sources, indent=2),
        encoding="utf-8",
    )
    write_csv_rows(
        data_dir / MANIFEST_NAME,
        ["dataset", "source_file", "output_file", "rows", "columns", "notes"],
        [
            source_manifest_row("loads/load_p_set", load_item, load_target),
            source_manifest_row("renewables/nsj_sfx_v1_5_bands", solar_item, solar_target),
        ],
    )
    return run_dir, data_dir, outputs_dir


def source_manifest_row(dataset: str, source_item: CatalogItem, target: Path) -> list[str]:
    columns, rows, _encoding = read_csv_rows(source_item.path)
    return [
        dataset,
        str(source_item.path),
        str(target),
        str(len(rows)),
        str(len(columns)),
        f"Selected from {source_item.dataset} for model run.",
    ]


def run_output_paths(outputs_dir: Path) -> dict[str, str]:
    return {
        "thermal_generation_by_interval_csv": str(outputs_dir / THERMAL_OUTPUT),
        "generation_by_interval_csv": str(outputs_dir / GENERATION_OUTPUT),
        "unserved_energy_by_interval_csv": str(outputs_dir / UNSERVED_OUTPUT),
        "load_by_bus_by_interval_csv": str(outputs_dir / LOAD_OUTPUT),
        "generator_dispatch_by_interval_csv": str(outputs_dir / GENERATOR_OUTPUT),
        "line_flow_by_interval_csv": str(outputs_dir / LINE_FLOW_OUTPUT),
        "reserves_by_interval_csv": str(outputs_dir / RESERVES_OUTPUT),
        "battery_soc_by_interval_csv": str(outputs_dir / BATTERY_SOC_OUTPUT),
    }


def solver_environment(solver_name: str) -> dict[str, str]:
    env = os.environ.copy()
    if solver_name.lower() == "gurobi":
        license_path = find_gurobi_license()
        if license_path:
            env["GRB_LICENSE_FILE"] = str(license_path)
    return env


def build_solve_command(
    data_dir: Path,
    outputs_dir: Path,
    solver_name: str,
    solver_log: bool,
    horizon_hours: float,
    lookahead_hours: float,
    nonanticipative_hours: float,
    solver_time_limit: float,
    solver_mip_gap: float,
    power_model: str = DEFAULT_POWER_MODEL,
    unbuffered: bool = False,
) -> list[str]:
    model = power_model_config(power_model)
    if model.get("custom_scenario_command"):
        command_script_path = Path(model["command_script_path"])
        command = [sys.executable]
        if unbuffered:
            command.append("-u")
        command.extend(
            [
                "-B",
                str(command_script_path),
                "--scenario-name",
                str(model.get("scenario_name", "custom_stochastic_dispatch")),
                "--data-dir",
                str(data_dir),
                "--sol-bess",
                str(model.get("sol_bess", "enabled")),
                "--nss-bess",
                str(model.get("nss_bess", "disabled")),
                "--nonanticipative-hours",
                str(nonanticipative_hours),
                "--solver-name",
                solver_name,
                "--solver-time-limit",
                str(solver_time_limit),
                "--solver-mip-gap",
                str(solver_mip_gap),
                "--output-dir",
                str(outputs_dir),
            ]
        )
        if solver_log:
            command.append("--solver-log")
        license_path = find_gurobi_license()
        if solver_name == "gurobi" and license_path:
            command.extend(["--gurobi-license-file", str(license_path)])
        return command

    raise AppError("This branch only supports the fast custom stochastic scenario.")


def run_network_script(
    data_dir: Path,
    outputs_dir: Path,
    power_model: str,
    solver_name: str,
    solver_log: bool,
    horizon_hours: float,
    lookahead_hours: float,
    nonanticipative_hours: float,
    solver_time_limit: float,
    solver_mip_gap: float,
) -> dict[str, Any]:
    output_paths = run_output_paths(outputs_dir)
    command = build_solve_command(
        data_dir,
        outputs_dir,
        solver_name,
        solver_log,
        horizon_hours,
        lookahead_hours,
        nonanticipative_hours,
        solver_time_limit,
        solver_mip_gap,
        power_model=power_model,
    )

    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=Path.cwd(),
            env=solver_environment(solver_name),
            capture_output=True,
            text=True,
            timeout=1800,
        )
        duration = time.perf_counter() - started
        return {
            "command": command_display(command),
            "returncode": completed.returncode,
            "succeeded": completed.returncode == 0,
            "timed_out": False,
            "duration_seconds": duration,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "outputs": output_paths,
        }
    except subprocess.TimeoutExpired as exc:
        duration = time.perf_counter() - started
        return {
            "command": command_display(command),
            "returncode": None,
            "succeeded": False,
            "timed_out": True,
            "duration_seconds": duration,
            "stdout": normalize_subprocess_output(exc.stdout),
            "stderr": normalize_subprocess_output(exc.stderr) + "\nRun timed out after 1800 seconds.",
            "outputs": output_paths,
        }


def prepare_run_request(payload: dict[str, Any]) -> dict[str, Any]:
    root = find_data_root(payload.get("root"))
    power_model = str(payload.get("power_model", DEFAULT_POWER_MODEL)).strip() or DEFAULT_POWER_MODEL
    model_config = power_model_config(power_model)
    load_dataset = str(payload.get("load_dataset", ""))
    solar_dataset = str(payload.get("solar_dataset", ""))
    solver_name = str(payload.get("solver_name", model_config["default_solver"])).strip() or str(model_config["default_solver"])
    solver_log = bool(payload.get("solver_log", False))
    horizon_hours = parse_positive_float(payload.get("horizon_hours", 24), "Reporting horizon hours")
    lookahead_hours = parse_nonnegative_float(payload.get("lookahead_hours", 24), "Lookahead hours")
    nonanticipative_hours = parse_nonnegative_float(payload.get("nonanticipative_hours", 20), "Generation non-anticipativity hours")
    solver_time_limit = parse_positive_float(payload.get("solver_time_limit", model_config.get("solver_time_limit", 360)), "Solver time limit seconds")
    solver_mip_gap = parse_nonnegative_float(payload.get("solver_mip_gap", model_config.get("solver_mip_gap", 0.005)), "Solver MIP gap")
    if horizon_hours > 8760:
        raise AppError("Reporting horizon hours must be 8760 or less.")
    if lookahead_hours > 8760:
        raise AppError("Lookahead hours must be 8760 or less.")
    if nonanticipative_hours > 8760:
        raise AppError("Generation non-anticipativity hours must be 8760 or less.")
    if solver_time_limit > 86400:
        raise AppError("Solver time limit must be 86400 seconds or less.")
    if solver_mip_gap > 1:
        raise AppError("Solver MIP gap must be between 0 and 1.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", solver_name):
        raise AppError("Solver name contains unsupported characters.")
    if solver_name not in solver_values():
        raise AppError(f"Unsupported solver: {solver_name}")
    if solver_name == "gurobi" and not find_gurobi_license():
        raise AppError("Gurobi solver selected but no Gurobi license file was found in the workspace.")

    load_item = find_catalog_item(root, load_dataset)
    solar_item = find_catalog_item(root, solar_dataset)
    if not is_compatible_load_source(load_item):
        raise AppError("Selected load source is missing DateTime or required demand bus columns.")
    if not is_compatible_solar_source(solar_item):
        raise AppError("Selected solar source is missing MONTH, DAY, PERIOD, or sample columns 1-5.")

    run_dir, data_dir, outputs_dir = prepare_model_run(
        root=root,
        load_item=load_item,
        solar_item=solar_item,
        power_model=power_model,
        solver_name=solver_name,
        solver_log=solver_log,
        horizon_hours=horizon_hours,
        lookahead_hours=lookahead_hours,
        nonanticipative_hours=nonanticipative_hours,
        solver_time_limit=solver_time_limit,
        solver_mip_gap=solver_mip_gap,
    )
    return {
        "root": root,
        "power_model": power_model,
        "power_model_label": str(model_config["label"]),
        "power_model_script": str(model_config["script"]),
        "load_dataset": load_dataset,
        "solar_dataset": solar_dataset,
        "solver_name": solver_name,
        "solver_log": solver_log,
        "horizon_hours": horizon_hours,
        "lookahead_hours": lookahead_hours,
        "nonanticipative_hours": nonanticipative_hours,
        "solver_time_limit": solver_time_limit,
        "solver_mip_gap": solver_mip_gap,
        "run_dir": run_dir,
        "data_dir": data_dir,
        "outputs_dir": outputs_dir,
    }


def start_run_job(payload: dict[str, Any]) -> dict[str, Any]:
    prepared = prepare_run_request(payload)
    job_id = uuid.uuid4().hex
    command = build_solve_command(
        prepared["data_dir"],
        prepared["outputs_dir"],
        prepared["solver_name"],
        prepared["solver_log"],
        prepared["horizon_hours"],
        prepared["lookahead_hours"],
        prepared["nonanticipative_hours"],
        prepared["solver_time_limit"],
        prepared["solver_mip_gap"],
        power_model=prepared["power_model"],
        unbuffered=True,
    )
    now = time.time()
    job = {
        "job_id": job_id,
        "status": "queued",
        "stage": "Queued",
        "stage_detail": "Queued.",
        "progress": RUN_STAGE_PROGRESS["Queued"],
        "started_at": now,
        "ended_at": None,
        "duration_seconds": 0.0,
        "run_dir": str(prepared["run_dir"]),
        "data_dir": str(prepared["data_dir"]),
        "outputs_dir": str(prepared["outputs_dir"]),
        "command": command_display(command),
        "returncode": None,
        "succeeded": False,
        "timed_out": False,
        "stdout": "",
        "stderr": "",
        "run_log_path": str(prepared["run_dir"] / RUN_OUTPUT_LOG),
        "outputs": run_output_paths(prepared["outputs_dir"]),
        "power_model": prepared["power_model"],
        "power_model_label": prepared["power_model_label"],
        "power_model_script": prepared["power_model_script"],
        "stderr_to_stdout": bool(power_model_config(prepared["power_model"]).get("stderr_to_stdout", False)),
        "solver_name": prepared["solver_name"],
        "solver_log": prepared["solver_log"],
        "horizon_hours": prepared["horizon_hours"],
        "lookahead_hours": prepared["lookahead_hours"],
        "nonanticipative_hours": prepared["nonanticipative_hours"],
        "solver_time_limit": prepared["solver_time_limit"],
        "solver_mip_gap": prepared["solver_mip_gap"],
        "selected_sources": {
            "load_dataset": prepared["load_dataset"],
            "solar_dataset": prepared["solar_dataset"],
        },
        "process": None,
        "pid": None,
        "cancel_requested": False,
    }
    with RUN_JOBS_LOCK:
        RUN_JOBS[job_id] = job
    initialize_job_log_file(job)
    append_job_log(job_id, "stdout", f"[{datetime.now().strftime('%H:%M:%S')}] Queued {prepared['power_model_label']} solve.\n")
    thread = threading.Thread(
        target=run_job_worker,
        args=(job_id, command, prepared["solver_name"]),
        name=f"pypsa-run-{job_id[:8]}",
        daemon=True,
    )
    thread.start()
    return public_job(job)


def run_job_worker(job_id: str, command: list[str], solver_name: str) -> None:
    update_job(job_id, status="running", stage="Starting solve process", stage_detail="Starting Python solve process.")
    append_job_log(job_id, "stdout", f"[{datetime.now().strftime('%H:%M:%S')}] Preparing live solve process.\n")
    started = time.perf_counter()
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            command,
            cwd=Path.cwd(),
            env=solver_environment(solver_name),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        update_job(job_id, process=process, pid=process.pid, stage="Building stochastic scenario", stage_detail="Building stochastic network and optimization model.")
        append_job_log(job_id, "stdout", f"[{datetime.now().strftime('%H:%M:%S')}] Started process {process.pid}. Building model inputs and scenario copies.\n")

        readers = []
        if process.stdout is not None:
            readers.append(threading.Thread(target=read_process_stream, args=(job_id, process.stdout, "stdout"), daemon=True))
        if process.stderr is not None:
            with RUN_JOBS_LOCK:
                stderr_to_stdout = bool(RUN_JOBS.get(job_id, {}).get("stderr_to_stdout"))
            stderr_stream_name = "stdout" if stderr_to_stdout else "stderr"
            readers.append(threading.Thread(target=read_process_stream, args=(job_id, process.stderr, stderr_stream_name), daemon=True))
        for reader in readers:
            reader.start()

        timed_out = False
        while process.poll() is None:
            with RUN_JOBS_LOCK:
                cancel_requested = bool(RUN_JOBS.get(job_id, {}).get("cancel_requested"))
            if cancel_requested:
                update_job(job_id, stage="Cancelled", stage_detail="Cancelling solve process.", progress=95)
                process.terminate()
                break
            if time.perf_counter() - started > 1800:
                timed_out = True
                update_job(job_id, timed_out=True, stage="Failed", stage_detail="Run timed out after 1800 seconds.", progress=100)
                process.terminate()
                break
            update_job(job_id, duration_seconds=time.perf_counter() - started)
            time.sleep(0.5)

        try:
            returncode = process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            returncode = process.wait(timeout=10)

        for reader in readers:
            reader.join(timeout=2)

        duration = time.perf_counter() - started
        with RUN_JOBS_LOCK:
            job = RUN_JOBS.get(job_id, {})
            cancel_requested = bool(job.get("cancel_requested"))
        if cancel_requested:
            update_job(
                job_id,
                status="cancelled",
                stage="Cancelled",
                stage_detail="Run cancelled by user.",
                progress=100,
                returncode=returncode,
                duration_seconds=duration,
                ended_at=time.time(),
            )
        elif timed_out:
            append_job_log(job_id, "stderr", "\nRun timed out after 1800 seconds.\n")
            update_job(
                job_id,
                status="failed",
                stage="Failed",
                stage_detail="Run timed out after 1800 seconds.",
                progress=100,
                returncode=returncode,
                duration_seconds=duration,
                ended_at=time.time(),
                timed_out=True,
            )
        elif returncode == 0:
            update_job(
                job_id,
                status="complete",
                stage="Complete",
                stage_detail="Solve complete and outputs exported.",
                progress=100,
                returncode=returncode,
                duration_seconds=duration,
                ended_at=time.time(),
                succeeded=True,
            )
        else:
            update_job(
                job_id,
                status="failed",
                stage="Failed",
                stage_detail=f"Solve process exited with code {returncode}.",
                progress=100,
                returncode=returncode,
                duration_seconds=duration,
                ended_at=time.time(),
            )
    except Exception as exc:
        append_job_log(job_id, "stderr", f"\n{exc}\n")
        update_job(
            job_id,
            status="failed",
            stage="Failed",
            stage_detail=str(exc),
            progress=100,
            duration_seconds=time.perf_counter() - started,
            ended_at=time.time(),
        )
        if process and process.poll() is None:
            process.kill()


def read_process_stream(job_id: str, stream: Any, stream_name: str) -> None:
    try:
        for line in iter(stream.readline, ""):
            append_job_log(job_id, stream_name, line)
            apply_progress_from_line(job_id, line)
    finally:
        try:
            stream.close()
        except Exception:
            pass


def apply_progress_from_line(job_id: str, line: str) -> None:
    text = line.strip()
    if not text:
        return
    lower = text.lower()
    if text == "stage=building_stochastic_scenario":
        update_job(job_id, stage="Building stochastic scenario", stage_detail="Building stochastic network and scenario copies.")
    elif text == "stage=exporting_outputs":
        update_job(job_id, stage="Exporting outputs", stage_detail="Writing interval output CSVs.")
    elif text == "stage=complete":
        update_job(job_id, stage="Complete", stage_detail="Solve complete; finalising output files.", progress=98)
    elif "solving base stochastic dispatch scenario" in lower:
        update_job(job_id, stage="Running solver", stage_detail=text)
    elif "wrote solution outputs" in lower:
        update_job(job_id, stage="Exporting outputs", stage_detail=text)
    elif "writing objective" in lower or "writing constraints" in lower or "write problem" in lower:
        update_job(job_id, stage="Writing optimization model", stage_detail=text)
    elif "solve problem using" in lower or "running highs" in lower or "presolving" in lower:
        update_job(job_id, stage="Running solver", stage_detail=text)
    elif "model status" in lower or "termination condition" in lower or "optimal" in lower:
        update_job(job_id, stage="Solver finished", stage_detail=text)
    else:
        with RUN_JOBS_LOCK:
            job = RUN_JOBS.get(job_id)
            if job and job.get("status") == "running":
                job["stage_detail"] = text[:240]


def update_job(job_id: str, **updates: Any) -> None:
    with RUN_JOBS_LOCK:
        job = RUN_JOBS.get(job_id)
        if not job:
            return
        if "stage" in updates and "progress" not in updates:
            updates["progress"] = max(float(job.get("progress", 0)), RUN_STAGE_PROGRESS.get(str(updates["stage"]), float(job.get("progress", 0))))
        job.update(updates)


def append_job_log(job_id: str, stream_name: str, text: str) -> None:
    text = ANSI_ESCAPE_RE.sub("", text).replace("\r", "\n")
    log_path = ""
    with RUN_JOBS_LOCK:
        job = RUN_JOBS.get(job_id)
        if not job:
            return
        current = str(job.get(stream_name, "")) + text
        if len(current) > 60000:
            current = current[-60000:]
        job[stream_name] = current
        log_path = str(job.get("run_log_path", ""))
    if log_path:
        append_run_log_file(Path(log_path), stream_name, text)


def initialize_job_log_file(job: dict[str, Any]) -> None:
    path_value = str(job.get("run_log_path", ""))
    if not path_value:
        return
    path = Path(path_value)
    lines = [
        "PyPSA run output log",
        f"created_at={datetime.now().isoformat(timespec='seconds')}",
        f"job_id={job.get('job_id', '')}",
        f"run_dir={job.get('run_dir', '')}",
        f"power_model={job.get('power_model_label', job.get('power_model', ''))}",
        f"solver={job.get('solver_name', '')}",
        f"horizon_hours={job.get('horizon_hours', '')}",
        f"lookahead_hours={job.get('lookahead_hours', '')}",
        f"nonanticipative_hours={job.get('nonanticipative_hours', '')}",
        f"solver_time_limit={job.get('solver_time_limit', '')}",
        f"solver_mip_gap={job.get('solver_mip_gap', '')}",
        f"command={job.get('command', '')}",
        "",
    ]
    with RUN_LOG_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")


def append_run_log_file(path: Path, stream_name: str, text: str) -> None:
    if not text:
        return
    label = "stderr" if stream_name == "stderr" else "stdout"
    with RUN_LOG_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="") as handle:
            for line in text.splitlines(True):
                if line.endswith("\n"):
                    handle.write(f"[{label}] {line}")
                else:
                    handle.write(f"[{label}] {line}\n")


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in job.items()
        if key not in {"process"}
    }


def get_public_job(job_id: str) -> dict[str, Any]:
    with RUN_JOBS_LOCK:
        job = RUN_JOBS.get(job_id)
        if not job:
            raise AppError("Run job was not found.", HTTPStatus.NOT_FOUND)
        copied = dict(job)
    return public_job(copied)


def cancel_run_job(job_id: str) -> dict[str, Any]:
    with RUN_JOBS_LOCK:
        job = RUN_JOBS.get(job_id)
        if not job:
            raise AppError("Run job was not found.", HTTPStatus.NOT_FOUND)
        job["cancel_requested"] = True
        job["stage_detail"] = "Cancel requested."
        process = job.get("process")
    if process and process.poll() is None:
        try:
            process.terminate()
        except Exception as exc:
            raise AppError(f"Could not cancel run: {exc}")
    return get_public_job(job_id)


def active_run_job() -> dict[str, Any] | None:
    with RUN_JOBS_LOCK:
        active_jobs = [
            dict(job)
            for job in RUN_JOBS.values()
            if job.get("status") in {"queued", "running"}
        ]
    if not active_jobs:
        return None
    active_jobs.sort(key=lambda job: float(job.get("started_at", 0.0)), reverse=True)
    return public_job(active_jobs[0])


def normalize_subprocess_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def command_display(command: list[str]) -> str:
    return " ".join(quote_command_part(part) for part in command)


def quote_command_part(part: str) -> str:
    if re.search(r"\s", part):
        return f'"{part}"'
    return part


def model_runs_root() -> Path:
    return (Path.cwd() / MODEL_RUNS_DIR).resolve()


def dashboard_output_files(output_dir: Path) -> list[Path]:
    return [output_dir / THERMAL_OUTPUT, output_dir / UNSERVED_OUTPUT, output_dir / LOAD_OUTPUT]


def list_output_runs() -> list[dict[str, Any]]:
    root = model_runs_root()
    if not root.exists():
        return []
    runs: list[dict[str, Any]] = []
    for run_dir in sorted((path for path in root.iterdir() if path.is_dir()), key=lambda path: path.name, reverse=True):
        output_dir = run_dir / OUTPUT_DIR_NAME
        files = dashboard_output_files(output_dir)
        complete = all(path.is_file() for path in files)
        status = "complete" if complete else "pending"
        if output_dir.exists() and not complete:
            status = "partial"
        elif not output_dir.exists() and not (run_dir / "selected_sources.json").exists():
            status = "unknown"
        runs.append(
            {
                "name": run_dir.name,
                "status": status,
                "run_dir": str(run_dir),
                "output_dir": str(output_dir),
                "modified": modified_time(run_dir),
                "files": [
                    {
                        "name": path.name,
                        "exists": path.is_file(),
                        "size_bytes": path.stat().st_size if path.is_file() else 0,
                    }
                    for path in files
                ],
            }
        )
    return runs


def default_output_run(runs: list[dict[str, Any]]) -> str:
    for run in runs:
        if run["status"] == "complete":
            return str(run["name"])
    return str(runs[0]["name"]) if runs else ""


def resolve_run_dir(run_name: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", run_name):
        raise AppError("Run name contains unsupported characters.")
    root = model_runs_root()
    run_dir = (root / run_name).resolve()
    if run_dir != root and root in run_dir.parents and run_dir.is_dir():
        return run_dir
    raise AppError("Run folder was not found.", HTTPStatus.NOT_FOUND)


def resolve_run_file(run_name: str, relative_file: str) -> Path:
    run_dir = resolve_run_dir(run_name)
    relative_file = unquote(relative_file).replace("\\", "/").strip()
    if not relative_file:
        raise AppError("File is required.")
    normalized = posixpath.normpath(relative_file)
    if normalized in {"", "."} or normalized.startswith("../") or normalized.startswith("/"):
        raise AppError("Run file path is not allowed.")
    candidate = (run_dir / Path(normalized)).resolve()
    if candidate != run_dir and run_dir in candidate.parents and candidate.is_file():
        return candidate
    raise AppError("Run file was not found.", HTTPStatus.NOT_FOUND)


def content_type_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return "text/csv; charset=utf-8"
    if suffix == ".json":
        return "application/json; charset=utf-8"
    if suffix in {".log", ".txt"}:
        return "text/plain; charset=utf-8"
    return "application/octet-stream"


def read_dict_rows(path: Path) -> list[dict[str, str]]:
    text, _encoding = read_text(path)
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


def run_file_url(run_dir: Path, path: Path) -> str:
    relative = path.resolve().relative_to(run_dir.resolve()).as_posix()
    return f"/api/run-file?run={quote(run_dir.name)}&file={quote(relative, safe='')}"


def output_files_json(output_dir: Path, run_dir: Path | None = None) -> list[dict[str, Any]]:
    run_dir = run_dir or output_dir.parent
    files = []
    for path in [
        *dashboard_output_files(output_dir),
        output_dir / GENERATION_OUTPUT,
        output_dir / GENERATOR_OUTPUT,
        output_dir / LINE_FLOW_OUTPUT,
        output_dir / RESERVES_OUTPUT,
        output_dir / BATTERY_SOC_OUTPUT,
        run_dir / RUN_OUTPUT_LOG,
    ]:
        exists = path.is_file()
        files.append(
            {
                "name": path.name,
                "path": str(path),
                "relative_path": path.resolve().relative_to(run_dir.resolve()).as_posix(),
                "url": run_file_url(run_dir, path) if exists else "",
                "exists": exists,
                "size_bytes": path.stat().st_size if exists else 0,
            }
        )
    return files


def run_settings_json(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "selected_sources.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def numeric_sort(values: set[str]) -> list[str]:
    def key(value: str) -> tuple[int, Any]:
        try:
            return (0, int(value))
        except ValueError:
            return (1, value)

    return sorted(values, key=key)


def parse_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def is_solar_dispatch_row(row: dict[str, str]) -> bool:
    carrier = str(row.get("carrier", "")).strip().lower()
    generator = str(row.get("generator", "")).strip().lower()
    component = str(row.get("component", "")).strip().lower()
    return carrier == "solar" or "solar" in generator or "solar" in component or generator == "north star junction sf"


def normalize_generation_rows(rows: list[dict[str, str]], value_key: str) -> list[dict[str, str]]:
    normalized = []
    for row in rows:
        item = dict(row)
        item["p_mw"] = str(row.get(value_key, row.get("p_mw", "")))
        normalized.append(item)
    return normalized


def aggregate_time_series_for_sample(
    rows: list[dict[str, str]],
    value_key: str,
    sample: str,
) -> dict[str, float]:
    values: dict[str, float] = {}
    for row in rows:
        if str(row.get("sample", "")) != sample:
            continue
        timestamp = str(row.get("DATETIME", ""))
        if not timestamp:
            continue
        values[timestamp] = values.get(timestamp, 0.0) + parse_float(row.get(value_key))
    return values


def chart_points(timestamps: list[str], values: dict[str, float]) -> list[dict[str, Any]]:
    return [
        {
            "time": timestamp,
            "time_label": format_time_label(timestamp),
            "value_mw": values.get(timestamp, 0.0),
        }
        for timestamp in timestamps
    ]


def generation_option_rows(generator_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    totals: dict[str, float] = {}
    for row in generator_rows:
        generator = str(row.get("generator", ""))
        if not generator:
            continue
        totals[generator] = totals.get(generator, 0.0) + abs(parse_float(row.get("p_mw")))
    options = [{"value": "__fleet__", "label": "Total generation fleet"}]
    options.extend(
        {"value": generator, "label": generator}
        for generator, _total in sorted(totals.items(), key=lambda item: item[1], reverse=True)
    )
    return options


def dispatch_chart_data(
    generator_rows: list[dict[str, str]],
    load_rows: list[dict[str, str]],
    unserved_rows: list[dict[str, str]],
    samples: list[str],
    selected_sample: str,
    selected_generator: str,
    sample_weight: float,
) -> dict[str, Any]:
    generator_options = generation_option_rows(generator_rows)
    valid_generators = {option["value"] for option in generator_options}
    selected_generator = selected_generator if selected_generator in valid_generators else "__fleet__"
    selected_rows = (
        generator_rows
        if selected_generator == "__fleet__"
        else [row for row in generator_rows if str(row.get("generator", "")) == selected_generator]
    )
    trace_samples = samples if selected_sample == "all" else [selected_sample]
    trace_colors = ["#1f6feb", "#087f8c", "#6f42c1", "#b7791f", "#c2410c", "#3b82f6", "#0f766e"]
    generation_by_sample = [
        (sample, aggregate_time_series_for_sample(selected_rows, "p_mw", sample))
        for sample in trace_samples
    ]
    load_series = aggregate_time_series(load_rows, "load_mw", selected_sample, samples, sample_weight)
    unserved_series = aggregate_time_series(unserved_rows, "unserved_mw", selected_sample, samples, sample_weight)
    timestamps = sorted(
        set(load_series)
        | set(unserved_series)
        | {timestamp for _sample, values in generation_by_sample for timestamp in values}
    )
    if not timestamps:
        timestamps = sorted({str(row.get("DATETIME", "")) for row in load_rows if str(row.get("DATETIME", ""))})

    entity_label = "Total generation fleet" if selected_generator == "__fleet__" else selected_generator
    traces = []
    for index, (sample, values) in enumerate(generation_by_sample):
        label = entity_label if selected_sample != "all" else f"S{sample}"
        traces.append(
            {
                "name": label,
                "kind": "generation",
                "sample": sample,
                "color": trace_colors[index % len(trace_colors)],
                "points": chart_points(timestamps, values),
            }
        )
    traces.append(
        {
            "name": "Load",
            "kind": "load",
            "sample": selected_sample,
            "color": "#207a4b",
            "dash": "6 4",
            "points": chart_points(timestamps, load_series),
        }
    )
    if any(abs(value) > 0.0001 for value in unserved_series.values()):
        traces.append(
            {
                "name": "Unserved",
                "kind": "unserved",
                "sample": selected_sample,
                "color": "#b42318",
                "dash": "3 4",
                "points": chart_points(timestamps, unserved_series),
            }
        )
    max_y = max(
        [0.0]
        + [point["value_mw"] for trace in traces for point in trace["points"]]
    )
    sample_label = "all samples" if selected_sample == "all" else f"sample {selected_sample}"
    return {
        "selected_generator": selected_generator,
        "generator_options": generator_options,
        "sample_mode": selected_sample,
        "title": f"{entity_label} across {sample_label}",
        "timestamps": [{"time": timestamp, "time_label": format_time_label(timestamp)} for timestamp in timestamps],
        "traces": traces,
        "max_y": max_y,
    }


def reserve_dashboard_data(
    reserve_rows: list[dict[str, str]],
    samples: list[str],
    interval_hours: float,
) -> dict[str, Any]:
    if not reserve_rows:
        return {"available": False, "reserve_options": [], "quantity_options": [], "selected_quantity": "provision", "series_by_reserve": {}, "summary": [], "providers": []}

    sample_weight = 1.0 / max(1, len(samples))
    reserve_sample_quantities: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    summary_quantities: dict[str, dict[str, dict[str, float]]] = {}
    provider_series: dict[tuple[str, str], dict[str, float]] = {}
    reserve_timestamps: dict[str, set[str]] = {}
    sample_set = set(samples)
    for row in reserve_rows:
        sample = str(row.get("sample", ""))
        if sample_set and sample and sample not in sample_set:
            continue
        timestamp = str(row.get("DATETIME", ""))
        reserve = str(row.get("reserve", "")).strip() or "Reserve"
        quantity = str(row.get("quantity", "")).strip().lower() or "value"
        provider = str(row.get("provider", "")).strip()
        if not timestamp:
            continue
        value = parse_float(row.get("value_mw"))
        sample_key = sample or "base"
        weight = sample_weight if sample else 1.0
        reserve_timestamps.setdefault(reserve, set()).add(timestamp)
        sample_values = reserve_sample_quantities.setdefault(reserve, {}).setdefault(quantity, {}).setdefault(sample_key, {})
        sample_values[timestamp] = sample_values.get(timestamp, 0.0) + value
        summary_values = summary_quantities.setdefault(reserve, {}).setdefault(quantity, {})
        summary_values[timestamp] = summary_values.get(timestamp, 0.0) + value * weight
        if quantity == "provision" and provider:
            key = (reserve, provider)
            values = provider_series.setdefault(key, {})
            values[timestamp] = values.get(timestamp, 0.0) + value * weight

    quantity_labels = {
        "requirement": "Requirement",
        "provision": "Provision",
        "shortage": "Shortage",
    }
    sample_colors = ["#1f6feb", "#087f8c", "#6f42c1", "#b7791f", "#c2410c", "#3b82f6", "#0f766e"]
    quantity_order = ("requirement", "provision", "shortage")
    available_quantities = [
        quantity
        for quantity in quantity_order
        if any(quantity in quantities for quantities in reserve_sample_quantities.values())
    ]
    quantity_options = [
        {"value": quantity, "label": quantity_labels.get(quantity, quantity.title())}
        for quantity in available_quantities
    ]
    reserve_options = [
        {"value": reserve, "label": reserve}
        for reserve in sorted(reserve_sample_quantities)
    ]
    series_by_reserve: dict[str, Any] = {}
    summary = []
    for reserve in sorted(reserve_sample_quantities):
        timestamps = sorted(reserve_timestamps.get(reserve, set()))
        quantities = reserve_sample_quantities[reserve]
        series_by_quantity: dict[str, Any] = {}
        for quantity in quantity_order:
            sample_values_by_time = quantities.get(quantity, {})
            if not sample_values_by_time:
                continue
            trace_samples = samples or numeric_sort(set(sample_values_by_time))
            traces = []
            for index, sample in enumerate(trace_samples):
                values = sample_values_by_time.get(sample)
                if values is None:
                    continue
                traces.append(
                    {
                        "name": f"S{sample}" if sample != "base" else "Base",
                        "quantity": quantity,
                        "sample": sample,
                        "color": sample_colors[index % len(sample_colors)],
                        "points": chart_points(timestamps, values),
                    }
                )
            max_y = max(
                [0.0]
                + [point["value_mw"] for trace in traces for point in trace["points"]]
            )
            series_by_quantity[quantity] = {
                "title": f"{reserve} - {quantity_labels.get(quantity, quantity.title())}",
                "timestamps": [{"time": timestamp, "time_label": format_time_label(timestamp)} for timestamp in timestamps],
                "traces": traces,
                "max_y": max_y,
            }
        reserve_quantities = [quantity for quantity in quantity_order if quantity in series_by_quantity]
        series_by_reserve[reserve] = {
            "available_quantities": reserve_quantities,
            "default_quantity": "provision" if "provision" in reserve_quantities else (reserve_quantities[0] if reserve_quantities else ""),
            "series_by_quantity": series_by_quantity,
        }

        def values_for(quantity: str) -> list[float]:
            values = summary_quantities.get(reserve, {}).get(quantity, {})
            return [values.get(timestamp, 0.0) for timestamp in timestamps]

        requirement_values = values_for("requirement")
        provision_values = values_for("provision")
        shortage_values = values_for("shortage")
        count = max(1, len(timestamps))
        summary.append(
            {
                "reserve": reserve,
                "avg_requirement_mw": sum(requirement_values) / count,
                "peak_requirement_mw": max(requirement_values, default=0.0),
                "avg_provision_mw": sum(provision_values) / count,
                "peak_provision_mw": max(provision_values, default=0.0),
                "peak_shortage_mw": max(shortage_values, default=0.0),
                "shortage_mwh": sum(shortage_values) * interval_hours,
            }
        )

    providers = []
    for (reserve, provider), values in provider_series.items():
        timestamps = sorted(reserve_timestamps.get(reserve, set()))
        count = max(1, len(timestamps))
        provider_values = [values.get(timestamp, 0.0) for timestamp in timestamps]
        providers.append(
            {
                "reserve": reserve,
                "provider": provider,
                "avg_mw": sum(provider_values) / count,
                "peak_mw": max(provider_values, default=0.0),
                "total_mwh": sum(provider_values) * interval_hours,
            }
        )
    providers.sort(key=lambda row: row["total_mwh"], reverse=True)
    return {
        "available": bool(reserve_options),
        "reserve_options": reserve_options,
        "quantity_options": quantity_options,
        "selected_quantity": "provision" if any(option["value"] == "provision" for option in quantity_options) else (quantity_options[0]["value"] if quantity_options else ""),
        "series_by_reserve": series_by_reserve,
        "summary": summary,
        "providers": providers,
    }


def battery_soc_dashboard_data(
    soc_rows: list[dict[str, str]],
    samples: list[str],
) -> dict[str, Any]:
    if not soc_rows:
        return {"available": False, "battery_options": [], "default_battery": "", "series_by_battery": {}}

    sample_colors = ["#1f6feb", "#087f8c", "#6f42c1", "#b7791f", "#c2410c", "#3b82f6", "#0f766e"]
    sample_set = set(samples)
    battery_values: dict[str, dict[str, dict[str, float]]] = {}
    battery_timestamps: dict[str, set[str]] = {}
    battery_enabled: dict[str, bool] = {}
    battery_capacity: dict[str, float] = {}

    for row in soc_rows:
        sample = str(row.get("sample", ""))
        if sample_set and sample and sample not in sample_set:
            continue
        timestamp = str(row.get("DATETIME", ""))
        battery = str(row.get("battery", "")).strip() or str(row.get("component", "")).strip()
        if not timestamp or not battery:
            continue
        sample_key = sample or "base"
        value = parse_float(row.get("state_of_charge_mwh"))
        values = battery_values.setdefault(battery, {}).setdefault(sample_key, {})
        values[timestamp] = values.get(timestamp, 0.0) + value
        battery_timestamps.setdefault(battery, set()).add(timestamp)
        if "enabled" in row:
            battery_enabled[battery] = battery_enabled.get(battery, False) or str(row.get("enabled", "")).strip().lower() == "true"
        if "p_nom_mw" in row:
            battery_capacity[battery] = max(battery_capacity.get(battery, 0.0), parse_float(row.get("p_nom_mw")))

    battery_options = []
    series_by_battery: dict[str, Any] = {}
    ordered_batteries = sorted(
        battery_values,
        key=lambda name: (not battery_enabled.get(name, True), name),
    )
    for battery in ordered_batteries:
        label = battery
        if battery in battery_enabled and not battery_enabled[battery]:
            label = f"{battery} (disabled)"
        battery_options.append({"value": battery, "label": label})

        timestamps = sorted(battery_timestamps.get(battery, set()))
        sample_values_by_time = battery_values[battery]
        trace_samples = samples or numeric_sort(set(sample_values_by_time))
        traces = []
        for index, sample in enumerate(trace_samples):
            values = sample_values_by_time.get(sample)
            if values is None:
                continue
            traces.append(
                {
                    "name": f"S{sample}" if sample != "base" else "Base",
                    "sample": sample,
                    "color": sample_colors[index % len(sample_colors)],
                    "points": chart_points(timestamps, values),
                }
            )
        max_y = max(
            [0.0]
            + [point["value_mw"] for trace in traces for point in trace["points"]]
        )
        series_by_battery[battery] = {
            "title": f"{battery} SoC (MWh)",
            "enabled": battery_enabled.get(battery, True),
            "p_nom_mw": battery_capacity.get(battery, 0.0),
            "timestamps": [{"time": timestamp, "time_label": format_time_label(timestamp)} for timestamp in timestamps],
            "traces": traces,
            "max_y": max_y,
        }

    return {
        "available": bool(battery_options),
        "battery_options": battery_options,
        "default_battery": battery_options[0]["value"] if battery_options else "",
        "series_by_battery": series_by_battery,
    }


def rows_by_dispatch_category(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    solar_rows = []
    non_solar_rows = []
    for row in rows:
        if is_solar_dispatch_row(row):
            solar_rows.append(row)
        else:
            non_solar_rows.append(row)
    return {"solar": solar_rows, "non_solar": non_solar_rows}


def dashboard_data(
    run_name: str,
    selected_sample: str,
    selected_chart_series: str = "__fleet__",
) -> dict[str, Any]:
    run_dir = resolve_run_dir(run_name)
    output_dir = run_dir / OUTPUT_DIR_NAME
    run_settings = run_settings_json(run_dir)
    files = dashboard_output_files(output_dir)
    if not all(path.is_file() for path in files):
        raise AppError("Selected run does not have the complete output CSV set.", HTTPStatus.NOT_FOUND)

    thermal_rows = read_dict_rows(output_dir / THERMAL_OUTPUT)
    unserved_rows = read_dict_rows(output_dir / UNSERVED_OUTPUT)
    load_rows = read_dict_rows(output_dir / LOAD_OUTPUT)
    generator_path = output_dir / GENERATOR_OUTPUT
    generation_path = output_dir / GENERATION_OUTPUT
    reserves_path = output_dir / RESERVES_OUTPUT
    battery_soc_path = output_dir / BATTERY_SOC_OUTPUT
    generator_rows = normalize_generation_rows(read_dict_rows(generator_path), "p_mw") if generator_path.is_file() else []
    if not generator_rows and generation_path.is_file():
        generator_rows = normalize_generation_rows(read_dict_rows(generation_path), "generation_mw")
    reserve_rows = read_dict_rows(reserves_path) if reserves_path.is_file() else []
    battery_soc_rows = read_dict_rows(battery_soc_path) if battery_soc_path.is_file() else []
    has_generator_dispatch = bool(generator_rows)
    generator_categories = rows_by_dispatch_category(generator_rows)
    solar_rows = generator_categories["solar"]
    samples = numeric_sort(
        {
            str(row.get("sample", ""))
            for row in thermal_rows + unserved_rows + load_rows + generator_rows + reserve_rows + battery_soc_rows
            if str(row.get("sample", ""))
        }
    )
    if selected_sample not in {"", "all"} and selected_sample not in samples:
        raise AppError("Selected sample is not present in the output files.")
    selected_sample = "all" if selected_sample in {"", "all"} else selected_sample
    interval_hours = infer_interval_hours(load_rows or thermal_rows or unserved_rows)
    sample_weight = 1.0 / max(1, len(samples)) if selected_sample == "all" else 1.0

    thermal_series = aggregate_time_series(thermal_rows, "generation_mw", selected_sample, samples, sample_weight)
    solar_series = aggregate_time_series(solar_rows, "p_mw", selected_sample, samples, sample_weight)
    load_series = aggregate_time_series(load_rows, "load_mw", selected_sample, samples, sample_weight)
    unserved_series = aggregate_time_series(unserved_rows, "unserved_mw", selected_sample, samples, sample_weight)
    timestamps = sorted(set(thermal_series) | set(solar_series) | set(load_series) | set(unserved_series))
    series = [
        {
            "time": timestamp,
            "time_label": format_time_label(timestamp),
            "thermal_mw": thermal_series.get(timestamp, 0.0),
            "solar_mw": solar_series.get(timestamp, 0.0),
            "generation_mw": thermal_series.get(timestamp, 0.0) + solar_series.get(timestamp, 0.0),
            "load_mw": load_series.get(timestamp, 0.0),
            "unserved_mw": unserved_series.get(timestamp, 0.0),
        }
        for timestamp in timestamps
    ]

    thermal_by_generator = aggregate_entity(
        thermal_rows,
        entity_key="generator",
        value_key="generation_mw",
        selected_sample=selected_sample,
        samples=samples,
        sample_weight=sample_weight,
        interval_hours=interval_hours,
    )
    solar_by_generator = aggregate_entity(
        solar_rows,
        entity_key="generator",
        value_key="p_mw",
        selected_sample=selected_sample,
        samples=samples,
        sample_weight=sample_weight,
        interval_hours=interval_hours,
    )
    generation_by_generator = (
        aggregate_entity(
            generator_rows,
            entity_key="generator",
            value_key="p_mw",
            selected_sample=selected_sample,
            samples=samples,
            sample_weight=sample_weight,
            interval_hours=interval_hours,
        )
        if has_generator_dispatch
        else thermal_by_generator
    )
    load_by_bus = aggregate_entity(
        load_rows,
        entity_key="bus",
        value_key="load_mw",
        selected_sample=selected_sample,
        samples=samples,
        sample_weight=sample_weight,
        interval_hours=interval_hours,
    )
    unserved_by_bus = aggregate_entity(
        unserved_rows,
        entity_key="bus",
        value_key="unserved_mw",
        selected_sample=selected_sample,
        samples=samples,
        sample_weight=sample_weight,
        interval_hours=interval_hours,
    )
    dispatch_chart = dispatch_chart_data(
        generator_rows=generator_rows,
        load_rows=load_rows,
        unserved_rows=unserved_rows,
        samples=samples,
        selected_sample=selected_sample,
        selected_generator=selected_chart_series,
        sample_weight=sample_weight,
    )
    reserve_data = reserve_dashboard_data(
        reserve_rows=reserve_rows,
        samples=samples,
        interval_hours=interval_hours,
    )
    battery_soc_data = battery_soc_dashboard_data(
        soc_rows=battery_soc_rows,
        samples=samples,
    )

    total_thermal_mwh = sum(row["total_mwh"] for row in thermal_by_generator)
    total_solar_mwh = sum(row["total_mwh"] for row in solar_by_generator)
    total_generation_mwh = total_thermal_mwh + total_solar_mwh
    total_load_mwh = sum(row["total_mwh"] for row in load_by_bus)
    total_unserved_mwh = sum(row["total_mwh"] for row in unserved_by_bus)
    summary = {
        "has_generator_dispatch": has_generator_dispatch,
        "total_thermal_mwh": total_thermal_mwh,
        "total_solar_mwh": total_solar_mwh,
        "total_generation_mwh": total_generation_mwh,
        "total_load_mwh": total_load_mwh,
        "total_unserved_mwh": total_unserved_mwh,
        "unserved_load_pct": (total_unserved_mwh / total_load_mwh * 100.0) if total_load_mwh else 0.0,
        "solar_generation_pct": (total_solar_mwh / total_generation_mwh * 100.0) if total_generation_mwh else 0.0,
        "peak_thermal_mw": max((row["thermal_mw"] for row in series), default=0.0),
        "peak_solar_mw": max((row["solar_mw"] for row in series), default=0.0),
        "peak_generation_mw": max((row["generation_mw"] for row in series), default=0.0),
        "peak_load_mw": max((row["load_mw"] for row in series), default=0.0),
        "peak_unserved_mw": max((row["unserved_mw"] for row in series), default=0.0),
        "generator_count": len(generation_by_generator),
        "bus_count": len(load_by_bus),
    }

    return {
        "ok": True,
        "run": run_dir.name,
        "run_dir": str(run_dir),
        "output_dir": str(output_dir),
        "run_settings": {
            "power_model": run_settings.get("power_model", ""),
            "power_model_script": run_settings.get("power_model_script", ""),
            "nonanticipative_hours": run_settings.get("nonanticipative_hours"),
            "solver_time_limit": run_settings.get("solver_time_limit"),
            "solver_mip_gap": run_settings.get("solver_mip_gap"),
        },
        "samples": samples,
        "selected_sample": selected_sample,
        "interval_hours": interval_hours,
        "snapshot_count": len(timestamps),
        "has_generator_dispatch": has_generator_dispatch,
        "series": series,
        "dispatch_chart": dispatch_chart,
        "reserves": reserve_data,
        "battery_soc": battery_soc_data,
        "thermal_by_generator": thermal_by_generator,
        "solar_by_generator": solar_by_generator,
        "generation_by_generator": generation_by_generator,
        "load_by_bus": load_by_bus,
        "unserved_by_bus": unserved_by_bus,
        "summary": summary,
        "files": output_files_json(output_dir, run_dir),
    }


def topology_output_files(output_dir: Path) -> list[Path]:
    return [
        output_dir / THERMAL_OUTPUT,
        output_dir / UNSERVED_OUTPUT,
        output_dir / LOAD_OUTPUT,
        output_dir / GENERATION_OUTPUT,
        output_dir / GENERATOR_OUTPUT,
        output_dir / LINE_FLOW_OUTPUT,
    ]


def topology_files_json(output_dir: Path) -> list[dict[str, Any]]:
    return [
        {
            "name": path.name,
            "path": str(path),
            "exists": path.is_file(),
            "size_bytes": path.stat().st_size if path.is_file() else 0,
        }
        for path in topology_output_files(output_dir)
    ]


def topology_data(run_name: str, selected_sample: str) -> dict[str, Any]:
    run_dir = resolve_run_dir(run_name)
    output_dir = run_dir / OUTPUT_DIR_NAME
    load_path = output_dir / LOAD_OUTPUT
    unserved_path = output_dir / UNSERVED_OUTPUT
    generation_path = output_dir / GENERATION_OUTPUT
    generator_path = output_dir / GENERATOR_OUTPUT
    thermal_path = output_dir / THERMAL_OUTPUT
    line_path = output_dir / LINE_FLOW_OUTPUT
    if not load_path.is_file():
        raise AppError("Selected run does not have load output for topology.", HTTPStatus.NOT_FOUND)

    load_rows = read_dict_rows(load_path)
    unserved_rows = read_dict_rows(unserved_path) if unserved_path.is_file() else []
    generator_rows, has_generator_dispatch = topology_generator_rows(generator_path, generation_path, thermal_path)
    line_rows = read_dict_rows(line_path) if line_path.is_file() else []
    has_line_flows = bool(line_rows)

    samples = topology_samples(generator_rows + load_rows + unserved_rows + line_rows)
    if selected_sample and selected_sample not in samples:
        raise AppError("Selected sample is not present in the output files.")
    selected_sample = selected_sample or samples[0]

    sample_load_rows = [row for row in load_rows if topology_include_sample(row, selected_sample)]
    sample_unserved_rows = [row for row in unserved_rows if topology_include_sample(row, selected_sample)]
    sample_generator_rows = [row for row in generator_rows if topology_include_sample(row, selected_sample)]
    sample_line_rows = [row for row in line_rows if topology_include_sample(row, selected_sample)]
    timestamps = sorted(
        {
            str(row.get("DATETIME", ""))
            for row in sample_load_rows + sample_unserved_rows + sample_generator_rows + sample_line_rows
            if str(row.get("DATETIME", ""))
        }
    )
    if not timestamps:
        raise AppError("Selected run does not contain any topology timesteps.", HTTPStatus.NOT_FOUND)

    generators_by_time: dict[str, list[dict[str, Any]]] = {}
    generation_by_time_bus: dict[str, dict[str, float]] = {}
    for row in sample_generator_rows:
        timestamp = str(row.get("DATETIME", ""))
        generator = str(row.get("generator", ""))
        bus = str(row.get("bus", "")) or GENERATOR_BUSES.get(generator, "Solomon Hub")
        value = parse_float(row.get("p_mw", row.get("generation_mw")))
        record = {
            "generator": generator,
            "component": str(row.get("component", "")),
            "bus": bus,
            "carrier": str(row.get("carrier", "")),
            "p_mw": value,
        }
        generators_by_time.setdefault(timestamp, []).append(record)
        bus_values = generation_by_time_bus.setdefault(timestamp, {})
        bus_values[bus] = bus_values.get(bus, 0.0) + value

    load_by_time_bus = aggregate_topology_bus_values(sample_load_rows, "load_mw")
    unserved_by_time_bus = aggregate_topology_bus_values(sample_unserved_rows, "unserved_mw")
    line_by_time_name = {
        (str(row.get("DATETIME", "")), str(row.get("line", ""))): row
        for row in sample_line_rows
        if str(row.get("DATETIME", "")) and str(row.get("line", ""))
    }

    frames = []
    load_buses = [
        bus
        for bus, point in BUS_LAYOUT.items()
        if point.get("type") == "load" or bus in DEMAND_BUSES
    ]
    for timestamp in timestamps:
        generation_by_bus = [
            {"bus": bus, "p_mw": value}
            for bus, value in sorted(generation_by_time_bus.get(timestamp, {}).items())
        ]
        loads = [
            {
                "bus": bus,
                "load_mw": load_by_time_bus.get(timestamp, {}).get(bus, 0.0),
                "unserved_mw": unserved_by_time_bus.get(timestamp, {}).get(bus, 0.0),
            }
            for bus in load_buses
        ]
        branches = []
        loading_values = []
        for line_name, bus0, bus1, static_limit in NETWORK_LINES:
            row = line_by_time_name.get((timestamp, line_name))
            p0_mw = parse_float_or_none(row.get("p0_mw")) if row else None
            limit_mw = parse_float_or_none(row.get("limit_mw")) if row else None
            if limit_mw is None:
                limit_mw = static_limit
            loading_pct = parse_float_or_none(row.get("loading_pct")) if row else None
            if loading_pct is None and p0_mw is not None and limit_mw:
                loading_pct = abs(p0_mw) / limit_mw * 100.0
            if loading_pct is not None:
                loading_values.append(loading_pct)
            branches.append(
                {
                    "name": line_name,
                    "bus0": bus0,
                    "bus1": bus1,
                    "p0_mw": p0_mw,
                    "limit_mw": limit_mw,
                    "loading_pct": loading_pct,
                    "has_flow": row is not None,
                }
            )
        generator_rows_for_time = sorted(
            generators_by_time.get(timestamp, []),
            key=lambda row: (row["bus"], row["generator"]),
        )
        frames.append(
            {
                "time": timestamp,
                "time_label": format_time_label(timestamp),
                "generators": generator_rows_for_time,
                "generation_by_bus": generation_by_bus,
                "loads": loads,
                "branches": branches,
                "summary": {
                    "total_generation_mw": sum(row["p_mw"] for row in generator_rows_for_time),
                    "total_load_mw": sum(row["load_mw"] for row in loads),
                    "total_unserved_mw": sum(row["unserved_mw"] for row in loads),
                    "max_loading_pct": max(loading_values) if loading_values else None,
                },
            }
        )

    return {
        "ok": True,
        "run": run_dir.name,
        "run_dir": str(run_dir),
        "output_dir": str(output_dir),
        "samples": samples,
        "selected_sample": selected_sample,
        "snapshot_count": len(frames),
        "has_generator_dispatch": has_generator_dispatch,
        "has_line_flows": has_line_flows,
        "layout": BUS_LAYOUT,
        "branches_static": [
            {"name": name, "bus0": bus0, "bus1": bus1, "limit_mw": limit}
            for name, bus0, bus1, limit in NETWORK_LINES
        ],
        "frames": frames,
        "files": topology_files_json(output_dir),
    }


def topology_generator_rows(generator_path: Path, generation_path: Path, thermal_path: Path) -> tuple[list[dict[str, str]], bool]:
    if generator_path.is_file():
        rows = normalize_generation_rows(read_dict_rows(generator_path), "p_mw")
        if rows:
            return rows, True
    if generation_path.is_file():
        rows = normalize_generation_rows(read_dict_rows(generation_path), "generation_mw")
        if rows:
            for row in rows:
                generator = str(row.get("generator", ""))
                row["bus"] = row.get("bus") or GENERATOR_BUSES.get(generator, "Solomon Hub")
                row["carrier"] = row.get("carrier") or ("solar" if is_solar_dispatch_row(row) else "gas")
            return rows, True
    if not thermal_path.is_file():
        return [], False
    rows = []
    for row in read_dict_rows(thermal_path):
        generator = str(row.get("generator", ""))
        rows.append(
            {
                "DATETIME": str(row.get("DATETIME", "")),
                "sample": str(row.get("sample", "")),
                "generator": generator,
                "component": str(row.get("component", "")),
                "bus": GENERATOR_BUSES.get(generator, "Solomon Hub"),
                "carrier": "thermal",
                "p_mw": str(row.get("generation_mw", "")),
            }
        )
    return rows, False


def topology_samples(rows: list[dict[str, str]]) -> list[str]:
    samples = numeric_sort({str(row.get("sample", "")) for row in rows if str(row.get("sample", ""))})
    return samples or [""]


def topology_include_sample(row: dict[str, str], selected_sample: str) -> bool:
    row_sample = str(row.get("sample", ""))
    return row_sample == selected_sample or (selected_sample == "" and row_sample == "")


def aggregate_topology_bus_values(rows: list[dict[str, str]], value_key: str) -> dict[str, dict[str, float]]:
    values: dict[str, dict[str, float]] = {}
    for row in rows:
        timestamp = str(row.get("DATETIME", ""))
        bus = str(row.get("bus", ""))
        if not timestamp or not bus:
            continue
        bus_values = values.setdefault(timestamp, {})
        bus_values[bus] = bus_values.get(bus, 0.0) + parse_float(row.get(value_key))
    return values


def infer_interval_hours(rows: list[dict[str, str]]) -> float:
    timestamps = sorted({str(row.get("DATETIME", "")) for row in rows if row.get("DATETIME")})
    if len(timestamps) < 2:
        return 0.5
    first = parse_dashboard_datetime(timestamps[0])
    second = parse_dashboard_datetime(timestamps[1])
    if first and second:
        hours = (second - first).total_seconds() / 3600.0
        return hours if hours > 0 else 0.5
    return 0.5


def parse_dashboard_datetime(value: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def format_time_label(value: str) -> str:
    parsed = parse_dashboard_datetime(value)
    if not parsed:
        return value
    return parsed.strftime("%d %b %H:%M")


def include_sample(row: dict[str, str], selected_sample: str) -> bool:
    return selected_sample == "all" or str(row.get("sample", "")) == selected_sample


def aggregate_time_series(
    rows: list[dict[str, str]],
    value_key: str,
    selected_sample: str,
    samples: list[str],
    sample_weight: float,
) -> dict[str, float]:
    values: dict[str, float] = {}
    for row in rows:
        if not include_sample(row, selected_sample):
            continue
        timestamp = str(row.get("DATETIME", ""))
        values[timestamp] = values.get(timestamp, 0.0) + parse_float(row.get(value_key)) * sample_weight
    return values


def aggregate_entity(
    rows: list[dict[str, str]],
    entity_key: str,
    value_key: str,
    selected_sample: str,
    samples: list[str],
    sample_weight: float,
    interval_hours: float,
) -> list[dict[str, Any]]:
    totals: dict[str, float] = {}
    by_entity_time: dict[tuple[str, str], float] = {}
    for row in rows:
        if not include_sample(row, selected_sample):
            continue
        entity = str(row.get(entity_key, ""))
        timestamp = str(row.get("DATETIME", ""))
        value = parse_float(row.get(value_key)) * sample_weight
        totals[entity] = totals.get(entity, 0.0) + value * interval_hours
        key = (entity, timestamp)
        by_entity_time[key] = by_entity_time.get(key, 0.0) + value

    result = []
    for entity, total_mwh in totals.items():
        peak_mw = max(
            (value for (candidate, _timestamp), value in by_entity_time.items() if candidate == entity),
            default=0.0,
        )
        result.append({entity_key: entity, "total_mwh": total_mwh, "peak_mw": peak_mw})
    return sorted(result, key=lambda row: row["total_mwh"], reverse=True)


def input_dataset_items(root: Path) -> list[CatalogItem]:
    return [
        item
        for item in catalog_items(root)
        if item.path.suffix.lower() == ".csv" and not item.advanced
    ]


def default_input_dataset(items: list[CatalogItem]) -> str:
    for preferred in ("loads/load_p_set", "renewables/nsj_sfx_v1_5_bands", "generators/commit"):
        if any(item.dataset == preferred for item in items):
            return preferred
    return items[0].dataset if items else ""


def input_record_timestamp(kind: str, row: dict[str, str]) -> datetime | None:
    timestamp = parse_dashboard_datetime(row.get("DateTime", ""))
    if timestamp is not None:
        return timestamp
    if kind != "renewable_profile":
        return None
    month = parse_int(row.get("MONTH", ""))
    day = parse_int(row.get("DAY", ""))
    period = parse_int(row.get("PERIOD", ""))
    if month is None or day is None or period is None:
        return None
    if month not in RENEWABLE_DAY_LIMITS or day < 1 or day > RENEWABLE_DAY_LIMITS[month] or period < 1 or period > 48:
        return None
    try:
        base = datetime(MODEL_WINDOW_YEAR, month, day)
    except ValueError:
        return None
    return base + timedelta(minutes=(period - 1) * MODEL_WINDOW_INTERVAL_MINUTES)


def filter_input_records_for_model_window(
    kind: str,
    records: list[dict[str, str]],
    model_window_hours: float | None,
) -> tuple[list[dict[str, str]], datetime | None, datetime | None]:
    if model_window_hours is None:
        return records, None, None
    timestamped = [
        (row, timestamp)
        for row in records
        if (timestamp := input_record_timestamp(kind, row)) is not None
    ]
    if not timestamped:
        return [], MODEL_WINDOW_START, MODEL_WINDOW_START + timedelta(hours=model_window_hours)

    def rows_in_window(start: datetime) -> list[dict[str, str]]:
        end = start + timedelta(hours=model_window_hours)
        return [
            row
            for row, timestamp in timestamped
            if start <= timestamp < end
        ]

    window_end = MODEL_WINDOW_START + timedelta(hours=model_window_hours)
    selected_rows = rows_in_window(MODEL_WINDOW_START)
    if selected_rows:
        return selected_rows, MODEL_WINDOW_START, window_end

    fallback_start = min(timestamp for _row, timestamp in timestamped)
    fallback_end = fallback_start + timedelta(hours=model_window_hours)
    return rows_in_window(fallback_start), fallback_start, fallback_end


def input_dashboard_data(
    root: Path,
    dataset: str,
    selected_series: str,
    model_window_hours: float | None = None,
) -> dict[str, Any]:
    item = find_catalog_item(root, dataset)
    columns, rows, _encoding = read_csv_rows(item.path)
    records = [dict(zip(columns, normalize_row(row, len(columns)))) for row in rows]
    kind = classify_input(columns, dataset)
    series_options = input_series_options(kind, columns, records)
    selected_series = selected_series if selected_series in series_options else (series_options[0] if series_options else "")
    numeric_columns = infer_numeric_columns(columns, records)
    chart_records, window_start, window_end = filter_input_records_for_model_window(kind, records, model_window_hours)
    chart = build_input_chart(kind, columns, chart_records, selected_series, numeric_columns)
    diagnostics = input_diagnostics(kind, columns, chart_records, selected_series, numeric_columns)
    schema = schema_for_dataset(dataset)

    return {
        "ok": True,
        "dataset": dataset,
        "relative_path": item.relative_path,
        "kind": kind,
        "kind_label": input_kind_label(kind),
        "row_count": len(rows),
        "chart_row_count": len(chart_records),
        "column_count": len(columns),
        "window": {
            "enabled": model_window_hours is not None,
            "hours": model_window_hours,
            "start": window_start.isoformat(sep=" ") if window_start else "",
            "end": window_end.isoformat(sep=" ") if window_end else "",
        },
        "columns": columns,
        "series_options": series_options,
        "selected_series": selected_series,
        "line_title": chart["line_title"],
        "bar_title": chart["bar_title"],
        "summary": chart["summary"],
        "series": chart["series"],
        "breakdown": chart["breakdown"],
        "shape": chart["shape"],
        "diagnostics": diagnostics,
        "preview_columns": columns[: min(8, len(columns))],
        "preview_rows": preview_rows(columns, records),
        "column_roles": column_roles(columns, schema, numeric_columns),
    }


def classify_input(columns: list[str], dataset: str) -> str:
    column_set = set(columns)
    normalized = dataset.replace("\\", "/").lower()
    if {"DateTime", *DEMAND_BUSES}.issubset(column_set):
        return "load_profile"
    if {"DateTime", "bus", "p_set"}.issubset(column_set):
        return "load_long"
    if {"MONTH", "DAY", "PERIOD"}.issubset(column_set):
        return "renewable_profile"
    if {"Name", "Value"}.issubset(column_set):
        return "name_value"
    if "datetime" in {column.lower() for column in columns} and normalized.startswith(("generators/", "raw/maintenance/")):
        return "generator_timeseries"
    if "DateTime" in column_set:
        return "timeseries"
    return "generic"


def input_kind_label(kind: str) -> str:
    labels = {
        "load_profile": "Wide load profile",
        "load_long": "Long load profile",
        "renewable_profile": "Renewable sample profile",
        "generator_timeseries": "Generator time series",
        "name_value": "Name/value table",
        "timeseries": "Time series",
        "generic": "CSV table",
    }
    return labels.get(kind, kind)


def input_series_options(kind: str, columns: list[str], records: list[dict[str, str]]) -> list[str]:
    if kind == "load_profile":
        return ["Total", *[column for column in DEMAND_BUSES if column in columns]]
    if kind == "load_long":
        buses = sorted({row.get("bus", "") for row in records if row.get("bus")})
        return ["Total", *buses]
    if kind == "renewable_profile":
        return [column for column in columns if column not in {"MONTH", "DAY", "PERIOD"}]
    if kind == "name_value":
        return ["Value"]
    numeric_columns = infer_numeric_columns(columns, records)
    if "DateTime" in columns:
        return ["Total", *[column for column in numeric_columns if column != "DateTime"]]
    return numeric_columns or columns[:1]


def infer_numeric_columns(columns: list[str], records: list[dict[str, str]]) -> list[str]:
    numeric: list[str] = []
    sample = records[: min(200, len(records))]
    for column in columns:
        values = [row.get(column, "") for row in sample if row.get(column, "") != ""]
        if values and sum(1 for value in values if parse_float_or_none(value) is not None) / len(values) >= 0.9:
            numeric.append(column)
    return numeric


def parse_float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_input_chart(
    kind: str,
    columns: list[str],
    records: list[dict[str, str]],
    selected_series: str,
    numeric_columns: list[str],
) -> dict[str, Any]:
    if kind == "load_profile":
        return build_wide_datetime_chart(
            records=records,
            entity_columns=[column for column in DEMAND_BUSES if column in columns],
            selected_series=selected_series,
            value_label="MW",
            line_title="Load Profile",
            bar_title="Load By Bus",
        )
    if kind == "load_long":
        return build_long_chart(
            records=records,
            entity_key="bus",
            value_key="p_set",
            selected_series=selected_series,
            value_label="MW",
            line_title="Load Profile",
            bar_title="Load By Bus",
        )
    if kind == "renewable_profile":
        sample_columns = [column for column in columns if column not in {"MONTH", "DAY", "PERIOD"}]
        return build_renewable_chart(records, sample_columns, selected_series)
    if kind == "name_value":
        return build_name_value_chart(records)
    if "DateTime" in columns:
        return build_wide_datetime_chart(
            records=records,
            entity_columns=[column for column in numeric_columns if column != "DateTime"],
            selected_series=selected_series,
            value_label="value",
            line_title="Time Series",
            bar_title="Totals By Column",
        )
    return build_generic_chart(columns, records, numeric_columns, selected_series)


def build_wide_datetime_chart(
    records: list[dict[str, str]],
    entity_columns: list[str],
    selected_series: str,
    value_label: str,
    line_title: str,
    bar_title: str,
) -> dict[str, Any]:
    series_points = []
    shape_totals: dict[int, list[float]] = {}
    for row in records:
        timestamp = row.get("DateTime", "")
        value = (
            sum(parse_float(row.get(column)) for column in entity_columns)
            if selected_series == "Total"
            else parse_float(row.get(selected_series))
        )
        series_points.append({"x": timestamp, "label": format_time_label(timestamp), "value": value})
        period = period_from_datetime(timestamp)
        if period is not None:
            shape_totals.setdefault(period, []).append(value)

    breakdown = []
    for column in entity_columns:
        values = [parse_float(row.get(column)) for row in records]
        breakdown.append({"label": column, "value": sum(values), "peak": max(values, default=0.0)})

    values = [point["value"] for point in series_points]
    summary = input_summary_tiles(
        total=sum(values),
        average=(sum(values) / len(values) if values else 0.0),
        peak=max(values, default=0.0),
        minimum=min(values, default=0.0),
        selected=selected_series,
        unit=value_label,
    )
    return {
        "line_title": line_title,
        "bar_title": bar_title,
        "summary": summary,
        "series": decimate_points(series_points),
        "breakdown": sorted(breakdown, key=lambda row: row["value"], reverse=True),
        "shape": average_shape_points(shape_totals),
    }


def build_long_chart(
    records: list[dict[str, str]],
    entity_key: str,
    value_key: str,
    selected_series: str,
    value_label: str,
    line_title: str,
    bar_title: str,
) -> dict[str, Any]:
    by_time: dict[str, float] = {}
    by_entity: dict[str, float] = {}
    shape_totals: dict[int, list[float]] = {}
    for row in records:
        entity = row.get(entity_key, "")
        if selected_series != "Total" and entity != selected_series:
            continue
        timestamp = row.get("DateTime", "")
        value = parse_float(row.get(value_key))
        by_time[timestamp] = by_time.get(timestamp, 0.0) + value
        by_entity[entity] = by_entity.get(entity, 0.0) + value
    for timestamp, value in by_time.items():
        period = period_from_datetime(timestamp)
        if period is not None:
            shape_totals.setdefault(period, []).append(value)
    series_points = [
        {"x": timestamp, "label": format_time_label(timestamp), "value": value}
        for timestamp, value in sorted(by_time.items())
    ]
    values = [point["value"] for point in series_points]
    summary = input_summary_tiles(
        total=sum(values),
        average=(sum(values) / len(values) if values else 0.0),
        peak=max(values, default=0.0),
        minimum=min(values, default=0.0),
        selected=selected_series,
        unit=value_label,
    )
    return {
        "line_title": line_title,
        "bar_title": bar_title,
        "summary": summary,
        "series": decimate_points(series_points),
        "breakdown": sorted(
            [{"label": entity, "value": value} for entity, value in by_entity.items()],
            key=lambda row: row["value"],
            reverse=True,
        ),
        "shape": average_shape_points(shape_totals),
    }


def build_renewable_chart(
    records: list[dict[str, str]],
    sample_columns: list[str],
    selected_series: str,
) -> dict[str, Any]:
    selected = selected_series if selected_series in sample_columns else (sample_columns[0] if sample_columns else "")
    series_points = []
    shape_totals: dict[int, list[float]] = {}
    for row in records:
        value = parse_float(row.get(selected))
        label = renewable_label(row)
        series_points.append({"x": label, "label": label, "value": value})
        period = parse_int(row.get("PERIOD", ""))
        if period is not None:
            shape_totals.setdefault(period, []).append(value)
    breakdown = []
    for column in sample_columns:
        values = [parse_float(row.get(column)) for row in records]
        breakdown.append({"label": f"Sample {column}", "value": sum(values) / len(values) if values else 0.0, "peak": max(values, default=0.0)})
    values = [point["value"] for point in series_points]
    summary = input_summary_tiles(
        total=sum(values),
        average=(sum(values) / len(values) if values else 0.0),
        peak=max(values, default=0.0),
        minimum=min(values, default=0.0),
        selected=f"Sample {selected}",
        unit="pu",
    )
    return {
        "line_title": "Renewable Rating Profile",
        "bar_title": "Average By Sample",
        "summary": summary,
        "series": decimate_points(series_points),
        "breakdown": sorted(breakdown, key=lambda row: row["value"], reverse=True),
        "shape": average_shape_points(shape_totals),
    }


def build_name_value_chart(records: list[dict[str, str]]) -> dict[str, Any]:
    rows = [{"label": row.get("Name", ""), "value": parse_float(row.get("Value"))} for row in records]
    values = [row["value"] for row in rows]
    summary = input_summary_tiles(
        total=sum(values),
        average=(sum(values) / len(values) if values else 0.0),
        peak=max(values, default=0.0),
        minimum=min(values, default=0.0),
        selected="Value",
        unit="value",
    )
    return {
        "line_title": "Name/Value Sequence",
        "bar_title": "Values",
        "summary": summary,
        "series": [{"x": row["label"], "label": row["label"], "value": row["value"]} for row in rows],
        "breakdown": sorted(rows, key=lambda row: row["value"], reverse=True),
        "shape": [{"x": str(index + 1), "label": str(index + 1), "value": row["value"]} for index, row in enumerate(rows)],
    }


def build_generic_chart(
    columns: list[str],
    records: list[dict[str, str]],
    numeric_columns: list[str],
    selected_series: str,
) -> dict[str, Any]:
    selected = selected_series if selected_series in numeric_columns else (numeric_columns[0] if numeric_columns else "")
    series_points = [
        {"x": str(index + 1), "label": str(index + 1), "value": parse_float(row.get(selected))}
        for index, row in enumerate(records)
    ]
    breakdown = []
    for column in numeric_columns:
        values = [parse_float(row.get(column)) for row in records]
        breakdown.append({"label": column, "value": sum(values)})
    values = [point["value"] for point in series_points]
    summary = input_summary_tiles(
        total=sum(values),
        average=(sum(values) / len(values) if values else 0.0),
        peak=max(values, default=0.0),
        minimum=min(values, default=0.0),
        selected=selected,
        unit="value",
    )
    return {
        "line_title": "Numeric Column",
        "bar_title": "Numeric Totals",
        "summary": summary,
        "series": decimate_points(series_points),
        "breakdown": sorted(breakdown, key=lambda row: row["value"], reverse=True),
        "shape": decimate_points(series_points[:96]),
    }


def input_summary_tiles(
    total: float,
    average: float,
    peak: float,
    minimum: float,
    selected: str,
    unit: str,
) -> list[dict[str, str]]:
    return [
        {"label": "Selected", "value": selected or "-", "note": "Active series"},
        {"label": "Total", "value": f"{total:,.1f}", "note": unit},
        {"label": "Average", "value": f"{average:,.3f}", "note": unit},
        {"label": "Peak", "value": f"{peak:,.3f}", "note": unit},
        {"label": "Minimum", "value": f"{minimum:,.3f}", "note": unit},
        {"label": "Range", "value": f"{(peak - minimum):,.3f}", "note": unit},
    ]


def decimate_points(points: list[dict[str, Any]], limit: int = 600) -> list[dict[str, Any]]:
    if len(points) <= limit:
        return points
    step = len(points) / limit
    return [points[min(int(index * step), len(points) - 1)] for index in range(limit)]


def period_from_datetime(value: str) -> int | None:
    parsed = parse_dashboard_datetime(value)
    if not parsed:
        return None
    return int(parsed.hour * 2 + parsed.minute // 30 + 1)


def renewable_label(row: dict[str, str]) -> str:
    month = row.get("MONTH", "")
    day = row.get("DAY", "")
    period = row.get("PERIOD", "")
    return f"{month}/{day} P{period}"


def average_shape_points(shape_totals: dict[int, list[float]]) -> list[dict[str, Any]]:
    return [
        {
            "x": str(period),
            "label": f"P{period}",
            "value": sum(values) / len(values) if values else 0.0,
        }
        for period, values in sorted(shape_totals.items())
    ]


def input_diagnostics(
    kind: str,
    columns: list[str],
    records: list[dict[str, str]],
    selected_series: str,
    numeric_columns: list[str],
) -> list[dict[str, Any]]:
    empty_values = sum(1 for row in records for column in columns if row.get(column, "") == "")
    duplicate_times = 0
    if "DateTime" in columns:
        timestamps = [row.get("DateTime", "") for row in records if row.get("DateTime", "")]
        duplicate_times = len(timestamps) - len(set(timestamps))
    series_values = [
        parse_float_or_none(row.get(selected_series))
        for row in records
        if selected_series in row and row.get(selected_series, "") != ""
    ]
    numeric_values = [value for value in series_values if value is not None]
    return [
        {"Metric": "Kind", "Value": input_kind_label(kind)},
        {"Metric": "Empty cells", "Value": empty_values},
        {"Metric": "Duplicate DateTime values", "Value": duplicate_times},
        {"Metric": "Numeric columns", "Value": len(numeric_columns)},
        {"Metric": "Selected numeric points", "Value": len(numeric_values)},
        {"Metric": "Selected non-numeric points", "Value": len(series_values) - len(numeric_values)},
    ]


def preview_rows(columns: list[str], records: list[dict[str, str]]) -> list[dict[str, str]]:
    preview_columns = columns[: min(8, len(columns))]
    return [
        {column: row.get(column, "") for column in preview_columns}
        for row in records[:20]
    ]


def column_roles(
    columns: list[str],
    schema: dict[str, Any],
    numeric_columns: list[str],
) -> list[dict[str, str]]:
    required = set(schema.get("required", []))
    datetime_columns = set(schema.get("datetime", []))
    renewable_samples = set(schema.get("renewable_samples", []))
    rows = []
    for column in columns:
        roles = []
        if column in required:
            roles.append("required")
        if column in datetime_columns or column == "DateTime":
            roles.append("datetime")
        if column in renewable_samples:
            roles.append("sample")
        if column in numeric_columns:
            roles.append("numeric")
        rows.append({"Column": column, "Role": ", ".join(roles) if roles else "text"})
    return rows


class CsvSourceEditorHandler(BaseHTTPRequestHandler):
    server_version = "CsvSourceEditor/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.log_date_time_string()} {format % args}")

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self.send_html(INDEX_HTML)
            elif parsed.path == "/runner":
                self.send_html(RUNNER_HTML)
            elif parsed.path == "/dashboard":
                self.send_html(DASHBOARD_HTML)
            elif parsed.path == "/inputs":
                self.send_html(INPUTS_HTML)
            elif parsed.path == "/topology":
                self.send_html(TOPOLOGY_HTML)
            elif parsed.path == "/api/catalog":
                self.handle_catalog(parsed)
            elif parsed.path == "/api/file":
                self.handle_file(parsed)
            elif parsed.path == "/api/run-options":
                self.handle_run_options(parsed)
            elif parsed.path == "/api/output-runs":
                self.handle_output_runs()
            elif parsed.path == "/api/dashboard-data":
                self.handle_dashboard_data(parsed)
            elif parsed.path == "/api/run-file":
                self.handle_run_file(parsed)
            elif parsed.path == "/api/input-datasets":
                self.handle_input_datasets(parsed)
            elif parsed.path == "/api/input-dashboard-data":
                self.handle_input_dashboard_data(parsed)
            elif parsed.path == "/api/topology-data":
                self.handle_topology_data(parsed)
            elif parsed.path == "/api/run-status":
                self.handle_run_status(parsed)
            elif parsed.path == "/api/active-run":
                self.handle_active_run()
            else:
                raise AppError("Not found.", HTTPStatus.NOT_FOUND)
        except AppError as exc:
            self.send_json({"ok": False, "error": str(exc)}, exc.status)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/validate":
                self.handle_validate()
            elif parsed.path == "/api/save":
                self.handle_save()
            elif parsed.path == "/api/save-copy":
                self.handle_save_copy()
            elif parsed.path == "/api/start-run":
                self.handle_start_run()
            elif parsed.path == "/api/cancel-run":
                self.handle_cancel_run()
            elif parsed.path == "/api/run-model":
                self.handle_run_model()
            else:
                raise AppError("Not found.", HTTPStatus.NOT_FOUND)
        except AppError as exc:
            self.send_json({"ok": False, "error": str(exc)}, exc.status)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_catalog(self, parsed: Any) -> None:
        root = find_data_root(query_value(parsed, "root"))
        items = catalog_items(root)
        self.send_json(
            {
                "ok": True,
                "data_root": str(root),
                "datasets": [item_to_json(item) for item in items],
                "default_dataset": default_dataset(items),
            }
        )

    def handle_file(self, parsed: Any) -> None:
        root = find_data_root(query_value(parsed, "root"))
        dataset = query_value(parsed, "dataset")
        if not dataset:
            raise AppError("Dataset is required.")
        item = find_catalog_item(root, dataset)
        columns, rows, encoding = read_csv_rows(item.path)
        validation = validate_table(dataset, columns, rows, item)
        self.send_json(
            {
                "ok": True,
                "dataset": item.dataset,
                "columns": columns,
                "rows": rows,
                "hash": file_hash(item.path),
                "encoding": encoding,
                "validation": validation,
                "file": {
                    "relative_path": item.relative_path,
                    "modified": modified_time(item.path),
                    "size": item.path.stat().st_size,
                },
            }
        )

    def handle_run_options(self, parsed: Any) -> None:
        root = find_data_root(query_value(parsed, "root"))
        options = compatible_run_options(root)
        self.send_json(
            {
                "ok": True,
                "data_root": str(root),
                "script": str((Path.cwd() / POWER_MODELS[DEFAULT_POWER_MODEL]["script"]).resolve()),
                "power_model_options": power_model_options(),
                "default_power_model": DEFAULT_POWER_MODEL,
                "load_options": [item_to_json(item) for item in options["load_options"]],
                "solar_options": [item_to_json(item) for item in options["solar_options"]],
                "default_load": options["default_load"],
                "default_solar": options["default_solar"],
                "solver_options": solver_options(),
                "default_solver": POWER_MODELS[DEFAULT_POWER_MODEL]["default_solver"],
                "default_horizon_hours": 24,
                "default_lookahead_hours": 24,
                "default_nonanticipative_hours": 20,
            }
        )

    def handle_output_runs(self) -> None:
        runs = list_output_runs()
        self.send_json(
            {
                "ok": True,
                "runs": runs,
                "default_run": default_output_run(runs),
            }
        )

    def handle_dashboard_data(self, parsed: Any) -> None:
        run = query_value(parsed, "run")
        if not run:
            run = default_output_run(list_output_runs())
        if not run:
            raise AppError("No model run folders were found.", HTTPStatus.NOT_FOUND)
        sample = query_value(parsed, "sample") or "all"
        selected_series = query_value(parsed, "series") or "__fleet__"
        self.send_json(dashboard_data(run, sample, selected_series))

    def handle_run_file(self, parsed: Any) -> None:
        run = query_value(parsed, "run")
        relative_file = query_value(parsed, "file")
        if not run:
            raise AppError("Run is required.")
        path = resolve_run_file(run, relative_file)
        self.send_file(path)

    def handle_input_datasets(self, parsed: Any) -> None:
        root = find_data_root(query_value(parsed, "root"))
        items = input_dataset_items(root)
        self.send_json(
            {
                "ok": True,
                "data_root": str(root),
                "datasets": [item_to_json(item) for item in items],
                "default_dataset": default_input_dataset(items),
            }
        )

    def handle_input_dashboard_data(self, parsed: Any) -> None:
        root = find_data_root(query_value(parsed, "root"))
        dataset = query_value(parsed, "dataset") or default_input_dataset(input_dataset_items(root))
        if not dataset:
            raise AppError("No input datasets were found.", HTTPStatus.NOT_FOUND)
        selected_series = query_value(parsed, "series")
        model_window_value = query_value(parsed, "model_window_hours")
        model_window_hours = None
        if model_window_value:
            model_window_hours = parse_positive_float(model_window_value, "Model window hours")
            if model_window_hours > 8760:
                raise AppError("Model window hours must be 8760 or less.")
        self.send_json(input_dashboard_data(root, dataset, selected_series, model_window_hours))

    def handle_topology_data(self, parsed: Any) -> None:
        run = query_value(parsed, "run")
        if not run:
            run = default_output_run(list_output_runs())
        if not run:
            raise AppError("No model run folders were found.", HTTPStatus.NOT_FOUND)
        sample = query_value(parsed, "sample")
        self.send_json(topology_data(run, sample))

    def handle_run_status(self, parsed: Any) -> None:
        job_id = query_value(parsed, "job_id")
        if not job_id:
            raise AppError("job_id is required.")
        self.send_json({"ok": True, "job": get_public_job(job_id)})

    def handle_active_run(self) -> None:
        self.send_json({"ok": True, "job": active_run_job()})

    def handle_validate(self) -> None:
        payload = self.read_json()
        root = find_data_root(payload.get("root"))
        dataset = str(payload.get("dataset", ""))
        item = find_catalog_item(root, dataset)
        columns, rows = clean_table(payload.get("columns"), payload.get("rows"))
        self.send_json({"ok": True, "validation": validate_table(dataset, columns, rows, item)})

    def handle_save(self) -> None:
        payload = self.read_json()
        root = find_data_root(payload.get("root"))
        dataset = str(payload.get("dataset", ""))
        item = find_catalog_item(root, dataset)
        columns, rows = clean_table(payload.get("columns"), payload.get("rows"))
        validation = validate_table(dataset, columns, rows, item)
        if validation["errors"]:
            self.send_json({"ok": False, "error": "Validation errors block save.", "validation": validation}, HTTPStatus.BAD_REQUEST)
            return

        original_hash = str(payload.get("original_hash", ""))
        current_hash = file_hash(item.path)
        if original_hash and original_hash != current_hash:
            raise AppError("File changed on disk after it was loaded. Reload before saving.", HTTPStatus.CONFLICT)

        backup_path = backup_file(root, item)
        write_csv_rows(item.path, columns, rows)
        update_manifest_counts(root, dataset, len(rows), len(columns))
        new_hash = file_hash(item.path)
        self.send_json(
            {
                "ok": True,
                "hash": new_hash,
                "validation": validate_table(dataset, columns, rows, item),
                "backup_relative_path": backup_path.relative_to(root).as_posix(),
            }
        )

    def handle_save_copy(self) -> None:
        payload = self.read_json()
        root = find_data_root(payload.get("root"))
        dataset = str(payload.get("dataset", ""))
        source_item = find_catalog_item(root, dataset)
        columns, rows = clean_table(payload.get("columns"), payload.get("rows"))
        relative_path = safe_relative_csv_path(str(payload.get("relative_path", "")))
        target = ensure_inside(root, root / relative_path)
        if target.exists():
            raise AppError("Copy target already exists.")
        validation = validate_table(dataset, columns, rows, source_item)
        if validation["errors"]:
            self.send_json({"ok": False, "error": "Validation errors block copy save.", "validation": validation}, HTTPStatus.BAD_REQUEST)
            return
        write_csv_rows(target, columns, rows)

        registered_dataset = ""
        if bool(payload.get("register")):
            registered_dataset = str(payload.get("new_dataset", "")).strip().replace("\\", "/")
            if not registered_dataset:
                registered_dataset = relative_path.removesuffix(".csv")
            if any(item.dataset == registered_dataset for item in catalog_items(root)):
                raise AppError("Manifest dataset name already exists.")
            add_manifest_row(
                root=root,
                source_item=source_item,
                dataset=registered_dataset,
                relative_path=relative_path,
                rows_count=len(rows),
                columns_count=len(columns),
                notes=str(payload.get("notes", f"Copy of {dataset}")),
            )

        self.send_json(
            {
                "ok": True,
                "relative_path": relative_path,
                "dataset": registered_dataset,
            }
        )

    def handle_start_run(self) -> None:
        payload = self.read_json()
        job = start_run_job(payload)
        self.send_json({"ok": True, "job_id": job["job_id"], "job": job})

    def handle_cancel_run(self) -> None:
        payload = self.read_json()
        job_id = str(payload.get("job_id", ""))
        if not job_id:
            raise AppError("job_id is required.")
        self.send_json({"ok": True, "job": cancel_run_job(job_id)})

    def handle_run_model(self) -> None:
        payload = self.read_json()
        prepared = prepare_run_request(payload)
        result = run_network_script(
            data_dir=prepared["data_dir"],
            outputs_dir=prepared["outputs_dir"],
            power_model=prepared["power_model"],
            solver_name=prepared["solver_name"],
            solver_log=prepared["solver_log"],
            horizon_hours=prepared["horizon_hours"],
            lookahead_hours=prepared["lookahead_hours"],
            nonanticipative_hours=prepared["nonanticipative_hours"],
            solver_time_limit=prepared["solver_time_limit"],
            solver_mip_gap=prepared["solver_mip_gap"],
        )
        result.update(
            {
                "ok": True,
                "run_dir": str(prepared["run_dir"]),
                "data_dir": str(prepared["data_dir"]),
                "outputs_dir": str(prepared["outputs_dir"]),
                "power_model": prepared["power_model"],
                "power_model_label": prepared["power_model_label"],
                "power_model_script": prepared["power_model_script"],
                "selected_sources": {
                    "load_dataset": prepared["load_dataset"],
                    "solar_dataset": prepared["solar_dataset"],
                },
                "horizon_hours": prepared["horizon_hours"],
                "lookahead_hours": prepared["lookahead_hours"],
                "nonanticipative_hours": prepared["nonanticipative_hours"],
                "solver_time_limit": prepared["solver_time_limit"],
                "solver_mip_gap": prepared["solver_mip_gap"],
            }
        )
        self.send_json(result)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        body = self.rfile.read(length).decode("utf-8")
        data = json.loads(body)
        if not isinstance(data, dict):
            raise AppError("JSON body must be an object.")
        return data

    def send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path) -> None:
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type_for_path(path))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'inline; filename="{path.name}"')
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def query_value(parsed: Any, name: str) -> str:
    values = parse_qs(parsed.query).get(name, [""])
    return values[0]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"Serve the {APP_TITLE} CSV editor.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), CsvSourceEditorHandler)
    print(f"{APP_TITLE} editor running at http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
