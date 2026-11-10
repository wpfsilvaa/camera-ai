"""Como a casa chama a pessoa acompanhada ("pai", "mãe", "avó"...): termos com o gênero certo para os textos."""
RELATIONS = {'pai': 'm', 'mãe': 'f', 'avô': 'm', 'avó': 'f', 'sogro': 'm', 'sogra': 'f', 'tio': 'm', 'tia': 'f', 'irmão': 'm', 'irmã': 'f', 'marido': 'm', 'esposa': 'f'}
DEFAULT = 'pai'


def normalize(relation) -> str:
    relation = (relation or '').strip().lower()
    return relation if relation in RELATIONS else DEFAULT


def terms(relation=DEFAULT) -> dict:
    """rel='mãe', my='minha', your='sua', the='a', of_the='da', he='ela', Rel='Mãe', label='Minha mãe'..."""
    relation = normalize(relation)
    f = RELATIONS[relation] == 'f'
    my, your = ('minha', 'sua') if f else ('meu', 'seu')
    return {'rel': relation, 'Rel': relation.capitalize(), 'my': my, 'your': your, 'the': 'a' if f else 'o', 'The': 'A' if f else 'O',
            'of_the': 'da' if f else 'do', 'he': 'ela' if f else 'ele', 'label': f'{my.capitalize()} {relation}', 'your_rel': f'{your} {relation}',
            'Your_rel': f'{your.capitalize()} {relation}', 'feminine': f}
