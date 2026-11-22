"""The tiles of the kitchen screen's board (calendar, analogue clock, phrase of the day, photo, next medicine): which ones, in which order."""
import re

IDS = ('calendar', 'clock', 'quote', 'photo', 'medication')
LABELS = {'calendar': 'Calendário', 'clock': 'Relógio analógico', 'quote': 'Frase do dia', 'photo': 'Foto da família', 'medication': 'Próximo remédio'}
DEFAULT_ORDER = 'calendar,-clock,-quote,-photo,-medication'   # "-" in front = off.
MAX_QUOTES, MAX_MEDS, QUOTE_LENGTH, MED_LENGTH = 40, 20, 160, 80
MED_LINE = re.compile(r'^\s*([01]?\d|2[0-3]):([0-5]\d)\s+(\S.*)$')

DEFAULT_QUOTES = (
    'Um dia de cada vez.', 'Hoje é um bom dia para sorrir.', 'Quem tem amigos tem tesouros.', 'A calma também é uma força.',
    'Pequenos passos levam longe.', 'Cuidar de si é um ato de carinho.', 'Todo dia traz uma nova chance.', 'A gratidão torna o dia mais leve.',
    'Um café e uma boa conversa resolvem muita coisa.', 'Respire fundo: tudo vai ficar bem.', 'A família é o nosso porto seguro.',
    'Hoje vale a pena ser gentil.', 'Quem planta carinho colhe alegria.', 'A paciência é amiga da saúde.', 'Beba água e sorria.',
    'Cada manhã é um presente.', 'O que importa é estar junto.', 'Caminhar um pouco faz bem ao corpo e à alma.', 'Boas lembranças aquecem o coração.',
    'Descansar também é produtivo.', 'A vida é feita de bons momentos simples.', 'Hoje, escolha a leveza.', 'Sorrir é o melhor remédio.',
    'Nunca é tarde para recomeçar.', 'Você é muito querido por aqui.', 'Faça algo de que goste hoje.', 'A sabedoria vem com o tempo.',
    'Um abraço conserta o dia.', 'Tudo tem o seu tempo.', 'Seja bem-vindo a mais um dia.',
)


def normalize(text):
    """'calendar,-clock,quote' -> a full list: every tile once, in the given order, the missing ones switched off at the end."""
    seen, out = set(), []
    for part in str(text or '').split(','):
        part = part.strip()
        name = part.lstrip('-')
        if name in IDS and name not in seen:
            seen.add(name)
            out.append(('-' if part.startswith('-') else '') + name)
    out += [f'-{name}' for name in IDS if name not in seen]
    return ','.join(out)


def order(text, calendar_on=True):
    """The tiles that are on, in order. The calendar is on or off only by its own switch ("Mostrar o calendário"); the list gives its place."""
    return [part.lstrip('-') for part in normalize(text).split(',') if (calendar_on if part.lstrip('-') == 'calendar' else not part.startswith('-'))]


def clean_lines(lines, limit, length):
    return [str(line).strip()[:length] for line in (lines or []) if str(line).strip()][:limit]


def effective(settings):
    """What the screen receives: the tiles on (in order), the phrases (the standard ones when none was written) and the medicine times."""
    return {'order': order(settings.kiosk_widgets, settings.kiosk_calendar_enabled),
            'quotes': clean_lines(settings.kiosk_quotes, MAX_QUOTES, QUOTE_LENGTH) or list(DEFAULT_QUOTES),
            'meds': [line for line in clean_lines(settings.kiosk_medications, MAX_MEDS, MED_LENGTH) if MED_LINE.match(line)]}
