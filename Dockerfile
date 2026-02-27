FROM ghcr.io/anomalyco/opencode:latest
USER root
RUN set -eux; \
    if command -v apt-get >/dev/null 2>&1; then \
        echo "Ubuntu";\
        apt-get update && apt-get install -y --no-install-recommends git python3 && rm -rf /var/lib/apt/lists/*; \
    elif command -v apk >/dev/null 2>&1; then \
        echo "Alpine";\
        apk add --no-cache git python3; \
    elif command -v dnf >/dev/null 2>&1; then \
        echo "Fedora";\
        dnf install -y git python3 && dnf clean all; \
    else \
        echo "No supported package manager found (apt/apk/dnf)." >&2; exit 1; \
    fi
RUN if command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1; then ln -s "$(command -v python3)" /usr/local/bin/python; fi
