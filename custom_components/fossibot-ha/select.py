"""Support for Fossibot select entities."""

import logging
from collections import OrderedDict

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import FossibotDataUpdateCoordinator
from .entity import FossibotEntity, device_profile
from .sydpower.registers_v1 import (
    FUNC_WRITE_STATE, IREG_V1_SYSTEM_STATE, state_word_with_bit,
)
from .sydpower.const import (
    HREG_AC_CHARGE_LEVEL,
    HREG_DC_INPUT_TYPE,
    REGISTER_AC_STANDBY_TIME,
    REGISTER_DC_STANDBY_TIME,
    REGISTER_LED,
    REGISTER_SCREEN_REST_TIME,
    REGISTER_SLEEP_TIME,
    REGISTER_USB_STANDBY_TIME,
)

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Register-based selects: each maps display labels → raw register values.
#
# ``key`` names the field the decoder writes the *current* value into. For
# most selects that is the same holding register being written; the LED mode
# is the exception — it is set through holding 27 but reported back through
# input register 25 ("LightMode"), which is why the previous implementation
# had to guess the active mode and could never show SOS or Flash.
#
# OrderedDict keeps the HA dropdown in a sensible order.
# ---------------------------------------------------------------------------

SELECT_DEFINITIONS = [
    {
        "name": "LED Mode",
        "key": "lightModeRaw",
        "register": REGISTER_LED,
        "unique_id_suffix": "led_mode",
        "options": OrderedDict([
            ("Off", 0), ("On", 1), ("SOS", 2), ("Flash", 3),
        ]),
    },
    {
        "name": "AC Charging Rate",
        "key": "acChargingRate",
        "register": HREG_AC_CHARGE_LEVEL,
        "unique_id_suffix": "ac_charge_level",
        "options": OrderedDict([
            ("Level 1", 1), ("Level 2", 2), ("Level 3", 3),
            ("Level 4", 4), ("Level 5", 5),
        ]),
    },
    {
        "name": "DC Input Type",
        "key": "dcInputTypeRaw",
        "register": HREG_DC_INPUT_TYPE,
        "unique_id_suffix": "dc_input_type",
        "category": EntityCategory.CONFIG,
        "options": OrderedDict([
            ("MPPT (PV)", 0), ("DC source", 1),
        ]),
    },
    {
        "name": "USB Standby Time",
        "key": "usbStandbyTime",
        "register": REGISTER_USB_STANDBY_TIME,
        "options": OrderedDict([
            ("Off", 0), ("3 min", 3), ("5 min", 5), ("10 min", 10), ("30 min", 30),
        ]),
    },
    {
        "name": "AC Standby Time",
        "key": "acStandbyTime",
        "register": REGISTER_AC_STANDBY_TIME,
        "options": OrderedDict([
            ("Off", 0), ("8 hours", 480), ("16 hours", 960), ("24 hours", 1440),
        ]),
    },
    {
        "name": "DC Standby Time",
        "key": "dcStandbyTime",
        "register": REGISTER_DC_STANDBY_TIME,
        "options": OrderedDict([
            ("Off", 0), ("8 hours", 480), ("16 hours", 960), ("24 hours", 1440),
        ]),
    },
    {
        "name": "Screen Rest Time",
        "key": "screenRestTime",
        "register": REGISTER_SCREEN_REST_TIME,
        "options": OrderedDict([
            ("Off", 0), ("3 min", 180), ("5 min", 300), ("10 min", 600), ("30 min", 1800),
        ]),
    },
    {
        "name": "Sleep Time",
        "key": "wholeMachineUnusedTime",
        "register": REGISTER_SLEEP_TIME,
        "options": OrderedDict([
            ("5 min", 5), ("10 min", 10), ("30 min", 30), ("8 hours", 480),
        ]),
    },
]

# Protocol V1: two-state settings that are single bits of the state word
# (input 75); the app's "DC input type setting" is bit 5, PV mode = 0.
V1_BIT_SELECT_DEFINITIONS = [
    {"name": "DC Input Type", "key": "dcInputTypeRaw", "bit": 5,
     "options": OrderedDict([("PV mode", 0), ("DC mode", 1)]),
     "category": EntityCategory.CONFIG},
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Fossibot select entities."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities = []
    for device_id in coordinator.data:
        if device_profile(coordinator, device_id) == 0:
            entities.extend(FossibotRegisterSelect(coordinator, device_id, **defn)
                            for defn in SELECT_DEFINITIONS)
        else:
            entities.extend(FossibotV1BitSelect(coordinator, device_id, **defn)
                            for defn in V1_BIT_SELECT_DEFINITIONS)

    async_add_entities(entities)


class FossibotRegisterSelect(FossibotEntity, SelectEntity):
    """Fossibot select backed by a Modbus register with discrete allowed values."""

    def __init__(
        self,
        coordinator: FossibotDataUpdateCoordinator,
        device_id: str,
        name: str,
        key: str,
        register: int,
        options: OrderedDict,
        unique_id_suffix: str | None = None,
        category: EntityCategory | None = None,
    ) -> None:
        """Initialize the register-based select."""
        super().__init__(coordinator, device_id)
        self._key = key
        self._register = register
        self._options_map = options                        # label → register value
        self._reverse_map = {v: k for k, v in options.items()}  # register value → label
        self._attr_name = name
        self._attr_unique_id = f"{device_id}_{unique_id_suffix or key}"
        self._attr_options = list(options.keys())
        self._attr_entity_category = category

    @property
    def current_option(self):
        """Return the currently selected option."""
        if self._device_id not in self.coordinator.data:
            return None
        raw = self.coordinator.data[self._device_id].get(self._key)
        if raw is None:
            return None
        return self._reverse_map.get(raw)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option not in self._options_map:
            _LOGGER.error("Invalid option for %s: %s", self._key, option)
            return

        reg_value = self._options_map[option]
        await self.coordinator.connector.run_command(
            self._device_id, "write_register", (self._register, reg_value)
        )
        await self.coordinator.async_request_refresh()


class FossibotV1BitSelect(FossibotRegisterSelect):
    """Protocol V1 select backed by one bit of the state word (input 75)."""

    def __init__(self, coordinator, device_id: str, name: str, key: str, bit: int,
                 options: OrderedDict, category: EntityCategory | None = None) -> None:
        super().__init__(coordinator, device_id, name, key, IREG_V1_SYSTEM_STATE,
                         options, category=category)
        self._bit = bit

    async def async_select_option(self, option: str) -> None:
        """Flip the bit in the last reported state word and write it back."""
        if option not in self._options_map:
            _LOGGER.error("Invalid option for %s: %s", self._key, option)
            return
        current = self.coordinator.data.get(self._device_id, {}).get("systemStateRaw")
        if current is None:
            _LOGGER.error("No state word known for %s yet, not writing", self._device_id)
            return
        word = state_word_with_bit(current, self._bit, bool(self._options_map[option]))
        await self.coordinator.connector.run_command(
            self._device_id, "write_v1", (FUNC_WRITE_STATE, IREG_V1_SYSTEM_STATE, word)
        )
        await self.coordinator.async_request_refresh()
