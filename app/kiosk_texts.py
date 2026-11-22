"""Texts the kitchen screen says (greetings, the day's briefing, suggestions): the standard wording and which ones can be edited.

A text may use {placeholders}; a piece in [brackets] is dropped when any placeholder inside it is empty (no weather, no suggestion...).
"""

PLACEHOLDERS = (
    ('nome', 'primeiro nome de quem foi reconhecido'), ('saudacao', 'Bom dia, Boa tarde ou Boa noite'),
    ('data', 'ex.: domingo, 22 de novembro'), ('dia', 'dia da semana'), ('hora', 'ex.: 17:46'),
    ('temperatura', 'ex.: 27°'), ('tempo', 'ex.: ensolarado'), ('max', 'máxima do dia'), ('min', 'mínima do dia'),
    ('chuva', 'chance de chuva, ex.: 70%'), ('sugestao', 'a primeira sugestão'), ('sugestoes', 'até duas sugestões'),
)

# (key, group, label, standard text)
TEXTS = (
    ('greet_morning', 'Saudação', 'Manhã (5h às 12h)', 'Bom dia, {nome}'),
    ('greet_afternoon', 'Saudação', 'Tarde (12h às 18h)', 'Boa tarde, {nome}'),
    ('greet_night', 'Saudação', 'Noite (18h às 5h)', 'Boa noite, {nome}'),
    ('greet_birthday', 'Saudação', 'Aniversário', '🎂 Feliz aniversário, {nome}!'),
    ('daily_day', 'Resumo do dia (primeira saudação do dia)', 'Dia normal',
     'Hoje é {data}. [Agora faz {temperatura} e o tempo está {tempo}. Máxima de {max} e mínima de {min}.] [Sugestão: {sugestoes}.]'),
    ('daily_night', 'Resumo do dia (primeira saudação do dia)', 'Noite (a partir das 18h)',
     'Hoje é {data}. [Agora faz {temperatura} e o tempo está {tempo}. Mínima de {min} esta noite.] [Sugestão: {sugestoes}.]'),
    ('daily_rain', 'Resumo do dia (primeira saudação do dia)', 'Chuva',
     'Hoje é {data}. [Agora faz {temperatura} e o tempo está {tempo}. Máxima de {max} e mínima de {min}.] [Há {chuva} de chance de chuva.] [Sugestão: {sugestoes}.]'),
    ('daily_storm', 'Resumo do dia (primeira saudação do dia)', 'Tempestade',
     'Atenção, {nome}: há risco de tempestade hoje. [Agora faz {temperatura}.] Prefira ficar em casa. [Sugestão: {sugestoes}.]'),
    ('tip_rain', 'Sugestões', 'Chuva ou tempestade', 'leve o guarda-chuva se for sair'),
    ('tip_hot', 'Sugestões', 'Calor (máxima de 30° ou mais)', 'beba bastante água e evite o sol do meio-dia'),
    ('tip_cold', 'Sugestões', 'Frio (mínima de 15° ou menos)', 'vista um agasalho'),
    ('tip_mild', 'Sugestões', 'Tempo bom', 'bom dia para uma caminhada leve'),
    ('tip_none', 'Sugestões', 'Sem previsão do tempo', 'lembre-se de beber água ao longo do dia'),
)
KEYS = tuple(key for key, *_ in TEXTS)
DEFAULTS = {key: text for key, _, _, text in TEXTS}
MAX_LENGTH = 240


def effective(settings):
    """The text of every entry: what was written in the settings, or the standard wording when left empty."""
    return {key: (getattr(settings, f'kiosk_text_{key}', '') or '').strip() or DEFAULTS[key] for key in KEYS}
