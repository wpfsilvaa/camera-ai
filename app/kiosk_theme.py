"""How the kitchen screen looks: ready-made palettes, custom colours, text size and which pieces are shown."""

COLORS = ('bg', 'ink', 'call', 'panic', 'accent')   # Background, text, "call the family" button, "I need help" button, highlights (dates, birthdays).
SHOW = ('weather', 'present', 'vigia', 'battery', 'date', 'holidays')
SIZES = ('pequeno', 'normal', 'grande')

# key -> (label, colours). "personalizada" uses the colours written in the settings.
PALETTES = {
    'padrao': ('Padrão (azul escuro)', {'bg': '#0d1519', 'ink': '#f0f6f8', 'call': '#0f6b82', 'panic': '#d6453a', 'accent': '#e6b45e'}),
    'verde': ('Verde calmo', {'bg': '#0e1812', 'ink': '#eef6f0', 'call': '#2f7d55', 'panic': '#d1493c', 'accent': '#d9c27a'}),
    'ambar': ('Âmbar quente', {'bg': '#17110c', 'ink': '#fbf3e8', 'call': '#a85d1a', 'panic': '#c93b34', 'accent': '#f0c36b'}),
    'claro': ('Claro', {'bg': '#f3f6f7', 'ink': '#13232b', 'call': '#0f6b82', 'panic': '#c43a2f', 'accent': '#a86a00'}),
    'contraste': ('Alto contraste', {'bg': '#000000', 'ink': '#ffffff', 'call': '#0b57d0', 'panic': '#d60000', 'accent': '#ffd400'}),
}
DEFAULT_PALETTE = 'padrao'


def effective(settings):
    """What the screen receives: the colours in use (a palette or the custom ones), the text size and what to show."""
    palette = settings.kiosk_palette
    colors = {name: getattr(settings, f'kiosk_color_{name}') for name in COLORS} if palette == 'personalizada' else dict(PALETTES.get(palette, PALETTES[DEFAULT_PALETTE])[1])
    return {'palette': palette, 'colors': colors, 'size': settings.kiosk_text_size, 'show': {name: bool(getattr(settings, f'kiosk_show_{name}')) for name in SHOW}}
