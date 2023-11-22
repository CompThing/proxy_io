"""Serial based connections to device under test.

This module provides a serial based connection to an adaption agent that can connect to SPI
and digital IO of device under test.
The adaptation agent is expected to be a small MCU running Circuit python to take simple commands over
serial interface return responses over the serial interface.
"""
__copyright__ = "Compute Thing Ltd"

from enum import Enum, auto
import logging
import queue
from serial import Serial, serial_for_url
import threading
from queue import Empty, Queue

import time
from typing import Final, Sequence, List

from serial.serialutil import PortNotOpenError


class ConnectionType(Enum):
    SPI = auto(),
    DIO = auto(),
    RELAY = auto()


class SerialCommand(Enum):
    VERSION = auto()
    HELP = auto()
    DIO_DIRECTION = auto()
    DIO_LIST = auto()
    DIO_CLEAR = auto()
    DIO_SET = auto()
    DIO_READ = auto()
    RELAY_LIST = auto()
    RELAY_SET = auto()
    RELAY_CLEAR = auto()
    SPI_SEND = auto()
    SPI_RECEIVE = auto()
    ERROR = auto()
    EXCEPTION = auto()


class SerialInterface(threading.Thread):
    """
    Wrapper for a physical serial interface.

    The serial interface will multiplex commands for multiple higher layer services.
    This means that a single physical interface can handle both SPI and DIO services.
    Each service needs to provide its own queue for responses.

    Commands are passed in input queue as a dictionary as follows:
    cmd_dict = {
        "service": DIO | SPI
        "command": <SerialCommands>
        "data"
    }
    """
    def __init__(self, serial_port):
        """
        Connection to CircuitPython MCU.

        A single serial interface will be shared by multiple SerialConnections used by DIO and SPI.

        Instance variables:
            driver_version: Version reported by Circuitpython MCU on startup
        """
        self.driver_version: str = None
        self.serial_port = serial_port
        self.connected = False
        self.alive = False
        self.input_q = Queue()
        self.service_qs = {}
        self.next_response_q = None
        super().__init__()

    def register(self, service: ConnectionType, service_q: Queue):
        self.service_qs[service] = service_q

    def run(self):
        self.alive = True
        with serial_for_url(self.serial_port, baudrate=115200, timeout=2) as serial_connection:
            while self.alive:
                try:
                    cmd_dict = self.input_q.get(True, 0.1)
                except (Empty, TimeoutError):
                    # Catch any output unrelated to a command
                    response_bytes = serial_connection.readlines()
                    response_text = [line.decode("UTF-8") for line in response_bytes]
                    if response_text:
                        self.next_response_q.put(response_text)
                else:
                    self.next_response_q = self.service_qs[cmd_dict["service"]]
                    serial_command_str = cmd_dict["command"].name + " " + cmd_dict["data"] + "\r\n"
                    try:
                        serial_connection.write(bytes(serial_command_str, encoding="UTF-8"))
                    except PortNotOpenError:
                        response_text = "ERROR: Cannot send DIO command as serial port not open."
                    else:
                        for _interval in range(20):
                            if serial_connection.in_waiting:
                                response_bytes = serial_connection.readlines()
                                response_text = [line.decode("UTF-8") for line in response_bytes]
                                if response_text[0] == serial_command_str:
                                    _commandecho = response_text.pop(0)
                                break
                            time.sleep(0.1)
                        else:
                            response_text = ["TIMEOUT"]
                    self.next_response_q.put(response_text)

    def close_service(self, service):
        _removed = self.service_qs.pop(service, None)
        if not self.service_qs:
            self.close()

    def close(self):
        self.alive = False
        self.join(timeout=2)


class SharedSerial:

    serial_interfaces = {}

    def __init__(self, serial_port, service):
        """
        Connection to CircuitPython MCU.

        Instance variables:
            driver_version: Version reported by Circuitpython MCU on startup
        """
        self._driver_version: str = None
        self.serial_port = serial_port
        self.service = service
        self.connected = False
        self.response_q = Queue()
        self.serial_interface = self.obtain_serial_interface(serial_port, service)
        super().__init__()

    @staticmethod
    def clean_response(text_response: List[str]):
        """
        Convert a raw byte string into a response structure.
        
        Response Structure:
            "Command":  original command or ERROR
            "data": Key value pairing from first line of response
            "extension": 2nd and subsequent lines from response
        """
        if not text_response:
            command = SerialCommand.ERROR
            data = {"error": "No response from MCU"}
        else:
            response_fields = text_response[0].split()
            if "ERROR:" in response_fields[:2]:
                command = SerialCommand.ERROR
                data = {"error": text_response[0]}
            if "EXCEPTION:" in response_fields[:2]:
                command = SerialCommand.EXCEPTION
                data = {"exception": text_response[0]}
            else:
                command = SerialCommand[response_fields[0]]
                data = " ".join(response_fields[1:])
        response = {
            "command": command,
            "data": data
        }
        if len(text_response) > 1:
            response["extension"] = "\n".join(text_response[1:])
        return response

    def obtain_serial_interface(self, serial_port, service):
        if serial_port not in self.__class__.serial_interfaces:
            serial_interface = SerialInterface(serial_port)
            serial_interface.daemon = True
            serial_interface.start()
            time.sleep(0.01)
            self.__class__.serial_interfaces[serial_port] = serial_interface
        self.__class__.serial_interfaces[serial_port].register(
            service=service,
            service_q=self.response_q
            )
        return self.__class__.serial_interfaces[serial_port]

    @property
    def driver_version(self):
        if not self._driver_version:
            driver_version_response = self.handle_command(
                command=SerialCommand.VERSION,
                data=""
            )
            self._driver_version = driver_version_response["data"]
        return self._driver_version

    def is_connected(self):
        return self.connected

    def handle_command(self, command, data):
        message_to_send = {
            "service": self.service,
            "command": command,
            "data": data
        }
        self.serial_interface.input_q.put(message_to_send)
        try:
            raw_response = self.response_q.get(True, 10)
        except queue.Empty:
            raw_response = ""
        cleaned = self.clean_response(raw_response)
        if "error" in cleaned or "exception" in cleaned:
            for key, value in cleaned.items():
                print(f"Key: {key} Value: {value}")
            return cleaned
        return cleaned

    def close_service(self, service):
        self.__class__.serial_interfaces[self.serial_port].close_service(
            service=service
            )


class BaseIo:
    """Common behaviour for Binary and Relay IO."""
    SERVICE = None

    def __init__(self, config: dict = None):
        if not config:
            # Proper init has to be done later
            self.shared_serial = None
            self.io_configuration: dict = {}
        else:
            self.io_configuration = config
            self.set_configuration(config)

    def get_driver_version(self) -> str:
        """Returns version Circuit Python MCU code."""
        return self.shared_serial.driver_version

    def get_list_of_devices_names(self) -> list:
        """Returns list of ports of connected MCUs."""
        device_names = [self.shared_serial.serial_port]
        return device_names

    def check_for_device(self, expected_device_name: str) -> bool:
        """
        Returns true if the provided device name is found.
        
        For a serial based IO connection, the device name is used to identify the
        serial port.
        If the serial connection has not already been made, it will be done here.
        """
        logging.debug(f"DigitalIO.check_for_device() called with: {expected_device_name=}")
        if not self.shared_serial:
            if "interface" not in self.io_configuration:
                self.io_configuration["interface"] = expected_device_name
            self.set_configuration()

        return self.shared_serial.is_connected()

    def set_configuration(self, config: dict = None):
        """Sets overall configuration."""
        logging.debug(f"IO.set_configuration() called with: {config=}")
        if config:
            self.io_configuration = config
        serial_port = self.io_configuration["interface"]
        self.shared_serial = SharedSerial(serial_port, service=self.__class__.SERVICE)

    def close(self):
        self.shared_serial.close_service(self.__class__.SERVICE)


class DigitalIO(BaseIo):
    """Access Digital IO via Serial Circuitpython MCU."""
    SERVICE = ConnectionType.DIO

    def __init__(self, config: dict = None):
        super().__init__(config)
        if not config:
            # Proper init has to be done later
            self.digital_input_configuration: dict = {}
            self.digital_output_configuration: dict = {}
            self.encoder_output_configuration: dict = {}

    @staticmethod
    def log_available_devices():
        """Prints out all found devices."""

    @staticmethod
    def log_avaliable_do_lines(device_name: str):
        """Prints out all the found lines for the provided device."""

    def set_configuration(self, config: dict = None):
        """Sets overall configuration."""
        logging.debug(f"DigitalIO.set_configuration() called with: {config=}")
        super().set_configuration(config)
        for input_value in self.io_configuration["inputs"].values():
            response = self.set_direction(pin_num=input_value, output=False)
            print(response)
        for output_value in self.io_configuration["outputs"].values():
            response = self.set_direction(pin_num=output_value, output=True)
            print(response)

    def info(self):
        dio_info = self.shared_serial.handle_command(
            command=SerialCommand.DIO_LIST,
            data=""
        )
        return dio_info.get("extension", "")

    def set_direction(self, pin_num, output):
        if output:
            data = "OUT"
        else:
            data = "IN"
        output = self.shared_serial.handle_command(
            command=SerialCommand.DIO_DIRECTION,
            data=f"{pin_num} {data}"
        )
        return output["data"]

    def read_input(self, input_name: str) -> str:
        """Gets the input state."""
        pin_info = self.shared_serial.handle_command(
            command=SerialCommand.DIO_READ,
            data=f"{input_name}"
        )
        return pin_info

    def write_output(self, output_name: str, output_state: str) -> str:
        """Sets the output state.
        output_name: str
        output_state: str
        """
        level = None
        if output_state == self.LEVEL_HIGH:
            level = True
        elif output_state == self.LEVEL_LOW:
            level = False
        return
        if output_state.upper() in ("TRUE", "SET"):
            pin_set_or_clear = SerialCommand.DIO_SET
        else:
            pin_set_or_clear = SerialCommand.DIO_CLEAR
        pin_set = self.shared_serial.handle_command(
            command=pin_set_or_clear,
            data=f"{output_name}"
        )
        return pin_set

    def force_encoder_output(self, encoder_name: str, requested_output_state: int) -> str:
        """Sets the encoder output state.
        Args:
            encoder_name: str : name used for encoder reference
            requested_output_state: int : encoder pin state to set
        """
        raise NotImplementedError("Cannot use encoder with serial controller.")

    def create_encoder_pulses(self, encoder_name: str, pulses_to_create: int):
        """Creation of encoder output pulses.
        Args:
            encoder_name: str : name used for encoder reference
            pulses_to_create: int : number of pulses to create and direction
                - positive/negative values will together with the encoder configuration determine emulation sequence
        """
        raise NotImplementedError("Cannot send encoder pulses via serial controller.")


class RelayIO(BaseIo):
    """Access Digital IO via Serial Circuitpython MCU."""
    SERVICE = ConnectionType.RELAY

    def set_relay_close(self, relay_number, closed: bool):
        if closed:
            relay_set_or_clear = SerialCommand.RELAY_SET
        else:
            relay_set_or_clear = SerialCommand.RELAY_CLEAR
        relay_info = self.shared_serial.handle_command(
            command=relay_set_or_clear,
            data=f"{relay_number}"
        )
        return relay_info

    def info(self):
        relay_info = self.shared_serial.handle_command(
            command=SerialCommand.RELAY_LIST,
            data=""
        )
        return relay_info


class SpiIo(BaseIo):
    def __init__(self, config: dict = None):
        self.spi_configuration = config
        serial_port = self.spi_configuration["interface"]
        self.shared_serial = SharedSerial(
            serial_port,
            service=ConnectionType.SPI
            )

    def send_message(self, message: bytes):
        response = self.shared_serial.handle_command(
            SerialCommand.SPI_SEND,
            message
            )
        print(response)
        return response

    def receive_message(self, receive_length: int) -> bytes:
        response = self.shared_serial.handle_command(
            SerialCommand.SPI_RECEIVE,
            bytes([receive_length])
            )
        print(response)
        return response

    def close(self):
        self.shared_serial.close_service(ConnectionType.SPI)
