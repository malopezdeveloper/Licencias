"""Clasificación basada en metadatos explícitos y reglas locales por referencia."""
import re
import xml.etree.ElementTree as ET

UNKNOWN = 'Sin identificar'
EDITIONS = ('Pro', 'Home', 'Pro N', 'Home N', 'Home Single Language', 'Enterprise', 'Enterprise N',
            'Education', 'Education N', 'Pro Education', 'Pro for Workstations', UNKNOWN)
CHANNELS = ('CMAR', 'OEM', 'Retail', 'Volumen MAK', 'Volumen KMS', 'Volumen', UNKNOWN)


def normalize_reference(value):
    return ' '.join(str(value or '').upper().split())[:200]


def edition_from_text(value):
    text = re.sub(r'[^a-z0-9]+', ' ', str(value).casefold()).strip()
    aliases = [('professionalworkstation', 'Pro for Workstations'), ('pro for workstations', 'Pro for Workstations'),
               ('professionaleducation', 'Pro Education'), ('pro education', 'Pro Education'),
               ('coresinglelanguage', 'Home Single Language'), ('home single language', 'Home Single Language'),
               ('professionaln', 'Pro N'), ('pro n', 'Pro N'), ('coren', 'Home N'), ('home n', 'Home N'),
               ('enterprisen', 'Enterprise N'), ('enterprise n', 'Enterprise N'),
               ('educationn', 'Education N'), ('education n', 'Education N'),
               ('professional', 'Pro'), ('pro', 'Pro'), ('core', 'Home'), ('home', 'Home'),
               ('enterprise', 'Enterprise'), ('education', 'Education')]
    for alias, edition in aliases:
        if re.search(r'(?<![a-z0-9])' + re.escape(alias) + r'(?![a-z0-9])', text):
            return edition
    return UNKNOWN


def channel_from_text(value):
    text = re.sub(r'[^a-z0-9]+', ' ', str(value).casefold()).strip()
    if re.search(r'\bcmar\b', text):
        return 'CMAR'
    if re.search(r'\boem\b', text):
        return 'OEM'
    if re.search(r'\bretail\b', text):
        return 'Retail'
    if re.search(r'\bmak\b', text):
        return 'Volumen MAK'
    if re.search(r'\bkms\b', text):
        return 'Volumen KMS'
    if re.search(r'\b(volume|volumen)\b', text):
        return 'Volumen'
    return UNKNOWN


def metadata(xml):
    root = ET.fromstring(xml)
    fields = {}
    for node in root.iter():
        tag = node.tag.split('}')[-1].casefold()
        # No examinar ProductKey, ProductKeyID ni el nombre del archivo para deducir tipo.
        if tag in ('productkeypartnumber', 'productkeystate', 'edition', 'editionid', 'windowsedition',
                   'productname', 'productdescription', 'description', 'channel', 'licensetype', 'licensechannel'):
            fields.setdefault(tag, []).append((node.text or '').strip()[:500])
    reference = normalize_reference(next(iter(fields.get('productkeypartnumber', [])), ''))
    edition_candidates = {edition_from_text(v) for k in ('edition', 'editionid', 'windowsedition', 'productname', 'productdescription') for v in fields.get(k, [])}
    channel_candidates = {channel_from_text(v) for k in ('channel', 'licensetype', 'licensechannel', 'productname', 'productdescription') for v in fields.get(k, [])}
    edition_candidates.discard(UNKNOWN)
    channel_candidates.discard(UNKNOWN)
    # Metadatos contradictorios también requieren revisión, nunca elegir al azar.
    edition = next(iter(edition_candidates)) if len(edition_candidates) == 1 else UNKNOWN
    channel = next(iter(channel_candidates)) if len(channel_candidates) == 1 else UNKNOWN
    return {'reference': reference, 'edition': edition, 'channel': channel,
            'classification_source': 'XML' if edition != UNKNOWN or channel != UNKNOWN else 'Pendiente',
            'xml_state': next(iter(fields.get('productkeystate', [])), '')}
