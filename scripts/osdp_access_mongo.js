'use strict';

/*
 * OSDP Access Controller MongoDB helpers for mongosh.
 *
 * Default usage:
 *   mongosh mongodb://localhost:27017/osdp_access
 *   load("scripts/osdp_access_mongo.js")
 *   osdpAccess.init()
 *   osdpAccess.help()
 *
 * Alternate demo database usage:
 *   load("scripts/osdp_access_mongo.js")
 *   const demo = createOsdpAccessApi("osdp_access_demo")
 *   demo.resetDatabase({ dropDatabase: true })
 *   demo.init()
 */

function createOsdpAccessApi(databaseName = 'osdp_access') {
  // Default reusable schedules mirror the Python backend model layer.
  const DEFAULT_SCHEDULES = [
    {
      name: '24/7',
      periods: [
        { days: [0, 1, 2, 3, 4, 5, 6], start: '00:00', end: '23:59' },
      ],
    },
    {
      name: 'Weekdays 8-18',
      periods: [
        { days: [0, 1, 2, 3, 4], start: '08:00', end: '18:00' },
      ],
    },
  ];

  const PANEL_USER_SEEDS = [
    {
      username: 'admin',
      role: 'admin',
      display_name: 'OSDP Administrator',
      password_hash: 'scrypt:32768:8:1$il0dUn4F7AkWapaL$cee1e40fd6b8841cbc6734c75b995df26e7bbf57988b0d5c9dd3de74a6d4a0a0f8da27b725a4d9d0763bdb11b8e322321264998918201f29740aa29e707407ba',
      active: true,
    },
    {
      username: 'demo',
      role: 'viewer',
      display_name: 'DB2 Demo Viewer',
      password_hash: 'scrypt:32768:8:1$tFtKHzA0Mnuw3fFr$3beaabd087bceff6fa1707e8990b5ed254fff9300980bc7df8e5d37b64628d4ff6f77e1f95ce96850f883c3003576bce4b9cb0a6f40070daa14ae0792bfcaae6',
      active: true,
    },
  ];

  // These are the collections used by the access controller application.
  const COLLECTIONS = [
    'users',
    'panel_users',
    'credentials',
    'events',
    'access_log',
    'readers',
    'schedules',
    'system_logs',
  ];

  // Work against the requested MongoDB database while keeping the API identical.
  const dbHandle = db.getSiblingDB(databaseName);

  // Return the current timestamp as a Mongo-friendly Date value.
  function nowUtc() {
    return new Date();
  }

  // Accept both ObjectId instances and string inputs from shell callers.
  function isObjectId(value) {
    return !!value && (
      value instanceof ObjectId ||
      value._bsontype === 'ObjectId' ||
      value._bsontype === 'ObjectID'
    );
  }

  // Normalize ids at the API boundary so CRUD helpers can accept strings safely.
  function toObjectId(value, fieldName = 'id') {
    if (value === null || value === undefined || value === '') {
      throw new Error(`${fieldName} is required`);
    }
    if (isObjectId(value)) {
      return value;
    }
    if (typeof value === 'string' && ObjectId.isValid(value)) {
      return new ObjectId(value);
    }
    throw new Error(`Invalid ${fieldName}: ${value}`);
  }

  // Card and PIN values are stored in uppercase to match the backend behavior.
  function normalizeHex(value, fieldName) {
    if (!value || typeof value !== 'string') {
      throw new Error(`${fieldName} is required`);
    }
    return value.trim().toUpperCase();
  }

  // Accept dates, ISO strings, or empty values when logging or upserting state.
  function toDate(value) {
    if (!value) {
      return nowUtc();
    }
    if (value instanceof Date) {
      return value;
    }
    return new Date(value);
  }

  // Format a date into HH:MM for schedule comparison.
  function hhmm(date) {
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    return `${hours}:${minutes}`;
  }

  // Convert JavaScript Sunday-first indexing to the Monday-first schedule model.
  function mondayBasedDow(date) {
    return (date.getDay() + 6) % 7;
  }

  // Remove only undefined fields so partial updates behave like $set patches.
  function cleanObject(doc) {
    return Object.fromEntries(
      Object.entries(doc).filter(([, value]) => value !== undefined)
    );
  }

  // Create missing collections up front so initialization is deterministic.
  function ensureCollections() {
    const existing = new Set(dbHandle.getCollectionNames());
    for (const name of COLLECTIONS) {
      if (!existing.has(name)) {
        dbHandle.createCollection(name);
      }
    }
    return dbHandle.getCollectionNames();
  }

  // Match the indexes created by the Python model layer and add sparse PIN lookup.
  function ensureIndexes() {
    dbHandle.users.createIndex({ username: 1 }, { unique: true, name: 'username_1_unique' });
    dbHandle.panel_users.createIndex({ username: 1 }, { unique: true, name: 'username_1_unique' });
    dbHandle.credentials.createIndex({ user_id: 1 }, { name: 'user_id_1' });
    dbHandle.credentials.createIndex({ card_hex: 1 }, { name: 'card_hex_1' });
    dbHandle.credentials.createIndex({ pin_hex: 1 }, { sparse: true, name: 'pin_hex_1_sparse' });
    dbHandle.events.createIndex({ ts: -1 }, { name: 'ts_desc' });
    dbHandle.access_log.createIndex({ ts: -1 }, { name: 'ts_desc' });
    dbHandle.readers.createIndex({ index: 1 }, { unique: true, name: 'index_1_unique' });
    dbHandle.schedules.createIndex({ name: 1 }, { unique: true, name: 'name_1_unique' });
    dbHandle.system_logs.createIndex({ ts: -1 }, { name: 'ts_desc' });
  }

  // Seed default schedules so schedule-dependent demos and CRUD calls always work.
  function seedSchedules() {
    for (const schedule of DEFAULT_SCHEDULES) {
      dbHandle.schedules.updateOne(
        { name: schedule.name },
        { $setOnInsert: schedule },
        { upsert: true }
      );
    }
    return listSchedules();
  }

  // Seed the fixed web-panel accounts used by the Flask login flow.
  function seedPanelUsers() {
    for (const panelUser of PANEL_USER_SEEDS) {
      dbHandle.panel_users.updateOne(
        { username: panelUser.username },
        {
          $setOnInsert: {
            ...panelUser,
            created: nowUtc(),
          },
        },
        { upsert: true }
      );
    }
    return listPanelUsers();
  }

  // Initialize the schema in one call for first use or demo resets.
  function init() {
    ensureCollections();
    ensureIndexes();
    seedSchedules();
    seedPanelUsers();
    return summary();
  }

  // Provide a compact overview of collection names and document counts.
  function summary() {
    return {
      db: databaseName,
      collections: dbHandle.getCollectionNames().sort(),
      counts: {
        users: dbHandle.users.countDocuments(),
        panel_users: dbHandle.panel_users.countDocuments(),
        credentials: dbHandle.credentials.countDocuments(),
        events: dbHandle.events.countDocuments(),
        access_log: dbHandle.access_log.countDocuments(),
        readers: dbHandle.readers.countDocuments(),
        schedules: dbHandle.schedules.countDocuments(),
        system_logs: dbHandle.system_logs.countDocuments(),
      },
    };
  }

  // Print the public API so the script is self-documenting inside mongosh.
  function help() {
    print(`OSDP Access Mongo helpers loaded as an API for database: ${databaseName}`);
    print('Core setup:');
    print('  osdpAccess.init()');
    print('  osdpAccess.summary()');
    print('  osdpAccess.resetDatabase({ dropDatabase: true|false })');
    print('Panel users:');
    print('  osdpAccess.listPanelUsers({ activeOnly: true|false })');
    print('  osdpAccess.getPanelUserByUsername(username)');
    print('Users:');
    print('  osdpAccess.createUser({...})');
    print('  osdpAccess.listUsers({ activeOnly: true|false })');
    print('  osdpAccess.getUserById(userId)');
    print('  osdpAccess.getUserByUsername(username)');
    print('  osdpAccess.updateUser(userId, fields)');
    print('  osdpAccess.deactivateUser(userId)');
    print('  osdpAccess.deleteUser(userId, { cascadeCredentials: true|false })');
    print('Credentials:');
    print('  osdpAccess.enrollCard({...})');
    print('  osdpAccess.enrollPin({...})');
    print('  osdpAccess.listCredentials({ user_id, activeOnly })');
    print('  osdpAccess.getCredentialById(credentialId)');
    print('  osdpAccess.findCredentialByCard(cardHex)');
    print('  osdpAccess.findCredentialByPin(pinHex)');
    print('  osdpAccess.updateCredential(credentialId, fields)');
    print('  osdpAccess.revokeCredential(credentialId)');
    print('  osdpAccess.deleteCredential(credentialId)');
    print('Schedules:');
    print('  osdpAccess.listSchedules()');
    print('  osdpAccess.getSchedule(name)');
    print('  osdpAccess.createSchedule({ name, periods })');
    print('  osdpAccess.updateSchedule(scheduleId, fields)');
    print('  osdpAccess.deleteSchedule(scheduleId)');
    print('  osdpAccess.checkSchedule(scheduleName, date)');
    print('Readers and logs:');
    print('  osdpAccess.upsertReader(index, fields)');
    print('  osdpAccess.getReader(index)');
    print('  osdpAccess.listReaders()');
    print('  osdpAccess.deleteReader(index)');
    print('  osdpAccess.logEvent(eventDoc)');
    print('  osdpAccess.getEvents({ limit, event_type, reader })');
    print('  osdpAccess.deleteEvents(filter)');
    print('  osdpAccess.logAccess({...})');
    print('  osdpAccess.getAccessLog({ limit, granted, reader })');
    print('  osdpAccess.deleteAccessLog(filter)');
    print('  osdpAccess.logSystem(level, source, message, data)');
    print('  osdpAccess.getSystemLogs({ limit, level, source })');
    print('  osdpAccess.deleteSystemLogs(filter)');
    print('Access evaluation:');
    print('  osdpAccess.checkReaderAccess(userDoc, readerIndex)');
    print('  osdpAccess.evaluateUserAccess(userDoc, readerIndex, date)');
    print('  osdpAccess.accessByCard({ card_hex, reader, when })');
    print('  osdpAccess.accessByPin({ pin_hex, reader, when })');
    print('Factory usage for demos:');
    print('  const demo = createOsdpAccessApi("osdp_access_demo")');
  }

  // Create a user document with the same shape as the backend application.
  function listPanelUsers({ activeOnly = true } = {}) {
    const filter = activeOnly ? { active: true } : {};
    return dbHandle.panel_users.find(filter).sort({ username: 1 }).toArray();
  }

  // Read a single panel user by unique username.
  function getPanelUserByUsername(username) {
    return dbHandle.panel_users.findOne({ username });
  }

  // Create a user document with the same shape as the backend application.
  function createUser({
    username,
    full_name = '',
    role = 'user',
    allowed_readers = [],
    schedule = '24/7',
    active = true,
  }) {
    if (!username) {
      throw new Error('username is required');
    }
    if (!Array.isArray(allowed_readers)) {
      throw new Error('allowed_readers must be an array');
    }
    const doc = {
      username,
      full_name,
      role,
      active,
      allowed_readers,
      schedule,
      created: nowUtc(),
    };
    return dbHandle.users.insertOne(doc);
  }

  // Read users with optional filtering for only active records.
  function listUsers({ activeOnly = true } = {}) {
    const filter = activeOnly ? { active: true } : {};
    return dbHandle.users.find(filter).sort({ username: 1 }).toArray();
  }

  // Read a single user by primary key.
  function getUserById(userId) {
    return dbHandle.users.findOne({ _id: toObjectId(userId, 'userId') });
  }

  // Read a single user by unique username.
  function getUserByUsername(username) {
    return dbHandle.users.findOne({ username });
  }

  // Update only the fields provided by the caller.
  function updateUser(userId, fields) {
    return dbHandle.users.updateOne(
      { _id: toObjectId(userId, 'userId') },
      { $set: cleanObject(fields) }
    );
  }

  // Soft-delete behavior matches the backend by toggling active to false.
  function deactivateUser(userId) {
    return updateUser(userId, { active: false });
  }

  // Optionally remove child credentials when deleting a user outright.
  function deleteUser(userId, { cascadeCredentials = false } = {}) {
    const objectId = toObjectId(userId, 'userId');
    if (cascadeCredentials) {
      dbHandle.credentials.deleteMany({ user_id: objectId });
    }
    return dbHandle.users.deleteOne({ _id: objectId });
  }

  // Insert a card credential and derive the decimal view used by the UI.
  function enrollCard({ user_id, card_hex, bits = 26, format = 0, reader = 0, active = true }) {
    const normalizedCard = normalizeHex(card_hex, 'card_hex');
    const doc = {
      user_id: toObjectId(user_id, 'user_id'),
      type: 'card',
      card_hex: normalizedCard,
      card_dec: BigInt(`0x${normalizedCard}`).toString(10),
      bits,
      format,
      reader,
      enrolled: nowUtc(),
      active,
    };
    return dbHandle.credentials.insertOne(doc);
  }

  // Insert a PIN credential for keypad workflows.
  function enrollPin({ user_id, pin_hex, reader = 0, active = true }) {
    const doc = {
      user_id: toObjectId(user_id, 'user_id'),
      type: 'pin',
      pin_hex: normalizeHex(pin_hex, 'pin_hex'),
      reader,
      enrolled: nowUtc(),
      active,
    };
    return dbHandle.credentials.insertOne(doc);
  }

  // Read credentials with optional user and active filters.
  function listCredentials({ user_id = null, activeOnly = true } = {}) {
    const filter = {};
    if (activeOnly) {
      filter.active = true;
    }
    if (user_id) {
      filter.user_id = toObjectId(user_id, 'user_id');
    }
    return dbHandle.credentials.find(filter).sort({ enrolled: -1 }).toArray();
  }

  // Read a single credential document by id.
  function getCredentialById(credentialId) {
    return dbHandle.credentials.findOne({ _id: toObjectId(credentialId, 'credentialId') });
  }

  // Update cards, PINs, or ownership while normalizing changed values.
  function updateCredential(credentialId, fields) {
    const updateFields = cleanObject({ ...fields });
    if (updateFields.card_hex) {
      updateFields.card_hex = normalizeHex(updateFields.card_hex, 'card_hex');
      updateFields.card_dec = BigInt(`0x${updateFields.card_hex}`).toString(10);
    }
    if (updateFields.pin_hex) {
      updateFields.pin_hex = normalizeHex(updateFields.pin_hex, 'pin_hex');
    }
    if (updateFields.user_id) {
      updateFields.user_id = toObjectId(updateFields.user_id, 'user_id');
    }
    return dbHandle.credentials.updateOne(
      { _id: toObjectId(credentialId, 'credentialId') },
      { $set: updateFields }
    );
  }

  // Soft-revoke a credential without removing historical access context.
  function revokeCredential(credentialId) {
    return updateCredential(credentialId, { active: false });
  }

  // Hard-delete a credential by id.
  function deleteCredential(credentialId) {
    return dbHandle.credentials.deleteOne({ _id: toObjectId(credentialId, 'credentialId') });
  }

  // Resolve a live card credential used by access workflows.
  function findCredentialByCard(cardHex) {
    return dbHandle.credentials.findOne({
      card_hex: normalizeHex(cardHex, 'card_hex'),
      type: 'card',
      active: true,
    });
  }

  // Resolve a live PIN credential used by access workflows.
  function findCredentialByPin(pinHex) {
    return dbHandle.credentials.findOne({
      pin_hex: normalizeHex(pinHex, 'pin_hex'),
      type: 'pin',
      active: true,
    });
  }

  // Read schedules alphabetically for UI or shell display.
  function listSchedules() {
    return dbHandle.schedules.find().sort({ name: 1 }).toArray();
  }

  // Read a single schedule by its unique name.
  function getSchedule(name) {
    return dbHandle.schedules.findOne({ name });
  }

  // Create a schedule document with embedded periods.
  function createSchedule({ name, periods }) {
    if (!name) {
      throw new Error('name is required');
    }
    if (!Array.isArray(periods)) {
      throw new Error('periods must be an array');
    }
    return dbHandle.schedules.insertOne({ name, periods });
  }

  // Update schedule metadata or period lists.
  function updateSchedule(scheduleId, fields) {
    return dbHandle.schedules.updateOne(
      { _id: toObjectId(scheduleId, 'scheduleId') },
      { $set: cleanObject(fields) }
    );
  }

  // Delete a schedule by id.
  function deleteSchedule(scheduleId) {
    return dbHandle.schedules.deleteOne({ _id: toObjectId(scheduleId, 'scheduleId') });
  }

  // Evaluate whether a specific date and time fits the named schedule.
  function checkSchedule(scheduleName, when = new Date()) {
    const schedule = getSchedule(scheduleName);
    if (!schedule) {
      return true;
    }
    const normalizedDate = toDate(when);
    const dow = mondayBasedDow(normalizedDate);
    const currentTime = hhmm(normalizedDate);
    for (const period of schedule.periods || []) {
      if ((period.days || []).includes(dow)) {
        const start = period.start || '00:00';
        const end = period.end || '23:59';
        if (start <= currentTime && currentTime <= end) {
          return true;
        }
      }
    }
    return false;
  }

  // Match the backend rule: an empty allowed_readers list means all readers.
  function checkReaderAccess(user, readerIndex) {
    if (!user) {
      return false;
    }
    const allowed = user.allowed_readers || [];
    if (!allowed.length) {
      return true;
    }
    return allowed.includes(readerIndex);
  }

  // Evaluate all access rules and return the same kind of reason strings used in logs.
  function evaluateUserAccess(user, readerIndex, when = new Date()) {
    if (!user) {
      return { granted: false, reason: 'user not found' };
    }
    if (!user.active) {
      return { granted: false, reason: 'user inactive' };
    }
    if (!checkReaderAccess(user, readerIndex)) {
      return { granted: false, reason: 'reader not allowed' };
    }
    if (!checkSchedule(user.schedule, when)) {
      return { granted: false, reason: 'outside schedule' };
    }
    return { granted: true, reason: 'allowed' };
  }

  // Store raw or normalized event documents and force a logged timestamp.
  function logEvent(eventDoc) {
    const doc = { ...eventDoc };
    doc.logged = nowUtc();
    doc.ts = doc.ts ? toDate(doc.ts) : nowUtc();
    return dbHandle.events.insertOne(doc);
  }

  // Query recent events by type and reader.
  function getEvents({ limit = 200, event_type = null, reader = null } = {}) {
    const filter = {};
    if (event_type) {
      filter.type = event_type;
    }
    if (reader !== null && reader !== undefined) {
      filter.reader = reader;
    }
    return dbHandle.events.find(filter).sort({ ts: -1 }).limit(limit).toArray();
  }

  // Delete events matching any caller-supplied filter.
  function deleteEvents(filter = {}) {
    return dbHandle.events.deleteMany(filter);
  }

  // Insert a final access-decision log entry.
  function logAccess({
    card_hex = null,
    pin_hex = null,
    user_id = null,
    username = null,
    granted = false,
    reader = 0,
    reason = '',
  }) {
    const doc = {
      ts: nowUtc(),
      card_hex: card_hex ? normalizeHex(card_hex, 'card_hex') : null,
      pin_hex: pin_hex ? normalizeHex(pin_hex, 'pin_hex') : null,
      user_id: user_id ? toObjectId(user_id, 'user_id') : null,
      username,
      granted,
      reader,
      reason,
    };
    return dbHandle.access_log.insertOne(doc);
  }

  // Read recent audit records with optional filters.
  function getAccessLog({ limit = 200, granted = null, reader = null } = {}) {
    const filter = {};
    if (granted !== null) {
      filter.granted = granted;
    }
    if (reader !== null && reader !== undefined) {
      filter.reader = reader;
    }
    return dbHandle.access_log.find(filter).sort({ ts: -1 }).limit(limit).toArray();
  }

  // Delete access log records matching a filter.
  function deleteAccessLog(filter = {}) {
    return dbHandle.access_log.deleteMany(filter);
  }

  // Maintain a single current-state document per reader index.
  function upsertReader(index, fields = {}) {
    const updateFields = cleanObject({ ...fields });
    if (updateFields.last_seen) {
      updateFields.last_seen = toDate(updateFields.last_seen);
    }
    return dbHandle.readers.updateOne(
      { index },
      { $set: updateFields },
      { upsert: true }
    );
  }

  // Read one reader state snapshot.
  function getReader(index) {
    return dbHandle.readers.findOne({ index });
  }

  // Read all reader snapshots in display order.
  function listReaders() {
    return dbHandle.readers.find().sort({ index: 1 }).toArray();
  }

  // Delete a reader snapshot by index.
  function deleteReader(index) {
    return dbHandle.readers.deleteOne({ index });
  }

  // Insert diagnostic log records for admin or firmware workflows.
  function logSystem(level, source, message, data = null) {
    const doc = {
      ts: nowUtc(),
      level,
      source,
      message,
    };
    if (data !== null && data !== undefined) {
      doc.data = data;
    }
    return dbHandle.system_logs.insertOne(doc);
  }

  // Read recent system logs with optional filtering.
  function getSystemLogs({ limit = 500, level = null, source = null } = {}) {
    const filter = {};
    if (level) {
      filter.level = level;
    }
    if (source) {
      filter.source = source;
    }
    return dbHandle.system_logs.find(filter).sort({ ts: -1 }).limit(limit).toArray();
  }

  // Delete diagnostic logs matching a filter.
  function deleteSystemLogs(filter = {}) {
    return dbHandle.system_logs.deleteMany(filter);
  }

  // Execute a full card access workflow and persist the audit result.
  function accessByCard({ card_hex, reader = 0, when = new Date() }) {
    const credential = findCredentialByCard(card_hex);
    if (!credential) {
      logAccess({ card_hex, granted: false, reader, reason: 'unknown card' });
      return { granted: false, reason: 'unknown card', credential: null, user: null };
    }
    const user = getUserById(credential.user_id);
    const decision = evaluateUserAccess(user, reader, when);
    logAccess({
      card_hex,
      user_id: credential.user_id,
      username: user ? user.username : 'unknown',
      granted: decision.granted,
      reader,
      reason: decision.reason,
    });
    return { ...decision, credential, user };
  }

  // Execute a full PIN access workflow and persist the audit result.
  function accessByPin({ pin_hex, reader = 0, when = new Date() }) {
    const credential = findCredentialByPin(pin_hex);
    if (!credential) {
      logAccess({ pin_hex, granted: false, reader, reason: 'unknown pin' });
      return { granted: false, reason: 'unknown pin', credential: null, user: null };
    }
    const user = getUserById(credential.user_id);
    const decision = evaluateUserAccess(user, reader, when);
    logAccess({
      pin_hex,
      user_id: credential.user_id,
      username: user ? user.username : 'unknown',
      granted: decision.granted,
      reader,
      reason: decision.reason,
    });
    return { ...decision, credential, user };
  }

  // Reset either by dropping the whole database or by clearing only known collections.
  function resetDatabase({ dropDatabase = false } = {}) {
    if (dropDatabase) {
      dbHandle.dropDatabase();
    } else {
      for (const name of COLLECTIONS) {
        dbHandle.getCollection(name).deleteMany({});
      }
    }
    return init();
  }

  // Provide direct collection access for advanced shell work when needed.
  function collection(name) {
    if (!COLLECTIONS.includes(name)) {
      throw new Error(`Unknown collection: ${name}`);
    }
    return dbHandle.getCollection(name);
  }

  return {
    DB_NAME: databaseName,
    init,
    help,
    summary,
    resetDatabase,
    collection,
    ensureCollections,
    ensureIndexes,
    seedSchedules,
    seedPanelUsers,
    listPanelUsers,
    getPanelUserByUsername,
    createUser,
    listUsers,
    getUserById,
    getUserByUsername,
    updateUser,
    deactivateUser,
    deleteUser,
    enrollCard,
    enrollPin,
    listCredentials,
    getCredentialById,
    updateCredential,
    revokeCredential,
    deleteCredential,
    findCredentialByCard,
    findCredentialByPin,
    listSchedules,
    getSchedule,
    createSchedule,
    updateSchedule,
    deleteSchedule,
    checkSchedule,
    checkReaderAccess,
    evaluateUserAccess,
    logEvent,
    getEvents,
    deleteEvents,
    logAccess,
    getAccessLog,
    deleteAccessLog,
    upsertReader,
    getReader,
    listReaders,
    deleteReader,
    logSystem,
    getSystemLogs,
    deleteSystemLogs,
    accessByCard,
    accessByPin,
  };
}

// Expose the API factory for safe demonstrations against a separate database.
globalThis.createOsdpAccessApi = createOsdpAccessApi;

// Keep the default helper name for the real application database.
globalThis.osdpAccess = createOsdpAccessApi();

print('Loaded osdpAccess Mongo helpers. Run osdpAccess.help() for usage.');