import logging
import queue
import pytest
import os
from serial_host import SerialInterface, SerialCommand, ConnectionType

if os.name == 'nt':
    SERIAL_INTERFACE = "COM4"
else:
    SERIAL_INTERFACE = "/dev/ttyACM0"

if "SERIAL_INTERFACE" in os.environ:
    SERIAL_INTERFACE = os.environ["SERIAL_INTERFACE"]

TEST_CONFIG = {
    "interface": SERIAL_INTERFACE,
    "inputs": {
        "in0": 0,
        "in2": 2,
        "in4": 4,
        "in6": 6
    },
    "outputs": {
        "out1": 1,
        "out3": 3,
        "out5": 5,
        "out7": 7
    }
}


@pytest.fixture(scope="session")
def serial_binding():
    serial_interface = SerialInterface(TEST_CONFIG["interface"])
    serial_interface.start()
    output_q = queue.Queue()
    serial_interface.register(ConnectionType.DIO, output_q)
    yield serial_interface, output_q
    serial_interface.close()

def test_version(serial_binding):
    """Test version can be obtained via both digital and spi interfaces."""
    serial_interface, service_q = serial_binding
    message_to_send = {
        "service": ConnectionType.DIO,
        "command": SerialCommand.VERSION,
        "data": ""
    }
    serial_interface.input_q.put(message_to_send)
    try:
        response = service_q.get(True, 10)
    except queue.Empty:
        assert False
    assert "VERSION" in response[0]
    assert len(response[0].split()) == 2

