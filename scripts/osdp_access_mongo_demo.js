'use strict';

/*
 * End-to-end mongosh demo for the OSDP access helper library.
 *
 * Usage:
 *   mongosh mongodb://localhost:27017 --quiet --eval "load('scripts/osdp_access_mongo.js'); load('scripts/osdp_access_mongo_demo.js');"
 *
 * The demo uses a separate database called osdp_access_demo so it does not
 * overwrite the real osdp_access application data.
 */

if (typeof createOsdpAccessApi !== 'function') {
  throw new Error('createOsdpAccessApi is not available. Load scripts/osdp_access_mongo.js first.');
}

const demoApi = createOsdpAccessApi('osdp_access_demo');

function banner(title) {
  print(`\n=== ${title} ===`);
}

function show(label, value) {
  print(`-- ${label}`);
  print(EJSON.stringify(value, null, 2));
}

function showResult(label, result) {
  show(label, result);
}

// Fixed timestamps make schedule and access results predictable in the output.
const mondayMorning = new Date('2026-05-11T09:15:00Z');
const saturdayNight = new Date('2026-05-09T22:00:00Z');

banner('1. Reset and initialize demo database');
show('resetDatabase({ dropDatabase: true })', demoApi.resetDatabase({ dropDatabase: true }));
show('listPanelUsers({ activeOnly: false })', demoApi.listPanelUsers({ activeOnly: false }));
showResult('resetPanelUserPassword("admin")', demoApi.resetPanelUserPassword('admin'));
show('getPanelUserByUsername("admin")', demoApi.getPanelUserByUsername('admin'));

banner('2. Create users');
const martinId = demoApi.createUser({
  username: 'martin',
  full_name: 'Martin Velichkovski',
  role: 'admin',
  allowed_readers: [0],
  schedule: '24/7',
}).insertedId;

const visitorId = demoApi.createUser({
  username: 'visitor',
  full_name: 'Weekend Visitor',
  role: 'user',
  allowed_readers: [1],
  schedule: 'Weekdays 8-18',
}).insertedId;

const tempUserId = demoApi.createUser({
  username: 'temp-delete',
  full_name: 'Temporary Demo User',
  role: 'user',
  allowed_readers: [],
  schedule: '24/7',
}).insertedId;

show('users after create', demoApi.listUsers({ activeOnly: false }));

banner('3. Read and update users');
show('getUserByUsername("martin")', demoApi.getUserByUsername('martin'));
showResult('updateUser(martin)', demoApi.updateUser(martinId, {
  full_name: 'Martin V.',
  allowed_readers: [0, 2],
}));
show('getUserById(martinId)', demoApi.getUserById(martinId));
showResult('deactivateUser(tempUserId)', demoApi.deactivateUser(tempUserId));
show('temp user after deactivate', demoApi.getUserById(tempUserId));

banner('4. Create, read, update, revoke, and delete credentials');
const martinCardId = demoApi.enrollCard({
  user_id: martinId,
  card_hex: '04A1B2C3D4',
  bits: 34,
  format: 0,
  reader: 0,
}).insertedId;

const martinPinId = demoApi.enrollPin({
  user_id: martinId,
  pin_hex: '1A2B',
  reader: 0,
}).insertedId;

const visitorPinId = demoApi.enrollPin({
  user_id: visitorId,
  pin_hex: 'BEEF',
  reader: 1,
}).insertedId;

const tempCredentialId = demoApi.enrollCard({
  user_id: tempUserId,
  card_hex: '0BADF00D',
  bits: 32,
  format: 1,
  reader: 3,
}).insertedId;

show('listCredentials()', demoApi.listCredentials({ activeOnly: false }));
show('findCredentialByCard("04A1B2C3D4")', demoApi.findCredentialByCard('04A1B2C3D4'));
showResult('updateCredential(martinCardId)', demoApi.updateCredential(martinCardId, {
  bits: 37,
  reader: 2,
}));
show('getCredentialById(martinCardId)', demoApi.getCredentialById(martinCardId));
showResult('revokeCredential(tempCredentialId)', demoApi.revokeCredential(tempCredentialId));
show('temp credential after revoke', demoApi.getCredentialById(tempCredentialId));
showResult('deleteCredential(tempCredentialId)', demoApi.deleteCredential(tempCredentialId));

banner('5. Create, read, update, delete schedules');
const weekendLabId = demoApi.createSchedule({
  name: 'Weekend Lab',
  periods: [
    { days: [5], start: '10:00', end: '14:00' },
    { days: [6], start: '11:00', end: '13:00' },
  ],
}).insertedId;

const deleteMeScheduleId = demoApi.createSchedule({
  name: 'Delete Me Schedule',
  periods: [
    { days: [0], start: '00:00', end: '00:30' },
  ],
}).insertedId;

show('listSchedules()', demoApi.listSchedules());
show('getSchedule("Weekend Lab")', demoApi.getSchedule('Weekend Lab'));
showResult('updateSchedule(weekendLabId)', demoApi.updateSchedule(weekendLabId, {
  periods: [
    { days: [5], start: '09:00', end: '15:00' },
    { days: [6], start: '11:00', end: '13:00' },
  ],
}));
show('checkSchedule("Weekdays 8-18", mondayMorning)', {
  schedule: 'Weekdays 8-18',
  when: mondayMorning,
  allowed: demoApi.checkSchedule('Weekdays 8-18', mondayMorning),
});
show('checkSchedule("Weekdays 8-18", saturdayNight)', {
  schedule: 'Weekdays 8-18',
  when: saturdayNight,
  allowed: demoApi.checkSchedule('Weekdays 8-18', saturdayNight),
});
showResult('deleteSchedule(deleteMeScheduleId)', demoApi.deleteSchedule(deleteMeScheduleId));

banner('6. Upsert, read, list, and delete readers');
showResult('upsertReader(0, ...)', demoApi.upsertReader(0, {
  addr: 0,
  state: 'ONLINE',
  sc: 1,
  tamper: 0,
  power: 0,
  vendor: 'E41E0A',
  model: 1,
  serial: '21AA0145',
  firmware: '2.83.0',
  last_seen: mondayMorning,
}));
showResult('upsertReader(1, ...)', demoApi.upsertReader(1, {
  addr: 1,
  state: 'OFFLINE',
  sc: 0,
  tamper: 0,
  power: 0,
  vendor: 'DEMO01',
  model: 2,
  serial: 'DEMO0001',
  firmware: '1.0.0',
  last_seen: saturdayNight,
}));
show('getReader(0)', demoApi.getReader(0));
show('listReaders()', demoApi.listReaders());
showResult('deleteReader(1)', demoApi.deleteReader(1));

banner('7. Log, query, and delete events');
demoApi.logEvent({ type: 'card', reader: 0, hex: '04A1B2C3D4', bits: 37, format: 0, ts: mondayMorning, raw: '!CARD demo' });
demoApi.logEvent({ type: 'pd_status', reader: 0, state: 'ONLINE', ts: mondayMorning, raw: '!PD 0 ONLINE' });
demoApi.logEvent({ type: 'demo_delete', reader: 9, ts: saturdayNight, raw: '!DEMO DELETE' });
show('getEvents({ limit: 10 })', demoApi.getEvents({ limit: 10 }));
showResult('deleteEvents({ type: "demo_delete" })', demoApi.deleteEvents({ type: 'demo_delete' }));

banner('8. Log, query, and delete system logs');
demoApi.logSystem('info', 'demo', 'Demo script started', { step: 8 });
demoApi.logSystem('warn', 'demo', 'Reader 1 was removed during cleanup');
demoApi.logSystem('info', 'demo-cleanup', 'This log will be deleted');
show('getSystemLogs({ limit: 10 })', demoApi.getSystemLogs({ limit: 10 }));
showResult('deleteSystemLogs({ source: "demo-cleanup" })', demoApi.deleteSystemLogs({ source: 'demo-cleanup' }));

banner('9. Access evaluation helpers');
show('evaluateUserAccess(martin, reader 0, mondayMorning)', demoApi.evaluateUserAccess(
  demoApi.getUserById(martinId),
  0,
  mondayMorning
));
show('evaluateUserAccess(visitor, reader 0, mondayMorning)', demoApi.evaluateUserAccess(
  demoApi.getUserById(visitorId),
  0,
  mondayMorning
));
show('evaluateUserAccess(visitor, reader 1, saturdayNight)', demoApi.evaluateUserAccess(
  demoApi.getUserById(visitorId),
  1,
  saturdayNight
));

banner('10. Access workflows and access log');
show('accessByCard(martin card)', demoApi.accessByCard({
  card_hex: '04A1B2C3D4',
  reader: 0,
  when: mondayMorning,
}));
show('accessByCard(unknown card)', demoApi.accessByCard({
  card_hex: 'FFFFFFFF',
  reader: 0,
  when: mondayMorning,
}));
show('accessByPin(visitor pin outside schedule)', demoApi.accessByPin({
  pin_hex: 'BEEF',
  reader: 1,
  when: saturdayNight,
}));
demoApi.logAccess({
  card_hex: 'DEADBEEF',
  granted: false,
  reader: 99,
  reason: 'manual demo delete',
});
show('getAccessLog({ limit: 10 })', demoApi.getAccessLog({ limit: 10 }));
showResult('deleteAccessLog({ reason: "manual demo delete" })', demoApi.deleteAccessLog({ reason: 'manual demo delete' }));

banner('11. Delete temporary user and final summary');
showResult('deleteUser(tempUserId)', demoApi.deleteUser(tempUserId));
show('listUsers({ activeOnly: false })', demoApi.listUsers({ activeOnly: false }));
show('final summary', demoApi.summary());