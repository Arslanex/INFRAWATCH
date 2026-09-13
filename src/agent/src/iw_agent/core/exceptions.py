from __future__ import annotations

from typing import ClassVar


class AgentError(Exception):
    service: ClassVar[str] = "agent"
    code: ClassVar[str] = "INFRAWATCH_AGENT_ERROR"

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        return f"[{self.service}/{self.code}] {self.message}"


class NetworkError(AgentError):
    service = "network"
    code = "NETWORK_ERROR"


class NetworkAccessDeniedError(NetworkError):
    code = "NETWORK_ACCESS_DENIED"

    def __init__(
        self,
        message: str = "net_connections denied — insufficient privileges",
    ):
        super().__init__(message)


class NetworkReadError(NetworkError):
    code = "NETWORK_READ_ERROR"


class ProcessError(AgentError):
    service = "processes"
    code = "PROCESS_ERROR"


class ProcessAccessDeniedError(ProcessError):
    code = "PROCESS_ACCESS_DENIED"

    def __init__(
        self,
        message: str = "process_iter denied — insufficient privileges",
    ):
        super().__init__(message)


class ProcessReadError(ProcessError):
    code = "PROCESS_READ_ERROR"


class ProcessCgroupUnreadableError(ProcessError):
    code = "PROCESS_CGROUP_UNREADABLE"


class DeviceError(AgentError):
    service = "device"
    code = "DEVICE_ERROR"


class DeviceMetricUnavailableError(DeviceError):
    code = "DEVICE_METRIC_UNAVAILABLE"


class DeviceDiskUnreadableError(DeviceError):
    code = "DEVICE_DISK_UNREADABLE"


class DockerError(AgentError):
    service = "docker"
    code = "DOCKER_ERROR"


class DockerUnavailableError(DockerError):
    code = "DOCKER_UNAVAILABLE"


class DockerTimeoutError(DockerError):
    code = "DOCKER_TIMEOUT"


class NginxError(AgentError):
    service = "ngnix"
    code = "NGINX_ERROR"


class NginxNotInstalledError(NginxError):
    code = "NGINX_NOT_INSTALLED"

    def __init__(self, message: str = "nginx is not installed on this host"):
        super().__init__(message)


class NginxCommandStartError(NginxError):
    code = "NGINX_COMMAND_START_FAILED"


class NginxCommandFailedError(NginxError):
    code = "NGINX_COMMAND_FAILED"


class NginxTimeoutError(NginxError):
    code = "NGINX_TIMEOUT"


class SslError(AgentError):
    service = "ssl"
    code = "SSL_ERROR"


class SslCertbotDirectoryUnreadableError(SslError):
    code = "SSL_CERTBOT_DIRECTORY_UNREADABLE"


class SslCertificateUnreadableError(SslError):
    code = "SSL_CERTIFICATE_UNREADABLE"


class CronError(AgentError):
    service = "cron"
    code = "CRON_ERROR"


class CronCrontabUnreadableError(CronError):
    code = "CRON_CRONTAB_UNREADABLE"


class CronExecutionLogUnreadableError(CronError):
    code = "CRON_EXECUTION_LOG_UNREADABLE"
