#include "osdp_cp.h"
#include "osdp_crypto.h"

static const char *cmdName(uint8_t cmd) {
    switch (cmd) {
    case CMD_POLL: return "POLL";
    case CMD_ID: return "ID";
    case CMD_CAP: return "CAP";
    case CMD_LSTAT: return "LSTAT";
    case CMD_ISTAT: return "ISTAT";
    case CMD_OSTAT: return "OSTAT";
    case CMD_LED: return "LED";
    case CMD_BUZ: return "BUZ";
    case CMD_OUT: return "OUT";
    case CMD_COMSET: return "COMSET";
    case CMD_KEYSET: return "KEYSET";
    case CMD_CHLNG: return "CHLNG";
    case CMD_SCRYPT: return "SCRYPT";
    default: return "CMD?";
    }
}

void OsdpCp::begin(HardwareSerial *ser, int de, long baud) {
    serial = ser; dePin = de;
    if (dePin >= 0) { pinMode(dePin, OUTPUT); digitalWrite(dePin, LOW); }
    serial->begin(baud);
}

int OsdpCp::addPd(uint8_t addr, const uint8_t *scbk) {
    if (numPd >= MAX_READERS) return -1;
    PdCtx *p = &pd[numPd]; memset(p, 0, sizeof(PdCtx));
    p->addr = addr; p->state = PD_OFFLINE; p->useCrc = true;
    if (scbk) { memcpy(p->scbk, scbk, 16); p->useScbkD = false; }
    else      { memcpy(p->scbk, SCBK_DEFAULT, 16); p->useScbkD = true; }
    return numPd++;
}

void OsdpCp::txRaw(const uint8_t *data, uint16_t len) {
    if (!serial) return;
    if (dePin >= 0) digitalWrite(dePin, HIGH);
    delayMicroseconds(500);   // was 200 — MAX485 DE propagation + line settle
    serial->write(OSDP_MARK);
    serial->write(data, len);
    serial->flush();
    delayMicroseconds(500);   // was 200 — last bit out before DE drops
    if (dePin >= 0) digitalWrite(dePin, LOW);
    busTxCount++;
}

int OsdpCp::buildPkt(PdCtx *p, uint8_t cmd, const uint8_t *data, uint16_t dlen, uint8_t scType) {
    uint16_t pos = 0;
    txBuf[pos++] = OSDP_SOM; txBuf[pos++] = p->addr;
    uint16_t lp = pos; txBuf[pos++] = 0; txBuf[pos++] = 0;
    uint8_t ctrl = p->seq & CTRL_SQN;
    if (p->useCrc) ctrl |= CTRL_CRC;
    if (scType) ctrl |= CTRL_SCB;
    txBuf[pos++] = ctrl;
    if (scType) {
        if (scType == SCS_11 || scType == SCS_13) { txBuf[pos++]=3; txBuf[pos++]=scType; txBuf[pos++]=p->useScbkD?0:1; }
        else if (scType == SCS_15 || scType == SCS_17) { txBuf[pos++]=2; txBuf[pos++]=scType; }
    }
    txBuf[pos++] = cmd;
    if (scType == SCS_17 && dlen > 0) {
        uint8_t enc[256]; uint8_t n = encryptData(enc, data, dlen, p->sEnc, p->rMac);
        memcpy(&txBuf[pos], enc, n*16); pos += n*16;
    } else if (data && dlen > 0) { memcpy(&txBuf[pos], data, dlen); pos += dlen; }
    if (scType == SCS_15 || scType == SCS_17) {
        uint16_t tl = pos + 4 + (p->useCrc ? 2 : 1);
        txBuf[lp]=tl&0xFF; txBuf[lp+1]=(tl>>8)&0xFF;
        uint8_t mf[16]; computeMac(mf, txBuf, pos, p->rMac, p->sMac1, p->sMac2);
        memcpy(&txBuf[pos], mf, 4); pos += 4; memcpy(p->cMac, mf, 16);
    } else {
        uint16_t tl = pos + (p->useCrc ? 2 : 1);
        txBuf[lp]=tl&0xFF; txBuf[lp+1]=(tl>>8)&0xFF;
    }
    if (p->useCrc) { uint16_t c=osdpCrc16(txBuf,pos); txBuf[pos++]=c&0xFF; txBuf[pos++]=(c>>8)&0xFF; }
    else { txBuf[pos]=osdpChecksum(txBuf,pos); pos++; }
    return pos;
}

int OsdpCp::parseReply(PdCtx *p, const uint8_t *buf, uint16_t len,
                        uint8_t *dOut, uint16_t *dlOut, uint8_t *scOut) {
    if (len<7||buf[0]!=OSDP_SOM) return -1;
    if ((buf[1]&0x7F)!=p->addr && (buf[1]&0x7F)!=0x7F &&
        !(p->comsetPending && (buf[1]&0x7F)==p->comsetNewAddr)) return -1;
    uint16_t pl=buf[2]|((uint16_t)buf[3]<<8); if(pl!=len) return -1;
    uint8_t ctrl=buf[4]; bool hasCrc=(ctrl&CTRL_CRC), hasScb=(ctrl&CTRL_SCB);
    if (hasCrc){uint16_t c=osdpCrc16(buf,pl-2),r=buf[pl-2]|((uint16_t)buf[pl-1]<<8);if(c!=r)return -1;}
    else{if(osdpChecksum(buf,pl-1)!=buf[pl-1])return -1;}
    uint16_t dOff; uint8_t rc, st=0;
    if(hasScb){uint8_t sl=buf[5];st=buf[6];dOff=(sl==3)?9:8;rc=(sl==3)?buf[8]:buf[7];}
    else{rc=buf[5];dOff=6;} *scOut=st;
    uint16_t cs=hasCrc?2:1;
    if(st==SCS_16||st==SCS_18){
        uint16_t mo=pl-cs-4; uint8_t rm[4];memcpy(rm,&buf[mo],4);
        uint8_t mf[16];computeMac(mf,buf,mo,p->cMac,p->sMac1,p->sMac2);
        if(memcmp(rm,mf,4)!=0)return -1; memcpy(p->rMac,mf,16);
        if(st==SCS_18&&dOut){*dlOut=decryptData(dOut,&buf[dOff],mo-dOff,p->sEnc,p->cMac);}
        else{uint16_t dl=mo-dOff;if(dOut&&dl>0)memcpy(dOut,&buf[dOff],dl);*dlOut=dl;}
    } else {uint16_t dl=pl-dOff-cs;if(dOut&&dl>0)memcpy(dOut,&buf[dOff],dl);*dlOut=dl;}
    return rc;
}

void OsdpCp::sendCmd(PdCtx *p, uint8_t cmd, const uint8_t *data, uint16_t dlen) {
    uint8_t sc = 0;
    if (p->scActive) sc = (cmd == CMD_POLL) ? SCS_15 : SCS_17;
    int n = buildPkt(p, cmd, data, dlen, sc);
    if (n > 0) txRaw(txBuf, n);
    p->lastCmd = cmd;
    p->lastPollMs = millis(); advanceSeq(p);
}

void OsdpCp::queueCmd(uint8_t i, uint8_t cmd, const uint8_t *data, uint16_t dlen) {
    if (i >= numPd) return;
    PdCtx *p = &pd[i];
    if (p->pendCount >= MAX_PENDING_CMDS) {
        if (onDebug) {
            char dbg[56];
            snprintf(dbg, sizeof(dbg), "QUEUE_FULL: drop oldest cmd=0x%02X", p->pend[p->pendHead].cmd);
            onDebug(i, dbg);
        }
        p->pendHead = (p->pendHead + 1) % MAX_PENDING_CMDS;
        p->pendCount--;
    }
    PendingCmd *s = &p->pend[p->pendTail];
    s->cmd = cmd;
    s->len = (dlen > sizeof(s->data)) ? sizeof(s->data) : dlen;
    if (data && s->len) memcpy(s->data, data, s->len);
    p->pendTail = (p->pendTail + 1) % MAX_PENDING_CMDS;
    p->pendCount++;
}

void OsdpCp::startSecureChannel(PdCtx *p) {
    p->scActive = false; randBytes(p->rndA, 8); p->state = PD_SC_INIT;
    if(onDebug) onDebug(0, p->useScbkD ? "SC_START: CHLNG using SCBK-D" : "SC_START: CHLNG using SCBK");
    int n = buildPkt(p, CMD_CHLNG, p->rndA, 8, SCS_11);
    if (n > 0) txRaw(txBuf, n);
    p->lastPollMs = millis(); advanceSeq(p);
}

void OsdpCp::sendPoll(uint8_t i)  { queueCmd(i, CMD_POLL); }
void OsdpCp::sendId(uint8_t i)    { uint8_t d=0; queueCmd(i, CMD_ID, &d, 1); }
void OsdpCp::sendCap(uint8_t i)   { uint8_t d=0; queueCmd(i, CMD_CAP, &d, 1); }
void OsdpCp::sendLstat(uint8_t i)  { queueCmd(i, CMD_LSTAT); }
void OsdpCp::sendIstat(uint8_t i)  { queueCmd(i, CMD_ISTAT); }
void OsdpCp::sendOstat(uint8_t i)  { queueCmd(i, CMD_OSTAT); }
void OsdpCp::sendLed(uint8_t i, const LedCmd *l) {
    uint8_t d[14]={l->reader,l->led,l->tmpCtrl,l->tmpOn,l->tmpOff,l->tmpOnCol,l->tmpOffCol,
                   (uint8_t)(l->tmpTimer&0xFF),(uint8_t)(l->tmpTimer>>8),
                   l->permCtrl,l->permOn,l->permOff,l->permOnCol,l->permOffCol};
    queueCmd(i, CMD_LED, d, 14);
}
void OsdpCp::sendBuz(uint8_t i, const BuzCmd *b) {
    uint8_t d[5]={b->reader,b->tone,b->on,b->off,b->count}; queueCmd(i,CMD_BUZ,d,5);
}
void OsdpCp::sendOut(uint8_t i, const OutCmd *o) {
    uint8_t d[4]={o->output,o->code,(uint8_t)(o->timer&0xFF),(uint8_t)(o->timer>>8)}; queueCmd(i,CMD_OUT,d,4);
}
void OsdpCp::sendComset(uint8_t i, uint8_t newAddr, uint32_t newBaud) {
    uint8_t d[5]={newAddr,(uint8_t)newBaud,(uint8_t)(newBaud>>8),(uint8_t)(newBaud>>16),(uint8_t)(newBaud>>24)};
    pd[i].comsetPending=true; pd[i].comsetNewAddr=newAddr;
    queueCmd(i,CMD_COMSET,d,5);
}
void OsdpCp::sendKeyset(uint8_t i, const uint8_t *newKey) {
    if (!pd[i].scActive) {
        if(onDebug) onDebug(i,"KEYSET_FAIL: secure channel not active");
        return;
    }
    uint8_t d[18]; d[0]=0x01; d[1]=0x10; memcpy(&d[2],newKey,16); queueCmd(i,CMD_KEYSET,d,18);
}
void OsdpCp::initSecureChannel(uint8_t i) {
    if(i>=numPd) return;
    pd[i].scRetries=0; pd[i].lastScAttemptMs=millis();
    queueCmd(i, CMD_CHLNG);
}

bool OsdpCp::isReaderIdle(uint8_t i, uint32_t now, uint32_t guardMs) const {
    if (i >= numPd) return true;
    const PdCtx *p = &pd[i];
    bool waitingForReply = (p->lastPollMs != 0) &&
                           (p->lastReplyMs == 0 || p->lastPollMs > p->lastReplyMs);
    if (p->state == PD_SC_INIT || waitingForReply || p->pendCount) return false;
    if (guardMs && p->lastReplyMs != 0 && (now - p->lastReplyMs) < guardMs) return false;
    return true;
}

void OsdpCp::sendBioRead(uint8_t i, uint8_t reader, uint8_t type, uint8_t format, uint8_t quality) {
    uint8_t d[4]={reader,type,format,quality};
    queueCmd(i, CMD_BIOREAD, d, 4);
}

void OsdpCp::sendBioMatch(uint8_t i, uint8_t reader, uint8_t type, uint8_t format, uint8_t quality,
                          const uint8_t *tmpl, uint16_t tmplLen) {
    if(tmplLen>MAX_BIO_BYTES) return;
    uint8_t d[6+MAX_BIO_BYTES];
    d[0]=reader;d[1]=type;d[2]=format;d[3]=quality;
    d[4]=(uint8_t)(tmplLen&0xFF);d[5]=(uint8_t)(tmplLen>>8);
    memcpy(&d[6],tmpl,tmplLen);
    queueCmd(i, CMD_BIOMATCH, d, 6+tmplLen);
}

void OsdpCp::processReply(uint8_t pi, uint8_t code, const uint8_t *data, uint16_t dlen, uint8_t scType) {
    PdCtx *p = &pd[pi]; p->lastReplyMs = millis(); p->retryCount = 0;
    p->parseFails = 0;
    // Forward EVERY reply to bridge
    if (onReply) onReply(pi, code, data, dlen);
    switch (code) {
    case REP_ACK:
        if (onDebug) {
            char d[48];
            snprintf(d, sizeof(d), "ACK: cmd=%s", cmdName(p->lastCmd));
            onDebug(pi, d);
        }
        if(p->state==PD_OFFLINE){
            p->state=PD_ONLINE;
            p->scRetries=0; p->lastScAttemptMs=0;
            p->seq=0; // reader likely reset seq tracking while offline; resync both sides
            if(onStatus)onStatus(pi,p->state);
            if(onDebug)onDebug(pi,"PD_ONLINE: reader responded, seq reset, will auto-SC");
        }
        if(p->state==PD_SC_INIT){
            p->state=PD_ONLINE;
            if(onDebug)onDebug(pi,"SC_FAIL: PD sent ACK instead of CCRYPT (SC not supported?)");
        }
        break;
    case REP_NAK:
        if(dlen>0 && data[0]==4){
            p->seq = 0;
            p->nextTxAllowedMs = millis() + SC_NAK_BACKOFF_MS;
            if(onDebug) {
                char d[80];
                snprintf(d, sizeof(d), "SEQ_RESET: NAK seq error after %s, resetting to 0",
                         cmdName(p->lastCmd));
                onDebug(pi, d);
            }
        } else {
            // NAK 1 (bad CRC) or other: brief settle before retrying
            p->nextTxAllowedMs = millis() + TX_RECOVERY_BACKOFF_MS;
        }
        if(onDebug){
            char d[64];
            uint8_t ne = dlen>0 ? data[0] : 0xFF;
            snprintf(d,sizeof(d),"NAK: cmd=%s err=%u",cmdName(p->lastCmd),ne);
            onDebug(pi,d);
        }
        if(p->state==PD_SC_INIT){
            p->state=PD_ONLINE;
            uint8_t ne = dlen>0 ? data[0] : 0xFF;
            if(onDebug){
                char d[48];snprintf(d,sizeof(d),"SC_FAIL: PD NAK'd challenge err=%d",ne);
                onDebug(pi,d);
            }
        }
        break;
    case REP_BUSY:
        if(p->state==PD_SC_INIT){
            p->state=PD_ONLINE;
            if(onDebug)onDebug(pi,"SC_FAIL: PD BUSY during challenge");
        }
        break;
    case REP_PDID:
        if(dlen>=12){memcpy(p->id.vendor,data,3);p->id.model=data[3];p->id.version=data[4];
        memcpy(p->id.serial,&data[5],4);p->id.fwMaj=data[9];p->id.fwMin=data[10];p->id.fwBuild=data[11];p->id.valid=true;}break;
    case REP_PDCAP:
        p->numCaps=0;for(uint16_t i=0;i+2<dlen&&p->numCaps<16;i+=3)p->caps[p->numCaps++]={data[i],data[i+1],data[i+2]};break;
    case REP_LSTATR: if(dlen>=2){p->tamper=data[0];p->power=data[1];}break;
    case REP_RAW:
        if(dlen>=4){CardData c={data[0],data[1],(uint16_t)(data[2]|(data[3]<<8)),{},(uint8_t)(dlen-4>MAX_CARD_BYTES?MAX_CARD_BYTES:dlen-4)};
        memcpy(c.data,&data[4],c.dataLen);if(onCard)onCard(pi,&c);}break;
    case REP_FMT:
        if(dlen>=3){uint8_t bl=dlen-3>MAX_CARD_BYTES?MAX_CARD_BYTES:dlen-3;
        CardData c={data[0],0xFF,(uint16_t)(data[2]*8),{},bl};memcpy(c.data,&data[3],bl);
        if(onCard)onCard(pi,&c);}break;
    case REP_KEYPAD: if(dlen>=3&&onKeypad){uint8_t kc=data[1];if(kc>dlen-2)kc=dlen-2;onKeypad(pi,&data[2],kc);}break;
    case REP_BIOREADR:
        if(dlen>=6){
            uint16_t bl=data[4]|((uint16_t)data[5]<<8);
            if(bl>MAX_BIO_BYTES)bl=MAX_BIO_BYTES;
            if(bl+6<=dlen){
                BioData b;b.readerNum=data[0];b.status=data[1];b.type=data[2];
                b.quality=data[3];b.dataLen=bl;memcpy(b.data,&data[6],bl);
                if(onBio)onBio(pi,&b);
            }
        }break;
    case REP_BIOMATCHR:
        if(dlen>=3){
            BioData b;memset(&b,0,sizeof(b));
            b.readerNum=data[0];b.status=data[1];
            b.quality=data[2];b.dataLen=0;
            if(onBio)onBio(pi,&b);
        }break;
    case REP_COM:
        if(dlen>=5){
            p->comsetPending=false;
            p->addr=data[0];
            uint32_t nb=data[1]|((uint32_t)data[2]<<8)|((uint32_t)data[3]<<16)|((uint32_t)data[4]<<24);
            if(nb>=9600&&nb<=115200){
                serial->end();
                serial->begin(nb);
            }
            // COMSET invalidates the secure channel
            if(p->scActive){
                p->scActive=false; p->hadSc=true;
                p->state=PD_ONLINE;
                p->scRetries=0; p->lastScAttemptMs=0;
                if(onStatus) onStatus(pi,p->state);
                if(onDebug) onDebug(pi,"SC_RESET: COMSET changed comm params");
            }
        }
        break;
    case REP_CCRYPT: handleCcrypt(pi,data,dlen);break;
    case REP_RMACI:  handleRmacI(pi,data,dlen);break;
    default: break;
    }
}

void OsdpCp::handleCcrypt(uint8_t pi, const uint8_t *data, uint16_t dlen) {
    PdCtx*p=&pd[pi];
    if(dlen<32){
        if(onDebug){char d[48];snprintf(d,sizeof(d),"SC_FAIL: CCRYPT too short dlen=%d",dlen);onDebug(pi,d);}
        p->state=PD_ONLINE;return;
    }
    if(p->state!=PD_SC_INIT){
        if(onDebug) onDebug(pi,"SC_FAIL: CCRYPT in wrong state");
        return;
    }
    if(onDebug) onDebug(pi,"SC_CCRYPT: received, deriving keys");
    memcpy(p->rndB,&data[8],8);

    // Try the configured key first, then common defaults
    static const uint8_t KEYS[][16] = {
        {0},{0},{0}  // placeholders, filled below
    };
    const uint8_t *tryKeys[4];
    int nKeys = 0;
    const uint8_t *primaryKey = p->useScbkD ? SCBK_DEFAULT : p->scbk;
    tryKeys[nKeys++] = primaryKey;

    // Common factory defaults to try if primary fails
    static const uint8_t KEY_ZEROS[16] = {0};
    static const uint8_t KEY_FF[16] = {0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,
                                        0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF};
    if(primaryKey != SCBK_DEFAULT) tryKeys[nKeys++] = SCBK_DEFAULT;
    tryKeys[nKeys++] = KEY_ZEROS;
    tryKeys[nKeys++] = KEY_FF;

    static const uint8_t ENC_TAGS[] = {0x04, 0x82};
    for(int ki=0; ki<nKeys; ki++){
        const uint8_t *key = tryKeys[ki];
        for(int ti=0; ti<2; ti++){
            deriveSessionKeys(p->sEnc,p->sMac1,p->sMac2,key,p->rndA,ENC_TAGS[ti]);
            uint8_t ec[16]; computeCryptogram(ec,p->rndA,p->rndB,p->sEnc);
            if(memcmp(ec,&data[16],16)==0){
                if(ki>0){
                    memcpy(p->scbk, key, 16);
                    p->useScbkD = false;
                    if(onDebug){
                        char d[60];
                        if(key==SCBK_DEFAULT) snprintf(d,sizeof(d),"SC_KEY: matched SCBK-D default");
                        else if(key==KEY_ZEROS) snprintf(d,sizeof(d),"SC_KEY: matched all-zeros key");
                        else if(key==KEY_FF)    snprintf(d,sizeof(d),"SC_KEY: matched all-FF key");
                        else snprintf(d,sizeof(d),"SC_KEY: matched alternate key");
                        onDebug(pi,d);
                    }
                }
                if(onDebug){
                    char d[60];snprintf(d,sizeof(d),"SC_CCRYPT: PD crypto OK (tag=0x%02X), sending SCRYPT",ENC_TAGS[ti]);
                    onDebug(pi,d);
                }
                computeCryptogram(p->serverCrypt,p->rndB,p->rndA,p->sEnc);
                int n=buildPkt(p,CMD_SCRYPT,p->serverCrypt,16,SCS_13);
                if(n>0)txRaw(txBuf,n);
                p->lastPollMs=millis(); advanceSeq(p);
                return;
            }
        }
    }
    // No key matched
    if(onDebug) onDebug(pi,"SC_FAIL: PD cryptogram mismatch (no matching key)");
    p->state=PD_ONLINE;
}
void OsdpCp::handleRmacI(uint8_t pi, const uint8_t *data, uint16_t dlen) {
    if(dlen<16){
        if(onDebug){char d[48];snprintf(d,sizeof(d),"SC_FAIL: RMACI too short dlen=%d",dlen);onDebug(pi,d);}
        pd[pi].state=PD_ONLINE;return;
    }
    PdCtx*p=&pd[pi];uint8_t ex[16];
    computeRmacI(ex,p->serverCrypt,p->sMac1,p->sMac2);
    if(memcmp(ex,data,16)==0){memcpy(p->rMac,data,16);p->scActive=true;p->state=PD_SECURE;
    p->scRetries=0;p->hadSc=true;
    if(onStatus)onStatus(pi,p->state);
    if(onDebug)onDebug(pi,"SC_OK: secure channel established");
    }else{p->state=PD_ONLINE;
    if(onDebug)onDebug(pi,"SC_FAIL: RMAC-I verification failed");}
}

void OsdpCp::tick() {
    if(!numPd||!serial)return; uint32_t now=millis();

    // Read available serial data
    while(serial->available()){
        if(rxLen<OSDP_MAX_PKT) rxBuf[rxLen++]=serial->read();
        else rxLen=0;
        busRxCount++;
        lastRxMs=now;
    }

    // Clear stale rx buffer (incomplete packet sitting too long)
    if(rxLen>0 && lastRxMs>0 && (now-lastRxMs)>RX_STALE_TIMEOUT_MS){
        if(onDebug) onDebug(curPd, "RX_STALE: clearing incomplete rx data");
        if(curPd < numPd) pd[curPd].nextTxAllowedMs = now + TX_RECOVERY_BACKOFF_MS;
        rxLen=0;
    }

    // Parse complete packets
    if(rxLen>=7){
        int si=-1;for(uint16_t i=0;i<rxLen;i++){if(rxBuf[i]==OSDP_SOM){si=i;break;}}
        if(si>0){memmove(rxBuf,&rxBuf[si],rxLen-si);rxLen-=si;}if(si<0)rxLen=0;
        if(rxLen>=4){uint16_t pl=rxBuf[2]|((uint16_t)rxBuf[3]<<8);
        if(pl<=rxLen&&pl>=7&&pl<=OSDP_MAX_PKT){
            uint8_t ra=rxBuf[1]&0x7F;
            for(uint8_t i=0;i<numPd;i++){if(pd[i].addr==ra||ra==0x7F||(pd[i].comsetPending&&pd[i].comsetNewAddr==ra)){
                uint8_t dO[256];uint16_t dl=0;uint8_t st=0;
                int r=parseReply(&pd[i],rxBuf,pl,dO,&dl,&st);
                if(r>=0){
                    processReply(i,r,dO,dl,st);
                } else {
                    pd[i].parseFails++;
                    if(onDebug){
                        char dbg[80];
                        snprintf(dbg,sizeof(dbg),"PARSE_FAIL: pd=%d cnt=%d sc=%d pl=%d",
                                i,pd[i].parseFails,pd[i].scActive,pl);
                        onDebug(i,dbg);
                    }
                    pd[i].nextTxAllowedMs = now + TX_RECOVERY_BACKOFF_MS;
                    // Too many parse failures during SC → break SC for recovery
                    if(pd[i].parseFails>=MAX_PARSE_FAILS && pd[i].scActive){
                        pd[i].scActive=false; pd[i].hadSc=true;
                        pd[i].state=PD_ONLINE; pd[i].parseFails=0;
                        pd[i].scRetries=0; pd[i].lastScAttemptMs=0;
                        pd[i].lastPollMs=0; pd[i].lastReplyMs=millis();
                        if(onDebug) onDebug(i,"SC_BREAK: too many parse fails, will auto-retry SC");
                        if(onStatus) onStatus(i,pd[i].state);
                    }
                }
                break;}}
            if(pl<rxLen){memmove(rxBuf,&rxBuf[pl],rxLen-pl);rxLen-=pl;}else rxLen=0;}}
    }

    PdCtx*p=&pd[curPd];

    // SC init timeout — use lastScAttemptMs (set from `now` at attempt start, never
    // from millis() inside a callback) to avoid uint32_t underflow that fired this
    // immediately after SCRYPT was sent.
    if(p->state==PD_SC_INIT&&!p->scActive){
        if(p->lastScAttemptMs && (now-p->lastScAttemptMs)>SC_INIT_TIMEOUT_MS){
            p->state=PD_ONLINE;
            p->lastPollMs=0;
            p->lastReplyMs=now;
            p->scRetries++;
            if(onDebug) onDebug(curPd,"SC_TIMEOUT: init timed out, will retry");
        }
        curPd=(curPd+1)%numPd;return;
    }

    bool waitingForReply = (p->lastPollMs != 0) &&
                           (p->lastReplyMs == 0 || p->lastPollMs > p->lastReplyMs);
    if(waitingForReply){
        if((now-p->lastPollMs)<REPLY_TIMEOUT_MS){
            curPd=(curPd+1)%numPd;return;
        }
        p->retryCount++;
        if(onDebug){
            char dbg[80];
            snprintf(dbg,sizeof(dbg),"TX_TIMEOUT: cmd=%s cnt=%d sc=%d state=%d",
                     cmdName(p->lastCmd),p->retryCount,p->scActive,p->state);
            onDebug(curPd,dbg);
        }
        // Do not replay stale secure-channel frames after a timeout.  Clear the
        // outstanding marker and let the poller send the next fresh command.
        p->lastPollMs=0;
        p->lastReplyMs=now;
        p->nextTxAllowedMs=now + TX_RECOVERY_BACKOFF_MS;
    }

    if(p->retryCount>=MAX_TX_RETRIES){
        if(p->state!=PD_OFFLINE){
            bool wasSc=p->scActive;
            p->state=PD_OFFLINE;p->scActive=false;
            p->comsetPending=false;
            if(wasSc) p->hadSc=true;
            if(onStatus)onStatus(curPd,p->state);
            if(onDebug) onDebug(curPd,"PD_OFFLINE: consecutive tx timeouts");
        }
        p->retryCount=0;
        p->lastPollMs=0;
        p->lastReplyMs=now;
    }

    if (now < p->nextTxAllowedMs) {
        curPd=(curPd+1)%numPd;return;
    }

    // Auto-initiate SC only when no command is outstanding and not waiting for reply.
    if(p->state==PD_ONLINE && !p->scActive && !waitingForReply && !p->pendCount &&
       p->scRetries<6 && (now-p->lastScAttemptMs)>=SC_RETRY_INTERVAL_MS){
        p->lastScAttemptMs=now;  // set from `now` (safe for uint32_t comparison in timeout check)
        p->scRetries++;
        if(onDebug){
            char dbg[60];
            snprintf(dbg,sizeof(dbg),"SC_AUTO: attempt %d/6",p->scRetries);
            onDebug(curPd,dbg);
        }
        startSecureChannel(p);
        curPd=(curPd+1)%numPd;return;
    }

    if(p->lastPollMs==0 || (now-p->lastPollMs)>=POLL_INTERVAL_MS){
        bool hp=false;PendingCmd pc={};
        if(p->pendCount){pc=p->pend[p->pendHead];p->pendHead=(p->pendHead+1)%MAX_PENDING_CMDS;p->pendCount--;hp=true;}
        if(hp&&pc.cmd==CMD_CHLNG)startSecureChannel(p);
        else if(hp)sendCmd(p,pc.cmd,pc.data,pc.len);
        else sendCmd(p,CMD_POLL);
    }
    curPd=(curPd+1)%numPd;
}
