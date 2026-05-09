/*
 * Blue Pill USB disconnect workaround — BOOTLOADER BUILD.
 *
 * Same D+/D- LOW trick as the app uses: drive PA12 and PA11 LOW for
 * ~750 ms so the host registers a proper USB disconnect → reconnect.
 *
 * This runs as a GCC constructor at priority 100 (before the Arduino
 * framework's init() at priority 101 which starts the USB peripheral).
 * Using a DIFFERENT priority than premain (101) also prevents LTO from
 * merging both constructors into one function with wrong ordering.
 *
 * The ~750 ms delay also adds to cold-boot time when the bootloader
 * will jump to app anyway, but that is acceptable.
 */

#include "stm32f1xx.h"

__attribute__((constructor(100)))
void _bluepill_usb_disconnect(void) {
    /* Enable clocks */
    RCC->APB2ENR |= RCC_APB2ENR_IOPAEN;
    RCC->APB1ENR |= RCC_APB1ENR_USBEN;
    __DSB();

    /* Power-down + force-reset USB peripheral */
    USB->CNTR = USB_CNTR_PDWN | USB_CNTR_FRES;
    USB->ISTR = 0;

    /* Drive PA12 (D+) LOW */
    GPIOA->CRH = (GPIOA->CRH & ~(0xFUL << 16)) | (0x2UL << 16);
    GPIOA->BRR = (1UL << 12);

    /* Drive PA11 (D-) LOW */
    GPIOA->CRH = (GPIOA->CRH & ~(0xFUL << 12)) | (0x2UL << 12);
    GPIOA->BRR = (1UL << 11);

    /* Hold SE0 for ~750 ms at 8 MHz HSI (constructors run before PLL). */
    for (volatile uint32_t i = 0; i < 1500000; i++) {
        __NOP();
    }
}
