import binascii
import time

import board
import busio
from adafruit_bus_device.spi_device import SPIDevice
from digitalio import DigitalInOut, Direction, Pull
import supervisor

VERSION = "0.0.1"
if board.board_id == 'raspberry_pi_pico':
    ALIVE_LED = board.LED
    DIO_PINS = [board.GP0, board.GP1, board.GP2, board.GP3, board.GP20, board.GP21, board.GP22, board.GP23]
    RELAY_PINS = [board.GP6, board.GP7]
    SPI_SCK = board.GP10
    SPI_MOSI = board.GP11
    SPI_MISO = board.GP12
    SPI_IRQ = board.GP13
    SPI_RST = board.GP14
else:
    ALIVE_LED = board.BLUE_LED
    DIO_PINS = [board.D0, board.D1, board.D2, board.D3, board.D4, board.A2, board.A3, board.A4]
    SPI_SCK = board.SCK
    SPI_MOSI = board.MOSI
    SPI_MISO = board.MISO
    SPI_IRQ = board.A0
    SPI_RST = board.D5


def bytes_to_hex(data):
    if isinstance(data, int):
        data = bytes([data])
    return "".join([chr(b) for b in binascii.hexlify(data, " ")])
    

def hexstr_to_bytes(hex_str):
    """
    Take a string of hex value and turn into bytes.

    Accept iterable or string with ":" or " " separators
    Insert leading 0 if single digit value
    """
    if isinstance(hex_str, str):
        if " " in hex_str:
            hex_str = hex_str.replace(" ", ":")
        if ":" in hex_str:
            hex_values = hex_str.split(":")
        else:
            hex_values = [hex_str]
    else:
        hex_values = hex_str
    clean_hex_values = []
    for hex_value in hex_values:
        if len(hex_value) % 2:
            clean_hex_values.append("0" + hex_value)
        else:
            clean_hex_values.append(hex_value)
    clean_hex_str = "".join(clean_hex_values)
    return binascii.unhexlify(clean_hex_str)


def code_version():
    return VERSION


class DigitalIo:
    """
    Provide serial access to as set of general purpose logical IO pins.
    
    These are mapped to the physical IO pins that are available.
    """
    def __init__(self):
        self._logical_pins = []
        for pin in DIO_PINS:
            new_pin = DigitalInOut(pin)
            new_pin.direction = Direction.INPUT
            new_pin.pull = Pull.DOWN
            self._logical_pins.append(new_pin)

    def direction(self, pin_num, output):
        if pin_num < len(self._logical_pins):
            if output.upper() in ("1", "OUT", "OUTPUT"):
                self._logical_pins[pin_num].direction = Direction.OUTPUT
            else:
                self._logical_pins[pin_num].direction = Direction.INPUT
                self._logical_pins[pin_num].pull = Pull.DOWN
            return str(pin_num) + " " + str(self._logical_pins[pin_num].direction)
        else:
            return "ERROR: Unknown Pin: " + str(pin_num)

    def list_pins(self):
        output_str = [""]
        for pin_num, pin in enumerate(self._logical_pins):
            output_str.append("    " + str(pin_num) + " " + str(DIO_PINS[pin_num]) + " " + str(pin.direction) + " " + str(pin.value))
        return "\n".join(output_str)

    def set_or_clear(self, pin_num, set_value):
        pin_num = int(pin_num)
        if pin_num < len(self._logical_pins) and self._logical_pins[pin_num].direction == Direction.OUTPUT:
            self._logical_pins[pin_num].value = set_value
            return str(pin_num) + " " + str(set_value)
        return "ERROR: Cannot set pin: " + str(pin_num)

    def read(self, pin_num):
        pin_num = int(pin_num)
        if pin_num < len(self._logical_pins):
            return str(pin_num) + " " + str(self._logical_pins[pin_num].value)
        return "ERROR: Cannot read pin: " + str(pin_num)


class LedHandler:
    def __init__(self, led_pin):
        self.led = DigitalInOut(led_pin)
        self.led.direction = Direction.OUTPUT
        self.counter = 0

    def update(self):
        self.counter = (self.counter + 1) % 20
        if self.counter == 0:
            self.led.value = False
        elif self.counter == 15:
            self.led.value = True
    

class Relay:
    def __init__(self):
        self.dio_relays = []
        for relay_pin in RELAY_PINS:
            dio_relay = DigitalInOut(relay_pin)
            dio_relay.direction = Direction.OUTPUT
            self.dio_relays.append(dio_relay)

    def list_pins(self):
        output_str = [""]
        for pin_num, pin in enumerate(self.dio_relays):
            output_str.append("    " + str(pin_num) + " " + str(RELAY_PINS[pin_num]) + " " + str(pin.value))
        return "\n".join(output_str)

    def read(self, pin_num):
        pin_num = int(pin_num)
        if pin_num < len(self.dio_relays):
            return str(pin_num) + " " + str(self.dio_relays[pin_num].value)
        return "ERROR: Cannot read relay pin: " + str(pin_num)

    def set_or_clear(self, pin_num, set_value):
        pin_num = int(pin_num)
        if pin_num < len(self.dio_relays):
            self.dio_relays[pin_num].value = set_value
            return str(pin_num) + " " + str(set_value)
        return "ERROR: Cannot set relay pin: " + str(pin_num)

            
class SpiInterface:
    def __init__(self, spi_device, irq, reset):
        self._irq = irq
        self.spi = spi_device

        # a cache of data, used for packet parsing
        self._buffer = []

        # Reset
        reset.direction = Direction.OUTPUT
        reset.value = False
        time.sleep(0.01)
        reset.value = True
        time.sleep(0.5)

        # irq line is active high input, so set a pulldown as a precaution
        self._irq.direction = Direction.INPUT
        self._irq.pull = Pull.DOWN

    def send(self, data):
        """data: bytes"""
        with self.spi as device:
            device.write(data, end=len(data))
        return "Sent: " + bytes_to_hex(data)

    def receive(self, length):
        rx_buffer = bytearray(length)
        with self.spi as device:
            device.readinto(rx_buffer)
        return "Received: " + bytes_to_hex(rx_buffer)

def help():
    help_text = """
    Commands:
      HELP
      DIO_DIRECTION <pin number> <[OUT,IN]>
      DIO_LIST
      DIO_CLEAR <pin number>
      DIO_SET <pin number>
      DIO_READ <pin number>
      SPI_SEND <hex bytes>
      SPI_RECEIVE <hex length>
      RELAY_LIST
      RELAY_SET <pin number>
      RELAY_CLEAR <pin_number>
      RELAY_READ
      VERSION
    """

    return help_text

def handle_cmd(cmd):
    cmd_parts = cmd.split()
    actions = {
        "HELP": help,
        "SPI_SEND": lambda: spi_interface.send(hexstr_to_bytes(cmd_parts[1:])),
        "SPI_RECEIVE": lambda: spi_interface.receive(hexstr_to_bytes(cmd_parts[1])[0]),
        "DIO_DIRECTION": lambda: digital_io.direction(int(cmd_parts[1]), cmd_parts[2]),
        "DIO_LIST": lambda: digital_io.list_pins(),
        "DIO_CLEAR": lambda: digital_io.set_or_clear(int(cmd_parts[1]), False),
        "DIO_SET": lambda: digital_io.set_or_clear(int(cmd_parts[1]), True),
        "DIO_READ": lambda: digital_io.read(int(cmd_parts[1])),
        "RELAY_LIST": lambda: relay.list_pins(),
        "RELAY_CLEAR": lambda: relay.set_or_clear(int(cmd_parts[1]), False),
        "RELAY_SET": lambda: relay.set_or_clear(int(cmd_parts[1]), True),
        "RELAY_READ": lambda: relay.read(int(cmd_parts[1])),
        "VERSION": lambda: code_version()
    }
    if cmd_parts:
        command = cmd_parts[0].upper()
        action = actions.get(command, None)
        if action:
            try:
                reply = action()
            except Exception as exc:
                print("EXCEPTION: Could not run: {} {} because {}".format(command, str(action), str(exc)))
            else:
                print("{} {}".format(command, reply))
        else:
            print("{} not understood".format(command))
            print(help())

# Init
spi_bus = busio.SPI(SPI_SCK, MOSI=SPI_MOSI, MISO=SPI_MISO)
cs = DigitalInOut(board.A1)
# CS is an active low output
cs.direction = Direction.OUTPUT
cs.value = True
spi_device = SPIDevice(spi_bus, cs)
irq = DigitalInOut(SPI_IRQ)
rst = DigitalInOut(SPI_RST)

spi_interface = SpiInterface(spi_device, irq, rst)
led_handler = LedHandler(ALIVE_LED)
digital_io = DigitalIo()
relay = Relay()
supervisor.disable_autoreload() 

# Main

while True:
    if supervisor.runtime.serial_bytes_available:
        cmd = input()
        handle_cmd(cmd)
    time.sleep(0.1)
    led_handler.update()

