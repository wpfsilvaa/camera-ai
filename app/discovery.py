"""Descoberta de totens (notebooks da cozinha) na rede local, e pareamento por código mostrado na tela do totem."""
import ipaddress
import json
import logging
import os
import secrets
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor

import httpx

log = logging.getLogger(__name__)
PORT = int(os.environ.get('CASA_TOTEM_PORT', '8765'))   # porta do monitor do totem
SERVICE = 'casa-presente-totem'
MAX_HOSTS = 1024   # Limite por varredura: redes grandes (/16) não são varridas inteiras.
SKIP_PREFIXES = ('lo', 'docker', 'br-', 'veth', 'virbr', 'tailscale', 'tun', 'wg', 'zt')


def local_networks():
    """Redes IPv4 privadas das interfaces físicas deste computador (cada uma limitada a /22, no máximo)."""
    found = []
    try:
        out = subprocess.run(['ip', '-4', '-o', 'addr', 'show', 'scope', 'global'], capture_output=True, text=True, timeout=3).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 4 or parts[1].startswith(SKIP_PREFIXES):
                continue
            found.append(ipaddress.ip_interface(parts[3]))
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    if not found:   # Sem o comando `ip`: descobre o endereço usado para sair para a rede.
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.connect(('192.0.2.1', 9))
                found.append(ipaddress.ip_interface(f'{probe.getsockname()[0]}/24'))
        except OSError:
            pass
    networks = []
    for interface in found:
        if not interface.ip.is_private:
            continue
        network = interface.network if interface.network.prefixlen >= 22 else ipaddress.ip_network(f'{interface.ip}/22', strict=False)
        if network not in networks:
            networks.append(network)
    return networks


def is_allowed_host(ip):
    """Só endereços da rede local: o painel nunca envia pedidos para a internet por este caminho."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return address.version == 4 and address.is_private and not (address.is_unspecified or address.is_multicast or address.is_link_local)


def probe(ip, token='', timeout=.7, client=None):
    """O totem em ip:8765, se houver: {'ip','name','paired','mine','build'}."""
    owner = client or httpx.Client(timeout=timeout)
    try:
        data = owner.get(f'http://{ip}:{PORT}/hello').json()
        if data.get('service') != SERVICE:
            return None
        mine = False
        if data.get('paired') and token:
            mine = owner.get(f'http://{ip}:{PORT}/status', headers={'Authorization': f'Bearer {token}'}).status_code == 200
        return {'ip': ip, 'name': str(data.get('name', ''))[:60], 'paired': bool(data.get('paired')), 'mine': mine, 'build': str(data.get('build', ''))[:40]}
    except (httpx.HTTPError, ValueError, OSError):
        return None
    finally:
        if client is None:
            owner.close()


def scan(token='', networks=None, timeout=.7, workers=64):
    """Procura totens: este computador (127.0.0.1) e todos os endereços das redes locais."""
    hosts = ['127.0.0.1']
    for network in networks if networks is not None else local_networks():
        hosts.extend(str(h) for h in list(network.hosts())[:MAX_HOSTS])
    hosts = list(dict.fromkeys(hosts))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = [r for r in pool.map(lambda ip: probe(ip, token, timeout), hosts) if r]
    return sorted(results, key=lambda r: (not r['mine'], r['paired'], r['ip']))


def pair(ip, code, token, timeout=5):
    """Entrega o token ao totem, que só aceita se o código da tela dele estiver certo. Levanta ValueError com a mensagem para o usuário."""
    if not is_allowed_host(ip):
        raise ValueError('Endereço inválido: só totens da rede local podem ser pareados.')
    code = ''.join(ch for ch in str(code) if ch.isdigit())
    if len(code) != 6:
        raise ValueError('Digite o código de 6 dígitos que aparece na tela do totem.')
    try:
        response = httpx.post(f'http://{ip}:{PORT}/pair', json={'code': code, 'token': token}, timeout=timeout)
    except httpx.HTTPError:
        raise ValueError('Não foi possível falar com o totem. Confira se ele está ligado e na mesma rede.') from None
    if response.status_code == 200:
        return True
    try:
        detail = response.json().get('error', '')
    except (ValueError, json.JSONDecodeError):
        detail = ''
    raise ValueError(detail or 'O totem recusou o pareamento.')


def new_token():
    return secrets.token_urlsafe(32)
