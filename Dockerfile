FROM python:3.12-slim

# qiskit-aer bundles libgomp, which uses initial-exec TLS. Python loads it with dlopen,
# so it must fit in the small static TLS surplus glibc reserves at startup. On the
# Debian 13 base of python:3.12-slim that surplus is already used up and the simulator
# exits with "libgomp...: cannot allocate memory in static TLS block". Reserve more,
# as Qiskit does for the same failure (https://github.com/Qiskit/qiskit/issues/17213).
ENV GLIBC_TUNABLES=glibc.rtld.optional_static_tls=65536

WORKDIR /app

COPY config.yaml .
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./qsa_sim ./qsa_sim

CMD ["python", "-m", "qsa_sim.app", "config.yaml"]
