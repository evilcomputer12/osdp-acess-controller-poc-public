#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>

#define OSDP_SOM    0x53
#define OSDP_MAX_PKT 512
#define OSDP_MARK   0xFF
#define CTRL_SQN    0x03
#define CTRL_CRC    0x04
#define CTRL_SCB    0x08

// Commands CP→PD
#define CMD_POLL    0x60
#define CMD_ID      0x61
#define CMD_CAP     0x62
#define CMD_LSTAT   0x64
#define CMD_ISTAT   0x65
#define CMD_OSTAT   0x66
#define CMD_RSTAT   0x67
#define CMD_OUT     0x68
#define CMD_LED     0x69
#define CMD_BUZ     0x6A
#define CMD_COMSET  0x6E
#define CMD_BIOREAD 0x73
#define CMD_BIOMATCH 0x74
#define CMD_KEYSET  0x75
#define CMD_CHLNG   0x76
#define CMD_SCRYPT  0x77

// Replies PD→CP
#define REP_ACK     0x40
#define REP_NAK     0x41
#define REP_PDID    0x45
#define REP_PDCAP   0x46
#define REP_LSTATR  0x48
#define REP_ISTATR  0x49
#define REP_OSTATR  0x4A
#define REP_RAW     0x50
#define REP_FMT     0x51
#define REP_KEYPAD  0x53
#define REP_COM     0x54
#define REP_BIOREADR 0x57
#define REP_BIOMATCHR 0x58
#define REP_CCRYPT  0x76
#define REP_RMACI   0x78
#define REP_BUSY    0x79

// Secure channel
#define SCS_11 0x11
#define SCS_12 0x12
#define SCS_13 0x13
#define SCS_14 0x14
#define SCS_15 0x15
#define SCS_16 0x16
#define SCS_17 0x17
#define SCS_18 0x18

// Timing
#define REPLY_TIMEOUT_MS        500   // was 400 — reader can take 400-450ms
#define POLL_INTERVAL_MS         50
#define SC_RETRY_INTERVAL_MS   2500   // was 1500 — less aggressive auto-retry
#define RX_STALE_TIMEOUT_MS     600   // was 500
#define TX_RECOVERY_BACKOFF_MS   80   // was 60 — short: reader times out if gap >200ms
#define SC_NAK_BACKOFF_MS       100   // after NAK4 seq-reset: brief settle, not 400ms
#define SC_INIT_TIMEOUT_MS     5000   // dedicated SC handshake window (CHLNG→RMACI)
#define MAX_TX_RETRIES            6   // was 8 — slightly faster offline detection
#define MAX_PARSE_FAILS          10

// Limits - bridge only needs 2 readers max
#define MAX_READERS      2
#define MAX_CARD_BYTES   16
#define MAX_BIO_BYTES    200
#define MAX_PENDING_CMDS 16

static const uint8_t SCBK_DEFAULT[16] = {
    0x30,0x31,0x32,0x33,0x34,0x35,0x36,0x37,
    0x38,0x39,0x3A,0x3B,0x3C,0x3D,0x3E,0x3F
};

enum PdState { PD_OFFLINE=0, PD_ONLINE, PD_SC_INIT, PD_SECURE, PD_ERROR };

struct CardData {
    uint8_t readerNum, format;
    uint16_t bitCount;
    uint8_t data[MAX_CARD_BYTES];
    uint8_t dataLen;
};

struct PdIdentity {
    uint8_t vendor[3], serial[4];
    uint8_t model, version, fwMaj, fwMin, fwBuild;
    bool valid;
};

struct PdCapRec { uint8_t fc, compliance, numOf; };
struct LedCmd {
    uint8_t reader, led;
    uint8_t tmpCtrl, tmpOn, tmpOff, tmpOnCol, tmpOffCol;
    uint16_t tmpTimer;
    uint8_t permCtrl, permOn, permOff, permOnCol, permOffCol;
};
struct BuzCmd { uint8_t reader, tone, on, off, count; };
struct OutCmd { uint8_t output, code; uint16_t timer; };
struct BioData {
    uint8_t readerNum, status, type, quality;
    uint8_t data[MAX_BIO_BYTES];
    uint16_t dataLen;
};
struct PendingCmd { uint8_t cmd; uint8_t data[256]; uint16_t len; };

struct PdCtx {
    uint8_t addr;
    PdState state;
    uint8_t seq;
    bool useCrc;
    PdIdentity id;
    PdCapRec caps[16]; uint8_t numCaps;
    uint8_t scbk[16]; bool useScbkD;
    uint8_t sEnc[16], sMac1[16], sMac2[16];
    uint8_t cMac[16], rMac[16];
    uint8_t rndA[8], rndB[8], serverCrypt[16];
    bool scActive;
    uint8_t tamper, power;
    uint32_t lastPollMs, lastReplyMs;
    uint8_t retryCount;
    uint8_t parseFails;
    uint8_t lastCmd;
    uint32_t nextTxAllowedMs;
    uint8_t scRetries;
    uint32_t lastScAttemptMs;
    bool hadSc;
    uint8_t comsetNewAddr; bool comsetPending;
    PendingCmd pend[MAX_PENDING_CMDS];
    uint8_t pendHead, pendTail, pendCount;
};

static inline void hexEncode(char *out, const uint8_t *d, int n) {
    for (int i = 0; i < n; i++) sprintf(out + i * 2, "%02X", d[i]);
    out[n * 2] = 0;
}
static inline int hexDecode(uint8_t *out, const char *h, int max) {
    int n = strlen(h) / 2; if (n > max) n = max;
    for (int i = 0; i < n; i++) sscanf(h + i * 2, "%2hhx", &out[i]);
    return n;
}
