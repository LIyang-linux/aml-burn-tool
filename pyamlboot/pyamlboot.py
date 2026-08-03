# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0 OR MIT
"""
Amlogic USB Boot Protocol Library
Based on pyamlboot by BayLibre / Neil Armstrong
https://github.com/superna9999/pyamlboot

Adapted for aml-burn-tool — 国产 eMMC 兼容版
"""
import os
import time
import usb.core
from struct import pack

# USB Control Transfer Request Codes
REQ_WRITE_MEM     = 0x01
REQ_READ_MEM      = 0x02
REQ_FILL_MEM      = 0x03
REQ_MODIFY_MEM    = 0x04
REQ_RUN_IN_ADDR   = 0x05
REQ_WRITE_AUX     = 0x06
REQ_READ_AUX      = 0x07
REQ_WR_LARGE_MEM  = 0x11
REQ_RD_LARGE_MEM  = 0x12
REQ_IDENTIFY_HOST = 0x20
REQ_TPL_CMD       = 0x30
REQ_TPL_STAT      = 0x31
REQ_WRITE_MEDIA   = 0x32
REQ_READ_MEDIA    = 0x33
REQ_BULKCMD       = 0x34
REQ_PASSWORD      = 0x35
REQ_NOP           = 0x36
REQ_GET_AMLC      = 0x50
REQ_WRITE_AMLC    = 0x60

FLAG_KEEP_POWER_ON = 0x10

MAX_LARGE_BLOCK_COUNT = 65535


class AmlogicSoC:
    """Represents an Amlogic SoC in USB boot Mode"""

    def __init__(self, idVendor=0x1b8e, idProduct=0xc003, timeout=0):
        """Find and connect to Amlogic device in USB boot mode"""
        start = time.time()
        while True:
            self.dev = usb.core.find(idVendor=idVendor, idProduct=idProduct)
            if self.dev is not None:
                break
            if timeout is not None and time.time() > start + timeout:
                break
            time.sleep(0.1)

        if self.dev is None:
            raise ValueError('Device not found')

    def writeSimpleMemory(self, address, data):
        """Write up to 64 bytes to memory via control transfer"""
        if len(data) > 64:
            raise ValueError('Maximum size of 64 bytes')
        self.dev.ctrl_transfer(
            bmRequestType=0x40,
            bRequest=REQ_WRITE_MEM,
            wValue=address >> 16,
            wIndex=address & 0xffff,
            data_or_wLength=data
        )

    def writeMemory(self, address, data):
        """Write data to memory in 64-byte chunks"""
        length = len(data)
        offset = 0
        while length:
            self.writeSimpleMemory(address + offset, data[offset:offset + 64])
            if length > 64:
                length -= 64
            else:
                break
            offset += 64

    def readSimpleMemory(self, address, length):
        """Read up to 64 bytes from memory"""
        if length == 0:
            return b''
        if length > 64:
            raise ValueError('Maximum size of 64 bytes')
        ret = self.dev.ctrl_transfer(
            bmRequestType=0xc0,
            bRequest=REQ_READ_MEM,
            wValue=address >> 16,
            wIndex=address & 0xffff,
            data_or_wLength=length
        )
        return bytes(ret)

    def readMemory(self, address, length):
        """Read data from memory in 64-byte chunks"""
        data = b''
        offset = 0
        while length:
            if length >= 64:
                data += self.readSimpleMemory(address + offset, 64)
                length -= 64
                offset += 64
            else:
                data += self.readSimpleMemory(address + offset, length)
                break
        return data

    def _writeLargeMemory(self, address, data, blockLength=64, appendZeros=False):
        """Write large data via control + bulk transfer"""
        if appendZeros:
            append = len(data) % blockLength
            if append > 0:
                data = data + b'\x00' * (blockLength - append)
        elif len(data) % blockLength != 0:
            raise ValueError('Large Data must be a multiple of block length')

        blockCount = int(len(data) / blockLength)

        controlData = pack('<IIII', address, len(data), 0, 0)

        cfg = self.dev.get_active_configuration()
        intf = cfg[(0, 0)]
        ep = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT
        )

        self.dev.ctrl_transfer(
            bmRequestType=0x40,
            bRequest=REQ_WR_LARGE_MEM,
            wValue=blockLength,
            wIndex=blockCount,
            data_or_wLength=controlData
        )

        offset = 0
        while blockCount > 0:
            ep.write(data[offset:offset + blockLength], 1000)
            offset += blockLength
            blockCount -= 1

    def writeLargeMemory(self, address, data, blockLength=64, appendZeros=False):
        """Write large data, splitting into MAX_LARGE_BLOCK_COUNT chunks"""
        blockCount = int(len(data) / blockLength)
        if len(data) % blockLength > 0:
            blockCount += 1

        transferCount = int(blockCount / MAX_LARGE_BLOCK_COUNT)
        if blockCount % MAX_LARGE_BLOCK_COUNT > 0:
            transferCount += 1

        offset = 0
        while transferCount > 0:
            if (offset + (MAX_LARGE_BLOCK_COUNT * blockLength)) > len(data):
                writeLength = len(data) - offset
            else:
                writeLength = MAX_LARGE_BLOCK_COUNT * blockLength
            self._writeLargeMemory(
                address + offset,
                data[offset:offset + writeLength],
                blockLength, appendZeros
            )
            offset += writeLength
            transferCount -= 1

    def run(self, address, keep_power=True):
        """Jump to address and execute"""
        if keep_power:
            data = address | FLAG_KEEP_POWER_ON
        else:
            data = address
        controlData = pack('<I', data)
        self.dev.ctrl_transfer(
            bmRequestType=0x40,
            bRequest=REQ_RUN_IN_ADDR,
            wValue=address >> 16,
            wIndex=address & 0xffff,
            data_or_wLength=controlData
        )

    def identify(self):
        """Identify the ROM Protocol — returns [ROM_major, ROM_minor, Stage_major, Stage_minor]"""
        ret = self.dev.ctrl_transfer(
            bmRequestType=0xc0,
            bRequest=REQ_IDENTIFY_HOST,
            wValue=0, wIndex=0,
            data_or_wLength=8
        )
        return bytes(ret)

    def bulkCmd(self, cmd):
        """Send a bulk command to U-Boot (after TPL is running)"""
        terminated = (cmd + '\0').encode()[:128]
        self.dev.ctrl_transfer(
            bmRequestType=0x40,
            bRequest=REQ_BULKCMD,
            wValue=0, wIndex=0,
            data_or_wLength=terminated
        )

    def tplStat(self, timeout=None):
        """Read TPL status"""
        return self.dev.ctrl_transfer(
            bmRequestType=0xc0,
            bRequest=REQ_TPL_STAT,
            wValue=0, wIndex=0,
            data_or_wLength=0x40,
            timeout=timeout
        )

    def nop(self):
        """No-Operation ping"""
        self.dev.ctrl_transfer(
            bmRequestType=0x40,
            bRequest=REQ_NOP,
            wValue=0, wIndex=0,
            data_or_wLength=None
        )

    def dispose(self):
        """Release USB device resources"""
        try:
            usb.util.dispose_resources(self.dev)
            self.dev = None
        except Exception:
            pass
