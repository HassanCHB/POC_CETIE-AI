"""
cabinet_sizing.py
─────────────────
Cabinet sizing simulation for CETIE AI Configurator.

Given electrical parameters, estimates the required cabinet surface areas
and compares against standard CETIE enclosure catalogue.

Usage (standalone test):
  python3 poc/cabinet_sizing.py
"""

import math


# ─── Component footprint database (estimated DIN-rail modules or cm² on chassis) ──
# Source: CETIE engineering standard values / manufacturer datasheets

# Modules = number of 9mm DIN-rail modules
COMPONENT_MODULES = {
    # General breakers / disconnects
    "interrupteur_general_1p":   3,
    "interrupteur_general_3p":   4,
    "interrupteur_general_4p":   5,

    # Motor starters (per motor)
    "disjoncteur_moteur_16a":    4,    # GV2 or equivalent
    "disjoncteur_moteur_40a":    5,
    "disjoncteur_moteur_63a":    8,
    "contacteur_9a":             3,
    "contacteur_16a":            3,
    "contacteur_25a":            4,
    "relais_thermique":          2,
    "bloc_disjoncteur_contacteur": 6,  # combined (disjo + contact in 1 block)

    # VFD (variateur) — footprint in cm²; included in chassis calc separately
    "variateur_2_2kw":   200,   # ~0.22m² chassis depth but flat: approx 150×200mm face
    "variateur_7_5kw":   350,
    "variateur_15kw":    500,
    "variateur_22kw":    700,
    "variateur_30kw":    900,
    "variateur_45kw":   1100,
    "variateur_75kw":   1500,

    # Soft starters
    "demarreur_progressif_7a":   6,
    "demarreur_progressif_25a":  8,
    "demarreur_progressif_60a": 12,

    # Control / automation
    "alimentation_24vdc":        4,
    "relais_control":            2,
    "plc_compact_m221":          6,
    "plc_compact_m241":          8,
    "plc_modular_350_cpu":      10,
    "plc_siemens_1212c":         6,
    "plc_siemens_1214c":         8,
    "carte_entrees_16":          4,
    "carte_sorties_16":          4,
    "carte_io_mixte":            4,

    # Sensors / instruments
    "relais_niveau":             4,
    "capteur_courant":           2,
    "voltmetre":                 2,
    "ampermetre":                2,

    # Terminal blocks (per group of 10)
    "bornier_group_10":          3,

    # Transformers
    "transfo_100va":             6,
    "transfo_500va":             8,
    "transfo_1kva":             12,
}

# DIN rail specs
MODULES_PER_RAIL    = 40    # typical 35mm DIN rail at 1m holds ~40 modules
RAIL_PITCH_MM       = 60    # vertical pitch between DIN rails (mm)
CABLE_DUCT_WIDTH_MM = 80    # horizontal cable duct width (mm)

# Cabinet dimension catalogue (CETIE standard): {model: (width_mm, height_mm, depth_mm)}
CETIE_CABINET_CATALOGUE = {
    "Coffret polyester 400×300×200":  (400,  300, 200),
    "Coffret polyester 500×400×200":  (500,  400, 200),
    "Coffret polyester 600×400×200":  (600,  400, 200),
    "Coffret polyester 800×600×300":  (800,  600, 300),
    "Armoire 600×400×250":            (600,  400, 250),
    "Armoire 800×600×300":            (800,  600, 300),
    "Armoire 1000×800×300":          (1000,  800, 300),
    "Armoire 1200×800×300":          (1200,  800, 300),
    "Armoire 1400×800×400":          (1400,  800, 400),
    "Armoire 1600×800×400":          (1600,  800, 400),
    "Armoire 1800×800×400":          (1800,  800, 400),
    "Armoire 2000×800×400":          (2000,  800, 400),
}

# Usable chassis fractions (accounts for frame, hinges, cable entry)
CHASSIS_USABLE_FRACTION = 0.80   # 80% of internal width × height
DOOR_USABLE_FRACTION    = 0.65   # 65% of door panel area
SPARE_RESERVE           = 0.20   # 20% spare space target


# ─── VFD footprint estimator ───────────────────────────────────────────────────

def vfd_footprint_cm2(power_kw: float, has_filter: bool = False) -> float:
    """Estimate VFD chassis footprint in cm²."""
    # Rough sizing: W×H face area based on power
    if power_kw <= 2.2:
        w, h = 12, 16
    elif power_kw <= 4.0:
        w, h = 14, 20
    elif power_kw <= 7.5:
        w, h = 16, 24
    elif power_kw <= 15.0:
        w, h = 20, 30
    elif power_kw <= 22.0:
        w, h = 24, 38
    elif power_kw <= 37.0:
        w, h = 30, 50
    elif power_kw <= 55.0:
        w, h = 36, 58
    else:
        w, h = 45, 70
    footprint = w * h  # cm²
    if has_filter:
        footprint *= 1.4   # filter adds ~40% height
    return round(footprint, 1)


# ─── Terminal block estimator ──────────────────────────────────────────────────

def terminal_block_length_mm(
    nb_motors: int,
    has_plc: bool,
    nb_io: int,
    supply_current_a: float,
) -> float:
    """Estimate required terminal block DIN rail length in mm."""
    # Power terminals (3-phase per motor + PE + neutral)
    terminals_power = nb_motors * 5
    # Control terminals (start/stop signals, status, emergency stop)
    terminals_control = 10 + nb_motors * 4
    # PLC I/O connections (2 terminals per I/O point)
    terminals_io = nb_io * 2 if has_plc else 0
    # Common bus terminals (3P + N + PE for supply)
    terminals_supply = 10

    total_terminals = terminals_power + terminals_control + terminals_io + terminals_supply + 10  # spare

    # 6mm pitch per terminal for up to 25A, 10mm for higher current
    pitch_mm = 10 if supply_current_a > 25 else 6
    return round(total_terminals * pitch_mm, 0)


# ─── Main calculation ──────────────────────────────────────────────────────────

def calculate_cabinet_sizing(
    supply_current_a: float,
    motor_feeders: list[dict],      # [{current_a: float, type: 'direct'|'vfd'|'soft'}]
    drives: list[dict],             # [{power_kw: float, has_filter: bool}]
    plc_type,                       # str or None: 'M221'|'M241'|'S7-1212C'|'S7-1214C'|None
    nb_io: int,
    nb_extra_modules: int = 0,      # extra DIN-rail modules (relays, PSU, etc.)
) -> dict:
    """
    Calculate required cabinet dimensions based on electrical parameters.

    Returns a dict with:
      - din_rail_modules_required: total modules needed on DIN rails
      - din_rail_length_mm: total DIN rail length
      - chassis_area_required_cm2: required chassis panel area
      - vfd_area_cm2: VFD footprint (on chassis or separate plate)
      - terminal_block_length_mm: terminal block DIN rail length
      - door_area_required_cm2: required door panel area
      - cable_duct_area_cm2: cable duct footprint
      - total_chassis_cm2: sum of all chassis requirements
      - recommended_cabinets: list of suitable cabinets sorted by size
      - smallest_fit: first cabinet that fits with ≥20% spare
    """
    has_plc = plc_type is not None

    # 1. DIN-rail modules for protection & control
    modules = 0

    # Main disconnect (interrupteur général)
    if supply_current_a <= 25:
        modules += COMPONENT_MODULES["interrupteur_general_3p"]
    elif supply_current_a <= 63:
        modules += COMPONENT_MODULES["interrupteur_general_4p"]
    else:
        modules += 10   # heavy-duty disconnector

    # Power distribution (répartiteur)
    modules += 4 if len(motor_feeders) > 1 else 0

    # Motor feeders
    for feeder in motor_feeders:
        ia = feeder.get("current_a", 10)
        ftype = feeder.get("type", "direct")
        if ftype in ("direct", "soft"):
            if ia <= 18:
                modules += COMPONENT_MODULES["disjoncteur_moteur_16a"]
                modules += COMPONENT_MODULES["contacteur_16a"]
            elif ia <= 40:
                modules += COMPONENT_MODULES["disjoncteur_moteur_40a"]
                modules += COMPONENT_MODULES["contacteur_25a"]
            else:
                modules += COMPONENT_MODULES["disjoncteur_moteur_63a"]
                modules += COMPONENT_MODULES["contacteur_25a"]
            if ftype == "soft":
                # soft-starter replaces contacteur with larger module
                if ia <= 7:
                    modules += COMPONENT_MODULES["demarreur_progressif_7a"]
                elif ia <= 25:
                    modules += COMPONENT_MODULES["demarreur_progressif_25a"]
                else:
                    modules += COMPONENT_MODULES["demarreur_progressif_60a"]
        # VFDs are on chassis, not DIN rail (handled separately)

    # Soft-starter: add to DIN rail if chosen
    for feeder in motor_feeders:
        if feeder.get("type") == "soft":
            ia = feeder.get("current_a", 10)

    # PLC / automation
    if plc_type:
        plc_key = {
            "M221": "plc_compact_m221",
            "M241": "plc_compact_m241",
            "S7-1212C": "plc_siemens_1212c",
            "S7-1214C": "plc_siemens_1214c",
        }.get(plc_type, "plc_compact_m221")
        modules += COMPONENT_MODULES.get(plc_key, 8)

        # I/O cards (one per 16 I/O)
        nb_io_cards = math.ceil(nb_io / 16) if nb_io > 8 else 0
        modules += nb_io_cards * COMPONENT_MODULES["carte_io_mixte"]

    # 24V PSU
    modules += COMPONENT_MODULES["alimentation_24vdc"]

    # Emergency stop relay
    modules += 2

    # Extra modules (relays, timers, etc.)
    modules += nb_extra_modules

    # DIN rail layout: estimate number of rails needed
    nb_rails = math.ceil(modules / MODULES_PER_RAIL)
    din_rail_length_mm = nb_rails * 1000  # 1m rails

    # 2. VFD area (on chassis or separate mounting plate)
    vfd_area_cm2 = sum(
        vfd_footprint_cm2(d.get("power_kw", 1.5), d.get("has_filter", False))
        for d in drives
    )

    # 3. Chassis area required
    # DIN rail area: each rail takes 60mm pitch × 1000mm width = 60×1000mm² / 100 = 600cm²
    # Formula: nb_rails × (RAIL_PITCH_MM/10 cm) × (1000mm/10 → 100cm) = nb_rails × RAIL_PITCH_MM × 10
    din_rail_area_cm2 = nb_rails * RAIL_PITCH_MM * 10   # e.g. 2×60×10 = 1200 cm²
    # Cable duct: 80mm × 1000mm per rail = 8000mm²/100 = 80cm² per 100mm → 800cm² per 1m duct
    cable_duct_area_cm2 = nb_rails * CABLE_DUCT_WIDTH_MM * 10   # e.g. 2×80×10 = 1600 cm²

    chassis_area_required_cm2 = din_rail_area_cm2 + vfd_area_cm2 + cable_duct_area_cm2

    # 4. Terminal blocks
    tb_length_mm = terminal_block_length_mm(len(motor_feeders), has_plc, nb_io, supply_current_a)

    # 5. Door area (instruments, HMI, pushbuttons)
    # Typical: 3 pushbuttons/indicators per motor + emergency stop + main selector
    door_modules_per_motor = 4   # start, stop, running indicator, fault indicator
    door_items = len(motor_feeders) * door_modules_per_motor + 4   # +4 for global controls
    # Each door component ≈ 50cm² (22.5mm cutout)
    door_area_required_cm2 = door_items * 50

    total_chassis_cm2 = chassis_area_required_cm2
    total_required_with_reserve_cm2 = total_chassis_cm2 * (1 + SPARE_RESERVE)

    # 6. Find suitable cabinets
    recommended = []
    for model, (w_mm, h_mm, d_mm) in CETIE_CABINET_CATALOGUE.items():
        chassis_available_cm2 = (w_mm * h_mm * CHASSIS_USABLE_FRACTION) / 100  # mm² → cm²
        door_available_cm2    = (w_mm * h_mm * DOOR_USABLE_FRACTION) / 100

        if chassis_available_cm2 >= total_required_with_reserve_cm2:
            spare_pct = (chassis_available_cm2 - chassis_area_required_cm2) / chassis_area_required_cm2
            recommended.append({
                "model":                    model,
                "dimensions_mm":            {"width": w_mm, "height": h_mm, "depth": d_mm},
                "chassis_available_cm2":    round(chassis_available_cm2, 0),
                "door_available_cm2":       round(door_available_cm2, 0),
                "spare_percentage":         round(spare_pct * 100, 1),
                "fits":                     True,
            })

    recommended.sort(key=lambda c: c["chassis_available_cm2"])
    smallest_fit = recommended[0] if recommended else None

    # If nothing fits, return the largest available with a warning
    if not recommended:
        model, (w, h, d) = list(CETIE_CABINET_CATALOGUE.items())[-1]
        smallest_fit = {
            "model": model,
            "dimensions_mm": {"width": w, "height": h, "depth": d},
            "chassis_available_cm2": round(w * h * CHASSIS_USABLE_FRACTION / 100, 0),
            "door_available_cm2":    round(w * h * DOOR_USABLE_FRACTION / 100, 0),
            "spare_percentage": -1,
            "fits": False,
            "warning": "Largest standard cabinet may be insufficient. Consider custom or multi-cabinet solution.",
        }

    return {
        "inputs": {
            "supply_current_a":   supply_current_a,
            "nb_motor_feeders":   len(motor_feeders),
            "nb_drives":          len(drives),
            "plc_type":           plc_type,
            "nb_io":              nb_io,
            "nb_extra_modules":   nb_extra_modules,
        },
        "din_rail_modules_required": modules,
        "nb_din_rails":              nb_rails,
        "din_rail_length_mm":        din_rail_length_mm,
        "chassis_area_required_cm2": round(chassis_area_required_cm2, 0),
        "chassis_with_20pct_spare_cm2": round(total_required_with_reserve_cm2, 0),
        "vfd_area_cm2":              round(vfd_area_cm2, 0),
        "din_rail_area_cm2":         round(din_rail_area_cm2, 0),
        "cable_duct_area_cm2":       round(cable_duct_area_cm2, 0),
        "terminal_block_length_mm":  tb_length_mm,
        "door_area_required_cm2":    round(door_area_required_cm2, 0),
        "recommended_cabinets":      recommended[:5],
        "smallest_fit":              smallest_fit,
    }


# ─── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== CETIE Cabinet Sizing Simulation ===\n")
    result = calculate_cabinet_sizing(
        supply_current_a=63,
        motor_feeders=[
            {"current_a": 14, "type": "direct"},
            {"current_a": 14, "type": "direct"},
        ],
        drives=[],
        plc_type="M221",
        nb_io=16,
        nb_extra_modules=4,
    )

    print(f"Inputs:          {result['inputs']}")
    print(f"DIN rail modules: {result['din_rail_modules_required']} ({result['nb_din_rails']} rails × 1m)")
    print(f"Chassis needed:  {result['chassis_area_required_cm2']} cm² ({result['chassis_with_20pct_spare_cm2']} cm² with 20% spare)")
    print(f"VFD area:        {result['vfd_area_cm2']} cm²")
    print(f"Terminal blocks: {result['terminal_block_length_mm']} mm")
    print(f"Door area:       {result['door_area_required_cm2']} cm²")
    print()
    print("Recommended cabinets:")
    for c in result["recommended_cabinets"]:
        print(f"  {c['model']}: {c['chassis_available_cm2']} cm² chassis, {c['spare_percentage']}% spare")
    print()
    if result["smallest_fit"]:
        sf = result["smallest_fit"]
        print(f"Smallest fit: {sf['model']} ({sf['dimensions_mm']['width']}×{sf['dimensions_mm']['height']}×{sf['dimensions_mm']['depth']} mm)")
