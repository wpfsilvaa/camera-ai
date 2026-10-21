"""One place that answers "is the system all right?": every component with a level (ok / warn / error / info) and what to do about it."""
import time

LEVELS = ('ok', 'info', 'warn', 'error')
RANK = {level: index for index, level in enumerate(LEVELS)}
SYSTEM_ALERTS = ('camera_offline', 'camera_online', 'backup', 'notebook_battery', 'notebook_unplugged', 'notebook_power_back', 'notebook_offline', 'notebook_online')


def item(key, title, level, detail, hint=''):
    return {'key': key, 'title': title, 'level': level, 'detail': detail, 'hint': hint}


def power_limits(resources, battery_plugged=None):
    """Why the processor may be running slower than it can: a list of short reasons (empty when it is not held back)."""
    reasons = []
    if not resources:
        return reasons
    if resources.get('power_profile') == 'power-saver':
        reasons.append('o modo de economia de energia está ligado')
    power = resources.get('cpu_power')
    if power and power['max']:
        if power['cap'] < .9 * power['max']:
            reasons.append(f"o processador está limitado a {power['cap']} MHz (o máximo é {power['max']} MHz)")
        elif power['cur'] < .7 * power['max'] and resources.get('cpu', 0) > 60:
            reasons.append(f"o processador está trabalhando a {power['cur']} MHz de {power['max']} MHz, mesmo ocupado (economia de energia ou calor)")
    if battery_plugged is False and not reasons:
        reasons.append('o computador está na bateria')
    return reasons


def cameras_items(snapshots, limits=()):
    out = []
    for camera in snapshots:
        title = f"Câmera {camera['name']}"
        if not camera['enabled']:
            out.append(item(f"camera-{camera['id']}", title, 'info', 'Pausada.', 'Inicie a câmera na visão geral quando quiser.'))
        elif camera['state'] == 'online':
            slow = camera.get('analysis_active') and (camera.get('fps') or 0) < 4
            detail = f"{camera.get('fps') or 0} quadros/s · análise {'ativa' if camera.get('analysis_active') else 'pausada'}"
            if camera.get('analysis_active') and camera.get('inference_ms'):
                detail += f" · cada detecção leva {round(camera['inference_ms'])} ms" + (f" ({camera['detector']})" if camera.get('detector') else '')
            if slow and limits:
                hint = f"Provável causa: {limits[0]}. Mude para o perfil Equilibrado ou Desempenho (ou ligue na tomada)."
            else:
                hint = 'O processador não está dando conta. Reduza a taxa de análise ou o tamanho da detecção.' if slow else ''
            out.append(item(f"camera-{camera['id']}", title, 'warn' if slow else 'ok', detail + (' · lenta' if slow else ''), hint))
        elif camera['state'] == 'connecting':
            out.append(item(f"camera-{camera['id']}", title, 'warn', 'Conectando…', 'Se demorar, confira o cabo, o endereço e a energia da câmera.'))
        else:
            out.append(item(f"camera-{camera['id']}", title, 'error', camera.get('error') or 'Sem imagem.', 'Confira a câmera e a rede. O sistema tenta reconectar sozinho.'))
    return out


def evaluate(data, now=None):
    """`data`: cameras, whatsapp, notebook, disk_free_gb, min_free_gb, resources, backup, backup_enabled, whatsapp_enabled,
    recognition, failed_clips, processing_clips, failed_deliveries, alerts, uptime."""
    now = now or time.time()
    limits = power_limits(data.get('resources'), (data['notebook'].get('plugged') if data['notebook'].get('state') in ('ok', 'battery') else None))
    items = cameras_items(data['cameras'], limits)

    whatsapp = data['whatsapp'].get('state')
    if whatsapp == 'connected':
        items.append(item('whatsapp', 'WhatsApp', 'ok', 'Conectado.'))
    elif data.get('whatsapp_enabled'):
        items.append(item('whatsapp', 'WhatsApp', 'error', 'Desconectado: os avisos e vídeos não estão saindo.' if whatsapp != 'unavailable' else 'Serviço do WhatsApp parado.',
                          'Em Configurações, reconecte o WhatsApp escaneando o código.' if whatsapp != 'unavailable' else 'Reinicie o serviço no computador.'))
    else:
        items.append(item('whatsapp', 'WhatsApp', 'info', 'Envios desligados nas configurações.'))

    notebook = data['notebook']
    state = notebook.get('state')
    if state == 'ok':
        plugged = 'na tomada' if notebook.get('plugged') else 'na bateria'
        items.append(item('notebook', 'Tela da cozinha', 'ok', f"Funcionando · bateria {notebook.get('battery')}% {plugged}."))
    elif state == 'battery':
        items.append(item('notebook', 'Tela da cozinha', 'warn', f"Sem energia, na bateria ({notebook.get('battery')}%).", 'Confira a tomada do notebook.'))
    elif state == 'offline':
        items.append(item('notebook', 'Tela da cozinha', 'error', 'Sem sinal do notebook.', 'Veja se ele está ligado e conectado ao wi-fi.'))
    else:
        items.append(item('notebook', 'Tela da cozinha', 'info', 'Monitoramento do notebook desligado.'))

    free, minimum = data['disk_free_gb'], data['min_free_gb']
    items.append(item('disk', 'Espaço em disco', 'error' if free < minimum else 'warn' if free < minimum * 3 else 'ok', f'{free} GB livres.',
                      'As gravações param abaixo do mínimo. Libere espaço em Configurações → Armazenamento.' if free < minimum * 3 else ''))

    resources = data.get('resources')
    if resources:
        problems = []
        level = 'ok'
        if resources.get('temp') is not None and resources['temp'] >= 75:
            problems.append(f"{resources['temp']:.0f} °C"); level = 'error' if resources['temp'] >= 85 else 'warn'
        memory = 100 * resources['mem_used'] / resources['mem_total']
        if memory > 80:
            problems.append(f'memória {memory:.0f}%'); level = 'error' if memory > 92 else max(level, 'warn', key=RANK.get)
        cpu = resources.get('cpu')   # The very first reading after a start has no CPU figure yet.
        if cpu is not None and cpu > 85:
            problems.append(f'CPU {cpu:.0f}%'); level = max(level, 'warn', key=RANK.get)
        if limits and level == 'ok':
            level = 'warn'
        text = ' · '.join(problems) if problems else (f'CPU {cpu:.0f}% · ' if cpu is not None else '') + f'memória {memory:.0f}%' + (f" · {resources['temp']:.0f} °C" if resources.get('temp') is not None else '')
        if limits:
            joined = '; '.join(limits)
            text += f' · {joined[0].upper()}{joined[1:]}'
        hint = ('Mude o perfil de energia para Equilibrado ou Desempenho (no notebook: powerprofilesctl set balanced).' if limits
                else 'Reduza a carga (menos análise por segundo, desligue o reconhecimento por corpo) ou melhore a ventilação.' if problems else '')
        items.append(item('resources', 'Computador', level, text, hint))

    if not data.get('backup_enabled'):
        items.append(item('backup', 'Backup', 'info', 'Desligado.', 'Ligue em Configurações para proteger o histórico e as pessoas cadastradas.'))
    else:
        backup = data.get('backup') or {}
        last = backup.get('last_ok')
        if backup.get('last_error') and (not last or backup.get('last_error_at', 0) >= last):
            items.append(item('backup', 'Backup', 'error', f"Falhou: {backup['last_error']}", 'Confira se o HD externo está conectado.'))
        elif last and now - last < 2 * 86400:
            items.append(item('backup', 'Backup', 'ok', 'Feito nas últimas 48 horas.'))
        else:
            items.append(item('backup', 'Backup', 'warn', 'Nenhum backup nas últimas 48 horas.', 'Confira o HD externo e o horário configurado.'))

    recognition = data['recognition']
    if recognition.get('error'):
        items.append(item('recognition', 'Reconhecimento facial', 'error', recognition['error'], 'Reinicie o sistema; se persistir, rode scripts/download_models.py.'))
    else:
        items.append(item('recognition', 'Reconhecimento facial', 'ok' if recognition.get('ready') else 'info', 'Pronto.' if recognition.get('ready') else 'Será iniciado com a câmera.'))

    failed, processing, deliveries = data['failed_clips'], data['processing_clips'], data['failed_deliveries']
    if failed or deliveries or processing > 5:
        parts = ([f'{failed} vídeo(s) não convertido(s)'] if failed else []) + ([f'{deliveries} envio(s) falharam'] if deliveries else []) + ([f'{processing} na fila'] if processing > 5 else [])
        items.append(item('videos', 'Vídeos', 'warn', ' · '.join(parts) + ' nas últimas 24 h.', 'Abra o histórico e tente novamente os que falharam.'))
    else:
        items.append(item('videos', 'Vídeos', 'ok', 'Sem pendências.'))

    level = max((i['level'] for i in items), key=RANK.get)
    counts = {name: sum(1 for i in items if i['level'] == name) for name in LEVELS}
    summary = {'ok': 'Tudo certo.', 'info': 'Tudo certo.', 'warn': f"{counts['warn']} aviso(s).", 'error': f"{counts['error']} problema(s)" + (f" e {counts['warn']} aviso(s)." if counts['warn'] else '.')}[level]
    return {'level': level, 'summary': summary, 'counts': counts, 'items': sorted(items, key=lambda i: -RANK[i['level']]), 'uptime': data.get('uptime'), 'alerts': data.get('alerts', [])}
