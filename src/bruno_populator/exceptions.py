"""Custom exceptions for Bruno Populator."""


class BrunoPopulatorError(Exception):
    """Base exception for all Bruno Populator errors."""

    pass


class ConfigurationError(BrunoPopulatorError):
    """Raised when configuration validation fails or input paths do not exist."""

    pass


class YamlGenerationError(BrunoPopulatorError):
    """Raised when generating a Bruno YAML request file fails."""

    pass


class BrunoCliError(BrunoPopulatorError):
    """Raised when Bruno CLI (`bru run`) fails or returns a non-zero exit code."""

    def __init__(self, message: str, exit_code: int = 1, stderr: str = ""):
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr
