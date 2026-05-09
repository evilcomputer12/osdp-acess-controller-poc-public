# OSDP Bridge — STM32 Blue Pill

Thin OSDP-to-USB bridge. MCU handles protocol + crypto + GPIO. Server handles everything else.

## What the MCU does
Polls readers over RS-485, handles secure channel AES-128, forwards events to PC, accepts commands from PC, controls relays, monitors sensors.

## What it does NOT do
Users, cards, access decisions, schedules, logging, UI — that's the server's job.

## USB Protocol (newline text, any serial terminal)

**Commands (PC → MCU):** `+PD 0` add reader, `ID 0` request ID, `CAP 0` capabilities, `LSTAT 0` status, `SC 0` secure channel, `COMSET 0 5 38400` change addr/baud, `KEYSET 0 <32hex>` program SCBK, `LED 0 <14 params>` LED control, `BUZ 0 2 2 1 3` buzzer, `OUT 0 0 5 30` output, `RELAY 0 T5000` pulse relay 5s, `SENSOR?` read sensors, `STATUS`, `PING`

**Events (MCU → PC):** `!CARD 0 DEADBEEF 32 0` card read, `!KEYPAD 0 31323334` keys, `!STATE 0 SECURE` state change, `!PDID 0 E41E0A 1 01020304 1.2.0` identity, `!LSTAT 0 0 0` tamper/power, `!NAK 0 3` error, `!DOOR 0 1` sensor change, `!RELAY 0 0` pulse expired

## Wiring
PA9→MAX485 DI, PA10→MAX485 RO, PA8→DE+RE, PA0/PA1→Relays, PB0/PB1→Sensors (pullup), PA4→floating (RNG)

## Server Integration Example
```
MCU→PC:  !CARD 0 DEADBEEF 32 0
PC:      lookup → "Martin" → allowed
PC→MCU:  RELAY 0 T5000
PC→MCU:  LED 0 0 0 2 10 0 2 2 30 1 10 0 1 1
PC→MCU:  BUZ 0 2 2 1 1
```

## RAM: ~3.5 KB total (fits in 20 KB easily)
