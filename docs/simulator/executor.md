# Executor program support

In addition to `sampler` and `estimator`, this API simulator accepts jobs with `"program_id": "executor"`.
An executor job runs a [`QuantumProgram`](https://quantum.cloud.ibm.com/docs/en/api/qiskit-ibm-runtime/quantum-program)
— the input format of the Qiskit Runtime `Executor`, which is also used by the executor-based
`Sampler` / `Estimator` of `qiskit-ibm-runtime`.

## Input

The job input stored in S3 compatible storage is the params model produced by `qiskit-ibm-runtime`, i.e. what
`Executor.run()` would send:

```python
import json
from qiskit_ibm_runtime import QuantumProgram
from qiskit_ibm_runtime.options_models.executor import ExecutorOptions
from qiskit_ibm_runtime.quantum_program.params_converters import QUANTUM_PROGRAM_PARAMS_CONVERTERS

program = QuantumProgram(shots=1000)
program.append_circuit_item(isa_circuit)                       # CircuitItem
# program.append_samplex_item(template, samplex, arguments)   # SamplexItem (samplomatic)

converter = QUANTUM_PROGRAM_PARAMS_CONVERTERS["v2.0"]
params = converter.encoder(program, ExecutorOptions())
input_json = json.dumps(params.model_dump(mode="json"))       # upload this as the job input
```

The simulator selects the converter by `schema_version` (`v0.1`, `v0.2`, `v1.0`, `v1.1`, `v2.0`), and restores
the `QuantumProgram` with `converter.decoder()`. Both `CircuitItem` and `SamplexItem` are supported.
`passthrough_data` and the semantic role (`sampler_v2`, `estimator_v2`) are preserved.

## Execution

The program is simulated with `qiskit_ibm_runtime.fake_provider.executor.run_quantum_program`, the same routine
used by the local testing mode of `qiskit-ibm-runtime`, on `AerSimulator.from_backend(<fake backend>)`. The noise
model of the selected fake backend is therefore applied.

## Results

Results are written in the `QuantumProgramResultModel` schema **v2.0**, which is decoded on the client side with
the `executor` decoders of `qiskit-ibm-runtime`:

```python
from functools import reduce
from qiskit_ibm_runtime.decoders.defaults import DEFAULT_DECODERS

result = reduce(
    lambda res, dec: dec.decode(res) if dec.is_applicable(res) else res,
    DEFAULT_DECODERS["executor"],
    result_json,
)
# -> QuantumProgramResult, or PrimitiveResult when the program was made by the executor-based Sampler/Estimator
```

`metadata.chunk_timing` contains a single chunk that spans the whole simulation.
`usage.quantum_nanoseconds` is the sum of Aer's `time_taken_execute`.

## Configuration

Simulator settings can be configured in the configuration file:

```yaml
aer_options:
  executor:
    # passed to AerSimulator.from_backend()
    backend_options:
      method: "matrix_product_state"
    # subset of qiskit_ibm_runtime SimulatorOptions
    simulator_options:
      seed_simulator: 42
      angle_decimals: 5
      warn_absent: true
```

and overridden per job through `ExecutorOptions.experimental["qsa_sim"]`:

```python
options = ExecutorOptions()
options.experimental = {
    "qsa_sim": {
        "backend_options": {"method": "stabilizer"},
        "simulator_options": {"seed_simulator": 123},
    }
}
```

## Limitations

- Results are always returned in schema `v2.0`. Clients must use `qiskit-ibm-runtime` 0.51.0 or later.
- Only `meas_level: classified` is supported. `kerneled`, `avg_kerneled` and `both` return IQ data (complex arrays
  named `<creg>_iq` / `<creg>_avg_iq`), which Aer cannot produce because it does not model readout signals.
  Jobs with these levels fail instead of silently returning bit arrays in the wrong format.
- `scheduler_timing` and `stretch_values` item metadata are not returned.
- `SimulatorOptions.layer_noise_model` (noise injection at tagged boxes) cannot be configured, because it is not
  JSON-serializable.
- `ExecutorOptions.init_qubits` and `rep_delay` have no effect on the simulation.
- The executor-based `Estimator` measures every qubit of the ISA circuit. On large backends (e.g. FakeBrisbane,
  FakeTorino) the noisy simulation falls back to statevector and may fail with
  `a circuit requires more memory than max_memory_mb`. Use a small backend, or set `backend_options.method`
  (e.g. `matrix_product_state`).
