"""Structured FX presets plus translators for FFmpeg and Lavalink."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import wavelink

PresetDefinition = dict[str, Any]


def normalize_preset_definition(definition: PresetDefinition | None) -> PresetDefinition:
    """Normalize a preset definition into a stable schema."""
    raw = deepcopy(definition or {})
    normalized: PresetDefinition = {
        "version": 1,
        "volume_multiplier": raw.get("volume_multiplier"),
        "timescale": raw.get("timescale"),
        "tremolo": raw.get("tremolo"),
        "vibrato": raw.get("vibrato"),
        "rotation_hz": raw.get("rotation_hz"),
        "karaoke": raw.get("karaoke"),
        "equalizer": raw.get("equalizer") or [],
        "low_pass": raw.get("low_pass"),
        "distortion": raw.get("distortion"),
        "channel_mix": raw.get("channel_mix"),
        "ffmpeg_only_filters": list(raw.get("ffmpeg_only_filters") or []),
    }
    return normalized


def _preset(
    *,
    volume_multiplier: float | None = None,
    timescale: dict[str, float] | None = None,
    tremolo: dict[str, float] | None = None,
    vibrato: dict[str, float] | None = None,
    rotation_hz: float | None = None,
    karaoke: dict[str, float] | None = None,
    equalizer: list[dict[str, float]] | None = None,
    low_pass: dict[str, float] | None = None,
    distortion: dict[str, float] | None = None,
    channel_mix: dict[str, float] | None = None,
    ffmpeg_only_filters: list[str] | None = None,
) -> PresetDefinition:
    return normalize_preset_definition(
        {
            "version": 1,
            "volume_multiplier": volume_multiplier,
            "timescale": timescale,
            "tremolo": tremolo,
            "vibrato": vibrato,
            "rotation_hz": rotation_hz,
            "karaoke": karaoke,
            "equalizer": equalizer or [],
            "low_pass": low_pass,
            "distortion": distortion,
            "channel_mix": channel_mix,
            "ffmpeg_only_filters": ffmpeg_only_filters or [],
        }
    )


BUILTIN_PRESETS: dict[str, PresetDefinition] = {
    "nightcore": _preset(timescale={"speed": 1.25, "pitch": 1.25, "rate": 1.0}),
    "vaporwave": _preset(timescale={"speed": 0.8, "pitch": 0.8, "rate": 1.0}),
    "bassboost": _preset(equalizer=[{"band": 0, "gain": 0.20}, {"band": 1, "gain": 0.15}]),
    "8d": _preset(rotation_hz=0.125),
    "karaoke": _preset(
        karaoke={"level": 1.0, "mono_level": 1.0, "filter_band": 220.0, "filter_width": 100.0}
    ),
    "tremolo": _preset(tremolo={"frequency": 6.0, "depth": 0.5}),
    "vibrato": _preset(vibrato={"frequency": 7.0, "depth": 0.5}),
    "echo": _preset(ffmpeg_only_filters=["aecho=0.8:0.88:60:0.4"]),
    "earrape": _preset(
        volume_multiplier=5.0,
        distortion={
            "sin_offset": 0.0,
            "sin_scale": 1.0,
            "cos_offset": 0.0,
            "cos_scale": 1.0,
            "tan_offset": 0.0,
            "tan_scale": 1.0,
            "offset": 0.0,
            "scale": 1.0,
        },
        ffmpeg_only_filters=["acrusher=samples=1:bits=8:mix=0.5"],
    ),
    "slowreverb": _preset(
        timescale={"speed": 0.85, "pitch": 0.85, "rate": 1.0},
        ffmpeg_only_filters=["aecho=0.8:0.7:100:0.5"],
    ),
    "pitchup": _preset(timescale={"speed": 1.0, "pitch": 1.15, "rate": 1.0}),
    "pitchdown": _preset(timescale={"speed": 1.0, "pitch": 0.85, "rate": 1.0}),
}

WARNING_PRESETS: set[str] = {"earrape"}

PRESET_DESCRIPTIONS: dict[str, str] = {
    "nightcore": "Speeds up and raises pitch for a nightcore effect",
    "vaporwave": "Slows down and lowers pitch for a vaporwave effect",
    "bassboost": "Heavy bass boost",
    "8d": "Pans audio between channels for a 3D effect",
    "karaoke": "Reduces center-channel vocals",
    "tremolo": "Rapid volume oscillation effect",
    "vibrato": "Rapid pitch oscillation effect",
    "echo": "Adds an echo or delay effect",
    "earrape": "Extreme distortion and volume (WARNING: LOUD!)",
    "slowreverb": "Slowed down with reverb for a dreamy effect",
    "pitchup": "Raises pitch without changing speed",
    "pitchdown": "Lowers pitch without changing speed",
}


def serialize_preset_definition(definition: PresetDefinition) -> str:
    """Serialize a preset definition for persistence."""
    return json.dumps(normalize_preset_definition(definition), separators=(",", ":"), sort_keys=True)


def deserialize_preset_definition(raw: str | None) -> PresetDefinition | None:
    """Deserialize a preset definition from JSON."""
    if not raw:
        return None
    return normalize_preset_definition(json.loads(raw))


def parse_preset_input(raw: str) -> PresetDefinition:
    """Parse JSON preset input from the command layer."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        # Legacy support: allow raw FFmpeg filters and store them in the compatibility layer.
        if raw.strip():
            return _preset(ffmpeg_only_filters=[raw.strip()])
        raise ValueError("Preset data must be valid JSON.") from exc

    if not isinstance(parsed, dict):
        raise ValueError("Preset data must be a JSON object.")

    return normalize_preset_definition(parsed)


def summarize_preset_definition(definition: PresetDefinition) -> str:
    """Summarize a preset definition for embeds."""
    normalized = normalize_preset_definition(definition)
    parts: list[str] = []
    if normalized["timescale"]:
        parts.append("timescale")
    if normalized["equalizer"]:
        parts.append("equalizer")
    if normalized["karaoke"]:
        parts.append("karaoke")
    if normalized["tremolo"]:
        parts.append("tremolo")
    if normalized["vibrato"]:
        parts.append("vibrato")
    if normalized["rotation_hz"] is not None:
        parts.append("rotation")
    if normalized["distortion"]:
        parts.append("distortion")
    if normalized["low_pass"]:
        parts.append("low-pass")
    if normalized["channel_mix"]:
        parts.append("channel-mix")
    if normalized["volume_multiplier"] is not None:
        parts.append(f"volume x{normalized['volume_multiplier']}")
    if normalized["ffmpeg_only_filters"]:
        parts.append("ffmpeg-only")
    return ", ".join(parts) if parts else "no effects"


def combine_preset_definitions(
    preset_names: list[str],
    custom_presets: dict[str, PresetDefinition] | None = None,
) -> PresetDefinition:
    """Combine built-in and custom presets into one normalized definition."""
    combined = normalize_preset_definition({})
    all_presets = dict(BUILTIN_PRESETS)
    if custom_presets:
        all_presets.update({name.lower(): normalize_preset_definition(value) for name, value in custom_presets.items()})

    for name in preset_names:
        key = name.lower()
        if key not in all_presets:
            raise ValueError(f"Unknown preset: {name}")
        _merge_preset(combined, all_presets[key])

    return combined


def _merge_preset(target: PresetDefinition, addition: PresetDefinition) -> None:
    addition = normalize_preset_definition(addition)
    scalar_keys = (
        "volume_multiplier",
        "timescale",
        "tremolo",
        "vibrato",
        "rotation_hz",
        "karaoke",
        "low_pass",
        "distortion",
        "channel_mix",
    )
    for key in scalar_keys:
        if addition.get(key) is not None:
            target[key] = deepcopy(addition[key])

    if addition["equalizer"]:
        target["equalizer"] = deepcopy(addition["equalizer"])

    if addition["ffmpeg_only_filters"]:
        existing = list(target["ffmpeg_only_filters"])
        for item in addition["ffmpeg_only_filters"]:
            if item not in existing:
                existing.append(item)
        target["ffmpeg_only_filters"] = existing


def preset_requires_ffmpeg(definition: PresetDefinition | None) -> bool:
    """Return True when the preset uses FFmpeg-only filters."""
    normalized = normalize_preset_definition(definition)
    return bool(normalized["ffmpeg_only_filters"])


def build_ffmpeg_filter_string(definition: PresetDefinition | None) -> str | None:
    """Translate a structured preset definition into an FFmpeg filter chain."""
    if definition is None:
        return None

    normalized = normalize_preset_definition(definition)
    parts: list[str] = []

    timescale = normalized["timescale"]
    if timescale:
        pitch = timescale.get("pitch", 1.0)
        speed = timescale.get("speed", 1.0)
        rate = timescale.get("rate", 1.0)
        if pitch != 1.0:
            parts.append(f"asetrate=48000*{pitch:.4f}")
            parts.append("aresample=48000")
        if speed != 1.0 or rate != 1.0:
            parts.append(f"atempo={(speed * rate):.4f}")

    equalizer = normalized["equalizer"]
    if equalizer:
        eq_parts = [f"equalizer=f={_band_to_frequency(item['band'])}:width_type=h:width=200:g={item['gain'] * 30:.2f}" for item in equalizer]
        parts.extend(eq_parts)

    karaoke = normalized["karaoke"]
    if karaoke:
        mono_level = karaoke.get("mono_level", 1.0)
        parts.append(f"stereotools=mlev={max(0.0, min(1.0, 1.0 - mono_level)):.2f}")

    tremolo = normalized["tremolo"]
    if tremolo:
        parts.append(f"tremolo=f={tremolo.get('frequency', 2.0):.2f}:d={tremolo.get('depth', 0.5):.2f}")

    vibrato = normalized["vibrato"]
    if vibrato:
        parts.append(f"vibrato=f={vibrato.get('frequency', 2.0):.2f}:d={vibrato.get('depth', 0.5):.2f}")

    rotation_hz = normalized["rotation_hz"]
    if rotation_hz is not None:
        parts.append(f"apulsator=mode=sine:hz={rotation_hz:.3f}:amount=1")

    low_pass = normalized["low_pass"]
    if low_pass:
        parts.append(f"lowpass=f={low_pass.get('smoothing', 20.0) * 100:.2f}")

    distortion = normalized["distortion"]
    if distortion:
        parts.append(
            "acrusher=samples=1:bits=8:mix=0.5"
        )

    channel_mix = normalized["channel_mix"]
    if channel_mix:
        parts.append(
            "pan=stereo|c0="
            f"{channel_mix.get('left_to_left', 1.0):.2f}*c0+{channel_mix.get('right_to_left', 0.0):.2f}*c1|"
            "c1="
            f"{channel_mix.get('left_to_right', 0.0):.2f}*c0+{channel_mix.get('right_to_right', 1.0):.2f}*c1"
        )

    parts.extend(normalized["ffmpeg_only_filters"])

    if normalized["volume_multiplier"] is not None:
        parts.append(f"volume={normalized['volume_multiplier']:.2f}")

    return ",".join(parts) if parts else None


def build_wavelink_filters(definition: PresetDefinition | None) -> wavelink.Filters | None:
    """Translate a structured preset definition into Lavalink filters."""
    if definition is None:
        return None

    normalized = normalize_preset_definition(definition)
    if preset_requires_ffmpeg(normalized):
        return None

    filters = wavelink.Filters()

    if normalized["volume_multiplier"] is not None:
        filters.volume = normalized["volume_multiplier"]

    if normalized["timescale"]:
        filters.timescale.set(**normalized["timescale"])

    if normalized["tremolo"]:
        tremolo = normalized["tremolo"]
        filters.tremolo.set(frequency=tremolo.get("frequency", 2.0), depth=tremolo.get("depth", 0.5))

    if normalized["vibrato"]:
        vibrato = normalized["vibrato"]
        filters.vibrato.set(frequency=vibrato.get("frequency", 2.0), depth=vibrato.get("depth", 0.5))

    if normalized["rotation_hz"] is not None:
        filters.rotation.set(rotation_hz=normalized["rotation_hz"])

    if normalized["karaoke"]:
        filters.karaoke.set(**normalized["karaoke"])

    if normalized["equalizer"]:
        filters.equalizer.set(bands=normalized["equalizer"])

    if normalized["low_pass"]:
        filters.low_pass.set(**normalized["low_pass"])

    if normalized["distortion"]:
        filters.distortion.set(**normalized["distortion"])

    if normalized["channel_mix"]:
        filters.channel_mix.set(**normalized["channel_mix"])

    return filters if filters() else None


def legacy_filter_string_to_definition(filter_string: str | None) -> PresetDefinition | None:
    """Best-effort migration from raw FFmpeg filter strings."""
    if not filter_string:
        return None

    for definition in BUILTIN_PRESETS.values():
        if build_ffmpeg_filter_string(definition) == filter_string:
            return deepcopy(definition)

    return _preset(ffmpeg_only_filters=[filter_string])


def get_all_preset_names(custom_filters: dict[str, PresetDefinition] | None = None) -> list[str]:
    """Get a sorted list of all available preset names (built-in + custom)."""
    names = list(BUILTIN_PRESETS.keys())
    if custom_filters:
        names.extend(custom_filters.keys())
    return sorted(set(names))


def _band_to_frequency(band: int) -> int:
    frequencies = [60, 170, 310, 600, 1000, 3000, 6000, 12000, 14000, 16000, 18000, 20000, 22000, 24000, 26000]
    index = max(0, min(band, len(frequencies) - 1))
    return frequencies[index]
