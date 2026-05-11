FROM python:3.11-slim

# System dependencies required at runtime inside the container:
# - ripgrep:         janskie's search_codebase tool prefers it over its Python
#                    fallback for much faster searches on real corpora.
# - git:             gitpython (used by get_repo_version) reads most data
#                    directly from the .git/ object database, but prints a
#                    loud "Bad git executable" warning at first use if the
#                    binary is missing. Installing git silences that and
#                    future-proofs is_dirty() edge cases that do shell out.
# - ca-certificates: HTTPS for any remote git/network operations (e.g. when
#                    a future `corpus sync` clones corpus repos from inside
#                    the container).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ripgrep \
        git \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Defensive: if any future minimal base image drops git, suppress
# gitpython's startup chatter rather than letting it pollute stderr on
# every janskie invocation.
ENV GIT_PYTHON_REFRESH=quiet

WORKDIR /app

# Install uv for fast package installation
COPY --from=ghcr.io/astral-sh/uv:0.9.8 /uv /usr/local/bin/uv

# Copy package files
COPY pyproject.toml README.md ./
COPY src/ src/

# Install africalim. The base install pulls in everything janskie needs at
# runtime; there is no `[full]` extra in v0.1.0.
RUN uv pip install --system --no-cache .

# Make CLI available
CMD ["africalim", "--help"]
