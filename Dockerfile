# Operating core image: the same image runs one-off commands and the scheduled worker.
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY mandate.toml mandate.simulated.toml ./
# integrations/registry.toml (platform-eligibility task) is mounted or copied when it exists; the core tolerates its absence.
RUN pip install --no-cache-dir -e ".[postgres]"
ENTRYPOINT ["arbitrage-ops"]
CMD ["status"]
