# jevvify in a container.
#
#   docker build -t jevvify . && docker run --rm -v "$PWD:/work" jevvify
#
# Demo on the bundled example (copied to /app/examples), no mount needed:
#
#   docker run --rm jevvify analyze /app/examples
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY . /app
RUN pip install ".[multilang]"

WORKDIR /work
ENTRYPOINT ["jevvify"]
CMD ["analyze", "/work"]
