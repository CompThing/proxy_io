import logging
import pytest
import os
from serial_host import DigitalIO, RelayIO, SpiIo, SerialCommand

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
def digital_relay_and_spi():
    spi_interface = SpiIo(config=TEST_CONFIG)
    dio_interface = DigitalIO(config=TEST_CONFIG)
    relay_interface = RelayIO(config=TEST_CONFIG)
    yield dio_interface, relay_interface, spi_interface
    spi_interface.close()
    dio_interface.close()
    relay_interface.close()

def test_version(digital_relay_and_spi):
    """Test version can be obtained via both digital and spi interfaces."""
    dio, realy, spi = digital_relay_and_spi
    for interface in dio, spi:
        driver_version = interface.get_driver_version()
        assert driver_version == "0.0.1"

def test_pin_read(digital_relay_and_spi):
    """Test version can be obtained via both digital and spi interfaces."""
    dio, relay, spi = digital_relay_and_spi
    pin_list = dio.read_input("1")
    assert pin_list["command"] == SerialCommand.DIO_READ
    assert len(pin_list) == 2
    print(pin_list)

def test_relay_list(digital_relay_and_spi):
    dio, relay, spi = digital_relay_and_spi
    relay_list = relay.info()
    logging.info(relay_list)
    assert "extension" in relay_list
    print(relay_list)

def test_relay_close(digital_relay_and_spi):
    dio, relay, spi = digital_relay_and_spi
    relay_state = relay.set_relay_close(0, True)
    assert len(relay_state) > 10
    print(relay_state)

def test_relay_open(digital_relay_and_spi):
    dio, relay, spi = digital_relay_and_spi
    relay_state = relay.set_relay_close(1, False)
    assert len(relay_state) > 10
    print(relay_state)
