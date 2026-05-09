/*
 * OSDP Bridge Bootloader — STM32 Blue Pill (STM32F103C8T6)
 *
 * 16KB USB CDC bootloader at 0x08000000.
 * Application starts at 0x08007000 (100KB available).
 *
 * Update mode is entered when:
 *   1. BKP_DR1 contains magic word (application sent BOOTLOADER command + reset)
 *   2. No valid application detected (erased flash or corrupted vector table)
 *   3. PA4 is held LOW at boot (hardware escape hatch — jumper PA4 to GND)
 *
 * Protocol (text, newline-terminated, over USB CDC):
 *   PC->BL: HELLO            ->  BL: !BOOTLOADER v1 APP=08007000 MAX=19000
 *   PC->BL: ERASE            ->  BL: OK  (erases all app pages)
 *   PC->BL: W<off4hex> <hex> ->  BL: OK  (write up to 256 bytes at offset)
 *   PC->BL: CRC <len> <crc>  ->  BL: OK  or  ERR:MISMATCH <actual>
 *   PC->BL: BOOT             ->  BL: OK  (jumps to application)
 *
 * Wiring: PA4 -> bootloader entry pin (hold LOW + reset to force update mode)
 */

#include <Arduino.h>

#ifndef APP_ADDR
#define APP_ADDR      0x08007000UL
#endif
#ifndef APP_MAX_SIZE
#define APP_MAX_SIZE  0x19000UL       // 100KB
#endif

#define PAGE_SIZE     1024U          // STM32F103 flash page = 1KB
#define NUM_APP_PAGES (APP_MAX_SIZE / PAGE_SIZE)
#define MAGIC_WORD    0xB007U        // 16-bit magic in BKP_DR1
#define ENTRY_PIN     PA4            // hold LOW at boot → force update mode
// ── IWDG (Independent Watchdog) ──────────────────────────────
// LSI ≈ 40 kHz.  Prescaler /64 → 625 Hz tick.  Reload 2500 → ~4 s timeout.
// Once started the IWDG cannot be stopped — the app must keep feeding it.
static void iwdgInit() {
    IWDG->KR  = 0xCCCC;          // start watchdog (forces LSI oscillator on)
    IWDG->KR  = 0x5555;          // unlock PR/RLR
    IWDG->PR  = 4;               // prescaler /64
    IWDG->RLR = 2500;            // ~4 s
    while (IWDG->SR) {}          // wait for registers to sync (LSI now running)
    IWDG->KR  = 0xAAAA;          // first feed with new reload value
}
static inline void iwdgFeed() { IWDG->KR = 0xAAAA; }

static void printBanner() {
    Serial.printf("!BOOTLOADER v2 APP=%08lX MAX=%lX\n",
                  (unsigned long)APP_ADDR, (unsigned long)APP_MAX_SIZE);
}
// ── Flash register helpers (direct register access, no HAL dependency) ──

static void flashUnlock() {
    FLASH->KEYR = 0x45670123UL;
    FLASH->KEYR = 0xCDEF89ABUL;
}

static void flashLock() {
    FLASH->CR |= FLASH_CR_LOCK;
}

static void flashErasePage(uint32_t pageAddr) {
    while (FLASH->SR & FLASH_SR_BSY) {}
    FLASH->CR |= FLASH_CR_PER;
    FLASH->AR  = pageAddr;
    FLASH->CR |= FLASH_CR_STRT;
    while (FLASH->SR & FLASH_SR_BSY) {}
    FLASH->CR &= ~FLASH_CR_PER;
}

static bool flashProgramHW(uint32_t addr, uint16_t hw) {
    FLASH->CR |= FLASH_CR_PG;
    *(volatile uint16_t *)addr = hw;
    while (FLASH->SR & FLASH_SR_BSY) {}
    FLASH->CR &= ~FLASH_CR_PG;
    return *(volatile uint16_t *)addr == hw;
}

// ── Hex helpers ──────────────────────────────────────────────────

static uint8_t hexNibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return 0;
}

static uint8_t hexByte(const char *s) {
    return (hexNibble(s[0]) << 4) | hexNibble(s[1]);
}

static uint32_t hexWord(const char *s, uint8_t nChars) {
    uint32_t v = 0;
    for (uint8_t i = 0; i < nChars; i++)
        v = (v << 4) | hexNibble(s[i]);
    return v;
}

// ── CRC-32 (same as zlib/Python) ────────────────────────────────

static uint32_t crc32(const uint8_t *data, uint32_t len) {
    uint32_t crc = 0xFFFFFFFFUL;
    for (uint32_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (int j = 0; j < 8; j++)
            crc = (crc & 1) ? (crc >> 1) ^ 0xEDB88320UL : crc >> 1;
    }
    return ~crc;
}

// ── App validity check ──────────────────────────────────────────

static bool isAppValid() {
    uint32_t sp = *(volatile uint32_t *)APP_ADDR;
    uint32_t pc = *(volatile uint32_t *)(APP_ADDR + 4);
    if (sp < 0x20000000UL || sp > 0x20005000UL) return false;
    if (pc < APP_ADDR   || pc > (APP_ADDR + APP_MAX_SIZE)) return false;
    return true;
}

// ── Jump to application ─────────────────────────────────────────

static void jumpToApp() __attribute__((noreturn));
static void jumpToApp() {
    __disable_irq();
    SysTick->CTRL = 0;
    SysTick->LOAD = 0;
    SysTick->VAL  = 0;
    for (int i = 0; i < 8; i++) {
        NVIC->ICER[i] = 0xFFFFFFFF;
        NVIC->ICPR[i] = 0xFFFFFFFF;
    }
    // Reset USB peripheral so app can re-init
    RCC->APB1RSTR |=  RCC_APB1RSTR_USBRST;
    RCC->APB1RSTR &= ~RCC_APB1RSTR_USBRST;
    RCC->APB1ENR  &= ~RCC_APB1ENR_USBEN;

    SCB->VTOR = APP_ADDR;
    __set_MSP(*(volatile uint32_t *)APP_ADDR);
    __enable_irq();
    ((void (*)(void))(*(volatile uint32_t *)(APP_ADDR + 4)))();
    for (;;) {}  // never reached
}

// ── Command buffer ──────────────────────────────────────────────

static char cmdBuf[580];   // enough for W<4hex> + space + 512hex + \0
static size_t cmdLen = 0;

// ── Command handler ─────────────────────────────────────────────

static void handleLine(char *line, size_t len) {
    // HELLO
    if (len >= 5 && memcmp(line, "HELLO", 5) == 0) {
        printBanner();
        return;
    }

    // ERASE
    if (len >= 5 && memcmp(line, "ERASE", 5) == 0) {
        flashUnlock();
        for (uint32_t p = 0; p < NUM_APP_PAGES; p++) {
            flashErasePage(APP_ADDR + p * PAGE_SIZE);
            iwdgFeed();   // each page erase can take ~40ms, keep WDG alive
        }
        flashLock();
        Serial.println("OK");
        return;
    }

    // W<offset_hex> <data_hex>  (offset: up to 5 hex chars for 100KB range)
    if (line[0] == 'W' && len > 4) {
        // Find space separator between offset and data
        char *sp = strchr(&line[1], ' ');
        if (!sp) { Serial.println("ERR:FMT"); return; }
        uint32_t offLen = sp - &line[1];
        uint32_t offset = hexWord(&line[1], offLen);
        const char *hex = sp + 1;
        uint32_t hexLen = len - (hex - line);
        uint32_t dataLen = hexLen / 2;

        if (dataLen == 0 || dataLen > PAGE_SIZE) {
            Serial.println("ERR:LEN");
            return;
        }
        uint32_t addr = APP_ADDR + offset;
        if (addr < APP_ADDR || addr + dataLen > APP_ADDR + APP_MAX_SIZE) {
            Serial.println("ERR:RANGE");
            return;
        }

        iwdgFeed();
        flashUnlock();
        for (uint32_t i = 0; i < dataLen; i += 2) {
            uint16_t hw = hexByte(&hex[i * 2]);
            if (i + 1 < dataLen)
                hw |= (uint16_t)hexByte(&hex[(i + 1) * 2]) << 8;
            else
                hw |= 0xFF00;  // pad odd byte
            if (!flashProgramHW(addr + i, hw)) {
                flashLock();
                Serial.println("ERR:FLASH");
                return;
            }
        }
        flashLock();
        Serial.println("OK");
        return;
    }

    // CRC <size_hex> <crc32_hex>
    if (len >= 4 && memcmp(line, "CRC ", 4) == 0) {
        char *p = &line[4];
        // Parse size
        char *sp = strchr(p, ' ');
        if (!sp) { Serial.println("ERR:FMT"); return; }
        *sp = '\0';
        uint32_t size = hexWord(p, strlen(p));
        uint32_t expected = hexWord(sp + 1, strlen(sp + 1));
        if (size > APP_MAX_SIZE) size = APP_MAX_SIZE;
        uint32_t actual = crc32((const uint8_t *)APP_ADDR, size);
        if (actual == expected) {
            Serial.println("OK");
        } else {
            Serial.printf("ERR:MISMATCH %08lX\n", actual);
        }
        return;
    }

    // BOOT
    if (len >= 4 && memcmp(line, "BOOT", 4) == 0) {
        if (!isAppValid()) {
            Serial.println("ERR:NO_APP");
            return;
        }
        Serial.println("OK");
        Serial.flush();
        delay(100);
        Serial.end();
        delay(50);
        jumpToApp();
    }

    Serial.println("ERR:UNKNOWN");
}

// ── Arduino entry ───────────────────────────────────────────────

void setup() {
    bool enterUpdate = false;

    // Check hardware entry pin (PA4 held LOW)
    pinMode(ENTRY_PIN, INPUT_PULLUP);
    delay(5);  // let pullup settle
    if (digitalRead(ENTRY_PIN) == LOW)
        enterUpdate = true;

    // Check BKP_DR1 for magic word.
    // BKP registers survive NVIC_SystemReset() but are cleared on power cycle,
    // so this reliably detects the app's BOOTLOADER reboot command without
    // any RAM/stack clobbering issues.
    RCC->APB1ENR |= RCC_APB1ENR_PWREN | RCC_APB1ENR_BKPEN;
    __DSB();
    if (BKP->DR1 == MAGIC_WORD) {
        PWR->CR |= PWR_CR_DBP;       // enable backup domain write
        BKP->DR1 = 0;                // clear so next power cycle boots normally
        PWR->CR &= ~PWR_CR_DBP;
        enterUpdate = true;
    }

    // Check app validity
    if (!enterUpdate && !isAppValid())
        enterUpdate = true;

    if (!enterUpdate) {
        jumpToApp();  // does not return
    }

    // ── Update mode ──
    iwdgInit();               // start ~4 s watchdog — resets if USB hangs
    Serial.begin(115200);
    uint32_t t = millis();
    while (!Serial && millis() - t < 3000) { delay(10); iwdgFeed(); }

    pinMode(PC13, OUTPUT);
    printBanner();
}

void loop() {
    iwdgFeed();               // keep watchdog alive every loop iteration

    // Slow-blink LED to indicate bootloader mode
    static uint32_t blink = 0;
    if (millis() - blink >= 1000) {
        blink = millis();
        digitalToggle(PC13);
    }

    // Read commands
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\r' || c == '\n') {
            if (cmdLen > 0) {
                cmdBuf[cmdLen] = '\0';
                handleLine(cmdBuf, cmdLen);
                cmdLen = 0;
            }
        } else if (cmdLen < sizeof(cmdBuf) - 1) {
            cmdBuf[cmdLen++] = c;
        }
    }
}
