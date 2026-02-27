"""Runtime constants shared across worker and runtime modules."""

# Docker image and container defaults
DEFAULT_DOCKER_IMAGE = "sisifo/opencode:latest"
DEFAULT_OPENCODE_SERVER_CMD = ["serve", "--hostname", "0.0.0.0", "--port", "8000"]

# OpenCode container directory paths
DEFAULT_CONTAINER_OPENCODE_CONFIG_DIR = "/root/.config/opencode"
DEFAULT_CONTAINER_OPENCODE_DATA_DIR = "/root/.local/share/opencode"
