"""Built-in FX preset constants and filter chain builder."""

from __future__ import annotations

# Built-in FFmpeg audio filter presets.
# Keys are preset names, values are FFmpeg -af filter strings.
BUILTIN_PRESETS: dict[str, str] = {
    "nightcore": "asetrate=48000*1.25,aresample=48000,atempo=1.0",
    "vaporwave": "asetrate=48000*0.8,aresample=48000,atempo=1.0",
    "bassboost": "bass=g=15:f=110:w=0.6",
    "8d": "apulsator=mode=sine:hz=0.125:amount=1",
    "karaoke": "stereotools=mlev=0.03",
    "tremolo": "tremolo=f=6:d=0.5",
    "vibrato": "vibrato=f=7:d=0.5",
    "echo": "aecho=0.8:0.88:60:0.4",
    "earrape": "acrusher=samples=1:bits=8:mix=0.5,volume=8",
    "slowreverb": "asetrate=48000*0.85,aresample=48000,aecho=0.8:0.7:100:0.5",
    "pitchup": "asetrate=48000*1.15,aresample=48000",
    "pitchdown": "asetrate=48000*0.85,aresample=48000",
}

# Presets that show a warning before applying
WARNING_PRESETS: set[str] = {"earrape"}

# Preset descriptions for help/list commands
PRESET_DESCRIPTIONS: dict[str, str] = {
    "nightcore": "Speeds up and raises pitch for a nightcore effect",
    "vaporwave": "Slows down and lowers pitch for a vaporwave/aesthetic effect",
    "bassboost": "Heavy bass boost (+15dB at 110Hz)",
    "8d": "Panning audio between channels for a 3D/8D effect",
    "karaoke": "Reduces center-channel vocals for a karaoke effect",
    "tremolo": "Rapid volume oscillation effect",
    "vibrato": "Rapid pitch oscillation effect",
    "echo": "Adds an echo/delay effect",
    "earrape": "Extreme distortion and volume (WARNING: LOUD!)",
    "slowreverb": "Slowed down with reverb for a dreamy/lofi effect",
    "pitchup": "Raises pitch without changing speed",
    "pitchdown": "Lowers pitch without changing speed",
}


def build_filter_chain(preset_names: list[str], custom_filters: dict[str, str] | None = None) -> str:
    """Build an FFmpeg -af filter string from a list of preset names.

    Args:
        preset_names: List of preset names to chain together.
        custom_filters: Optional dict of custom preset name -> filter string.

    Returns:
        Combined FFmpeg -af filter string with presets joined by commas.

    Raises:
        ValueError: If a preset name is not found.
    """
    all_presets = dict(BUILTIN_PRESETS)
    if custom_filters:
        all_presets.update(custom_filters)

    filters = []
    for name in preset_names:
        name_lower = name.lower()
        if name_lower not in all_presets:
            raise ValueError(f"Unknown preset: {name}")
        filters.append(all_presets[name_lower])

    return ",".join(filters)


def get_all_preset_names(custom_filters: dict[str, str] | None = None) -> list[str]:
    """Get a sorted list of all available preset names (built-in + custom)."""
    names = list(BUILTIN_PRESETS.keys())
    if custom_filters:
        names.extend(custom_filters.keys())
    return sorted(set(names))
