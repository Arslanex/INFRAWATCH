from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from cryptography import x509
from cryptography.x509.oid import ExtensionOID, NameOID

from iw_agent.core._thread import read
from iw_agent.core.exceptions import (
    SslCertbotDirectoryUnreadableError,
    SslCertificateUnreadableError,
)
from iw_agent.core.logger import logger
from iw_agent.modules.ssl.schemas import Certificate

DEFAULT_CERTBOT_LIVE_DIR = "/etc/letsencrypt/live"
_CERT_FILE_NAMES = ("fullchain.pem", "cert.pem")


async def collect_certificates(
    certbot_live_dir: str = DEFAULT_CERTBOT_LIVE_DIR,
    nginx_cert_paths: list[str] | None = None,
) -> list[Certificate]:
    return await read(_collect_certificates, certbot_live_dir, nginx_cert_paths or [])


def _collect_certificates(
    certbot_live_dir: str,
    nginx_cert_paths: list[str],
) -> list[Certificate]:
    certificates: list[Certificate] = []
    seen_paths: set[str] = set()

    # 1. certbot live + nginx ssl_certificate yollarını tek tek oku
    for cert_path, source in _certificate_candidates(certbot_live_dir, nginx_cert_paths):
        if cert_path in seen_paths:
            continue
        seen_paths.add(cert_path)

        certificate = _read_certificate(cert_path, source)
        if certificate is not None:
            certificates.append(certificate)

    logger.debug("collected %d certificates", len(certificates))
    return certificates


def cert_name_from_path(cert_path: str) -> str:
    return Path(cert_path).parent.name


async def find_certificate(
    cert_path: str,
    *,
    certbot_live_dir: str = DEFAULT_CERTBOT_LIVE_DIR,
    nginx_cert_paths: list[str] | None = None,
) -> Certificate | None:
    certificates = await collect_certificates(
        certbot_live_dir=certbot_live_dir,
        nginx_cert_paths=[cert_path, *(nginx_cert_paths or [])],
    )
    normalized = cert_path.strip()
    return next((cert for cert in certificates if cert.cert_path == normalized), None)


def _certificate_candidates(certbot_live_dir: str, nginx_cert_paths: list[str]):
    live_directory = Path(certbot_live_dir)
    if live_directory.is_dir():
        try:
            for domain_directory in sorted(live_directory.iterdir()):
                for file_name in _CERT_FILE_NAMES:
                    candidate = domain_directory / file_name
                    if candidate.is_file():
                        yield str(candidate), "certbot"
                        break
        except OSError as exc:
            # /etc/letsencrypt çoğu hostta root-only (TR-02)
            logger.debug(
                "%s",
                SslCertbotDirectoryUnreadableError(f"{certbot_live_dir}: {exc}"),
            )

    for cert_path in nginx_cert_paths:
        yield cert_path, "other"


def _read_certificate(cert_path: str, source: str) -> Certificate | None:
    try:
        raw_bytes = Path(cert_path).read_bytes()
        x509_certificate = x509.load_pem_x509_certificate(raw_bytes)
    except (OSError, ValueError) as exc:
        # Okunamayan dosya sadece o sertifikayı atlar, tick kırılmaz
        logger.debug(
            "%s",
            SslCertificateUnreadableError(f"{cert_path}: {exc}"),
        )
        return None

    return Certificate(
        domain=_domain_of(x509_certificate),
        issuer=_issuer_of(x509_certificate),
        not_before=_timezone_aware(x509_certificate.not_valid_before_utc),
        not_after=_timezone_aware(x509_certificate.not_valid_after_utc),
        cert_path=cert_path,
        source=source,
    )


def _domain_of(certificate: x509.Certificate) -> str:
    try:
        san_extension = certificate.extensions.get_extension_for_oid(
            ExtensionOID.SUBJECT_ALTERNATIVE_NAME
        )
        dns_names = san_extension.value.get_values_for_type(x509.DNSName)  # type: ignore[attr-defined]
        if dns_names:
            return dns_names[0]
    except x509.ExtensionNotFound:
        pass

    common_names = certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    return str(common_names[0].value) if common_names else ""


def _issuer_of(certificate: x509.Certificate) -> str | None:
    common_names = certificate.issuer.get_attributes_for_oid(NameOID.COMMON_NAME)
    return str(common_names[0].value) if common_names else None


def _timezone_aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


if __name__ == "__main__":
    import asyncio
    import sys

    async def _main() -> None:
        certbot_live_dir = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CERTBOT_LIVE_DIR
        nginx_paths = sys.argv[2:] if len(sys.argv) > 2 else []

        certificates = await collect_certificates(
            certbot_live_dir=certbot_live_dir,
            nginx_cert_paths=nginx_paths,
        )

        print(f"found {len(certificates)} certificates\n")
        for certificate in certificates:
            not_after = (
                certificate.not_after.isoformat()
                if certificate.not_after is not None
                else "-"
            )
            print(
                f"{certificate.domain:<30} "
                f"issuer={certificate.issuer or '-':<20} "
                f"expires={not_after} "
                f"source={certificate.source} "
                f"path={certificate.cert_path}"
            )

    asyncio.run(_main())
