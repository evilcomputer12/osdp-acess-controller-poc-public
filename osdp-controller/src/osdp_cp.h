#pragma once
#include <Arduino.h>
#include "osdp_defs.h"

// All callbacks fire on the bridge layer which formats and sends to USB
typedef void (*CardCb)(uint8_t pdIdx, const CardData *card);
typedef void (*KeypadCb)(uint8_t pdIdx, const uint8_t *keys, uint8_t count);
typedef void (*StatusCb)(uint8_t pdIdx, PdState state);
// Generic: fires for EVERY parsed reply so bridge can forward raw events
typedef void (*ReplyCb)(uint8_t pdIdx, uint8_t code, const uint8_t *data, uint16_t dlen);
// Debug: fires for diagnostic messages
typedef void (*DebugCb)(uint8_t pdIdx, const char *msg);
typedef void (*BioCb)(uint8_t pdIdx, const BioData *bio);

class OsdpCp {
public:
    PdCtx pd[MAX_READERS];
    uint8_t numPd = 0;
    CardCb   onCard   = nullptr;
    KeypadCb onKeypad = nullptr;
    StatusCb onStatus = nullptr;
    ReplyCb  onReply  = nullptr;   // every reply gets forwarded
    DebugCb  onDebug  = nullptr;   // diagnostic messages
    BioCb    onBio    = nullptr;    // biometric events
    HardwareSerial *serial = nullptr;
    int dePin = -1;
    volatile uint32_t busTxCount = 0, busRxCount = 0;

    int  addPd(uint8_t addr, const uint8_t *scbk = nullptr);
    void begin(HardwareSerial *ser, int dePin, long baud);
    void tick();
    void sendPoll(uint8_t i);
    void sendId(uint8_t i);
    void sendCap(uint8_t i);
    void sendLstat(uint8_t i);
    void sendIstat(uint8_t i);
    void sendOstat(uint8_t i);
    void sendLed(uint8_t i, const LedCmd *led);
    void sendBuz(uint8_t i, const BuzCmd *buz);
    void sendOut(uint8_t i, const OutCmd *out);
    void sendComset(uint8_t i, uint8_t newAddr, uint32_t newBaud);
    void sendKeyset(uint8_t i, const uint8_t *newKey);
    void sendBioRead(uint8_t i, uint8_t reader, uint8_t type, uint8_t format, uint8_t quality);
    void sendBioMatch(uint8_t i, uint8_t reader, uint8_t type, uint8_t format, uint8_t quality, const uint8_t *tmpl, uint16_t tmplLen);
    void initSecureChannel(uint8_t i);
    bool isReaderIdle(uint8_t i, uint32_t now, uint32_t guardMs = 0) const;

private:
    uint8_t txBuf[OSDP_MAX_PKT], rxBuf[OSDP_MAX_PKT];
    uint16_t rxLen = 0;
    uint8_t curPd = 0;
    uint32_t lastRxMs = 0;

    int  buildPkt(PdCtx *p, uint8_t cmd, const uint8_t *data, uint16_t dlen, uint8_t scType);
    int  parseReply(PdCtx *p, const uint8_t *buf, uint16_t len, uint8_t *dOut, uint16_t *dlOut, uint8_t *scOut);
    void sendCmd(PdCtx *p, uint8_t cmd, const uint8_t *data=nullptr, uint16_t dlen=0);
    void queueCmd(uint8_t i, uint8_t cmd, const uint8_t *data=nullptr, uint16_t dlen=0);
    void startSecureChannel(PdCtx *p);
    void processReply(uint8_t pdIdx, uint8_t code, const uint8_t *data, uint16_t dlen, uint8_t scType);
    void handleCcrypt(uint8_t pdIdx, const uint8_t *data, uint16_t dlen);
    void handleRmacI(uint8_t pdIdx, const uint8_t *data, uint16_t dlen);
    void advanceSeq(PdCtx *p) { p->seq = (p->seq >= 3) ? 1 : p->seq + 1; }
    void txRaw(const uint8_t *data, uint16_t len);
};
