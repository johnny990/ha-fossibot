"""Actions (services) of the Fossibot integration.

``fossibot.set_charge_schedule`` writes one custom AC charge window of a
protocol V1 station the way the app's "send to device" does: the three
holding words of the window in one frame, then the enable bit in input 83.
"""

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .const import DOMAIN
from .sydpower.registers_v1 import (
    FUNC_WRITE_HOLDING, FUNC_WRITE_STATE, HREG_V1_CHARGE_WINDOW_TIME,
    IREG_V1_CHARGE_SCHEDULE_FLAGS, WEEKDAYS, encode_charge_window, state_word_with_bit,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_SET_CHARGE_SCHEDULE = "set_charge_schedule"

REPEAT_OPTIONS = ["daily"] + [d.lower() for d in WEEKDAYS]

SET_CHARGE_SCHEDULE_SCHEMA = vol.Schema({
    vol.Required("device_id"): cv.string,
    vol.Required("window"): vol.All(vol.Coerce(int), vol.Range(min=1, max=3)),
    vol.Required("start_time"): cv.time,
    vol.Required("end_time"): cv.time,
    vol.Optional("energy_kwh", default=0.0): vol.All(vol.Coerce(float), vol.Range(min=0, max=25.5)),
    vol.Optional("target_soc", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
    vol.Optional("repeat", default=["daily"]): vol.All(cv.ensure_list, [vol.In(REPEAT_OPTIONS)]),
    vol.Optional("enabled"): cv.boolean,
})


def _days_mask(repeat: list) -> int:
    if "daily" in repeat:
        return 0x7F
    return sum(1 << i for i, name in enumerate(WEEKDAYS) if name.lower() in repeat)


def _find_device(hass: HomeAssistant, device_id: str):
    """Resolve an HA device id to (coordinator, fossibot device id)."""
    entry = dr.async_get(hass).async_get(device_id)
    if entry is None:
        raise HomeAssistantError("Unknown device %s" % device_id)
    macs = [ident for domain, ident in entry.identifiers if domain == DOMAIN]
    if not macs:
        raise HomeAssistantError("Device %s is not a Fossibot device" % device_id)
    for coordinator in hass.data.get(DOMAIN, {}).values():
        if macs[0] in coordinator.data:
            return coordinator, macs[0]
    raise HomeAssistantError("Fossibot device %s is not loaded" % macs[0])


async def _set_charge_schedule(hass: HomeAssistant, call: ServiceCall) -> None:
    coordinator, mac = _find_device(hass, call.data["device_id"])
    data = coordinator.data.get(mac, {})
    if data.get("protocolProfile") != 1:
        raise HomeAssistantError("Charge schedules need a protocol V1 station")

    start, end = call.data["start_time"], call.data["end_time"]
    try:
        words = encode_charge_window(
            start.hour, start.minute, end.hour, end.minute,
            call.data["energy_kwh"], call.data["target_soc"], _days_mask(call.data["repeat"]),
        )
    except ValueError as err:
        raise HomeAssistantError(str(err)) from err

    window = call.data["window"] - 1
    base = HREG_V1_CHARGE_WINDOW_TIME[window]
    ok = await coordinator.connector.run_command(mac, "write_v1", (FUNC_WRITE_HOLDING, base, words))
    if not ok:
        raise HomeAssistantError("Writing charge window %d failed, see the log" % (window + 1))

    if "enabled" in call.data:
        flags = data.get("chargeScheduleFlagsRaw")
        if flags is None:
            raise HomeAssistantError("Schedule flags not read yet, enable the window later")
        word = state_word_with_bit(flags, window, call.data["enabled"])
        await coordinator.connector.run_command(
            mac, "write_v1", (FUNC_WRITE_STATE, IREG_V1_CHARGE_SCHEDULE_FLAGS, word))

    await coordinator.async_request_refresh()


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions once."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_CHARGE_SCHEDULE):
        return

    async def handle(call: ServiceCall) -> None:
        await _set_charge_schedule(hass, call)

    hass.services.async_register(
        DOMAIN, SERVICE_SET_CHARGE_SCHEDULE, handle, schema=SET_CHARGE_SCHEDULE_SCHEMA)
