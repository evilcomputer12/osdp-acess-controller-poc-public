/*
 * OSDP Bridge — STM32 Blue Pill (STM32F103C8T6)
 * 
 * Pure OSDP-to-USB-CDC bridge. The MCU handles ONLY:
 *   - RS-485 OSDP protocol (polling, framing, crypto, secure channel)
 *   - GPIO relay/sensor control
 *   - Forwarding events to the PC over USB CDC
 *   - Accepting commands from the PC over USB CDC
 *
 * The PC/server handles ALL business logic:
 *   users, cards, schedules, access decisions, logging, UI
 *
 * ─── USB CDC Protocol (newline-terminated text) ─────────
 *
 * Commands (PC → MCU):
 *   +PD <addr> [scbk_32hex]      Add reader at address
 *   ID <n>                        Request reader identity
 *   CAP <n>                       Request capabilities
 *   LSTAT <n>                     Request local status
 *   ISTAT <n>                     Request input status
 *   OSTAT <n>                     Request output status
 *   SC <n>                        Initiate secure channel
 *   COMSET <n> <addr> <baud>      Change reader addr/baud
 *   KEYSET <n> <32hex>            Program SCBK (requires SC)
 *   LED <n> <14 space-sep bytes>  Send LED command
 *   BUZ <n> <tone> <on> <off> <cnt>  Buzzer
 *   OUT <n> <output> <code> <timer>   Output control
 *   RELAY <n> <0|1|Tms>           Set/pulse GPIO relay
 *   RELAYGPIO <0|1>               Disable/enable physical relay GPIO drive
 *   SENSOR?                       Query sensor pins
 *   STATUS                        System status summary
 *   PING                          Keepalive
 *
 * Events (MCU → PC):
 *   !CARD <n> <hex> <bits> <fmt>        Card read
 *   !KEYPAD <n> <hex_keys>              Keypad data
 *   !STATE <n> <OFFLINE|ONLINE|SECURE>  Reader state change
 *   !REPLY <n> <code_hex> <data_hex>    Every OSDP reply (raw)
 *   !PDID <n> <vendor> <model> <serial> <fw>
 *   !LSTAT <n> <tamper> <power>
 *   !NAK <n> <error_code>
 *   !SENSOR <mask_hex>                  Sensor state
 *   !DOOR <n> <0|1>                     Door sensor change
 *   PONG
 *   OK
 *   ERR:<message>
 *
 * Wiring:
 *   PA9/PA10 → USART1 TX/RX → MAX485 DI/RO
 *   PA8      → MAX485 DE+RE
 *   PA0      → Relay 1
 *   PA1      → Relay 2
 *   PB0      → Door sensor 1 (pullup, LOW=closed)
 *   PB1      → Door sensor 2 (pullup, LOW=closed)
 *   PA4      → Leave floating (ADC noise for RNG)
 *   PC13     → Onboard LED (heartbeat)
 *   USB      → CDC serial to PC
 */

#include <Arduino.h>
#include "osdp_cp.h"

// ─── Pin config ──────────────────────────────────────────────────
#define PIN_RS485_DE  PA8
#define PIN_RELAY0    PA0
#define PIN_RELAY1    PA1
#define PIN_SENSOR0   PB0
#define PIN_SENSOR1   PB1
#define PIN_HEARTBEAT PC13
#define NUM_RELAYS    2
#define NUM_SENSORS   2

static const uint32_t RELAY_OSDP_IDLE_GUARD_MS = 80;  // was 40 — wider guard after last reply
static const uint32_t RELAY_DEFER_MAX_MS = 800;

static const uint8_t relayPins[NUM_RELAYS] = {PIN_RELAY0, PIN_RELAY1};
static const uint8_t sensorPins[NUM_SENSORS] = {PIN_SENSOR0, PIN_SENSOR1};
static uint32_t relayPulseEnd[NUM_RELAYS] = {};
static bool relayPulsing[NUM_RELAYS] = {};
static bool relayState[NUM_RELAYS] = {};
static bool relaySwitchPending[NUM_RELAYS] = {};
static bool relayPendingState[NUM_RELAYS] = {};
static bool relayPendingPulse[NUM_RELAYS] = {};
static uint32_t relayPendingPulseMs[NUM_RELAYS] = {};
static uint32_t relayPendingSinceMs[NUM_RELAYS] = {};
static uint8_t lastSensor[NUM_SENSORS] = {};
static bool relayGpioEnabled = true;

OsdpCp osdp;
char cmdBuf[512];
size_t cmdLen = 0;
Stream *usb = &Serial;  // USB CDC
volatile bool verboseMode = false;
static uint32_t lastHeartbeat = 0;
static uint32_t lastAutoStatus = 0;

// Bootloader magic word -- written to BKP_DR1 before reset
#define BL_MAGIC_WORD  0xB007U
#define FW_VERSION     "1.2.34"

// ── IWDG (Independent Watchdog) ──────────────────────────────
// The bootloader starts the IWDG before jumping here.  IWDG cannot be stopped,
// so we just keep feeding it.  If the bootloader was bypassed (ST-Link direct
// flash) we start it ourselves.
static void iwdgInit() {
    IWDG->KR  = 0xCCCC;          // start (forces LSI on; no-op if already running)
    IWDG->KR  = 0x5555;          // unlock PR/RLR
    IWDG->PR  = 4;               // prescaler /64  (LSI 40kHz → 625 Hz)
    IWDG->RLR = 2500;            // reload → ~4 s timeout
    while (IWDG->SR) {}          // wait for registers to sync (LSI now running)
    IWDG->KR  = 0xAAAA;          // first feed with new reload value
}
static inline void iwdgFeed() { IWDG->KR = 0xAAAA; }

// ─── Emit events to PC ──────────────────────────────────────────
static void onCard(uint8_t pi, const CardData *c) {
    char hex[MAX_CARD_BYTES * 2 + 1];
    hexEncode(hex, c->data, c->dataLen);
    usb->printf("!CARD %d %s %d %d\n", pi, hex, c->bitCount, c->format);
}

static void onKeypad(uint8_t pi, const uint8_t *keys, uint8_t count) {
    if (count > 31) count = 31;  // prevent hex[64] buffer overflow
    // Deduplicate: OSDP readers re-report the same keypad data on every POLL
    // until their internal buffer times out. Keep the window short so repeated
    // identical key presses are not swallowed as duplicates.
    static uint8_t lastKeys[32];
    static uint8_t lastCount = 0;
    static uint8_t lastPi = 0xFF;
    static uint32_t lastMs = 0;
    uint32_t now = millis();
    if (count == lastCount && pi == lastPi && count > 0 &&
        (now - lastMs) < 120 && memcmp(keys, lastKeys, count) == 0) {
        return;
    }
    memcpy(lastKeys, keys, count);
    lastCount = count;
    lastPi = pi;
    lastMs = now;

    char hex[64];
    hexEncode(hex, keys, count);
    usb->printf("!KEYPAD %d %s\n", pi, hex);
}

static void onStatus(uint8_t pi, PdState s) {
    const char *n[] = {"OFFLINE", "ONLINE", "SC_INIT", "SECURE", "ERROR"};
    usb->printf("!STATE %d %s\n", pi, n[s]);
}

static void onReply(uint8_t pi, uint8_t code, const uint8_t *data, uint16_t dlen) {
    // Emit structured events for specific replies
    switch (code) {
    case REP_PDID:
        if (dlen >= 12) {
            char v[7], s[9];
            hexEncode(v, data, 3); hexEncode(s, &data[5], 4);
            usb->printf("!PDID %d %s %d %s %d.%d.%d\n", pi, v, data[3], s, data[9], data[10], data[11]);
        }
        break;
    case REP_PDCAP:
        usb->printf("!PDCAP %d", pi);
        for (uint16_t i = 0; i + 2 < dlen; i += 3)
            usb->printf(" %d:%d:%d", data[i], data[i+1], data[i+2]);
        usb->println();
        break;
    case REP_LSTATR:
        if (dlen >= 2) usb->printf("!LSTAT %d %d %d\n", pi, data[0], data[1]);
        break;
    case REP_ISTATR: {
        char hex[17]; hexEncode(hex, data, dlen > 8 ? 8 : dlen);
        usb->printf("!ISTAT %d %s\n", pi, hex);
        break;
    }
    case REP_OSTATR: {
        char hex[17]; hexEncode(hex, data, dlen > 8 ? 8 : dlen);
        usb->printf("!OSTAT %d %s\n", pi, hex);
        break;
    }
    case REP_NAK:
        usb->printf("!NAK %d %d\n", pi, dlen > 0 ? data[0] : 0xFF);
        break;
    case REP_COM:
        if (dlen >= 5) {
            uint32_t baud = data[1] | (data[2]<<8) | (data[3]<<16) | ((uint32_t)data[4]<<24);
            usb->printf("!COM %d %d %lu\n", pi, data[0], baud);
        }
        break;
    case REP_BUSY:
        usb->printf("!BUSY %d\n", pi);
        break;
    case REP_BIOREADR:
        usb->printf("!BIOREADR %d len=%d\n", pi, dlen);
        break;
    case REP_BIOMATCHR:
        usb->printf("!BIOMATCHR %d len=%d\n", pi, dlen);
        break;
    case REP_CCRYPT:
        usb->printf("!CCRYPT %d len=%d\n", pi, dlen);
        break;
    case REP_RMACI:
        usb->printf("!RMACI %d len=%d\n", pi, dlen);
        break;
    default:
        break;
    }
}

static void onDebug(uint8_t pi, const char *msg) {
    if (!verboseMode) return;
    usb->printf("!DBG %d %s\n", pi, msg);
}

static void onBio(uint8_t pi, const BioData *b) {
    if (b->dataLen > 0) {
        // Bio read: template data available (enrollment/scan)
        char hex[MAX_BIO_BYTES * 2 + 1];
        uint16_t encLen = b->dataLen > MAX_BIO_BYTES ? MAX_BIO_BYTES : b->dataLen;
        hexEncode(hex, b->data, encLen);
        usb->printf("!BIO %d reader=%d status=%d type=%d quality=%d len=%d %s\n",
                     pi, b->readerNum, b->status, b->type, b->quality, b->dataLen, hex);
    } else {
        // Bio match result (no template data)
        usb->printf("!BIOMATCH %d reader=%d status=%d quality=%d\n",
                     pi, b->readerNum, b->status, b->quality);
    }
}

// ─── Parse helper ────────────────────────────────────────────────
static int splitArgs(char *line, char **argv, int max) {
    int argc = 0; char *p = line;
    while (*p && argc < max) {
        while (*p == ' ' || *p == '\t') p++;
        if (!*p) break;
        argv[argc++] = p;
        while (*p && *p != ' ' && *p != '\t') p++;
        if (*p) *p++ = 0;
    }
    return argc;
}

// ─── Relay output state machine ─────────────────────────────
static void driveRelayPin(int n, bool on) {
    if (relayGpioEnabled) digitalWrite(relayPins[n], on ? HIGH : LOW);
}

static void scheduleRelaySwitch(int n, bool on, bool pulse, uint32_t pulseMs) {
    relayPendingState[n] = on;
    relayPendingPulse[n] = pulse;
    relayPendingPulseMs[n] = pulseMs;
    relayPendingSinceMs[n] = millis();
    relaySwitchPending[n] = true;
}

// ─── Handle one command line from PC ─────────────────────────────
static void handleCmd(char *line) {
    char *av[16] = {};
    int ac = splitArgs(line, av, 16);
    if (!ac) return;

    // PING
    if (!strcmp(av[0], "PING")) { usb->println("PONG"); return; }

    // FWVERSION
    if (!strcmp(av[0], "FWVERSION")) {
        usb->printf("!FWVERSION %s\n", FW_VERSION);
        return;
    }

    // BOOTLOADER — write magic to BKP_DR1 and reset into bootloader
    if (!strcmp(av[0], "BOOTLOADER")) {
        usb->println("OK REBOOTING");
        usb->flush();
        delay(100);
        RCC->APB1ENR |= RCC_APB1ENR_PWREN | RCC_APB1ENR_BKPEN;
        __DSB();
        PWR->CR |= PWR_CR_DBP;       // enable backup domain write
        BKP->DR1 = BL_MAGIC_WORD;
        PWR->CR &= ~PWR_CR_DBP;
        NVIC_SystemReset();  // does not return
    }

    // DEBUG [0|1]
    if (!strcmp(av[0], "DEBUG")) {
        if (ac >= 2) verboseMode = atoi(av[1]);
        else verboseMode = !verboseMode;
        usb->printf("OK debug=%d\n", verboseMode ? 1 : 0);
        return;
    }

    // STATUS
    if (!strcmp(av[0], "STATUS")) {
        usb->printf("!STATUS readers=%d tx=%lu rx=%lu uptime=%lu\n",
                     osdp.numPd, osdp.busTxCount, osdp.busRxCount, millis() / 1000);
        for (int i = 0; i < osdp.numPd; i++) {
            PdCtx *p = &osdp.pd[i];
            const char *sn[] = {"OFFLINE","ONLINE","SC_INIT","SECURE","ERROR"};
            usb->printf("!PD %d addr=%d state=%s sc=%d tamper=%d power=%d\n",
                         i, p->addr, sn[p->state], p->scActive, p->tamper, p->power);
        }
        return;
    }

    // +PD <addr> [scbk_32hex]
    if (!strcmp(av[0], "+PD") && ac >= 2) {
        uint8_t addr = atoi(av[1]);
        uint8_t key[16]; const uint8_t *kp = nullptr;
        if (ac >= 3 && strlen(av[2]) == 32) {
            hexDecode(key, av[2], 16); kp = key;
        }
        int idx = osdp.addPd(addr, kp);
        if (idx >= 0) usb->printf("OK pd=%d\n", idx);
        else usb->println("ERR:MAX_READERS");
        return;
    }

    // SENSOR?
    if (!strcmp(av[0], "SENSOR?")) {
        uint8_t mask = 0;
        for (int i = 0; i < NUM_SENSORS; i++)
            if (digitalRead(sensorPins[i]) == LOW) mask |= (1 << i);
        usb->printf("!SENSOR 0x%02X\n", mask);
        return;
    }

    // RELAYGPIO <0|1> - diagnostics: keep logical relay events, bypass coil drive.
    if (!strcmp(av[0], "RELAYGPIO") && ac >= 2) {
        relayGpioEnabled = atoi(av[1]) != 0;
        for (int i = 0; i < NUM_RELAYS; i++) {
            digitalWrite(relayPins[i], relayGpioEnabled && relayState[i] ? HIGH : LOW);
        }
        usb->printf("OK relay_gpio=%d\n", relayGpioEnabled ? 1 : 0);
        return;
    }

    // RELAY <n> <0|1|Tms>
    if (!strcmp(av[0], "RELAY") && ac >= 3) {
        int n = atoi(av[1]);
        if (n < 0 || n >= NUM_RELAYS) { usb->println("ERR:BAD_RELAY"); return; }
        if (av[2][0] == 'T' || av[2][0] == 't') {
            uint32_t ms = atol(&av[2][1]);
            scheduleRelaySwitch(n, true, true, ms);
        } else {
            scheduleRelaySwitch(n, av[2][0] == '1', false, 0);
        }
        usb->println("OK");
        return;
    }

    // All reader commands need index as first arg
    if (ac < 2) { usb->println("ERR:NEED_ARGS"); return; }
    int ri = atoi(av[1]);
    if (ri < 0 || ri >= osdp.numPd) { usb->println("ERR:BAD_PD"); return; }

    if (!strcmp(av[0], "ID"))    { osdp.sendId(ri);    usb->println("OK"); return; }
    if (!strcmp(av[0], "CAP"))   { osdp.sendCap(ri);   usb->println("OK"); return; }
    if (!strcmp(av[0], "LSTAT")) { osdp.sendLstat(ri);  usb->println("OK"); return; }
    if (!strcmp(av[0], "ISTAT")) { osdp.sendIstat(ri);  usb->println("OK"); return; }
    if (!strcmp(av[0], "OSTAT")) { osdp.sendOstat(ri);  usb->println("OK"); return; }
    if (!strcmp(av[0], "SC"))    { osdp.initSecureChannel(ri); usb->println("OK"); return; }

    if (!strcmp(av[0], "COMSET") && ac >= 4) {
        osdp.sendComset(ri, atoi(av[2]), atol(av[3]));
        usb->println("OK"); return;
    }
    if (!strcmp(av[0], "KEYSET") && ac >= 3 && strlen(av[2]) == 32) {
        uint8_t key[16]; hexDecode(key, av[2], 16);
        osdp.sendKeyset(ri, key);
        if (osdp.pd[ri].scActive) {
            memcpy(osdp.pd[ri].scbk, key, 16);
            osdp.pd[ri].useScbkD = false;
            usb->println("OK");
        } else {
            usb->println("ERR:NEED_SC");
        }
        return;
    }
    if (!strcmp(av[0], "BUZ") && ac >= 6) {
        BuzCmd b = {0, (uint8_t)atoi(av[2]), (uint8_t)atoi(av[3]),
                    (uint8_t)atoi(av[4]), (uint8_t)atoi(av[5])};
        osdp.sendBuz(ri, &b); usb->println("OK"); return;
    }
    if (!strcmp(av[0], "OUT") && ac >= 5) {
        OutCmd o = {(uint8_t)atoi(av[2]), (uint8_t)atoi(av[3]), (uint16_t)atoi(av[4])};
        osdp.sendOut(ri, &o); usb->println("OK"); return;
    }
    if (!strcmp(av[0], "LED") && ac >= 15) {
        LedCmd l = {(uint8_t)atoi(av[2]), (uint8_t)atoi(av[3]),
                    (uint8_t)atoi(av[4]), (uint8_t)atoi(av[5]), (uint8_t)atoi(av[6]),
                    (uint8_t)atoi(av[7]), (uint8_t)atoi(av[8]), (uint16_t)atoi(av[9]),
                    (uint8_t)atoi(av[10]), (uint8_t)atoi(av[11]), (uint8_t)atoi(av[12]),
                    (uint8_t)atoi(av[13]), (uint8_t)atoi(av[14])};
        osdp.sendLed(ri, &l); usb->println("OK"); return;
    }
    // BIOREAD <n> <reader> <type> <format> <quality>
    if (!strcmp(av[0], "BIOREAD") && ac >= 6) {
        osdp.sendBioRead(ri, (uint8_t)atoi(av[2]), (uint8_t)atoi(av[3]),
                         (uint8_t)atoi(av[4]), (uint8_t)atoi(av[5]));
        usb->println("OK"); return;
    }
    // BIOMATCH <n> <reader> <type> <format> <quality> <template_hex>
    if (!strcmp(av[0], "BIOMATCH") && ac >= 7) {
        uint8_t tmpl[MAX_BIO_BYTES];
        int tlen = hexDecode(tmpl, av[6], MAX_BIO_BYTES);
        if (tlen > 0) {
            osdp.sendBioMatch(ri, (uint8_t)atoi(av[2]), (uint8_t)atoi(av[3]),
                              (uint8_t)atoi(av[4]), (uint8_t)atoi(av[5]), tmpl, tlen);
            usb->println("OK");
        } else {
            usb->println("ERR:BAD_TEMPLATE");
        }
        return;
    }

    usb->println("ERR:UNKNOWN");
}

// ─── Check for door sensor changes → async event ────────────────
static void checkSensors() {
    for (int i = 0; i < NUM_SENSORS; i++) {
        uint8_t now = digitalRead(sensorPins[i]);
        if (now != lastSensor[i]) {
            lastSensor[i] = now;
            usb->printf("!DOOR %d %d\n", i, now == LOW ? 1 : 0);
        }
    }
}

// ─── Check relay pulse timeouts ──────────────────────────────────
static void checkRelays() {
    uint32_t now = millis();
    for (int i = 0; i < NUM_RELAYS; i++) {
        if (relaySwitchPending[i]) {
            bool turningOn = relayPendingState[i];
            bool canDefer = turningOn && i < osdp.numPd;
            if (canDefer && !osdp.isReaderIdle(i, now, RELAY_OSDP_IDLE_GUARD_MS) &&
                (now - relayPendingSinceMs[i]) < RELAY_DEFER_MAX_MS) {
                continue;
            }
            relaySwitchPending[i] = false;
            relayState[i] = relayPendingState[i];
            driveRelayPin(i, relayState[i]);
            relayPulsing[i] = relayPendingPulse[i];
            if (relayPulsing[i]) relayPulseEnd[i] = now + relayPendingPulseMs[i];
            usb->printf("!RELAY %d %d\n", i, relayState[i] ? 1 : 0);
        }
        if (relayPulsing[i] && (int32_t)(now - relayPulseEnd[i]) >= 0) {
            relayState[i] = false;
            driveRelayPin(i, false);
            relayPulsing[i] = false;
            usb->printf("!RELAY %d 0\n", i);
        }
    }
}

// ─── Setup ───────────────────────────────────────────────────────
void setup() {
    iwdgInit();   // start / re-arm ~4 s watchdog (survives from bootloader)

    // USB disconnect already handled by usb_disconnect.c constructor
    Serial.begin(115200);
    uint32_t ws = millis();
    while (!Serial && (millis() - ws) < 1000) { delay(10); iwdgFeed(); }

    // GPIO
    for (int i = 0; i < NUM_RELAYS; i++) { pinMode(relayPins[i], OUTPUT); digitalWrite(relayPins[i], LOW); }
    for (int i = 0; i < NUM_SENSORS; i++) { pinMode(sensorPins[i], INPUT_PULLUP); lastSensor[i] = digitalRead(sensorPins[i]); }
    pinMode(PIN_HEARTBEAT, OUTPUT);

    // OSDP
    osdp.onCard   = onCard;
    osdp.onKeypad = onKeypad;
    osdp.onStatus = onStatus;
    osdp.onReply  = onReply;
    osdp.onDebug  = onDebug;
    osdp.onBio    = onBio;

    // Default: one reader at addr 0, 9600 baud, SCBK-D
    osdp.addPd(0, nullptr);
    osdp.begin(&Serial1, PIN_RS485_DE, 9600);

    Serial.println("!BOOT OSDP-Bridge " FW_VERSION);
    usb->printf("!CONFIG rs485=USART1 baud=9600 de=PA8 readers=%d\n", osdp.numPd);
}

// ─── Loop ────────────────────────────────────────────────────────
void loop() {    iwdgFeed();   // keep watchdog alive — resets MCU if loop() ever stalls >4s
    // OSDP protocol engine
    osdp.tick();

    // USB CDC command input
    while (Serial.available()) {
        char ch = Serial.read();
        if (ch == '\r' || ch == '\n') {
            if (cmdLen > 0) {
                cmdBuf[cmdLen] = 0;
                handleCmd(cmdBuf);
                cmdLen = 0;
            }
        } else if (cmdLen < sizeof(cmdBuf) - 1) {
            cmdBuf[cmdLen++] = ch;
        }
    }

    // Async sensor monitoring
    checkSensors();
    checkRelays();

    // LED indicator logic:
    //   - Solid ON until any reader comes online
    //   - After online, blink with TX/RX activity (polling)
    static uint32_t prevTx = 0, prevRx = 0;
    static bool anyOnline = false;
    if (!anyOnline) {
        for (int i = 0; i < osdp.numPd; i++) {
            if (osdp.pd[i].state >= PD_ONLINE) { anyOnline = true; break; }
        }
    }
    // Check if all readers went offline again
    if (anyOnline) {
        bool still = false;
        for (int i = 0; i < osdp.numPd; i++) {
            if (osdp.pd[i].state >= PD_ONLINE) { still = true; break; }
        }
        if (!still) anyOnline = false;
    }
    if (!anyOnline) {
        digitalWrite(PIN_HEARTBEAT, LOW);  // solid ON (active LOW)
    } else {
        if (osdp.busTxCount != prevTx || osdp.busRxCount != prevRx) {
            prevTx = osdp.busTxCount;
            prevRx = osdp.busRxCount;
            digitalToggle(PIN_HEARTBEAT);
        }
    }

    // Periodic heartbeat event to bridge (every 2 seconds)
    if (millis() - lastHeartbeat >= 2000) {
        lastHeartbeat = millis();
        usb->printf("!HEARTBEAT tx=%lu rx=%lu uptime=%lu\n",
                     osdp.busTxCount, osdp.busRxCount, millis() / 1000);
    }

    // Auto-status every 30s so bridge stays in sync
    if (millis() - lastAutoStatus >= 30000) {
        lastAutoStatus = millis();
        for (int i = 0; i < osdp.numPd; i++) {
            PdCtx *p = &osdp.pd[i];
            const char *sn[] = {"OFFLINE","ONLINE","SC_INIT","SECURE","ERROR"};
            usb->printf("!PD %d addr=%d state=%s sc=%d tamper=%d power=%d\n",
                         i, p->addr, sn[p->state], p->scActive, p->tamper, p->power);
        }
    }
}
