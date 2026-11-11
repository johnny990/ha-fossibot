"""Protocol V1 decoding, checked against frames captured from a FOSSiBOT F7200.

Both frames came from the station's local-MQTT responses (2026-11-10); the
expected values are what the BrightEMS app showed at the time or what the
app bundle's register table says the word means.
"""

import pytest

from fossibot_ha.sydpower.modbus import parse_registers
from fossibot_ha.sydpower.registers_v1 import (
    PROTOCOL_V1, decode_holding_registers_v1, decode_input_registers_v1,
    detect_protocol,
)

TOPIC_INPUT = "AC276E61B29E/device/response/client/04"
TOPIC_HOLDING = "AC276E61B29E/device/response/client/data"

# payload hex as published by the station: 6-byte header, 100 words, CRC
HOLDING_HEX = (
    "110300000064000000000000000000c8000000000001000000000000000000000000"
    "000000000000000000000000000000140000000005a0012c006403840005000301e0"
    "000000000320ffff000affff000038b8005a007f0000000000000000000000000010"
    "000f0012001a00000000000000000000000000000000000000000000000000000000"
    "0000000000000a0a0a0a0a0a0a0a00000000000000000000000000000000ffffffff"
    "00000000000000000320000000000000000000000000000000000000000000000000"
    "00003892"
)
# AC output on, 816 W load, SoC 70 %, USB device drawing 6 W
INPUT_IDLE_HEX = (
    "11040000006400000002000000000000000000000000023d1388090001f403300330"
    "00000000000000000000000000000000000000000000000000000000000000000000"
    "00460000000000000000300040003000400000000000000000000000000000000000"
    "000000000000000000000110081a0000000000000000000000030003000000000000"
    "000000fe00fe000000000000000000ea000000001898189800000006000000000000"
    "00000001000000030000000000000000032e0000000000000000000000001a0b0a11"
    "2e398797"
)
# later, 173 W load, SoC 67 %
INPUT_LOADED_HEX = (
    "1104000000640000000200000000000000000000000002381388090201f400ad00b3"
    "00000000000000000000000000000000000000000000000000000000000000000000"
    "00430000000000000000300040003000400000000000000000000000000000000000"
    "000000000000000000000110081a0000000000000000000000030003000000000000"
    "0000010b010b00000000000000000383000000001898189800000006000000000000"
    "0000000100000003000000000000000000ad0000000000000000000000001a0b0a12"
    "09156987"
)


def words(hex_payload: str):
    data = bytes.fromhex(hex_payload)[6:]
    return [(data[i] << 8) | data[i + 1] for i in range(0, len(data), 2)]


HOLDING = words(HOLDING_HEX)
INPUT_IDLE = words(INPUT_IDLE_HEX)
INPUT_LOADED = words(INPUT_LOADED_HEX)


def test_frames_are_100_registers_plus_crc():
    assert len(HOLDING) == len(INPUT_IDLE) == len(INPUT_LOADED) == 101


def test_detect_protocol_from_holding_7():
    assert detect_protocol(HOLDING) == PROTOCOL_V1
    assert detect_protocol([0] * 100) == 0
    assert detect_protocol([]) == 0


def test_holding_decode():
    out = decode_holding_registers_v1(HOLDING)
    assert out["protocolProfile"] == PROTOCOL_V1
    assert out["protocolVersion"] == 1
    assert out["dcInputMaxCurrent"] == 20
    assert out["acStandbyTime"] == 1440
    assert out["screenRestTime"] == 300
    assert out["dischargeLowerLimit"] == 10.0
    assert out["acChargingUpperLimit"] == 90.0
    assert out["wholeMachineUnusedTime"] == 5
    assert out["usbStandbyTime"] == 3
    assert out["dcStandbyTime"] == 480
    assert out["gridTieMaxPower"] == 800
    # app shows "H_AC v1.6" and "panel v2.6"
    assert out["versionAcSoftware"] == "1.6"
    assert out["versionPanelSoftware"] == "2.6"


def test_input_decode_idle_frame():
    out = decode_input_registers_v1(INPUT_IDLE)
    assert out["protocolProfile"] == PROTOCOL_V1
    assert out["soc"] == 70
    assert out["acOutputPower"] == 816
    assert out["dcOutputPower"] == 6
    assert out["totalOutput"] == 822
    assert out["acInput"] == 0 and out["totalInput"] == 0
    assert out["acOutputVoltage"] == 230.4
    assert out["acOutputFrequency"] == 50.0
    assert out["remainingDischargeTime"] == 234
    assert out["pvEnergyToday"] == 3
    assert out["pvEnergyTotal"] == 0.003
    assert out["acOutput"] is True and out["acInverterOutput"] is True
    assert out["dcOutput"] is True and out["usbOutput"] is True
    assert out["gridVoltagePresent"] is False
    assert out["dcChargeVoltagePresent"] is True   # input 53 bit 8
    assert out["buzzerEnabled"] is True
    assert out["deviceTime"] == "2026-11-10 17:46:57"
    assert "soc_s1" not in out


def test_input_decode_loaded_frame():
    out = decode_input_registers_v1(INPUT_LOADED)
    assert out["soc"] == 67
    assert out["acOutputPower"] == 173
    assert out["remainingDischargeTime"] == 899
    assert out["deviceTime"] == "2026-11-10 18:09:21"


def test_parse_registers_routes_by_profile():
    v1 = parse_registers(INPUT_IDLE, TOPIC_INPUT, protocol=PROTOCOL_V1)
    assert v1["soc"] == 70
    v0 = parse_registers(INPUT_IDLE, TOPIC_INPUT)
    assert v0.get("soc") != 70   # the V0 table reads this frame wrong, as observed
    assert parse_registers(HOLDING, TOPIC_HOLDING, protocol=PROTOCOL_V1)["protocolVersion"] == 1


@pytest.mark.parametrize("raw,expected", [(70, 70), (0x8046, 70), (0, 0)])
def test_soc_low_seven_bits(raw, expected):
    from fossibot_ha.sydpower.registers_v1 import decode_v1_soc
    assert decode_v1_soc(raw) == expected


# --- writes -----------------------------------------------------------------

from fossibot_ha.sydpower.modbus import ModbusValidationError, get_write_modbus_v1, ta
from fossibot_ha.sydpower.registers_v1 import (
    FUNC_WRITE_HOLDING, FUNC_WRITE_STATE, HREG_V1_DISCHARGE_SOC_MIN,
    IREG_V1_SYSTEM_STATE, STATE_SWITCH_BITS, state_word_with_bit,
)


def test_state_word_bit_flip_keeps_other_bits():
    word = 0x1898                                   # captured: AC on, DC/USB on, buzzer on
    assert state_word_with_bit(word, STATE_SWITCH_BITS["acOutput"], False) == 0x1888
    assert state_word_with_bit(0x1888, STATE_SWITCH_BITS["acOutput"], True) == 0x1898
    assert state_word_with_bit(word, STATE_SWITCH_BITS["buzzerEnabled"], False) == 0x1818
    assert state_word_with_bit(0xFFFF, 4, False) == 0xFFEF


def test_v1_state_write_frame_matches_app_layout():
    # [addr, func, reg, count_hi, count_lo, value_hi, value_lo, crc_hi, crc_lo]
    frame = get_write_modbus_v1(0x11, FUNC_WRITE_STATE, IREG_V1_SYSTEM_STATE, 0x1888)
    assert frame[:7] == [0x11, 0x05, 0x4B, 0x00, 0x01, 0x18, 0x88]
    assert len(frame) == 9
    crc = ta(frame[:7])
    assert frame[7:] == [(crc >> 8) & 0xFF, crc & 0xFF]


def test_v1_holding_write_frame():
    frame = get_write_modbus_v1(0x11, FUNC_WRITE_HOLDING, HREG_V1_DISCHARGE_SOC_MIN, 100)
    assert frame[:7] == [0x11, 0x06, 0x1A, 0x00, 0x01, 0x00, 0x64]


@pytest.mark.parametrize("func,register,value", [
    (FUNC_WRITE_HOLDING, HREG_V1_DISCHARGE_SOC_MIN, 501),   # above the 50 % floor limit
    (FUNC_WRITE_HOLDING, 27, 599),                          # below the 60 % ceiling limit
    (FUNC_WRITE_HOLDING, 24, 5001),
    (FUNC_WRITE_HOLDING, 7, 1),                             # protocol version: never
    (FUNC_WRITE_HOLDING, 0, 1),                             # factory reset: never
    (FUNC_WRITE_STATE, 53, 0),                              # only the state word is writable
    (FUNC_WRITE_STATE, IREG_V1_SYSTEM_STATE, 0x10000),
])
def test_v1_write_refusals(func, register, value):
    with pytest.raises(ModbusValidationError):
        get_write_modbus_v1(0x11, func, register, value)


# --- custom charge schedule ---------------------------------------------------

from fossibot_ha.sydpower.registers_v1 import (
    FUNC_WRITE_STATE as _F5, IREG_V1_CHARGE_SCHEDULE_FLAGS, decode_charge_window,
)


def test_schedule_enable_write_matches_app_capture():
    # app "send to device" with window 1 enabled: 11 05 53 0001 0001 580e
    frame = get_write_modbus_v1(0x11, _F5, IREG_V1_CHARGE_SCHEDULE_FLAGS, 1)
    assert bytes(frame).hex() == "11055300010001580e"
    with pytest.raises(ModbusValidationError):
        get_write_modbus_v1(0x11, _F5, IREG_V1_CHARGE_SCHEDULE_FLAGS, 8)


def test_charge_window_packing():
    # 01:30-02:40, 1.5 kWh, to 80 %, every Monday
    time_word = (2 << 11) | (4 << 8) | (1 << 3) | 3
    assert decode_charge_window(time_word, (15 << 8), 1 << 1) == "01:30-02:40 1.5 kWh Mon"
    assert decode_charge_window(time_word, 80, 1 << 1) == "01:30-02:40 to 80 % Mon"
    assert decode_charge_window(0, 0, 0) == "not set"
    assert decode_charge_window(0xFFFF, 0, 0) == "not set"
    assert decode_charge_window(None, 0, 0) is None


def test_captured_holding_frame_schedule_and_flags():
    out = decode_holding_registers_v1(HOLDING)
    assert out["chargeSchedule1"] == "23:00-07:00 to 90 % Daily"   # holding 38-40 = 0x38B8, 90, 0x7F
    assert out["chargeSchedule2"] == "not set"
    inp = decode_input_registers_v1(INPUT_IDLE)
    assert inp["chargeSchedule1Enabled"] is True and inp["chargeSchedule2Enabled"] is False  # input 83 = 1
    assert inp["acCustomCharge"] is True            # state word bit 12


def test_charge_window_write_matches_app_capture():
    from fossibot_ha.sydpower.registers_v1 import encode_charge_window
    # app edit: 01:30-02:40, 1.5 kWh, every Monday -> 11 06 26 0003 140b 0f00 0002 a613
    words = encode_charge_window(1, 30, 2, 40, 1.5, 0, 1 << 1)
    assert words == [0x140B, 0x0F00, 0x0002]
    assert bytes(get_write_modbus_v1(0x11, FUNC_WRITE_HOLDING, 38, words)).hex() == "1106260003140b0f000002a613"
    # app restore: 23:00-07:00, to 90 %, daily -> 11 06 26 0003 38b8 005a 007f f6f2
    words = encode_charge_window(23, 0, 7, 0, 0, 90, 0x7F)
    assert bytes(get_write_modbus_v1(0x11, FUNC_WRITE_HOLDING, 38, words)).hex() == "110626000338b8005a007ff6f2"


@pytest.mark.parametrize("args", [
    (1, 35, 2, 40, 0, 50, 0x7F),    # minutes not a multiple of 10
    (1, 30, 1, 30, 0, 50, 0x7F),    # start == end
    (1, 30, 2, 40, 1.5, 80, 0x7F),  # amount and target at once
    (1, 30, 2, 40, 0, 101, 0x7F),   # SoC above 100
    (1, 30, 2, 40, 0, 50, 0x80),    # 8th day bit
])
def test_charge_window_encode_refusals(args):
    from fossibot_ha.sydpower.registers_v1 import encode_charge_window
    with pytest.raises(ValueError):
        encode_charge_window(*args)


def test_multi_word_write_only_for_window_bases():
    with pytest.raises(ModbusValidationError):
        get_write_modbus_v1(0x11, FUNC_WRITE_HOLDING, 26, [100, 100, 100])
    with pytest.raises(ModbusValidationError):
        get_write_modbus_v1(0x11, FUNC_WRITE_HOLDING, 38, [0x140B, 0x0F00])     # two words
    with pytest.raises(ModbusValidationError):
        get_write_modbus_v1(0x11, FUNC_WRITE_HOLDING, 38, [0x140B, 0x0F65, 2])  # SoC 101


def test_dc_usb_output_bit_matches_app_capture():
    # app USB/DC off then on: 11 05 4b 0001 1810 56e4 / 11 05 4b 0001 1818 90e5
    assert state_word_with_bit(0x1818, STATE_SWITCH_BITS["dcUsbOutput"], False) == 0x1810
    assert bytes(get_write_modbus_v1(0x11, FUNC_WRITE_STATE, IREG_V1_SYSTEM_STATE, 0x1810)).hex() == "11054b0001181056e4"
    assert decode_input_registers_v1(INPUT_IDLE)["dcUsbOutput"] is True   # 0x1898 has bit 3


def test_ac_output_bit_matches_app_capture():
    # app AC output off: 11 05 4b 0001 1808 5ce4 (bit 4 cleared from 0x1818)
    assert state_word_with_bit(0x1818, STATE_SWITCH_BITS["acOutput"], False) == 0x1808
    assert bytes(get_write_modbus_v1(0x11, FUNC_WRITE_STATE, IREG_V1_SYSTEM_STATE, 0x1808)).hex() == "11054b000118085ce4"
