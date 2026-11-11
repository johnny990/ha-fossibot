"""Protocol V1 register decoding (newer stations such as the FOSSiBOT F7200).

Source: the BrightEMS app bundle (``app-service.js``, profile
``portable-power-station-v1``) carries the V1 register table as one object;
indices below are copied from it. V1 keeps the V0 identity block (holding
47-50 board versions) but moves every live value: inputs, SoC, state bits
and timers all live at different words, and the three output switches are
bits of input register 75 instead of holding 24-26. Writes are not
implemented yet, so this profile is read-only.

A device is on V1 when holding register 7 reads 1 (``detect_protocol``);
holding 5, the V0 version register, stays 0 on such firmware.
"""

from typing import Any, Dict, List, Optional

from .registers import _map, _set, combine_words, decode_bits

PROTOCOL_V1 = 1

# Holding register carrying the protocol version on V1 firmware
HREG_V1_PROTOCOL_VERSION = 7

# --- Input registers (function 04) -----------------------------------------
IREG_V1_DC_CHARGE_POWER = 0
IREG_V1_AC_CHARGE_POWER = 2
IREG_V1_PV1_CHARGE_POWER = 3
IREG_V1_PV2_CHARGE_POWER = 4
IREG_V1_PV3_CHARGE_POWER = 5
IREG_V1_PV4_CHARGE_POWER = 6
IREG_V1_AC_GRID_POWER = 7
IREG_V1_AC_OUTPUT_POWER = 12
IREG_V1_MAIN_BAT = 31          # low 7 bits = SoC %, upper bits = BMS flags
IREG_V1_SLAVE_BAT_FIRST = 32   # 32..35 = slave 1..4
IREG_V1_DEVICE_STATE_1 = 53
IREG_V1_DEVICE_STATE_2 = 54
IREG_V1_PV_ENERGY_TOTAL_H = 59
IREG_V1_PV_ENERGY_TOTAL_L = 60
IREG_V1_PV_ENERGY_TODAY = 61
IREG_V1_CHARGE_APPOINTMENT = 70
IREG_V1_REMAINING_CHARGE_TIME = 71
IREG_V1_REMAINING_DISCHARGE_TIME = 72
IREG_V1_SYSTEM_STATE = 75
IREG_V1_TOTAL_DC_DISCHARGE_POWER = 78
IREG_V1_TIME_YEAR_MONTH = 97
IREG_V1_TIME_DAY_HOUR = 98
IREG_V1_TIME_MIN_SEC = 99
IREG_V1_CHARGE_SCHEDULE_FLAGS = 83   # grid_charge_custom_enable_flag: bits 0-2 = windows 1-3

# Custom charge windows (holding): time word, amount/target word, repeat word
HREG_V1_CHARGE_WINDOW_TIME = (38, 41, 44)
HREG_V1_CHARGE_WINDOW_AMOUNT = (39, 42, 45)
HREG_V1_CHARGE_WINDOW_REPEAT = (40, 43, 46)

# Observed on an F7200, not in the app table: 230.4 V / 50.0 Hz while the
# inverter runs, the voltage decaying to 0 after it is switched off.
IREG_V1_AC_OUTPUT_VOLTAGE = 10
IREG_V1_AC_OUTPUT_FREQUENCY = 11

# --- Holding registers (function 03) ---------------------------------------
HREG_V1_GRID_CHARGE_LEVEL = 1
HREG_V1_DC_INPUT_MAX_CURRENT = 21
HREG_V1_DC_INPUT_CURRENT_SET = 23
HREG_V1_AC_SLEEP_TIME = 24
HREG_V1_LCD_DIM_TIME = 25
HREG_V1_DISCHARGE_SOC_MIN = 26
HREG_V1_CHARGE_SOC_MAX = 27
HREG_V1_SHUTDOWN_WAIT_TIME = 28
HREG_V1_USB_SLEEP_TIME = 29
HREG_V1_DC_SLEEP_TIME = 30
HREG_V1_ECO_SOC = 31
HREG_V1_VERSION_AC = 47
HREG_V1_VERSION_BMS = 48
HREG_V1_VERSION_PV = 49
HREG_V1_VERSION_PANEL = 50
HREG_V1_UPS_MODE = 85
HREG_V1_GRID_TIE_MAX_POWER = 86
HREG_V1_CHARGE_PRIORITY = 88

# Bit names, keys chosen to match the V0 decoder where the meaning is the same
# so the existing binary sensors and switch states keep working.
DEVICE_STATE_1_BITS: Dict[int, str] = {
    5: "gridVoltagePresent",      # AC_Vol_Exist_status
    6: "gridCharging",            # AC_charge_onoff
    7: "gridDischarging",         # grid_discharge_onoff
    8: "dcChargeVoltagePresent",  # Low_PV_Vol_Exist_status
    9: "dcCharging",              # Low_PV_charge_onoff
}
DEVICE_STATE_2_BITS: Dict[int, str] = {
    9: "carChargeVoltagePresent",  # Car_charge_Vol_Exist_status
    10: "carCharging",             # Car_charge_onoff
    11: "dcPortOutput",            # DC_usb_pd_led_wirelesscharge_Port_Out_onoff
    12: "pvHighVoltagePresent",    # High_PV_Vol_Exist_status
    13: "pvHighVoltageCharging",   # High_PV_charge_onoff
}
SYSTEM_STATE_BITS: Dict[int, str] = {
    # bits 0-2 carry balcony-inverter names in the app table (self-use, grid
    # pause, idle) and are left unnamed for stations
    3: "dcUsbOutput",              # DC/USB outputs: app toggle captured as bit 3 on the F7200
    4: "acOutput",                 # AC_BackUp_Output_KEY_onoff
    5: "dcInputTypeRaw",
    6: "acSilentCharging",
    7: "buzzerEnabled",
    # charge / grid modes, from the app's charge-setting pages
    8: "gridAutoEnabled",
    9: "gridImmediateEnabled",
    10: "gridCustomEnabled",
    12: "acCustomCharge",           # charge_custom_enable ("AC Custom Charge" toggle)
    13: "ecoMode",
    14: "appControlSleep",         # APP_control_remote_shutoff
}


def detect_protocol(holding: List[int]) -> int:
    """Return the protocol profile a holding-register frame declares."""
    if len(holding) > HREG_V1_PROTOCOL_VERSION and holding[HREG_V1_PROTOCOL_VERSION] == 1:
        return PROTOCOL_V1
    return 0


def _bits(out: Dict[str, Any], raw: Optional[int], table: Dict[int, str]) -> None:
    if raw is None:
        return
    for bit, key in table.items():
        out[key] = bool(raw & (1 << bit))


def decode_v1_version(raw: int) -> Optional[str]:
    """Board version as the app prints it: 16 -> "1.6"."""
    return None if raw == 0 else "%d.%d" % (raw // 10, raw % 10)


def decode_v1_soc(raw: int) -> Optional[int]:
    """SoC lives in the low 7 bits; 0 means no pack (slaves)."""
    return raw & 0x7F


WEEKDAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")


def decode_charge_window(time_word: Optional[int], amount_word: Optional[int],
                         repeat_word: Optional[int]) -> Optional[str]:
    """One custom charge window as the app shows it, e.g. "01:30-02:40 1.5 kWh to 80 % Mon".

    Time word: bits 15-11 end hour, 10-8 end minute/10, 7-3 start hour,
    2-0 start minute/10; 0, 0xFFFF or start == end means not set. Amount word:
    high byte kWh x10, low byte target SoC %. Repeat word: low byte bits 0-6 =
    Sunday..Saturday, all seven = Daily.
    """
    if time_word is None or amount_word is None or repeat_word is None:
        return None
    if time_word in (0, 0xFFFF):
        return "not set"
    end_h, end_m = (time_word >> 11) & 0x1F, ((time_word >> 8) & 0x7) * 10
    start_h, start_m = (time_word >> 3) & 0x1F, (time_word & 0x7) * 10
    if (start_h, start_m) == (end_h, end_m) or start_h > 24 or end_h > 24:
        return "not set"
    days = [WEEKDAYS[i] for i in range(7) if repeat_word & (1 << i)]
    repeat = "Daily" if len(days) == 7 else (" ".join(days) or "once")
    # the app stores either an energy amount or a target SoC, zeroing the other
    kwh, soc = (amount_word >> 8) / 10, amount_word & 0xFF
    target = "%.1f kWh" % kwh if kwh else "to %d %%" % soc
    return "%02d:%02d-%02d:%02d %s %s" % (start_h, start_m, end_h, end_m, target, repeat)


def encode_charge_window(start_h: int, start_m: int, end_h: int, end_m: int,
                         kwh: float, soc: int, days_mask: int) -> List[int]:
    """Pack one window into its three holding words (see decode_charge_window).

    Minutes must be multiples of 10 (3-bit field); ``kwh`` and ``soc`` are
    exclusive the way the app treats them, so one of them must be 0.
    """
    for h, m in ((start_h, start_m), (end_h, end_m)):
        if not (0 <= h <= 24 and 0 <= m <= 59 and m % 10 == 0):
            raise ValueError("time must be within 00:00-24:00 with minutes in steps of 10")
    if (start_h, start_m) == (end_h, end_m):
        raise ValueError("start and end must differ")
    kwh_x10 = int(round(kwh * 10))
    if not (0 <= kwh_x10 <= 255 and 0 <= soc <= 100):
        raise ValueError("energy 0-25.5 kWh, target SoC 0-100 %")
    if kwh_x10 and soc:
        raise ValueError("set either an energy amount or a target SoC, not both")
    if not 0 <= days_mask <= 0x7F:
        raise ValueError("repeat mask is 7 bits, Sunday = bit 0")
    return [
        (end_h << 11) | ((end_m // 10) << 8) | (start_h << 3) | (start_m // 10),
        (kwh_x10 << 8) | soc,
        days_mask,
    ]


def decode_input_registers_v1(registers: List[int]) -> Dict[str, Any]:
    """Decode a V1 input-register (function 04) response."""
    out: Dict[str, Any] = {"protocolProfile": PROTOCOL_V1}

    def reg(index: int) -> Optional[int]:
        return registers[index] if index < len(registers) else None

    for key, index in (
        ("dcInput", IREG_V1_DC_CHARGE_POWER),
        ("acInput", IREG_V1_AC_CHARGE_POWER),
        ("pv1Input", IREG_V1_PV1_CHARGE_POWER),
        ("pv2Input", IREG_V1_PV2_CHARGE_POWER),
        ("pv3Input", IREG_V1_PV3_CHARGE_POWER),
        ("pv4Input", IREG_V1_PV4_CHARGE_POWER),
        ("acGridPower", IREG_V1_AC_GRID_POWER),
        ("acOutputPower", IREG_V1_AC_OUTPUT_POWER),
        ("dcOutputPower", IREG_V1_TOTAL_DC_DISCHARGE_POWER),
        ("chargeAppointmentRemaining", IREG_V1_CHARGE_APPOINTMENT),
        ("remainingChargeTime", IREG_V1_REMAINING_CHARGE_TIME),
        ("remainingDischargeTime", IREG_V1_REMAINING_DISCHARGE_TIME),
        ("pvEnergyToday", IREG_V1_PV_ENERGY_TODAY),
        ("systemStateRaw", IREG_V1_SYSTEM_STATE),
    ):
        _set(out, key, reg(index))

    # Sums the app does not publish as registers; documented as derived.
    inputs = [out.get(k) for k in ("dcInput", "acInput", "pv1Input", "pv2Input", "pv3Input", "pv4Input")]
    if all(v is not None for v in inputs):
        out["totalInput"] = sum(inputs)
    if out.get("acOutputPower") is not None and out.get("dcOutputPower") is not None:
        out["totalOutput"] = out["acOutputPower"] + out["dcOutputPower"]

    _set(out, "acOutputVoltage", _map(reg(IREG_V1_AC_OUTPUT_VOLTAGE), lambda v: round(v / 10, 1)))
    _set(out, "acOutputFrequency", _map(reg(IREG_V1_AC_OUTPUT_FREQUENCY), lambda v: round(v / 10, 1)))

    _set(out, "soc", _map(reg(IREG_V1_MAIN_BAT), decode_v1_soc))
    for n in range(4):
        raw = reg(IREG_V1_SLAVE_BAT_FIRST + n)
        if raw:
            out["soc_s%d" % (n + 1)] = decode_v1_soc(raw)

    high, low = reg(IREG_V1_PV_ENERGY_TOTAL_H), reg(IREG_V1_PV_ENERGY_TOTAL_L)
    if high is not None and low is not None:
        out["pvEnergyTotal"] = round(combine_words(high, low) / 1000, 3)  # Wh -> kWh

    _bits(out, reg(IREG_V1_DEVICE_STATE_1), DEVICE_STATE_1_BITS)
    _bits(out, reg(IREG_V1_DEVICE_STATE_2), DEVICE_STATE_2_BITS)
    _bits(out, reg(IREG_V1_SYSTEM_STATE), SYSTEM_STATE_BITS)
    if "dcPortOutput" in out:
        # one master bit covers DC, USB and LED on V1
        out["dcOutput"] = out["usbOutput"] = out["dcPortOutput"]
    if "acOutput" in out:
        out["acInverterOutput"] = out["acOutput"]
    state = reg(IREG_V1_SYSTEM_STATE)
    if state is not None:
        out["activeStates"] = decode_bits(state, SYSTEM_STATE_BITS)

    flags = reg(IREG_V1_CHARGE_SCHEDULE_FLAGS)
    if flags is not None:
        out["chargeScheduleFlagsRaw"] = flags
        for n in range(3):
            out["chargeSchedule%dEnabled" % (n + 1)] = bool(flags & (1 << n))

    ym, dh, ms = (reg(IREG_V1_TIME_YEAR_MONTH), reg(IREG_V1_TIME_DAY_HOUR), reg(IREG_V1_TIME_MIN_SEC))
    if None not in (ym, dh, ms) and ym:
        out["deviceTime"] = "20%02d-%02d-%02d %02d:%02d:%02d" % (
            ym >> 8, ym & 0xFF, dh >> 8, dh & 0xFF, ms >> 8, ms & 0xFF)

    return out


def decode_holding_registers_v1(registers: List[int]) -> Dict[str, Any]:
    """Decode a V1 holding-register (function 03) response."""
    out: Dict[str, Any] = {"protocolProfile": PROTOCOL_V1}

    def reg(index: int) -> Optional[int]:
        return registers[index] if index < len(registers) else None

    _set(out, "protocolVersion", reg(HREG_V1_PROTOCOL_VERSION))
    for key, index in (
        ("acChargingRate", HREG_V1_GRID_CHARGE_LEVEL),
        ("dcInputMaxCurrent", HREG_V1_DC_INPUT_MAX_CURRENT),
        ("maximumChargingCurrent", HREG_V1_DC_INPUT_CURRENT_SET),
        ("acStandbyTime", HREG_V1_AC_SLEEP_TIME),
        ("screenRestTime", HREG_V1_LCD_DIM_TIME),
        ("wholeMachineUnusedTime", HREG_V1_SHUTDOWN_WAIT_TIME),
        ("usbStandbyTime", HREG_V1_USB_SLEEP_TIME),
        ("dcStandbyTime", HREG_V1_DC_SLEEP_TIME),
        ("ecoSoc", HREG_V1_ECO_SOC),
        ("upsMode", HREG_V1_UPS_MODE),
        ("gridTieMaxPower", HREG_V1_GRID_TIE_MAX_POWER),
        ("chargePriority", HREG_V1_CHARGE_PRIORITY),
    ):
        _set(out, key, reg(index))
    # same 0.1 % units as the V0 limits (100 = 10 %, 900 = 90 %)
    _set(out, "dischargeLowerLimit", _map(reg(HREG_V1_DISCHARGE_SOC_MIN), lambda v: round(v / 10, 1)))
    _set(out, "acChargingUpperLimit", _map(reg(HREG_V1_CHARGE_SOC_MAX), lambda v: round(v / 10, 1)))

    for n in range(3):
        window = decode_charge_window(
            reg(HREG_V1_CHARGE_WINDOW_TIME[n]), reg(HREG_V1_CHARGE_WINDOW_AMOUNT[n]),
            reg(HREG_V1_CHARGE_WINDOW_REPEAT[n]))
        if window is not None:
            out["chargeSchedule%d" % (n + 1)] = window

    for key, index in (
        ("versionAc", HREG_V1_VERSION_AC),
        ("versionBms", HREG_V1_VERSION_BMS),
        ("versionPv", HREG_V1_VERSION_PV),
        ("versionPanel", HREG_V1_VERSION_PANEL),
    ):
        _set(out, "%sSoftware" % key, _map(reg(index), decode_v1_version))

    return out


# ---------------------------------------------------------------------------
# Writes (V1)
#
# The app writes with a frame the V0 document does not have:
#   [addr, func, reg, 0x00, 0x01, value_hi, value_lo, crc_hi, crc_lo]
# func 6 for a holding register, func 5 for the state word (input 75): the
# app reads the current word, flips one bit and writes the whole word back.
# ---------------------------------------------------------------------------

FUNC_WRITE_HOLDING = 6
FUNC_WRITE_STATE = 5

# bits of input 75 the integration is allowed to flip
STATE_SWITCH_BITS: Dict[str, int] = {
    "dcUsbOutput": 3,         # DC/USB outputs (captured from the app on an F7200)
    "acOutput": 4,            # AC_BackUp_Output_KEY_onoff
    "acSilentCharging": 6,    # silent_charging_mode
    "buzzerEnabled": 7,       # Buzzer_enable
    "acCustomCharge": 12,     # charge_custom_enable; app toggle captured as bit 12
}

# Per-window enables of the custom charge schedule (input 83, func 5)
SCHEDULE_SWITCH_BITS: Dict[str, int] = {
    "chargeSchedule1Enabled": 0,
    "chargeSchedule2Enabled": 1,
    "chargeSchedule3Enabled": 2,
}

# (func, register) -> allowed values; ranges follow the V0 document's limits
# for the same settings (the app bundle gives no ranges)
WRITABLE_REGISTERS_V1: Dict[tuple, range] = {
    (FUNC_WRITE_STATE, IREG_V1_SYSTEM_STATE): range(0, 0x10000),
    (FUNC_WRITE_STATE, IREG_V1_CHARGE_SCHEDULE_FLAGS): range(0, 8),
    # custom charge windows: three words per window in one func-6 frame, the
    # app writes them as [time, amount, repeat] starting at the window base
    (FUNC_WRITE_HOLDING, HREG_V1_CHARGE_WINDOW_TIME[0]): range(0, 0x10000),
    (FUNC_WRITE_HOLDING, HREG_V1_CHARGE_WINDOW_TIME[1]): range(0, 0x10000),
    (FUNC_WRITE_HOLDING, HREG_V1_CHARGE_WINDOW_TIME[2]): range(0, 0x10000),
    (FUNC_WRITE_HOLDING, HREG_V1_DC_INPUT_CURRENT_SET): range(1, 21),   # app offers 1-20 A
    (FUNC_WRITE_HOLDING, HREG_V1_AC_SLEEP_TIME): range(0, 5001),
    (FUNC_WRITE_HOLDING, HREG_V1_LCD_DIM_TIME): range(0, 5001),
    (FUNC_WRITE_HOLDING, HREG_V1_DISCHARGE_SOC_MIN): range(0, 501),
    (FUNC_WRITE_HOLDING, HREG_V1_CHARGE_SOC_MAX): range(600, 1001),
    (FUNC_WRITE_HOLDING, HREG_V1_SHUTDOWN_WAIT_TIME): range(0, 5001),
    (FUNC_WRITE_HOLDING, HREG_V1_USB_SLEEP_TIME): range(0, 5001),
    (FUNC_WRITE_HOLDING, HREG_V1_DC_SLEEP_TIME): range(0, 5001),
}


def state_word_with_bit(current: int, bit: int, on: bool) -> int:
    """Return the state word with one bit set or cleared, all others kept."""
    return (current | (1 << bit)) if on else (current & ~(1 << bit) & 0xFFFF)

WINDOW_BASE_REGISTERS_V1 = frozenset(HREG_V1_CHARGE_WINDOW_TIME)


def validate_charge_window_words(words: List[int]) -> None:
    """Refuse window words that decode_charge_window would not accept."""
    from .modbus import ModbusValidationError  # local import, modbus imports this module
    time_word, amount_word, repeat_word = words
    if decode_charge_window(time_word, amount_word, repeat_word) == "not set" and time_word != 0:
        raise ModbusValidationError("window time word %d is not a valid start/end pair" % time_word)
    if not 0 <= (amount_word & 0xFF) <= 100 or not 0 <= amount_word <= 0xFFFF:
        raise ModbusValidationError("window amount word %d: target SoC must be 0-100" % amount_word)
    if not 0 <= repeat_word <= 0x7F:
        raise ModbusValidationError("window repeat word %d must be a 7-bit day mask" % repeat_word)
