/*
 * Blue Pill USB disconnect workaround.
 *
 * Most Blue Pill clones have 10 kΩ (or 4.7 kΩ) on PA12 (USB D+)
 * instead of 1.5 kΩ.  After reset the host never sees a proper
 * disconnect -> connect transition, causing
 * "Device Descriptor Request Failed" on Windows.
 *
 * Fix: use a GCC constructor (runs before main/setup) to
 *   1. Power-down the USB peripheral
 *   2. Drive PA12 (D+) LOW via bare GPIO registers
 *   3. Hold for ~800 ms so the host registers SE0 (disconnect)
 *   4. Leave PA12 LOW — Serial.begin() in setup() will re-init
 *      the USB peripheral and reclaim the pin atomically, so
 *      there is no window where D+ is HIGH but USB is not ready.
 */

#include "stm32f1xx.h"

__attribute__((constructor(101)))
void _bluepill_usb_disconnect(void) {
    /* ── 1. Enable clocks ──────────────────────────────────── */
    RCC->APB2ENR |= RCC_APB2ENR_IOPAEN;       /* GPIOA clock  */
    RCC->APB1ENR |= RCC_APB1ENR_USBEN;         /* USB clock    */
    __DSB();  /* ensure writes land before we read back */

    /* ── 2. Power-down + force-reset the USB peripheral ──── */
    USB->CNTR = USB_CNTR_PDWN | USB_CNTR_FRES; /* disconnect   */
    USB->ISTR = 0;                              /* clear flags  */

    /* ── 3. Drive PA12 (D+) LOW via GPIO ─────────────────── */
    /* CRH bits [19:16] control PA12: mode=10 (2 MHz out), cnf=00 (push-pull) */
    GPIOA->CRH = (GPIOA->CRH & ~(0xFUL << 16)) | (0x2UL << 16);
    GPIOA->BRR = (1UL << 12);                  /* PA12 = LOW   */

    /* Also pull PA11 (D−) LOW for good measure */
    GPIOA->CRH = (GPIOA->CRH & ~(0xFUL << 12)) | (0x2UL << 12);
    GPIOA->BRR = (1UL << 11);                  /* PA11 = LOW   */

    /* ── 4. Hold D+/D− LOW for ~800 ms ──────────────────── */
    /* At reset HSI = 8 MHz.  ~10 cycles/iteration → 1.5M iters ≈ 1.9 s.
     * Generous: ensures Windows USB hub driver registers disconnect. */
    for (volatile uint32_t i = 0; i < 1500000; i++) {
        __NOP();
    }

    /* ── 5. Leave PA12/PA11 LOW — do NOT release to floating.
     *    Serial.begin() in setup() calls HAL_PCD_MspInit() which
     *    reconfigures both pins as AF push-pull for USB and starts
     *    the peripheral, so D+ only goes HIGH when USB is ready
     *    to answer the first SETUP packet.  ──────────────────── */
}
