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

"""Tests for the executor program of QSAService"""

import json
import logging
import time
from functools import reduce
from pathlib import Path

import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit import Parameter
from qiskit.primitives import PrimitiveResult
from qiskit.quantum_info import SparsePauliOp
from qiskit.transpiler import generate_preset_pass_manager

from qiskit_ibm_runtime import QuantumProgram
from qiskit_ibm_runtime.decoders.defaults import DEFAULT_DECODERS
from qiskit_ibm_runtime.fake_provider import FakeLagosV2
from qiskit_ibm_runtime.executor_estimator.prepare import prepare as estimator_prepare
from qiskit_ibm_runtime.executor_sampler.prepare import prepare as sampler_prepare
from qiskit_ibm_runtime.options_models.estimator import EstimatorOptions
from qiskit_ibm_runtime.options_models.executor import ExecutorOptions
from qiskit_ibm_runtime.options_models.sampler import SamplerOptions
from qiskit_ibm_runtime.quantum_program.params_converters import (
    QUANTUM_PROGRAM_PARAMS_CONVERTERS,
)
from qiskit_ibm_runtime.results import QuantumProgramResult

from qsa_sim.qsa_service import QSAService
from qsa_sim.consts import PYTEST_JOBS_DIR
from .test_qsa_base import QSASTestBase

logging.getLogger(__name__).setLevel(logging.WARNING)


def generate_executor_input(
    program: QuantumProgram,
    options: ExecutorOptions | None = None,
    schema_version: str = "v2.0",
) -> str:
    """Generate input JSON in the same way as ``qiskit_ibm_runtime.Executor.run()``."""
    converter = QUANTUM_PROGRAM_PARAMS_CONVERTERS[schema_version]
    params = converter.encoder(program, options or ExecutorOptions())
    return json.dumps(params.model_dump(mode="json"))


def decode_executor_result(result_str: str):
    """Decode results in the same way as ``RuntimeJobV2.result()`` for ``executor``."""
    return reduce(
        lambda result, decoder: (
            decoder.decode(result) if decoder.is_applicable(result) else result
        ),
        DEFAULT_DECODERS["executor"],
        result_str,
    )


class QSAExecutorTest(QSASTestBase):
    """Test cases for QSA Executor Services"""

    def setUp(self):
        super().setUp()
        self.service.close()
        self.service = QSAService(
            include_opt_fields=True,
            multiprocess=False,
            jobs_dir=PYTEST_JOBS_DIR,
            aer_options={"executor": {"simulator_options": {"seed_simulator": 7}}},
        )
        self.backend = self.service._get_backend(  # pylint: disable=protected-access
            self.service.default_backend_name
        )

    def run_executor(
        self, input_str: str, wait_completion: bool = True, backend_name: str = None
    ):
        """Run an executor job and return (job, raw result json)."""
        dir_path = Path(self._storage_dir_name)
        self._request_count += 1
        input_file_path = dir_path / f"input-{self._request_count}.json"
        results_file_path = dir_path / f"results-{self._request_count}.json"
        input_file_path.write_text(input_str, encoding="utf-8")

        job = self._generate_job(
            input_file_path,
            results_file_path,
            "executor",
            backend_name or self.service.default_backend_name,
        )
        self.assertEqual(self.service.execute_job(job), {"ok": True})
        if not wait_completion:
            return job, None

        while (status := self.service.job_status(job))["status"] == "Running":
            time.sleep(0.5)
        if status["status"] != "Completed":
            raise ValueError(status.get("reason_message", status))
        self.assertGreater(job["metrics"]["circuits_execution_time_ns"], 0)
        return job, results_file_path.read_text(encoding="utf-8")

    def _bell(self, measure: bool = True) -> QuantumCircuit:
        circ = QuantumCircuit(2)
        circ.h(0)
        circ.cx(0, 1)
        if measure:
            circ.measure_all()
        return self._pm.run(circ)

    def test_circuit_items(self):
        """Raw QuantumProgram with parametrized circuit items"""
        theta = Parameter("theta")
        circ = QuantumCircuit(1)
        circ.rx(theta, 0)
        circ.measure_all()
        isa = self._pm.run(circ)

        program = QuantumProgram(
            shots=1000, passthrough_data={"tag": "abc", "arr": np.arange(3.0)}
        )
        program.append_circuit_item(isa, circuit_arguments=np.array([[0.0], [np.pi]]))
        program.append_circuit_item(self._bell())

        _, result_str = self.run_executor(generate_executor_input(program))

        # The raw JSON must follow the v2.0 result schema.
        raw = json.loads(result_str)
        self.assertEqual(raw["schema_version"], "v2.0")
        parts = raw["metadata"]["chunk_timing"][0]["parts"]
        self.assertEqual([p["size"] for p in parts], [2, 1])

        result = decode_executor_result(result_str)
        self.assertIsInstance(result, QuantumProgramResult)
        self.assertEqual(len(result), 2)
        self.assertEqual(result.passthrough_data["tag"], "abc")
        np.testing.assert_array_equal(result.passthrough_data["arr"], np.arange(3.0))

        meas = result[0]["meas"]
        self.assertEqual(meas.shape, (2, 1000, 1))
        # rx(0) -> |0>, rx(pi) -> |1> (with readout noise)
        self.assertLess(meas[0].mean(), 0.1)
        self.assertGreater(meas[1].mean(), 0.9)

        bell = result[1]["meas"]
        self.assertEqual(bell.shape, (1000, 2))
        agree = np.mean(bell[:, 0] == bell[:, 1])
        self.assertGreater(agree, 0.85)

    def test_client_side_sampler(self):
        """QuantumProgram generated by the executor-based Sampler (twirling enabled)"""
        options = SamplerOptions()
        options.twirling.enable_gates = True
        options.twirling.enable_measure = True
        program, executor_options = sampler_prepare(
            [self._bell()], options, shots=2000, backend=self.backend
        )
        program._semantic_role = "sampler_v2"  # pylint: disable=protected-access

        _, result_str = self.run_executor(
            generate_executor_input(program, executor_options)
        )
        result = decode_executor_result(result_str)
        self.assertIsInstance(result, PrimitiveResult)
        counts = result[0].data.meas.get_counts()
        # Twirling may round the total shots up to a multiple of the randomizations.
        self.assertGreaterEqual(sum(counts.values()), 2000)
        self.assertGreater(
            (counts.get("00", 0) + counts.get("11", 0)) / sum(counts.values()), 0.85
        )

    def test_client_side_estimator(self):
        """QuantumProgram generated by the executor-based Estimator

        The executor-based Estimator measures every qubit of the ISA circuit, so a small
        backend is used here to keep the noisy statevector simulation tractable.
        """
        backend_name = FakeLagosV2.backend_name
        backend = self.service._get_backend(  # pylint: disable=protected-access
            backend_name
        )
        circ = QuantumCircuit(2)
        circ.h(0)
        circ.cx(0, 1)
        isa = generate_preset_pass_manager(optimization_level=1, backend=backend).run(
            circ
        )
        obs = SparsePauliOp(["ZZ", "XX", "ZI"]).apply_layout(isa.layout)
        program, executor_options = estimator_prepare(
            [(isa, obs)], EstimatorOptions(), precision=0.05, backend=backend
        )
        program._semantic_role = "estimator_v2"  # pylint: disable=protected-access

        _, result_str = self.run_executor(
            generate_executor_input(program, executor_options),
            backend_name=backend_name,
        )
        result = decode_executor_result(result_str)
        self.assertIsInstance(result, PrimitiveResult)
        # <ZZ> + <XX> + <ZI> = 2 for the Bell state
        self.assertAlmostEqual(float(result[0].data.evs), 2.0, delta=0.3)

    def test_seed_reproducibility(self):
        """Same seed gives the same samples"""
        program = QuantumProgram(shots=100)
        program.append_circuit_item(self._bell())
        input_str = generate_executor_input(program)

        _, first = self.run_executor(input_str)
        _, second = self.run_executor(input_str)
        np.testing.assert_array_equal(
            decode_executor_result(first)[0]["meas"],
            decode_executor_result(second)[0]["meas"],
        )

    def test_experimental_overrides(self):
        """Per-job overrides via options.experimental['qsa_sim']"""
        program = QuantumProgram(shots=100)
        program.append_circuit_item(self._bell())

        def run_with_seed(seed):
            options = ExecutorOptions()
            options.experimental = {
                "qsa_sim": {"simulator_options": {"seed_simulator": seed}}
            }
            _, result_str = self.run_executor(generate_executor_input(program, options))
            return decode_executor_result(result_str)[0]["meas"]

        np.testing.assert_array_equal(run_with_seed(123), run_with_seed(123))
        self.assertFalse(np.array_equal(run_with_seed(123), run_with_seed(456)))

    def test_invalid_input(self):
        """Invalid inputs make the job fail"""
        for input_str in [
            json.dumps({"quantum_program": {}}),  # no schema_version
            json.dumps({"schema_version": "v9.9"}),  # unsupported version
            json.dumps({"schema_version": "v2.0", "quantum_program": {}}),  # invalid
        ]:
            with self.subTest(input_str=input_str):
                with self.assertRaises(ValueError):
                    self.run_executor(input_str)

    def test_unsupported_meas_level(self):
        """meas_level other than 'classified' makes the job fail (no IQ data in Aer)"""
        for meas_level in ["kerneled", "avg_kerneled", "both"]:
            with self.subTest(meas_level=meas_level):
                program = QuantumProgram(shots=100, meas_level=meas_level)
                program.append_circuit_item(self._bell())
                with self.assertRaisesRegex(ValueError, "meas_level"):
                    self.run_executor(generate_executor_input(program))

    def test_unknown_program(self):
        """Unknown program_id still fails"""
        job = self._generate_job(
            Path(self._storage_dir_name) / "x.json",
            Path(self._storage_dir_name) / "y.json",
            "unknown",
            self.service.default_backend_name,
        )
        self.assertEqual(self.service.execute_job(job), {"ok": False})
