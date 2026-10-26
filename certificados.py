"""CA local y certificado HTTPS para un nombre DNS o una IP."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import ipaddress
import os
import uuid


def generate(directory, hostname):
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    except ImportError:
        raise RuntimeError('Instale las dependencias: python -m pip install -r requirements.txt') from None
    hostname = hostname.strip()
    if not hostname or any(ch in hostname for ch in '/\\:*?"<>|') and ':' not in hostname:
        raise ValueError('Nombre de servidor no válido.')
    try:
        san = x509.IPAddress(ipaddress.ip_address(hostname))
    except ValueError:
        san = x509.DNSName(hostname.encode('idna').decode('ascii'))
    folder = Path(directory) / ('tls_' + uuid.uuid4().hex[:12])
    folder.mkdir(parents=True)
    moment = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'PULSIA Licencias CA ' + uuid.uuid4().hex[:8])])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(moment - timedelta(minutes=5)).not_valid_after(moment + timedelta(days=3650))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
                                      data_encipherment=False, key_agreement=False, key_cert_sign=True,
                                      crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
          .sign(ca_key, hashes.SHA256()))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)]))
            .issuer_name(ca.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(moment - timedelta(minutes=5)).not_valid_after(moment + timedelta(days=825))
            .add_extension(x509.SubjectAlternativeName([san]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    files = {'cert': folder / 'servidor.crt', 'key': folder / 'servidor.key', 'ca': folder / 'ca.pem'}
    files['cert'].write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    files['ca'].write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    files['key'].write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
    files['key'].chmod(0o600)
    # No se necesita guardar la clave privada de la CA para este certificado.
    return {k: str(v.resolve()) for k, v in files.items()}
