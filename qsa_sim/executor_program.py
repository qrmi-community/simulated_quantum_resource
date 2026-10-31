# -*- coding: utf-8 -*-

# (C) Copyright 2026 IBM. All Rights Reserved.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Support for the ``executor`` program (Qiskit Runtime Executor / QuantumProgram).

Input parameters are produced on the client side by
``QUANTUM_PROGRAM_PARAMS_CONVERTERS[version].encoder(program, options)`` and are decoded
here with the matching ``decoder``. The decoded :class:`~qiskit_ibm_runtime.QuantumProgram`
is simulated with Aer, and the :class:`~qiskit_ibm_runtime.results.QuantumProgramResult` is
encoded into the ``QuantumProgramResultModel`` schema that
``qiskit_ibm_runtime.decoders.executor.decoder.ExecutorResultDecoder`` understands.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Tuple

import numpy as np
from ibm_quantum_schemas.common import CompressedTensorModel
from ibm_quantum_schemas.executor.version_2_0 import (
    ChunkPart,
    ChunkSpan,
    ItemMetadataModel,
    MetadataModel,
    QuantumProgramResultItemModel,
    QuantumProgramResultModel,
)
from qiskit_aer import AerSimulator
from qiskit_ibm_runtime.fake_provider.executor.run_quantum_program import (
    run_quantum_program,
)
from qiskit_ibm_runtime.options_models.executor import ExecutorOptions
from qiskit_ibm_runtime.options_models.simulator import SimulatorOptions
from qiskit_ibm_runtime.quantum_program import QuantumProgram
from qiskit_ibm_runtime.quantum_program.converters.converters_2_0 import (
    passthrough_data_to_2_0,
)
from qiskit_ibm_runtime.quantum_program.params_converters import (
    QUANTUM_PROGRAM_PARAMS_CONVERTERS,
)
from qiskit_ibm_runtime.results import QuantumProgramResult

_logger = logging.getLogger("api")

RESULT_SCHEMA_VERSION = "v2.0"
"""Schema version of the results written by this simulator."""

EXPERIMENTAL_OPTIONS_KEY = "qsa_sim"
"""Key under ``ExecutorOptions.experimental`` used to override simulator settings per job."""

SUPPORTED_SIMULATOR_OPTIONS = ("seed_simulator", "angle_decimals", "warn_absent")
"""``SimulatorOptions`` fields that can be configured (``layer_noise_model`` is not
JSON-serializable and therefore not supported)."""


@dataclass
class ExecutorRunSettings:
    """Simulation settings resolved from the configuration file and the job parameters."""

    backend_options: Dict[str, Any] = field(default_factory=dict)
    """Options passed to the ``AerSimulator`` constructor."""

    simulator_options: Dict[str, Any] = field(default_factory=dict)
    """Subset of ``SimulatorOptions`` (see ``SUPPORTED_SIMULATOR_OPTIONS``)."""


def decode_executor_params(raw: str) -> Tuple[QuantumProgram, ExecutorOptions, str]:
    """Decode the executor job parameters.

    Args:
        raw: JSON string of the params model (``ParamsModel.model_dump(mode="json")``).

    Returns:
        A tuple of the quantum program, the executor options and the schema version.

    Raises:
        ValueError: If the schema version is missing or unsupported.
    """
    try:
        schema_version = json.loads(raw)["schema_version"]
    except (KeyError, TypeError) as err:
        raise ValueError("No schema_version in executor input.") from err

    try:
        converter = QUANTUM_PROGRAM_PARAMS_CONVERTERS[schema_version]
    except KeyError as err:
        raise ValueError(
            f"Unsupported executor schema_version: {schema_version}. "
            f"Supported: {list(QUANTUM_PROGRAM_PARAMS_CONVERTERS)}"
        ) from err

    model = converter.model.model_validate_json(raw)
    program, options = converter.decoder(model)

    # Samplexes restored from their serialized form are not finalized yet.
    for item in program.items:
        samplex = getattr(item, "samplex", None)
        if samplex is not None and not getattr(samplex, "_finalized", True):
            samplex.finalize()

    return program, options, schema_version


def resolve_run_settings(
    config_options: Dict[str, Any] | None, executor_options: ExecutorOptions
) -> ExecutorRunSettings:
    """Merge settings from the config file with per-job overrides.

    Per-job overrides are read from ``ExecutorOptions.experimental["qsa_sim"]``, e.g.::

        executor.options.experimental = {
            "qsa_sim": {
                "backend_options": {"method": "stabilizer"},
                "simulator_options": {"seed_simulator": 42},
            }
        }
    """
    config_options = config_options or {}
    job_options = (executor_options.experimental or {}).get(
        EXPERIMENTAL_OPTIONS_KEY
    ) or {}

    for key in job_options:
        if key not in ("backend_options", "simulator_options"):
            _logger.warning(
                "Unsupported experimental.%s.%s. Ignored.",
                EXPERIMENTAL_OPTIONS_KEY,
                key,
            )

    backend_options = dict(config_options.get("backend_options", {})) | dict(
        job_options.get("backend_options", {})
    )
    simulator_options = dict(config_options.get("simulator_options", {})) | dict(
        job_options.get("simulator_options", {})
    )
    for key in list(simulator_options):
        if key not in SUPPORTED_SIMULATOR_OPTIONS:
            _logger.warning("Unsupported simulator option %s. Ignored.", key)
            simulator_options.pop(key)

    return ExecutorRunSettings(
        backend_options=backend_options, simulator_options=simulator_options
    )


def run_executor_program(
    backend, program: QuantumProgram, settings: ExecutorRunSettings
) -> Tuple[QuantumProgramResult, dt.datetime, dt.datetime]:
    """Simulate a quantum program.

    The fake backend is wrapped by ``AerSimulator.from_backend`` so that its noise model is used,
    and ``backend_options`` (e.g. ``method``) are applied to the simulator.

    Returns:
        The result, and the start and stop time (UTC) of the simulation.
    """
    simulator = (
        backend
        if isinstance(backend, AerSimulator) and not settings.backend_options
        else AerSimulator.from_backend(backend, **settings.backend_options)
    )
    sim_options = SimulatorOptions(**settings.simulator_options)

    start = dt.datetime.now(dt.timezone.utc)
    result = run_quantum_program(simulator, program, sim_options)
    stop = dt.datetime.now(dt.timezone.utc)
    return result, start, stop


def _item_size(item) -> Tuple[int, int]:
    """Return (ndim, number of elements) of a quantum program item."""
    shape = tuple(item.shape)
    return len(shape), math.prod(shape)


def _to_tensor(value: np.ndarray) -> CompressedTensorModel:
    value = np.asarray(value)
    try:
        return CompressedTensorModel.from_numpy(value)
    except ValueError:
        # Fallback for dtypes not supported by the schema.
        if np.issubdtype(value.dtype, np.complexfloating):
            return CompressedTensorModel.from_numpy(value.astype(np.complex128))
        return CompressedTensorModel.from_numpy(value.astype(np.float64))


def encode_quantum_program_result(
    result: QuantumProgramResult,
    program: QuantumProgram,
    start: dt.datetime,
    stop: dt.datetime,
) -> str:
    """Encode a :class:`QuantumProgramResult` to the v2.0 ``QuantumProgramResultModel`` JSON.

    This is the inverse of ``qiskit_ibm_runtime.decoders.executor.converters
    .quantum_program_result_from_2_0``. Since the simulator executes the whole program at once,
    the timing metadata contains a single chunk that covers every element of every item.
    """
    parts = []
    for idx, item in enumerate(program.items):
        ndim, size = _item_size(item)
        parts.append(
            ChunkPart(
                idx_item=idx,
                size=size,
                permutation=list(range(ndim)),
                element_range=(0, size, 1),
            )
        )

    data = [
        QuantumProgramResultItemModel(
            results={name: _to_tensor(value) for name, value in item_result.items()},
            # scheduler_timing / stretch_values are hardware-only features.
            metadata=ItemMetadataModel(),
        )
        for item_result in result
    ]

    model = QuantumProgramResultModel(
        schema_version=RESULT_SCHEMA_VERSION,
        data=data,
        metadata=MetadataModel(
            chunk_timing=[ChunkSpan(start=start, stop=stop, parts=parts)]
        ),
        passthrough_data=passthrough_data_to_2_0(program.passthrough_data),
        semantic_role=getattr(program, "_semantic_role", None),
    )
    return model.model_dump_json()


def usage_nanoseconds(
    result: QuantumProgramResult, start: dt.datetime, stop: dt.datetime
) -> int:
    """Simulation time in nanoseconds.

    Sums ``simulator_metadata.time_taken_execute`` reported by Aer, falling back to the
    wall-clock duration of the simulation.
    """
    total = 0.0
    found = False
    for item_result in result:
        metadata = getattr(item_result, "metadata", None)
        if isinstance(metadata, dict):
            sim_meta = metadata.get("simulator_metadata") or {}
            if "time_taken_execute" in sim_meta:
                total += float(sim_meta["time_taken_execute"])
                found = True
    if not found:
        total = (stop - start).total_seconds()
    return int(total * 1_000_000_000)
