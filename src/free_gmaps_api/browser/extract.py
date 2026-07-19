from __future__ import annotations

import re


def extract_coordinates_from_url(url: str) -> tuple[float, float] | None:
    match = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", url)
    if match:
        return float(match.group(1)), float(match.group(2))
    match2 = re.search(r"viewpoint=(-?\d+\.\d+),(-?\d+\.\d+)", url)
    if match2:
        return float(match2.group(1)), float(match2.group(2))
    match3 = re.search(r"ll=(-?\d+\.\d+),(-?\d+\.\d+)", url)
    if match3:
        return float(match3.group(1)), float(match3.group(2))
    match4 = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", url)
    if match4:
        return float(match4.group(1)), float(match4.group(2))
    return None


def extract_zoom_from_url(url: str) -> float | None:
    match = re.search(r"@-?\d+\.\d+,-?\d+\.\d+,(\d+\.?\d*)z", url)
    if match:
        return float(match.group(1))
    match2 = re.search(r"zoom=(\d+)", url)
    if match2:
        return float(match2.group(1))
    return None


def extract_plus_code_from_text(text: str) -> str | None:
    match = re.search(
        r"\b([23456789CFGHJMPQRVWX]{4,8}\+[23456789CFGHJMPQRVWX]{2,3}(?:\s+\w+)?)\b", text
    )
    if match:
        return match.group(1).strip()
    return None


def extract_dms_from_text(text: str) -> str | None:
    match = re.search(
        r"\d{1,3}°\d{1,2}′\d{1,2}(?:\.\d+)?[″\"]?\s*[NS],?\s*\d{1,3}°\d{1,2}′\d{1,2}(?:\.\d+)?[″\"]?\s*[EW]",
        text,
    )
    if match:
        return match.group(0)
    return None


def extract_decimal_coords_from_text(text: str) -> str | None:
    match = re.search(r"(-?\d{1,3}\.\d{4,}),\s*(-?\d{1,3}\.\d{4,})", text)
    if match:
        return match.group(0)
    return None


def extract_orientation_from_url(url: str) -> dict[str, float]:
    result: dict[str, float] = {}
    heading_param = re.search(r"heading=(-?\d+\.?\d*)", url)
    if heading_param:
        result["heading"] = float(heading_param.group(1))
    h = re.search(r",(\d+\.?\d*)h[,/]", url)
    if h and "heading" not in result:
        result["heading"] = float(h.group(1))
    pitch_param = re.search(r"pitch=(-?\d+\.?\d*)", url)
    if pitch_param:
        result["pitch"] = float(pitch_param.group(1))
    t = re.search(r",(-?\d+\.?\d*)t[,/]", url)
    if t and "pitch" not in result:
        result["pitch"] = float(t.group(1))
    fov_param = re.search(r"fov=(\d+\.?\d*)", url)
    if fov_param:
        result["fov"] = float(fov_param.group(1))
    y = re.search(r",(\d+\.?\d*)y[,/]", url)
    if y and "fov" not in result:
        result["fov"] = float(y.group(1))
    return result


def extract_place_url_ids(url: str) -> list[str]:
    hex_ids = re.findall(r"\b0x[0-9a-f]+\b", url)
    if hex_ids:
        return hex_ids
    pid = re.search(r"[?&]place_id=([^&]+)", url)
    if pid:
        return [pid.group(1)]
    return []
