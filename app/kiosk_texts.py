"""Texts the kitchen screen says (greetings, the day's briefing, suggestions): the standard wording and which ones can be edited.

A text may use {placeholders}; a piece in [brackets] is dropped when any placeholder inside it is empty (no weather, no suggestion...).
"""

PLACEHOLDERS = (
    ('nome', 'primeiro nome de quem foi reconhecido'), ('saudacao', 'Bom dia, Boa tarde ou Boa noite'),
    ('data', 'ex.: domingo, 22 de novembro'), ('dia', 'dia da semana'), ('hora', 'ex.: 17:46'),
    ('temperatura', 'ex.: 27°'), ('clima', 'oração pronta, ex.: o céu está limpo'), ('tempo', 'descrição crua, ex.: céu limpo'), ('max', 'máxima do dia'), ('min', 'mínima do dia'),
    ('chuva', 'chance de chuva, ex.: 70%'), ('sugestao', 'a primeira sugestão'), ('sugestoes', 'até duas sugestões'),
)

# (key, group, label, standard text). "a | b" gives variations: one is picked for each greeting, so the screen does not repeat itself.
TEXTS = (
    ('greet_morning', 'Saudação', 'Manhã (5h às 12h)', 'Bom dia, {nome}! | Bom dia, {nome}, que bom te ver! | Olá, {nome}! Bom dia!'),
    ('greet_afternoon', 'Saudação', 'Tarde (12h às 18h)', 'Boa tarde, {nome}! | Oi, {nome}! Boa tarde! | Boa tarde, {nome}, como vai?'),
    ('greet_night', 'Saudação', 'Noite (18h às 5h)', 'Boa noite, {nome}! | Oi, {nome}! Boa noite! | Boa noite, {nome}, que bom te ver!'),
    ('greet_birthday', 'Saudação', 'Aniversário', 'Parabéns, {nome}! Hoje é o seu dia! 🎂 | Feliz aniversário, {nome}! 🎂'),
    ('daily_day', 'Resumo do dia (primeira saudação do dia)', 'Dia normal',
     'Hoje é {data}. [Agora faz {temperatura} e {clima}. A máxima de hoje é {max} e a mínima, {min}.] [{sugestoes}]'),
    ('daily_night', 'Resumo do dia (primeira saudação do dia)', 'Noite (a partir das 18h)',
     'Hoje é {data}. [Agora faz {temperatura} e {clima}. A mínima de hoje é {min}.] [{sugestoes}]'),
    ('daily_rain', 'Resumo do dia (primeira saudação do dia)', 'Chuva',
     'Hoje é {data}. [Agora faz {temperatura} e {clima}.] [Tem {chuva} de chance de chuva.] [{sugestoes}]'),
    ('daily_storm', 'Resumo do dia (primeira saudação do dia)', 'Tempestade',
     'Atenção: há risco de tempestade hoje. [Agora faz {temperatura}.] É melhor ficar em casa e longe das janelas.'),
    ('tip_rain', 'Sugestões (frases completas)', 'Chuva', 'Se for sair, leve o guarda-chuva.'),
    ('tip_hot', 'Sugestões (frases completas)', 'Calor (máxima de 30° ou mais)', 'Beba bastante água e evite o sol do meio-dia.'),
    ('tip_cold', 'Sugestões (frases completas)', 'Frio (mínima de 15° ou menos)', 'Vista um agasalho, está fresquinho.'),
    ('tip_mild', 'Sugestões (frases completas)', 'Tempo bom (de dia)', 'O dia está bom para uma caminhada leve.'),
    ('tip_night', 'Sugestões (frases completas)', 'Noite', 'Tenha uma ótima noite de descanso.'),
    ('tip_none', 'Sugestões (frases completas)', 'Sem previsão do tempo', 'Lembre-se de beber água ao longo do dia.'),
)
KEYS = tuple(key for key, *_ in TEXTS)
DEFAULTS = {key: text for key, _, _, text in TEXTS}
MAX_LENGTH = 240


def effective(settings):
    """The text of every entry: what was written in the settings, or the standard wording when left empty."""
    return {key: (getattr(settings, f'kiosk_text_{key}', '') or '').strip() or DEFAULTS[key] for key in KEYS}
