FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AGENT_APP_WORKSPACE=/workspace
WORKDIR /workspace
COPY agent_app/pyproject.toml agent_app/README.md /workspace/agent_app/
COPY agent_app/src /workspace/agent_app/src
COPY docs/merchant_lending/demo_parameters.json /workspace/docs/merchant_lending/demo_parameters.json
COPY examples/merchant_sandbox /workspace/examples/merchant_sandbox
RUN python -m pip install --no-cache-dir ./agent_app \
    && useradd --uid 10001 --create-home merchant \
    && mkdir -p /workspace/outputs \
    && chown -R merchant:merchant /workspace
USER merchant
EXPOSE 8781
ENTRYPOINT ["python", "-m", "merchant_sandbox.review_api"]
CMD ["--host", "0.0.0.0", "--port", "8781", "--db", "/workspace/outputs/reviews.sqlite3"]
